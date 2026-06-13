import re


_ORDINALS = (
    "", "Pertama", "Kedua", "Ketiga", "Keempat", "Kelima",
    "Keenam", "Ketujuh", "Kedelapan", "Kesembilan", "Kesepuluh",
)


def normalize_tts_text(value: str) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"https?://\S+", " tautan ", text)
    text = re.sub(r"^\s*#{1,6}\s+", "", text, flags=re.MULTILINE)

    def numbered_item(match: re.Match[str]) -> str:
        number = int(match.group(1))
        label = _ORDINALS[number] if number < len(_ORDINALS) else f"Nomor {number}"
        return f"{label}, "

    text = re.sub(r"^\s*(\d{1,2})[.)]\s+", numbered_item, text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[;]+", ",", text)
    text = re.sub(r"[:]+(?=\s)", ",", text)
    text = re.sub(r"[!?]{2,}", lambda match: match.group(0)[0], text)
    text = re.sub(r"\.{3,}", ".", text)
    text = re.sub(r"[*_`#>|~]", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(
        r"([.!?,])?\s*\n{2,}\s*",
        lambda match: f"{match.group(1)} " if match.group(1) else ". ",
        text,
    )
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"\s+([,.;!?])", r"\1", text)
    text = re.sub(r"([.!?])(?=[A-Za-zÀ-ÿ])", r"\1 ", text)
    text = re.sub(r",{2,}", ",", text)
    return re.sub(r"\s+", " ", text).strip()
