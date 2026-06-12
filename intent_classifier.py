"""
intent_classifier.py — Klasifikasi kompleksitas pesan untuk pipeline adaptif.

Menentukan apakah pesan user butuh full reasoning pipeline (Pro) atau cukup
jalur cepat (Standard). Heuristik dulu (gratis); LLM hanya dipanggil untuk
kasus ambigu, dengan satu panggilan kecil ber-format JSON.
"""
from __future__ import annotations

from base import BaseAgent

# Pesan yang cocok pola ini SELALU dianggap simple — tidak pernah memanggil LLM.
_SIMPLE_PATTERNS = (
    "halo", "hai", "hi", "hello", "selamat",
    "terima kasih", "thanks", "makasih",
    "harga paket", "berapa harga", "biaya berapa",
    "jam operasional", "alamat", "kontak",
)

# Pesan yang mengandung kata-kata ini cenderung butuh analisis/penalaran.
_COMPLEX_HINTS = (
    "kenapa", "mengapa", "analisis", "analisa", "bandingkan", "perbandingan",
    "rekomendasi strategi", "prediksi", "outlook", "dampak", "risiko",
    "kelebihan dan kekurangan", "trade-off", "trade off",
    # Pertanyaan komparatif/analitis tentang BotNesia atau bisnis tenant
    "bedanya", "perbedaan", "kelemahan", "bagaimana cara", "cara meningkatkan",
    "cara menaikkan",
)

MAX_SIMPLE_LEN = 60  # karakter — pesan pendek sangat mungkin simple


def heuristic_complexity(user_message: str) -> str | None:
    """Return 'simple' | 'complex' | None (None = perlu penilaian LLM)."""
    text = (user_message or "").strip().lower()
    if not text:
        return "simple"
    if any(h in text for h in _COMPLEX_HINTS):
        return "complex"
    if len(text) <= MAX_SIMPLE_LEN:
        return "simple"
    if any(p in text for p in _SIMPLE_PATTERNS):
        return "simple"
    return None  # ambigu -> LLM


class IntentClassifier(BaseAgent):
    name = "intent_classifier"
    system_prompt = (
        "Kamu adalah pengklasifikasi niat pesan untuk chatbot bisnis. "
        "Balas HANYA dalam format JSON."
    )

    async def classify(self, user_message: str) -> dict:
        """
        Returns: {"complexity": "simple"|"complex", "reason": str, "source": "heuristic"|"llm"}
        """
        h = heuristic_complexity(user_message)
        if h is not None:
            return {"complexity": h, "reason": "heuristic", "source": "heuristic"}

        if not self.api_key:
            return {"complexity": "simple", "reason": "no_llm_fallback", "source": "heuristic"}

        prompt = (
            "Klasifikasikan pesan berikut sebagai 'simple' atau 'complex'.\n"
            "'simple' = sapaan, FAQ, harga produk, pertanyaan singkat satu fakta.\n"
            "'complex' = butuh analisis/penalaran multi-faktor, perbandingan, "
            "penjelasan kausal (kenapa/mengapa), rekomendasi strategis.\n\n"
            f"Pesan: {user_message}\n\n"
            'Jawab dalam format JSON: {"complexity": "simple"|"complex", "reason": "<alasan singkat>"}'
        )
        result = await self._call_llm_json(
            [{"role": "system", "content": self.system_prompt},
             {"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=80,
            default={"complexity": "simple", "reason": "parse_error"},
        )
        result.setdefault("complexity", "simple")
        if result["complexity"] not in ("simple", "complex"):
            result["complexity"] = "simple"
        result["source"] = "llm"
        return result
