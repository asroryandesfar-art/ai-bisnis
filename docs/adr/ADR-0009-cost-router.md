# ADR-0009 — Cost Router (routing model per kelas tugas)

- **Status:** Accepted — classifier 5-arah + `route_for_message` + wiring chat-stream (opt-in) selesai
- **Tanggal:** 2026-07-22
- **Konteks fase:** Fase 3 (Efisiensi & Operabilitas), item **P2-A**
- **Terkait:** ADR-0002 (feature flag), ADR-0007 (Evaluation — kalibrasi ke depan), SmartModelRouter

## Konteks
Audit: routing model masih **binary** (`cost_intelligence.choose_model` → economy/
quality) & provider chain fixed; belum memilih model sesuai **jenis** tugas
(coding→coding-model, complex→reasoning, vision→vision) → potensi overspend
(task ringan ke model mahal) atau underserve.

## Keputusan
Tambah **classifier 5-arah** `classify_task_class(msg, reasoning_mode, has_image)`
→ simple|medium|complex|coding|vision (deterministik: hint vision/coding →
heuristic_complexity → panjang). `router_params(class)` → `{tier, task_type}` yang
DIKENALI SmartModelRouter (task_type: standard/reasoning/coding/multimodal).
`SmartModelRouter.route_for_message/stream_for_message` = klasifikasi→route otomatis.
Wired ke `chat_streaming.stream_answer` (opt-in `user_message`/`org_id`), **gate
`is_enabled("cost_router", org_id)`** — OFF/tanpa user_message → perilaku lama
(`task_type="standard"`) byte-identik.

## Alternatif
1. **Classifier LLM.** Ditolak untuk gate awal: latensi/biaya per pesan; heuristik deterministik dulu (bisa di-augment LLM nanti).
2. **Ubah choose_model binary jadi 5-arah.** Ditolak: choose_model hanya punya cheap/strong; model reasoning/coding/vision ada di SmartModelRouter via task_type → arahkan ke sana.
3. **Classifier + task_type→SmartModelRouter (DIPILIH).** Reuse provider mapping existing; additive; backward-compatible.

## Konsekuensi
**Positif:** task ringan tetap murah (DeepSeek-chat), complex→R1, coding→Claude/deepseek-chat, vision→Gemini → hemat biaya + kualitas lebih pas. Sinyal Evaluation (P1-D) bisa mengkalibrasi mapping. **Batasan/GOTCHA:** `task_type` untuk simple/medium WAJIB `"standard"` (BUKAN `"chat"` — `chat` ada di `deepseek._SKIP_TASKS` → DeepSeek tak resolve → streaming tanpa provider); provider chain akhir tetap milik SmartModelRouter (vision butuh Gemini terkonfigurasi).

## Rencana
- **P2-A (selesai):** classifier + mapping + `route_for_message` + wiring chat-stream (flag-gated). 8 test.
- **P2-A.2:** wire jalur agent LLM lain (`route_for_message`) + kalibrasi mapping dari `task_evaluations` (biaya vs skor). Klasifikasi LLM-augmented untuk kasus ambigu.

## Rollback
Flag `cost_router` OFF → `task_type="standard"` (perilaku lama). Fungsi baru additive/idle.
