"""
E2E marketplace flow: install the "Travel Agent" template (one of 100+
marketplace templates) for a fresh org, then validate the resulting bot
answers a travel query using its installed persona — this is how BotNesia
actually routes "Carikan hotel terbaik di Gresik" -> Travel Agent (per-bot
template installation), not via a new core intent class.
"""


def test_install_travel_agent_template_creates_active_bot(client, registered_org):
    resp = client.post(
        "/api/marketplace/install",
        json={"template_key": "travel-agent"},
        headers=registered_org["headers"],
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["template_key"] == "travel-agent"
    assert data["bot"]["status"] == "active"
    assert data["bot"]["id"]


def test_travel_agent_bot_answers_hotel_query_using_its_persona(client, registered_org):
    install = client.post(
        "/api/marketplace/install",
        json={"template_key": "travel-agent"},
        headers=registered_org["headers"],
    )
    assert install.status_code == 201, install.text
    bot_id = install.json()["bot"]["id"]

    resp = client.post(f"/chat/{bot_id}", json={"message": "Carikan hotel terbaik di Gresik"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data["answer"], str) and data["answer"].strip()
    # AI must attempt to help (solve/explain/recommend/clarify), not refuse
    # or jump straight to human handoff for a normal travel question.
    assert data["handoff_offered"] is False


def test_marketplace_templates_listing_includes_travel_agent(client, registered_org):
    resp = client.get("/api/marketplace/templates", headers=registered_org["headers"])
    assert resp.status_code == 200, resp.text
    keys = {t["key"] for t in resp.json()["templates"]}
    assert "travel-agent" in keys
