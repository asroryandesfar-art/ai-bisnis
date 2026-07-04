"""
CARA SAMBUNGKAN multi-agent ke BotNesia main.py
================================================
Tambahkan kode di bawah ini ke chat() endpoint di main.py BotNesia,
SETELAH membangun konteks (system prompt + knowledge base) dan SEBELUM return.

Lokasi: setelah baris `answer = data["choices"][0]["message"]["content"]`
"""

# ── Tambahkan di Settings class BotNesia (main.py) ────────────────
"""
agent_url:    str = "http://localhost:8001"
agent_secret: str = "agent-secret-ganti-ini-dengan-random-string"
"""

# ── Tambahkan helper function di main.py BotNesia ─────────────────
async def call_agent_pipeline(
    bot_id:          str,
    org_id:          str,
    conversation_id: str,
    user_message:    str,
    messages:        list,
    knowledge_base_context: str = "",
    resolved:        bool = False,
) -> dict | None:
    """
    Kirim pesan ke multi-agent system dan return hasilnya.
    Return None jika agent system tidak tersedia (graceful fallback).
    """
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            res = await client.post(
                f"{cfg.agent_url}/process",
                json={
                    "bot_id":                 bot_id,
                    "org_id":                 org_id,
                    "conversation_id":        conversation_id,
                    "user_message":           user_message,
                    "messages":               messages,
                    "knowledge_base_context": knowledge_base_context,
                    "resolved":               resolved,
                },
                headers={"x-agent-secret": cfg.agent_secret},
            )
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"[Agent] Pipeline tidak tersedia: {e}")
    return None


# ── Tambahkan di dalam chat() endpoint, setelah dapat `answer` ───
"""
Di dalam async def chat(bot_id, body, pool):
  ...
  # Setelah: answer = data["choices"][0]["message"]["content"]
  
  # Panggil agent pipeline (non-blocking fallback)
  agent_data = await call_agent_pipeline(
      bot_id          = bot_id,
      org_id          = str(bot["org_id"]),
      conversation_id = conv_id,
      user_message    = body.message,
      messages        = messages_for_llm,  # riwayat percakapan
      knowledge_base_context = system,        # system prompt termasuk KB chunks
  )

  # Jika agent berhasil, pakai jawaban yang sudah disempurnakan
  if agent_data:
      answer = agent_data.get("final_answer", answer)

      # Handle escalation
      if agent_data.get("should_escalate"):
          await pool.execute(
              "UPDATE conversations SET handoff_needed=TRUE WHERE id=$1",
              conv_id,
          )
          # Kirim webhook ke klien jika perlu
          await dispatch_webhook(
              str(bot["org_id"]),
              "handoff.needed",
              {
                  "conv_id":       conv_id,
                  "urgency":       agent_data.get("escalation_urgency"),
                  "reason":        agent_data.get("escalation_message"),
                  "recommended_team": agent_data.get("recommended_team"),
              },
              pool,
          )

      # Simpan analytics dari agent ke DB (opsional)
      analytics = agent_data.get("analytics", {})
      # Contoh: simpan sentiment score
      # await pool.execute(
      #     "UPDATE conversations SET sentiment_score=$1 WHERE id=$2",
      #     analytics.get("sentiment", {}).get("score", 0),
      #     conv_id,
      # )
  
  # Lanjut seperti biasa dengan answer yang sudah mungkin disempurnakan
  ...
"""

# ── Test manual via curl ────────────────────────────────────────
"""
# 1. Jalankan agent server:
uvicorn agent_api:app --reload --port 8001

# 2. Test langsung:
curl -X POST http://localhost:8001/process \
  -H "Content-Type: application/json" \
  -H "x-agent-secret: agent-secret-ganti-ini-dengan-random-string" \
  -d '{
    "bot_id": "bot-123",
    "org_id": "org-123",
    "conversation_id": "conv-456",
    "user_message": "Pesanan saya sudah seminggu belum sampai, ini penipuan!",
    "messages": [
      {"role": "user", "content": "Halo"},
      {"role": "assistant", "content": "Halo! Ada yang bisa dibantu?"},
      {"role": "user", "content": "Pesanan saya sudah seminggu belum sampai, ini penipuan!"}
    ],
    "knowledge_base_context": "Estimasi pengiriman: 3-5 hari kerja. Untuk komplain: hubungi CS."
  }'

# 3. Cek insights:
curl http://localhost:8001/insights/bot-123 \
  -H "x-agent-secret: agent-secret-ganti-ini-dengan-random-string"

# 4. Cek training recommendations:
curl http://localhost:8001/training/bot-123 \
  -H "x-agent-secret: agent-secret-ganti-ini-dengan-random-string"
"""
