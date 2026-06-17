"""
E2E routing validation through the REAL /chat/{bot_id} endpoint (not just
unit-level route_intent()) — mirrors the 5 core scenarios from
test_routing_validation.py but exercising the full real stack.
"""
import pytest


@pytest.mark.parametrize(
    ("message", "expected_intent"),
    [
        ("Apa itu Bitcoin?", "general"),
        ("Saya mau bicara dengan admin", "human_handoff"),
    ],
)
def test_chat_routes_to_expected_intent(client, bot, chat_user_meta, message, expected_intent):
    resp = client.post(f"/chat/{bot}", json={"message": message, "user_meta": chat_user_meta})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["intent"] == expected_intent, data
    assert data["confidence"] is not None


def test_explicit_admin_request_allows_handoff_through_real_endpoint(client, bot, chat_user_meta):
    resp = client.post(f"/chat/{bot}", json={"message": "Saya mau bicara dengan admin", "user_meta": chat_user_meta})
    assert resp.status_code == 200, resp.text
    assert resp.json()["handoff_offered"] is True


def test_administrasi_question_does_not_falsely_trigger_handoff(client, bot, chat_user_meta):
    """Regression for the real bug fixed in handoff_guard.py/escalation.py:
    'admin' as a substring of 'administrasi' used to falsely trigger handoff."""
    resp = client.post(f"/chat/{bot}", json={"message": "Biaya administrasi bulanan berapa ya?", "user_meta": chat_user_meta})
    assert resp.status_code == 200, resp.text
    assert resp.json()["handoff_offered"] is False
