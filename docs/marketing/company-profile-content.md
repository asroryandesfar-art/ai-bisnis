# BotNesia — Company Profile (Source Content)

Ini adalah source-of-truth teks untuk `BotNesia-Company-Profile.pdf` (versi profesional,
revisi 2026-06-22). Edit teks di sini, lalu salin ke `scripts/generate_company_profile_pdf.py`
(fungsi `build_story()`) dan jalankan:

```
python3 scripts/capture_marketing_screenshots.py   # regenerate 3 screenshot (perlu server lokal jalan)
python3 scripts/generate_company_profile_pdf.py    # regenerate PDF
```

**Catatan desain:** PDF ini sekarang dirender langsung dengan reportlab Platypus (bukan lewat
`document_generator.generate_pdf()` yang generik) supaya bisa punya layout 2 kolom, kartu
bertinta warna, dan screenshot tertanam — gaya "modern startup", bukan dokumen polos.

## Apa itu BotNesia?
AI Workforce Platform untuk bisnis Indonesia: tim AI lengkap (Customer Service, Sales, Marketing, Finance, HR, Operations, Security, Executive Assistant) bekerja 24/7, tanpa pelanggan membangun tim teknologi sendiri.

## Visi & Misi
**Visi:** Menjadi platform AI Workforce nomor satu di Indonesia — setiap UMKM hingga perusahaan besar bisa memiliki tim AI selengkap perusahaan teknologi besar, tanpa membangun tim engineering sendiri.

**Misi:** Membantu jutaan UMKM dan perusahaan Indonesia menggunakan AI tanpa harus memiliki tim teknologi mahal.

## Current Stage (menggantikan badge "Investor/Government/PDF Ready")
- Multi-Agent AI Workforce Platform — dibangun dan beroperasi penuh (8+ AI agent: CS, Sales, Marketing, Finance, HR, Operations, Security, Executive)
- Arsitektur multi-tenant tingkat enterprise — RBAC, audit log, isolasi data per workspace
- Public Interactive Demo — live dan bisa diakses publik tanpa pendaftaran
- Executive Analytics & AI Business Analyst — beroperasi, menghasilkan root cause analysis dan rekomendasi nyata dari data live
- Pengembangan berkelanjutan — platform terus diperluas secara aktif

*Catatan penyesuaian dari draft awal user: "MVP Completed" diganti jadi pernyataan yang lebih akurat (platform sudah jauh melampaui MVP — 20 fase pembangunan AI Workforce sudah live), dan "Pilot Customer Program Open"/"Strategic Partnership Opportunities" dipindah jadi kalimat undangan terbuka di bagian Closing (bukan diklaim sebagai program yang sudah berjalan, karena belum ada bukti program pilot formal yang aktif) — supaya section ini tetap 100% bisa diverifikasi, sesuai instruksi.*

## Screenshot
1. **Landing Page** — `app.botnesia.uk`
2. **Executive Center** — company health score & AI Business Analyst
3. **Investor Demo Mode** — analisis AI live, publik tanpa login (`app.botnesia.uk/demo`)

(Regenerate via `scripts/capture_marketing_screenshots.py`, disimpan di `docs/marketing/screenshots/`.)

## Target Market & Technology
**Target Market:** UMKM, bisnis menengah (SME), dan enterprise yang butuh AI Workforce multi-tenant dengan kendali akses korporat.

**Technology:** FastAPI + PostgreSQL, Groq LLM, arsitektur multi-agent dengan Supervisor Agent; keputusan penting selalu memerlukan persetujuan manusia.

## Founder Story
Didirikan oleh Asrori, yang melihat jarak antara bisnis kecil-menengah Indonesia dengan AI yang sebenarnya bisa membantu mereka tumbuh — bukan karena teknologinya tidak ada, tapi karena terlalu mahal dan rumit untuk dipasang sendiri.

Misi pendiri: *"Membantu jutaan UMKM dan perusahaan Indonesia menggunakan AI tanpa harus memiliki tim teknologi mahal."*

## Closing (kotak highlight ungu)
**Mari Berkolaborasi**

BotNesia is currently focused on helping Indonesian businesses adopt AI through a practical, affordable, and scalable AI Workforce platform.

We are open to pilot programs, partnerships, incubation opportunities, and strategic collaborations.

## Kontak (footer)
asroryandesfar@gmail.com · app.botnesia.uk · app.botnesia.uk/demo (demo interaktif, tanpa pendaftaran)
