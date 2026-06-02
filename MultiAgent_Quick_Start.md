# 🚀 MULAI DARI SINI - Multi-Agent AI Action Plan

Dokumen ini adalah quick-start praktis untuk system multi-agent BotNesia yang ada di repo ini.

---

## RINGKASAN

Kamu ingin sistem yang bisa:
- ngerti query user
- akses berita terbaru
- akses harga kripto / saham
- bikin gambar / video
- personalisasi jawaban sesuai user
- tetap jujur, tidak ngarang

Di repo ini, fondasinya **sudah ada**.

Yang aktif sekarang:
- multi-agent supervisor
- CS agent
- news pipeline
- market data pipeline
- Replicate media generation
- dashboard untuk testing

---

## FILE PENTING YANG SUDAH ADA

### Core runtime
- `C:\Users\asror\OneDrive\Dokumen\ai bisnis\main.py`
- `C:\Users\asror\OneDrive\Dokumen\ai bisnis\supervisor.py`
- `C:\Users\asror\OneDrive\Dokumen\ai bisnis\cs_agent.py`
- `C:\Users\asror\OneDrive\Dokumen\ai bisnis\analytics.py`
- `C:\Users\asror\OneDrive\Dokumen\ai bisnis\escalation.py`
- `C:\Users\asror\OneDrive\Dokumen\ai bisnis\trainer.py`

### Real-time data
- `C:\Users\asror\OneDrive\Dokumen\ai bisnis\news_fetcher.py`
- `C:\Users\asror\OneDrive\Dokumen\ai bisnis\finance_fetcher.py`

### Media
- `C:\Users\asror\OneDrive\Dokumen\ai bisnis\media_gen.py`

### Dashboard / UI
- `C:\Users\asror\OneDrive\Dokumen\ai bisnis\dashboard-connected.html`

---

## ARSITEKTUR SIMPEL

```text
User message
   ↓
Supervisor / Router
   ↓
CS Agent + optional helpers
   ├─ News fetcher
   ├─ Finance fetcher
   ├─ Escalation
   ├─ Analytics / training
   └─ Media generation
   ↓
Final response
```

---

## YANG SUDAH BERJALAN SEKARANG

### 1. Berita
- bisa ambil dari RSS / Atom
- bisa ambil dari Google News RSS
- bisa ambil dari URL artikel langsung
- bisa ekstrak kutipan penting

### 2. Market data
- kripto → CoinGecko
- saham → Yahoo Finance quote endpoint
- query campuran saham + kripto sudah didukung

### 3. Media
- gambar → Replicate Flux
- video → Replicate HappyHorse / Seedance

### 4. Tone
- bisa diarahkan lewat prompt / profile / style agent

---

## HAL YANG PERLU KAMU PAHAM

### Sumber tidak otomatis ditampilkan

Sistem sekarang dioptimalkan untuk:
- jawab isi dulu
- sumber / link hanya keluar jika user minta

Jadi default UX:
- lebih natural
- tidak berisik
- tidak seperti dump artikel

Kalau user minta:
- "sumbernya?"
- "kasih link"
- "mana referensinya?"

baru sumber ditampilkan.

---

## SETUP SINGKAT

### 1. Pastikan `.env` terisi

Minimal:

```env
GROQ_API_KEY=...
REPLICATE_API_TOKEN=...
REPLICATE_IMAGE_MODEL=black-forest-labs/flux-2-pro
REPLICATE_VIDEO_MODEL=alibaba/happyhorse-1.0,bytedance/seedance-2.0
NEWS_ENABLED=true
NEWS_RSS_FEEDS=...
```

### 2. Jalankan server

```bash
python run_server.py
```

atau pakai launcher:

```bash
start.cmd
```

### 3. Buka dashboard

```text
http://127.0.0.1:8000/dashboard
```

---

## TES CEPAT

### Market
- `harga btc sekarang`
- `harga saham apple dan btc sekarang`
- `berapa harga bbca hari ini`

### News
- `berita AI terbaru`
- `ringkas berita bitcoin hari ini`
- kirim URL artikel langsung

### Media
- `buat gambar tentang AI agents`
- `buat video futuristik tentang bitcoin`

---

## IMPLEMENTATION ORDER

### Hari ini
- cek `.env`
- restart server
- tes chat
- tes berita
- tes market
- tes gambar/video

### Minggu ini
- rapikan profile personalization
- tambah user memory
- tambah source-on-demand formatting
- tambah ranking berita khusus niche kamu

### Setelah itu
- monetization
- auth yang lebih rapi
- usage analytics
- per-user memory / preference

---

## GOAL PRAKTIS

Target terbaik untuk sistem ini bukan “semua bisa sempurna sekaligus”.

Target realistis:
1. current info akurat
2. tone enak
3. media jalan
4. tidak halusinasi
5. gampang dipakai user

Kalau 5 hal itu stabil, sistem ini sudah kuat banget.

