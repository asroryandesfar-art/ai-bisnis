"""
Multi-agent reference templates aligned with the active BotNesia stack.

IMPORTANT:
- This file is a reference / starter template
- It does not replace the production runtime in `main.py`
- It is intentionally aligned with:
  - Groq
  - FastAPI
  - RSS/direct-source news retrieval
  - Replicate media generation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from datetime import datetime
import os


# ─────────────────────────────────────────────────────────────
# USER PROFILE
# ─────────────────────────────────────────────────────────────


@dataclass
class UserProfile:
    name: str
    interests: list[str]
    personality: str = "balanced"
    language: str = "id"
    tone_target: str = "friend"
    communication_style: str = "clear"
    previous_topics: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "interests": self.interests,
            "personality": self.personality,
            "language": self.language,
            "tone_target": self.tone_target,
            "communication_style": self.communication_style,
            "previous_topics": self.previous_topics,
        }


# ─────────────────────────────────────────────────────────────
# LIGHTWEIGHT ROUTER TEMPLATE
# ─────────────────────────────────────────────────────────────


class RouterAgent:
    """
    Reference-only router.
    In production, BotNesia uses the supervisor pipeline.
    """

    def route(self, query: str, profile: UserProfile) -> dict[str, Any]:
        q = (query or "").lower()
        need_news = any(k in q for k in ["berita", "news", "terkini", "update", "headline"])
        need_visual = any(k in q for k in ["gambar", "image", "thumbnail", "video"])
        need_market = any(k in q for k in ["harga", "price", "btc", "bitcoin", "saham", "stock"])

        agents = ["CS_AGENT"]
        if need_news:
            agents.append("NEWS_AGENT")
        if need_market:
            agents.append("MARKET_AGENT")
        if need_visual:
            agents.append("VISUAL_AGENT")

        return {
            "agents_needed": agents,
            "priority_order": agents[:],
            "context_for_agents": profile.to_dict(),
            "needs_sources_exposed": False,
        }


# ─────────────────────────────────────────────────────────────
# NEWS AGENT TEMPLATE
# ─────────────────────────────────────────────────────────────


class NewsAgent:
    """
    Reference adapter.
    For real implementation, use `news_fetcher.py`.
    """

    async def fetch(self, query: str) -> dict[str, Any]:
        from news_fetcher import build_news_context

        text = await build_news_context(query, limit=6, include_bodies=True)
        return {
            "query": query,
            "context": text,
        }


# ─────────────────────────────────────────────────────────────
# MARKET AGENT TEMPLATE
# ─────────────────────────────────────────────────────────────


class MarketAgent:
    """
    Reference adapter.
    For real implementation, use `finance_fetcher.py`.
    """

    async def fetch(self, query: str) -> dict[str, Any]:
        from finance_fetcher import (
            fetch_crypto_quotes,
            fetch_stock_quotes,
            combine_market_answers,
        )

        crypto = await fetch_crypto_quotes(query)
        stocks = await fetch_stock_quotes(query)
        answer = combine_market_answers(crypto, stocks)
        return {
            "query": query,
            "answer": answer,
        }


# ─────────────────────────────────────────────────────────────
# PERSONALITY ADAPTER TEMPLATE
# ─────────────────────────────────────────────────────────────


class PersonalityAdapter:
    def adapt(self, content: str, profile: UserProfile) -> str:
        text = (content or "").strip()
        if not text:
            return text

        if profile.personality == "critical":
            prefix = "Oke, kita lihat ini secara realistis. "
        elif profile.personality == "optimistic":
            prefix = "Menarik, ini sisi positif yang paling penting. "
        else:
            prefix = "Ini ringkasannya. "

        if profile.language.startswith("mixed"):
            return prefix + text
        if profile.language == "en":
            return text
        return prefix + text


# ─────────────────────────────────────────────────────────────
# VISUAL AGENT TEMPLATE
# ─────────────────────────────────────────────────────────────


class VisualPromptAgent:
    def build_image_prompt(self, topic: str) -> str:
        return (
            f"{topic}, high-detail cinematic composition, clear focal point, "
            "professional lighting, premium editorial style, clean modern aesthetic"
        )

    def build_video_prompt(self, topic: str) -> str:
        return (
            f"{topic}, cinematic motion, smooth camera movement, rich lighting, "
            "high production quality, visually coherent storytelling"
        )


# ─────────────────────────────────────────────────────────────
# MINI ORCHESTRATOR TEMPLATE
# ─────────────────────────────────────────────────────────────


class MultiAgentOrchestrator:
    """
    Reference-only orchestrator.
    Use this for experiments, learning, or separate services.
    Production app flow remains in `main.py`.
    """

    def __init__(self, profile: UserProfile):
        self.profile = profile
        self.router = RouterAgent()
        self.news = NewsAgent()
        self.market = MarketAgent()
        self.personality = PersonalityAdapter()
        self.visual = VisualPromptAgent()

    async def process_query(self, query: str) -> dict[str, Any]:
        route = self.router.route(query, self.profile)
        q = (query or "").lower()

        news_ctx = ""
        market_answer = ""
        visual_prompt = ""

        if "NEWS_AGENT" in route["agents_needed"]:
            news_ctx = (await self.news.fetch(query)).get("context", "")

        if "MARKET_AGENT" in route["agents_needed"]:
            market_answer = (await self.market.fetch(query)).get("answer", "")

        if "VISUAL_AGENT" in route["agents_needed"]:
            if "video" in q:
                visual_prompt = self.visual.build_video_prompt(query)
            else:
                visual_prompt = self.visual.build_image_prompt(query)

        base_answer = market_answer or news_ctx or f"Permintaan diterima: {query}"
        final_answer = self.personality.adapt(base_answer, self.profile)

        return {
            "route": route,
            "answer": final_answer,
            "visual_prompt": visual_prompt,
            "sources_exposed": False,
        }


# ─────────────────────────────────────────────────────────────
# EXAMPLE USAGE
# ─────────────────────────────────────────────────────────────


if __name__ == "__main__":
    import asyncio

    profile = UserProfile(
        name="Asrori",
        interests=["AI", "crypto", "blockchain", "education"],
        personality="critical",
        language="mixed_indo_english",
        tone_target="friend",
        communication_style="technical but accessible",
    )

    orchestrator = MultiAgentOrchestrator(profile)

    async def _demo() -> None:
        queries = [
            "Kasih aku update Bitcoin terbaru",
            "harga saham apple dan btc sekarang",
            "bikin prompt gambar tentang multi-agent AI",
        ]
        for q in queries:
            result = await orchestrator.process_query(q)
            print("\nUSER:", q)
            print("ROUTE:", result["route"])
            print("ANSWER:", result["answer"])
            if result["visual_prompt"]:
                print("VISUAL:", result["visual_prompt"])

    asyncio.run(_demo())
