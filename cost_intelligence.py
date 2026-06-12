"""AI cost estimation, budget status, and adaptive model routing."""
from __future__ import annotations

import contextvars
import json
import os
from dataclasses import dataclass
from decimal import Decimal


# Groq public pricing, USD per 1M tokens. Override with AI_MODEL_PRICING_JSON.
DEFAULT_MODEL_PRICING = {
    "llama-3.1-8b-instant": {"input": Decimal("0.05"), "output": Decimal("0.08")},
    "llama-3.3-70b-versatile": {"input": Decimal("0.59"), "output": Decimal("0.79")},
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
    rates = registry.get(model)
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
