import asyncio
from pathlib import Path

from bn_platform.feedback_learning import (
    FeedbackRequest,
    classify_learning_action,
    record_feedback,
)


def test_learning_action_classification():
    assert classify_learning_action(
        answer="Maaf, saya tidak tahu.", model="multi-agent", source_chunks=[]
    )[0] == "knowledge"
    assert classify_learning_action(
        answer="Jawaban tersedia tetapi kurang membantu.", model="multi-agent", source_chunks=["chunk-1"]
    )[0] == "prompt"
    assert classify_learning_action(
        answer="AI gagal.", model="system:human-handoff", source_chunks=[]
    )[0] == "workflow"


class AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self):
        self.calls = []

    def transaction(self):
        return AsyncContext(self)

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return {
            "id": "feedback-1", "tenant_id": "tenant-1",
            "conversation_id": "conversation-1", "message_id": "message-1",
            "rating": args[4], "comment": args[5], "created_at": "now",
        }

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return "OK"


class FakePool:
    def __init__(self, message):
        self.message = message
        self.connection = FakeConnection()

    async def fetchrow(self, sql, *args):
        return self.message

    def acquire(self):
        return AsyncContext(self.connection)


def message_record(*, model="multi-agent", source_chunks=None):
    return {
        "id": "message-1", "answer": "Jawaban AI", "model": model,
        "source_chunks": ["chunk-1"] if source_chunks is None else source_chunks,
        "conversation_id": "conversation-1", "bot_id": "bot-1",
        "org_id": "tenant-1", "question": "Bagaimana cara refund?",
    }


def test_negative_feedback_creates_actionable_learning_queue_item():
    pool = FakePool(message_record())
    body = FeedbackRequest(
        message_id="message-1", conversation_id="conversation-1",
        rating="not_helpful", comment="Jawaban tidak menjelaskan langkahnya.",
    )

    result = asyncio.run(record_feedback(pool, tenant_id="tenant-1", body=body))

    queue_call = next(call for call in pool.connection.calls if "INSERT INTO feedback_learning_queue" in call[1])
    assert result["rating"] == "not_helpful"
    assert queue_call[2][5] == "Bagaimana cara refund?"
    assert queue_call[2][8] == "prompt"


def test_helpful_feedback_dismisses_pending_learning_item():
    pool = FakePool(message_record())
    body = FeedbackRequest(
        message_id="message-1", conversation_id="conversation-1", rating="helpful",
    )

    asyncio.run(record_feedback(pool, tenant_id="tenant-1", body=body))

    assert any("status='dismissed'" in sql for kind, sql, _ in pool.connection.calls if kind == "execute")


def test_feedback_learning_routes_schema_and_ui_are_present():
    import main

    paths = {getattr(route, "path", "") for route in main.app.routes}
    assert "/api/feedback-learning/feedback" in paths
    assert "/api/feedback-learning/public/{bot_id}" in paths
    assert "/api/feedback-learning/summary" in paths
    assert "/api/feedback-learning/queue" in paths
    assert "/api/feedback-learning/queue/{item_id}" in paths

    schema = (Path(__file__).resolve().parent / "schema.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS feedback_records" in schema
    assert "CREATE TABLE IF NOT EXISTS feedback_learning_queue" in schema
    for field in ("tenant_id", "conversation_id", "rating", "comment", "created_at"):
        assert field in schema

    root = Path(__file__).resolve().parent
    # UI strings may live in app.js or i18n.js (post i18n migration).
    frontend = "\n".join((root / f"frontend/{f}").read_text() for f in ("app.js", "i18n.js"))
    sdk = (root / "api.js").read_text()
    assert "/api/feedback-learning/public/${botId}" in sdk
    assert "👍 Helpful" in frontend
    assert "👎 Not Helpful" in frontend
    assert "Top Positive Feedback" in frontend
    assert "Most Failed Questions" in frontend
