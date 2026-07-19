"""Deteksi eksekusi 'zombie' — running yang macet melewati ambang → stalled/OFFLINE."""
from datetime import datetime, timezone, timedelta

from bn_platform.ai_observability import is_stalled, STALL_SECONDS


def test_running_beyond_threshold_is_stalled():
    old = datetime.now(timezone.utc) - timedelta(seconds=STALL_SECONDS + 60)
    assert is_stalled("running", old) is True


def test_running_recent_not_stalled():
    recent = datetime.now(timezone.utc) - timedelta(seconds=5)
    assert is_stalled("running", recent) is False


def test_completed_statuses_never_stalled():
    old = datetime.now(timezone.utc) - timedelta(days=1)
    assert is_stalled("success", old) is False
    assert is_stalled("error", old) is False
    assert is_stalled("skipped", old) is False


def test_none_last_seen_not_stalled():
    assert is_stalled("running", None) is False


def test_naive_datetime_handled():
    naive = datetime.utcnow() - timedelta(seconds=STALL_SECONDS + 30)  # tanpa tz
    assert is_stalled("running", naive) is True


def test_stall_seconds_configured():
    assert STALL_SECONDS >= 1
