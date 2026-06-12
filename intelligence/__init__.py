"""
intelligence/ — BotNesia Intelligence Platform

Modul ini mengubah tiap percakapan menjadi aset data jangka panjang:
Conversation Memory, FAQ Engine, Sales Intelligence, Knowledge Graph,
Customer Intelligence, dan laporan Auto-Learning harian.

Lihat ARCHITECTURE.md untuk diagram & penjelasan menyeluruh.
"""
from __future__ import annotations

__all__ = [
    "cfg",
    "get_pool",
]

from .config import cfg
from .db import get_pool
