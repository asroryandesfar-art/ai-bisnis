"""
Validasi end-to-end (LLM nyata, bukan mock) untuk memory_agent.py — sesuai
skenario di spesifikasi "Production Readiness Phase":

  1. "Nama saya Asrori" -> 10 pesan netral lain -> "Siapa nama saya?"
     harus menjawab benar (fakta nama tersimpan & tersurfaced lewat
     UserProfile.to_context_string()).
  2. "Saya punya toko baju" -> 10 pesan netral lain -> "Promosi apa yang
     cocok?" harus tetap punya konteks bisnis sebelumnya.

Memory jangka panjang kini disimpan di Postgres (bukan file JSON lokal),
jadi tes ini jalan lewat pool DB sungguhan, di-passing ke
enrich_context()/run() lewat context["_observability_pool"] -- sama seperti
yang main.py /chat handler lakukan di production.

Test ini memanggil Groq sungguhan (lewat MemoryAgent._call_llm_json) karena
ekstraksi fakta adalah proses LLM-driven — di-skip otomatis jika
GROQ_API_KEY tidak terkonfigurasi di environment test.
"""
import asyncio
import uuid

import asyncpg
import pytest

import main
import memory_agent

pytestmark = pytest.mark.skipif(
    not main.cfg.groq_api_key,
    reason="GROQ_API_KEY tidak terkonfigurasi — skip validasi memory live",
)


def _run(coro_fn):
    async def _wrapped():
        pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            await coro_fn(pool)
        finally:
            await pool.close()
    asyncio.run(_wrapped())


def _fresh_agent() -> memory_agent.MemoryAgent:
    """Reset singleton store global supaya tiap test punya state bersih."""
    memory_agent._global_store = None
    return memory_agent.MemoryAgent(api_key=main.cfg.groq_api_key)


async def _turn(agent, pool, *, conv_id, user_id, org_id, bot_id, user_message, bot_response, history):
    """Simulasikan satu giliran percakapan nyata: enrich_context() (READ,
    sebelum CS Agent) lalu run() (WRITE, setelah Supervisor)."""
    enriched = await agent.enrich_context({
        "conversation_id": conv_id, "user_id": user_id,
        "org_id": org_id, "bot_id": bot_id, "user_message": user_message,
        "_observability_pool": pool,
    })
    enriched["bot_response"] = bot_response
    enriched["messages"] = list(history)
    result = await agent.run(enriched)
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": bot_response})
    return enriched, result


_FILLER_TURNS = [
    ("Jam operasional toko jam berapa?", "Toko kami buka setiap hari jam 09.00-21.00 ya."),
    ("Apakah bisa COD?", "Bisa, COD tersedia untuk wilayah tertentu."),
    ("Ongkir ke Surabaya berapa?", "Ongkir ke Surabaya sekitar Rp15.000-20.000 tergantung kurir."),
    ("Stok ukuran L masih ada?", "Untuk ukuran L silakan cek di halaman produk, stok update real-time."),
    ("Apakah ada diskon member?", "Ada, member dapat diskon 10% untuk setiap pembelian."),
    ("Cara bayar pakai apa saja?", "Bisa transfer bank, e-wallet, atau COD."),
    ("Berapa lama proses pengiriman?", "Proses pengiriman 1-3 hari kerja setelah pesanan dikonfirmasi."),
    ("Apakah barang bisa ditukar?", "Bisa ditukar dalam 7 hari selama barang belum dipakai."),
    ("Apakah ada toko fisik?", "Saat ini kami hanya jual online, belum ada toko fisik."),
    ("Terima kasih infonya", "Sama-sama, senang bisa membantu!"),
]
assert len(_FILLER_TURNS) == 10


def test_remembers_user_name_after_ten_unrelated_turns():
    async def body(pool):
        agent = _fresh_agent()
        conv_id = f"conv-{uuid.uuid4()}"
        user_id = f"user-{uuid.uuid4()}"
        org_id, bot_id = "test-org", "test-bot"
        history: list[dict] = []

        await _turn(
            agent, pool, conv_id=conv_id, user_id=user_id, org_id=org_id, bot_id=bot_id,
            user_message="Halo, nama saya Asrori",
            bot_response="Halo Asrori, senang bisa membantu Anda hari ini!",
            history=history,
        )

        for user_msg, bot_resp in _FILLER_TURNS:
            await _turn(
                agent, pool, conv_id=conv_id, user_id=user_id, org_id=org_id, bot_id=bot_id,
                user_message=user_msg, bot_response=bot_resp, history=history,
            )

        final_context = await agent.enrich_context({
            "conversation_id": conv_id, "user_id": user_id,
            "org_id": org_id, "bot_id": bot_id, "user_message": "Siapa nama saya?",
            "_observability_pool": pool,
        })
        kb_context = final_context.get("knowledge_base_context", "")
        assert "asrori" in kb_context.lower(), (
            f"Nama user 'Asrori' tidak ditemukan di knowledge_base_context setelah 10 giliran. "
            f"Isi context: {kb_context!r}"
        )

    _run(body)


def test_remembers_business_context_after_ten_unrelated_turns():
    async def body(pool):
        agent = _fresh_agent()
        conv_id = f"conv-{uuid.uuid4()}"
        user_id = f"user-{uuid.uuid4()}"
        org_id, bot_id = "test-org", "test-bot"
        history: list[dict] = []

        await _turn(
            agent, pool, conv_id=conv_id, user_id=user_id, org_id=org_id, bot_id=bot_id,
            user_message="Saya punya toko baju online",
            bot_response="Baik, saya catat ya. Toko baju online Anda mau dibantu apa?",
            history=history,
        )

        for user_msg, bot_resp in _FILLER_TURNS:
            await _turn(
                agent, pool, conv_id=conv_id, user_id=user_id, org_id=org_id, bot_id=bot_id,
                user_message=user_msg, bot_response=bot_resp, history=history,
            )

        final_context = await agent.enrich_context({
            "conversation_id": conv_id, "user_id": user_id,
            "org_id": org_id, "bot_id": bot_id, "user_message": "Promosi apa yang cocok untuk bisnis saya?",
            "_observability_pool": pool,
        })
        kb_context = final_context.get("knowledge_base_context", "")
        assert "baju" in kb_context.lower(), (
            f"Konteks bisnis 'toko baju' tidak ditemukan di knowledge_base_context setelah 10 giliran. "
            f"Isi context: {kb_context!r}"
        )

    _run(body)


def test_cross_conversation_profile_persists_for_same_user():
    """Fakta harus survive lintas conversation_id yang BERBEDA untuk user yang sama
    (UserProfile di-keyed oleh org_id:bot_id:user_id, bukan conv_id)."""
    async def body(pool):
        agent = _fresh_agent()
        user_id = f"user-{uuid.uuid4()}"
        org_id, bot_id = "test-org", "test-bot"

        conv_1 = f"conv-{uuid.uuid4()}"
        history_1: list[dict] = []
        await _turn(
            agent, pool, conv_id=conv_1, user_id=user_id, org_id=org_id, bot_id=bot_id,
            user_message="Nama saya Asrori dan saya punya toko baju",
            bot_response="Siap Asrori, dicatat ya.",
            history=history_1,
        )

        conv_2 = f"conv-{uuid.uuid4()}"
        final_context = await agent.enrich_context({
            "conversation_id": conv_2, "user_id": user_id,
            "org_id": org_id, "bot_id": bot_id, "user_message": "Siapa nama saya?",
            "_observability_pool": pool,
        })
        kb_context = final_context.get("knowledge_base_context", "")
        assert "asrori" in kb_context.lower(), (
            f"Fakta tidak survive lintas conversation_id berbeda untuk user yang sama. "
            f"Isi context: {kb_context!r}"
        )

    _run(body)
