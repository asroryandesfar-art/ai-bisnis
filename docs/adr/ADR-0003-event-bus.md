# ADR-0003 — Event Bus (`event_bus`)

- **Status:** Accepted — in-process backend selesai; Redis Streams menyusul
- **Tanggal:** 2026-07-22
- **Konteks fase:** Fase 1 Fondasi Platform, item **P0-C**
- **Terkait:** ADR-0001 (shared state), P0-D (durable runtime = produser pertama)

## Konteks
Modul saling memanggil langsung (mis. penulisan memory, workflow, web-intelligence)
→ coupling erat, sulit menambah konsumen (observability, evaluasi, memory) tanpa
mengubah produser. Butuh mekanisme publish/subscribe standar.

## Keputusan
Modul mandiri `event_bus` dengan `publish(type, payload)` + `subscribe(type, handler)`.
Backend default **in-process**: dispatch sinkron per-publish, error tiap handler
**diisolasi** (satu konsumen gagal tak merusak publisher/konsumen lain), handler
sync/async didukung, ada wildcard `*` untuk observability. Envelope terstandardisasi
`{id, type, org_id, ts, payload, trace_id}`. Konstanta tipe event di `events.py`
(TaskStarted/Finished/Failed, MemoryUpdated, KnowledgeUpdated, Browser/Scraper
Finished, WorkflowCompleted).

## Alternatif
1. **Message broker penuh (Kafka/RabbitMQ).** Ditolak: berat untuk kebutuhan awal; Redis sudah ada.
2. **Panggilan langsung (status quo).** Ditolak: coupling, sulit di-extend.
3. **In-process bus + jalur Redis Streams (DIPILIH).** Risiko terkecil (additive, sinkron, testable), Redis Streams belakangan untuk durability lintas-proses.

## Konsekuensi
**Positif:** decoupling; konsumen baru (observability/eval/memory) tinggal subscribe tanpa menyentuh produser; testable & error-isolated.
**Batasan (jujur):** in-process = konsumen berjalan di proses & waktu publisher (handler lambat menahan publisher); tidak durable lintas-proses/restart. **Follow-up:** backend Redis Streams (consumer group, retry, DLQ, replay) di belakang antarmuka yang sama, di-gate feature flag (P0-B).

## Rollback
Modul bisa idle (zero wiring saat ini). Produser/konsumen mengadopsi bertahap; lepas subscribe → tak ada efek.

## Status implementasi
- ✅ in-process bus + envelope + wildcard + isolasi error + 8 test.
- ⏳ Redis Streams backend (durable) + konsumen worker.
- Produser pertama: P0-D (TaskStarted/Finished/Failed).
