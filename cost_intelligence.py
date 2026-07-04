"""AI cost estimation, budget status, and adaptive model routing."""
from __future__ import annotations

import contextvars
import json
import os
from dataclasses import dataclass
from decimal import Decimal


# Provider pricing, USD per 1M tokens. Override any entry with AI_MODEL_PRICING_JSON.
DEFAULT_MODEL_PRICING = {
    # Groq
    "llama-3.1-8b-instant":                       {"input": Decimal("0.05"),   "output": Decimal("0.08")},
    "llama-3.3-70b-versatile":                     {"input": Decimal("0.59"),   "output": Decimal("0.79")},
    "meta-llama/llama-4-scout-17b-16e-instruct":   {"input": Decimal("0.11"),   "output": Decimal("0.34")},
    # Gemini 2.5
    "gemini-2.5-flash":                            {"input": Decimal("0.075"),  "output": Decimal("0.30")},
    "gemini-2.5-flash-preview-05-20":              {"input": Decimal("0.075"),  "output": Decimal("0.30")},
    "gemini-2.5-pro":                              {"input": Decimal("1.25"),   "output": Decimal("10.00")},
    "gemini-2.5-pro-preview-06-05":                {"input": Decimal("1.25"),   "output": Decimal("10.00")},
    # Gemini 2.0
    "gemini-2.0-flash":                            {"input": Decimal("0.10"),   "output": Decimal("0.40")},
    # Gemini 1.5 (legacy)
    "gemini-1.5-flash":                            {"input": Decimal("0.075"),  "output": Decimal("0.30")},
    "gemini-1.5-pro":                              {"input": Decimal("1.25"),   "output": Decimal("5.00")},
    # OpenRouter — OpenAI via OpenRouter
    "openai/gpt-4o":                               {"input": Decimal("2.50"),   "output": Decimal("10.00")},
    "openai/gpt-4o-mini":                          {"input": Decimal("0.15"),   "output": Decimal("0.60")},
    "openai/o1-mini":                              {"input": Decimal("3.00"),   "output": Decimal("12.00")},
    # OpenRouter — DeepSeek via OpenRouter
    "deepseek/deepseek-chat":                      {"input": Decimal("0.27"),   "output": Decimal("1.10")},
    "deepseek/deepseek-r1":                        {"input": Decimal("0.55"),   "output": Decimal("2.19")},
    # DeepSeek direct API (api.deepseek.com)
    "deepseek-chat":                               {"input": Decimal("0.27"),   "output": Decimal("1.10")},
    "deepseek-reasoner":                           {"input": Decimal("0.55"),   "output": Decimal("2.19")},
    # OpenRouter — Qwen via OpenRouter
    "qwen/qwen-2.5-72b-instruct":                  {"input": Decimal("0.35"),   "output": Decimal("0.40")},
    "qwen/qwen-2.5-coder-32b-instruct":            {"input": Decimal("0.06"),   "output": Decimal("0.06")},
    # OpenRouter — Mistral via OpenRouter
    "mistralai/mistral-7b-instruct":               {"input": Decimal("0.06"),   "output": Decimal("0.06")},
    "mistralai/mixtral-8x22b-instruct":            {"input": Decimal("0.90"),   "output": Decimal("0.90")},
    # OpenRouter — Meta Llama via OpenRouter
    "meta-llama/llama-3.3-70b-instruct":           {"input": Decimal("0.59"),   "output": Decimal("0.79")},
}


def _pricing_registry() -> dict[str, dict[str, Decimal]]:
    registry = {name: dict(rates) for name, rates in DEFAULT_MODEL_PRICING.items()}
    raw = os.environ.get("AI_MODEL_PRICING_JSON", "").strip()
    if not raw:
        return registry
    try:
        overrides = json.loads(raw)
        for model, rates in overrides.items():
            registry[str(model)] = {
                "input": Decimal(str(rates["input"])),
                "output": Decimal(str(rates["output"])),
            }
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        pass
    return registry


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    """Estimate provider cost using USD prices per one million tokens."""
    registry = _pricing_registry()
    # Strip provider prefix (e.g. "gemini:gemini-2.5-flash" → "gemini-2.5-flash")
    bare = model.split(":")[-1] if ":" in model else model
    rates = registry.get(model) or registry.get(bare)
    if rates is None:
        rates = registry.get(bare.split("/")[-1])
    if rates is None:
        rates = registry.get(model.split("/")[-1])
    if rates is None:
        rates = {
            "input": Decimal(os.environ.get("AI_DEFAULT_INPUT_COST_PER_MILLION", "0.59")),
            "output": Decimal(os.environ.get("AI_DEFAULT_OUTPUT_COST_PER_MILLION", "0.79")),
        }
    million = Decimal("1000000")
    cost = (
        Decimal(max(0, int(prompt_tokens or 0))) * rates["input"]
        + Decimal(max(0, int(completion_tokens or 0))) * rates["output"]
    ) / million
    return cost.quantize(Decimal("0.00000001"))


def budget_status(monthly_cost: float | Decimal, monthly_budget: float | Decimal) -> dict:
    cost = Decimal(str(monthly_cost or 0))
    budget = Decimal(str(monthly_budget or 0))
    if budget <= 0:
        return {"percentage": 0.0, "level": "unconfigured", "message": "Monthly budget belum diatur."}
    percentage = float((cost / budget * Decimal("100")).quantize(Decimal("0.01")))
    if percentage >= 100:
        level, message = "exceeded", "Budget bulanan telah mencapai atau melewati 100%."
    elif percentage >= 90:
        level, message = "critical", "Pemakaian biaya telah mencapai 90% budget bulanan."
    elif percentage >= 80:
        level, message = "warning", "Pemakaian biaya telah mencapai 80% budget bulanan."
    else:
        level, message = "healthy", "Pemakaian biaya masih dalam budget."
    return {"percentage": percentage, "level": level, "message": message}


def task_complexity(user_message: str, reasoning_mode: str = "standard") -> str:
    from intent_classifier import heuristic_complexity

    heuristic = heuristic_complexity(user_message)
    if heuristic in {"simple", "complex"}:
        return heuristic
    if reasoning_mode == "pro":
        return "complex"
    return "complex" if len((user_message or "").strip()) > 240 else "simple"


@dataclass(frozen=True)
class ModelRoute:
    complexity: str
    model: str
    tier: str


_model_route: contextvars.ContextVar[ModelRoute | None] = contextvars.ContextVar(
    "botnesia_model_route", default=None
)


def choose_model(
    user_message: str,
    reasoning_mode: str,
    cheap_model: str,
    strong_model: str,
) -> ModelRoute:
    complexity = task_complexity(user_message, reasoning_mode)
    if complexity == "simple":
        return ModelRoute(complexity, cheap_model or strong_model, "economy")
    return ModelRoute(complexity, strong_model or cheap_model, "quality")


def set_model_route(route: ModelRoute):
    return _model_route.set(route)


def reset_model_route(token) -> None:
    _model_route.reset(token)


def routed_model(default_model: str) -> str:
    route = _model_route.get()
    return route.model if route and route.model else default_model


def current_model_route() -> ModelRoute | None:
    return _model_route.get()
