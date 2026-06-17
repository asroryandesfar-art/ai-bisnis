"""
E2E: Frontend-equivalent (TestClient) -> API -> Supervisor -> Agent ->
Knowledge -> Database -> Response, for the core chat flow. Real Postgres,
real Groq — no FakePool/mocks (see tests/e2e/conftest.py).
"""


def test_chat_returns_real_answer_with_routing_metadata(client, bot):
    resp = client.post(f"/chat/{bot}", json={"message": "Apa itu Bitcoin?"})
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert isinstance(data["answer"], str) and data["answer"].strip()
    assert data["session_id"]
    assert data["message_id"]
    assert isinstance(data["latency_ms"], int)
    assert data["intent"] in (
        "general", "business", "faq", "sales", "customer_service",
        "knowledge", "analytics", "human_handoff",
    )
    assert data["selected_agent"]
    # "Confidence routing wajib tampil"
    assert data["confidence"] is not None
    assert 0.0 <= data["confidence"] <= 1.0
    assert isinstance(data["handoff_offered"], bool)


def test_chat_persists_messages_and_continues_session(client, bot):
    first = client.post(f"/chat/{bot}", json={"message": "Halo, nama saya Budi"})
    assert first.status_code == 200, first.text
    session_id = first.json()["session_id"]

    second = client.post(f"/chat/{bot}", json={
        "message": "Apa kabar?", "session_id": session_id,
    })
    assert second.status_code == 200, second.text
    assert second.json()["session_id"] == session_id


def test_chat_against_inactive_or_missing_bot_returns_404(client):
    import uuid
    resp = client.post(f"/chat/{uuid.uuid4()}", json={"message": "Halo"})
    assert resp.status_code == 404
