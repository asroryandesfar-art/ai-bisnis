# 🔌 Multi-Agent → BotNesia App Integration Map

Dokumen ini menjelaskan **langkah berikutnya** untuk menghubungkan framework multi-agent ke aplikasi BotNesia yang sedang aktif.

---

## 1. Tujuan

Ada 2 jalur kerja yang sekarang disatukan:

1. **Framework / dokumentasi / template**
2. **App production yang benar-benar jalan**

Targetnya bukan membuat sistem baru dari nol, tapi:
- memakai framework sebagai panduan
- menghubungkannya ke runtime BotNesia sekarang
- memastikan semua agent punya titik sambung yang jelas

---

## 2. Mapping Framework → Runtime Aktif

| Framework Concept | BotNesia Runtime |
|---|---|
| Router Agent | `supervisor.py` |
| Content / CS Agent | `cs_agent.py` |
| News Agent | `news_fetcher.py` |
| Market Data Agent | `finance_fetcher.py` |
| Personality Adapter | `cs_agent.py` + system prompt strategy |
| Visual Agent | `media_gen.py` + `/media/image` + `/media/video` |
| Escalation Agent | `escalation.py` |
| Analytics Agent | `analytics.py` |
| Trainer Agent | `trainer.py` |
| App Entry | `main.py` |

---

## 3. Langkah Teknis Berikutnya

### A. Router / Supervisor

**Status sekarang**
- Sudah ada di `supervisor.py`
- Sudah dipakai dari `main.py`

**Next step**
- tambah explicit routing flags untuk:
  - `needs_news`
  - `needs_market`
  - `needs_visual`
  - `needs_source_exposure`

**Tujuan**
- supaya keputusan agent lebih transparan dan gampang di-debug

---

### B. News Agent

**Status sekarang**
- `news_fetcher.py` sudah support:
  - RSS
  - Atom
  - URL artikel langsung
  - Google News wrapper

**Next step**
- tambah ranking berbasis kategori user
- tambah cache query berita populer
- tambah "source-on-demand formatter"

**Tujuan**
- berita lebih relevan
- lebih hemat request
- sumber hanya keluar saat user minta

---

### C. Market Data Agent

**Status sekarang**
- `finance_fetcher.py` sudah support:
  - crypto via CoinGecko
  - stock via Yahoo Finance quote

**Next step**
- tambah alias saham Indonesia lebih banyak
- tambah formatter untuk multi-asset comparison
- tambah handling query seperti:
  - "bandingkan BTC vs NVDA"
  - "top movers"

---

### D. Personality Layer

**Status sekarang**
- personality mostly ada di prompt engineering

**Next step**
- simpan profile user per org/user/session
- buat preset:
  - critical
  - balanced
  - optimistic
  - mentor
  - friend

**Tujuan**
- respons konsisten
- tidak perlu re-prompt manual tiap saat

---

### E. Visual / Media

**Status sekarang**
- `/media/image` dan `/media/video` sudah aktif
- Replicate image/video models sudah terhubung

**Next step**
- buat mode:
  - prompt-only
  - generate-now
- tambah preset:
  - thumbnail
  - infographic
  - cinematic
  - product visual

---

## 4. Perubahan Paling Bernilai Setelah Ini

Kalau mau prioritas paling efektif:

### Prioritas 1
- simpan `user profile`
- router aware terhadap profile

### Prioritas 2
- cache news + market
- kurangi latency

### Prioritas 3
- visual preset + reusable content preset

### Prioritas 4
- admin page untuk lihat:
  - routing decisions
  - fetched news context
  - market context
  - final answer path

---

## 5. Saran Implementasi Praktis

### Week 1
- finalize routing flags
- finalize source-on-demand
- persist profile minimum

### Week 2
- add memory per user/session
- add analytics page for agent traces

### Week 3
- add content presets + media presets
- start packaging for team / client use

---

## 6. Outcome yang Diinginkan

Kalau semua next step ini dilakukan, BotNesia akan jadi:

- current-info aware
- personalized
- multi-agent by design
- source-safe
- visual-capable
- production-ready

Dan yang paling penting: tetap nyambung ke sistem yang sekarang, bukan bikin arsitektur baru yang putus dari runtime aktif.

