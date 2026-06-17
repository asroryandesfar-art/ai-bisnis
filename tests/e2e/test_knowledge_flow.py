"""
E2E knowledge flow: upload a document to a bot's knowledge base, confirm it
indexes (processing is synchronous in _process_document_sync, so status is
already final by the time upload returns), then ask a question only that
document can answer and confirm the response actually uses it (not a
generic fallback).
"""

UNIQUE_FACT = "Toko kami buka jam 08:00 dan tutup jam 22:00 setiap hari Senin sampai Minggu."


def test_uploaded_document_indexes_successfully(client, registered_org, bot):
    files = {"file": ("jam-operasional.txt", UNIQUE_FACT.encode("utf-8"), "text/plain")}
    resp = client.post(
        f"/bots/{bot}/documents", files=files, headers=registered_org["headers"],
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "ready", data


def test_chat_uses_uploaded_knowledge_to_answer(client, registered_org, bot):
    files = {"file": ("jam-operasional.txt", UNIQUE_FACT.encode("utf-8"), "text/plain")}
    upload = client.post(
        f"/bots/{bot}/documents", files=files, headers=registered_org["headers"],
    )
    assert upload.status_code == 201, upload.text
    assert upload.json()["status"] == "ready"

    resp = client.post(f"/chat/{bot}", json={"message": "Jam berapa toko buka dan tutup?"})
    assert resp.status_code == 200, resp.text
    answer = resp.json()["answer"].lower()
    assert "08:00" in answer or "08.00" in answer or "jam 8" in answer, (
        f"Jawaban tidak menggunakan informasi dari knowledge base yang baru diupload: {answer!r}"
    )


def test_url_ingestion_rejects_internal_network_target(client, registered_org, bot):
    """SSRF regression: /bots/{bot_id}/documents/url used to fetch ANY
    submitted URL server-side with zero validation. A malicious/curious
    tenant could point it at a cloud metadata endpoint or internal service."""
    resp = client.post(
        f"/bots/{bot}/documents/url",
        json={"url": "http://169.254.169.254/latest/meta-data/"},
        headers=registered_org["headers"],
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "failed", data
