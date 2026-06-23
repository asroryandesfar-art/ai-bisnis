"""
general_ai_engine.py — General AI Agent untuk BotNesia.

Modul ini TIDAK memanggil LLM. Sama seperti business_consultant_engine.py:
hanya mendeteksi jenis pertanyaan (heuristik/regex) dan menyediakan blok
instruksi ("style guidance") yang digabungkan ke `knowledge_base_context`
oleh `reasoning_controller.ReasoningController.analyze()`.

Tujuan: BotNesia tidak boleh terasa "cuma bisa jawab FAQ perusahaan" --
pertanyaan umum (pengetahuan umum, terjemahan, penulisan kreatif, sains,
hitung-hitungan) di luar topik bisnis tenant harus dijawab penuh percaya
diri seperti asisten AI serba-bisa, bukan ditolak/diarahkan balik ke topik
bisnis.
"""
from __future__ import annotations

import re

GENERAL_AI_PATTERN = re.compile(
    r"apa\s+itu\s+\w|"
    r"siapa\s+(yang\s+menjadi\s+)?(presiden|wakil\s+presiden|gubernur|wali\s*kota|bupati|"
    r"menteri|perdana\s+menteri|raja|ratu|paus|ceo|ketua\s+umum|ilmuwan|penemu|penulis)\b|"
    r"jelaskan\s+(hukum|teori|konsep|rumus|sejarah|proses)|"
    r"terjemahkan|translate\s+(ke|to|dari)|artinya\s+dalam\s+bahasa|"
    r"dalam\s+bahasa\s+(inggris|indonesia|jepang|mandarin|arab|jerman|perancis|spanyol)|"
    r"buatkan\s+(puisi|cerita|cerpen|pantun|lagu|naskah|lirik|surat\s+(lamaran|resmi|izin))|"
    r"tuliskan\s+(puisi|cerita|cerpen|pantun)|tulis\s+(puisi|cerita|cerpen|pantun)|"
    r"buat\s+(puisi|pantun|cerpen)|"
    r"ringkas(kan)?\s+(artikel|teks|paragraf)|"
    r"hitung(kan|lah)?\s+\d|konversi(kan)?\s+\d",
    re.IGNORECASE,
)


def is_general_ai_request(text: str) -> bool:
    """True jika pesan adalah permintaan pengetahuan umum/terjemahan/penulisan
    kreatif/utilitas umum -- bukan pertanyaan seputar bisnis tenant."""
    return bool(GENERAL_AI_PATTERN.search(text or ""))


GENERAL_AI_BLOCK = """## General AI Agent (pengetahuan umum, di luar topik bisnis tenant)
Pertanyaan ini bersifat umum (pengetahuan umum, terjemahan, penulisan kreatif, sains,
hitung-hitungan, dll), BUKAN tentang bisnis/produk tenant. Jawab LANGSUNG dan LENGKAP
seperti asisten AI serbaguna:
- Jangan menolak atau mengarahkan balik ke topik bisnis/BotNesia hanya karena
  pertanyaannya bukan tentang bisnis tenant.
- Jangan bilang "saya hanya bisa membantu soal [bisnis tenant]" -- BotNesia tetap bisa
  membantu kebutuhan umum sehari-hari pengguna.
- Tetap ikuti Truthfulness Policy: jika kamu tidak yakin/tidak tahu suatu fakta spesifik
  (misal data terkini yang bisa berubah), katakan itu secara jujur -- jangan mengarang."""
