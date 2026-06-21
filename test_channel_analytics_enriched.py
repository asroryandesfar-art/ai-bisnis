"""Tests for ChannelManager.analytics() enrichment (BotNesia Phase Next —
Phase 11, Multi Channel Center): per-channel response_rate_pct (outbound/
inbound message ratio), ai_resolution_rate_pct and satisfaction_avg (both
derived from conversations.channel + handoff_needed/rating, since
channel_messages.conversation_id is never populated by _process_inbound).
"""
import asyncio

from bn_platform.channel_manager import ChannelManager


class FakePool:
    def __init__(self, *, summary_row, usage_rows, conv_rows):
        self._summary_row = summary_row
        self._usage_rows = usage_rows
        self._conv_rows = conv_rows
        self.calls: list[tuple] = []

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self._summary_row

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        if "FROM channels c" in sql:
            return self._usage_rows
        if "FROM conversations" in sql:
            return self._conv_rows
        return []


def _summary(total=10, active=4, response_ms=500, inbound=6, outbound=4, conversions=1):
    return {
        "total_messages": total, "active_users": active, "response_time_ms": response_ms,
        "inbound_messages": inbound, "outbound_messages": outbound, "conversions": conversions,
    }


def test_analytics_computes_response_rate_per_channel():
    pool = FakePool(
        summary_row=_summary(),
        usage_rows=[{"channel": "whatsapp", "messages": 10, "active_users": 3, "response_time_ms": 450, "inbound_messages": 6, "outbound_messages": 3}],
        conv_rows=[],
    )
    result = asyncio.run(ChannelManager(pool).analytics("org-1", days=30))
    assert result["channel_usage"][0]["response_rate_pct"] == 50.0


def test_analytics_handles_zero_inbound_without_division_error():
    pool = FakePool(
        summary_row=_summary(inbound=0, outbound=0),
        usage_rows=[{"channel": "telegram", "messages": 0, "active_users": 0, "response_time_ms": 0, "inbound_messages": 0, "outbound_messages": 0}],
        conv_rows=[],
    )
    result = asyncio.run(ChannelManager(pool).analytics("org-1", days=30))
    assert result["channel_usage"][0]["response_rate_pct"] == 0.0
    assert result["response_rate_pct"] == 0.0


def test_analytics_computes_ai_resolution_rate_from_conversations_channel():
    pool = FakePool(
        summary_row=_summary(),
        usage_rows=[{"channel": "instagram", "messages": 5, "active_users": 2, "response_time_ms": 300, "inbound_messages": 3, "outbound_messages": 2}],
        conv_rows=[{"channel": "instagram", "conversations": 8, "ai_resolved_conversations": 6, "avg_rating": 4.5}],
    )
    result = asyncio.run(ChannelManager(pool).analytics("org-1", days=30))
    row = result["channel_usage"][0]
    assert row["ai_resolution_rate_pct"] == 75.0
    assert row["satisfaction_avg"] == 4.5
    assert row["conversations"] == 8


def test_analytics_resolution_rate_none_when_no_conversations_for_channel():
    pool = FakePool(
        summary_row=_summary(),
        usage_rows=[{"channel": "facebook", "messages": 1, "active_users": 1, "response_time_ms": 0, "inbound_messages": 1, "outbound_messages": 0}],
        conv_rows=[],
    )
    result = asyncio.run(ChannelManager(pool).analytics("org-1", days=30))
    row = result["channel_usage"][0]
    assert row["ai_resolution_rate_pct"] is None
    assert row["satisfaction_avg"] is None


def test_analytics_overall_ai_resolution_rate_aggregates_across_channels():
    pool = FakePool(
        summary_row=_summary(),
        usage_rows=[
            {"channel": "whatsapp", "messages": 5, "active_users": 2, "response_time_ms": 100, "inbound_messages": 3, "outbound_messages": 2},
            {"channel": "telegram", "messages": 5, "active_users": 2, "response_time_ms": 100, "inbound_messages": 3, "outbound_messages": 2},
        ],
        conv_rows=[
            {"channel": "whatsapp", "conversations": 10, "ai_resolved_conversations": 8, "avg_rating": 4.0},
            {"channel": "telegram", "conversations": 10, "ai_resolved_conversations": 5, "avg_rating": 3.0},
        ],
    )
    result = asyncio.run(ChannelManager(pool).analytics("org-1", days=30))
    assert result["ai_resolution_rate_pct"] == 65.0
    assert result["satisfaction_avg"] == 3.5


def test_analytics_query_scopes_conversations_by_org_id_and_window():
    pool = FakePool(summary_row=_summary(), usage_rows=[], conv_rows=[])
    asyncio.run(ChannelManager(pool).analytics("org-42", days=7))
    conv_call = next(c for c in pool.calls if c[0] == "fetch" and "FROM conversations" in c[1])
    assert conv_call[2] == ("org-42", 7)
    assert "org_id=$1" in conv_call[1]
