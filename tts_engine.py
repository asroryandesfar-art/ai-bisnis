import re


_ORDINALS = (
    "", "Pertama", "Kedua", "Ketiga", "Keempat", "Kelima",
    "Keenam", "Ketujuh", "Kedelapan", "Kesembilan", "Kesepuluh",
)


_NUM_WORDS = (
    "nol", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan",
)
_SCALE_WORDS = ((1_000_000_000_000, "triliun"), (1_000_000_000, "miliar"), (1_000_000, "juta"), (1_000, "ribu"))
_SCALE_ALIASES = {"ribu": "ribu", "juta": "juta", "miliar": "miliar", "milyar": "miliar", "miliyar": "miliar", "triliun": "triliun", "teriliun": "triliun"}
_SCALE_PATTERN = r"ribu|juta|miliar|milyar|miliyar|triliun|teriliun"
_NUMBER_TOKEN = r"\d{1,3}(?:\.\d{3})+|\d+(?:[,.]\d+)?"
_RANGE_SEP = r"(?:-|–|—|s/d|sd|sampai|hingga)"


def _under_thousand_to_words(number: int) -> str:
    if number < 10:
        return _NUM_WORDS[number]
    if number == 10:
        return "sepuluh"
    if number == 11:
        return "sebelas"
    if number < 20:
        return f"{_NUM_WORDS[number - 10]} belas"
    if number < 100:
        tens, rest = divmod(number, 10)
        words = f"{_NUM_WORDS[tens]} puluh"
        return f"{words} {_under_thousand_to_words(rest)}" if rest else words
    hundreds, rest = divmod(number, 100)
    words = "seratus" if hundreds == 1 else f"{_NUM_WORDS[hundreds]} ratus"
    return f"{words} {_under_thousand_to_words(rest)}" if rest else words


def _number_to_indonesian_words(number: int) -> str:
    if number < 0:
        return f"minus {_number_to_indonesian_words(abs(number))}"
    if number < 1000:
        return _under_thousand_to_words(number)
    parts: list[str] = []
    remainder = number
    for scale, label in _SCALE_WORDS:
        value, remainder = divmod(remainder, scale)
        if not value:
            continue
        if scale == 1000 and value == 1:
            parts.append("seribu")
        else:
            parts.append(f"{_number_to_indonesian_words(value)} {label}")
    if remainder:
        parts.append(_under_thousand_to_words(remainder))
    return " ".join(parts)


def _spoken_decimal_number(value: str) -> str:
    integer, decimal = re.split(r"[,.]", value, maxsplit=1)
    integer_words = _number_to_indonesian_words(int(integer or "0"))
    decimal_words = " ".join(_NUM_WORDS[int(ch)] for ch in decimal if ch.isdigit())
    return f"{integer_words} koma {decimal_words}" if decimal_words else integer_words


def _number_token_to_words(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", value):
        return _number_to_indonesian_words(int(value.replace(".", "")))
    if re.fullmatch(r"\d+[,.]\d+", value):
        return _spoken_decimal_number(value)
    return _number_to_indonesian_words(int(value))


def _normalize_spoken_ranges(text: str) -> str:
    def currency_range(match: re.Match[str]) -> str:
        left = _number_token_to_words(match.group(1))
        right = _number_token_to_words(match.group(2))
        return f"{left} rupiah hingga {right} rupiah"

    text = re.sub(
        rf"\b(?:Rp\.?|IDR)\s*({_NUMBER_TOKEN})\s*{_RANGE_SEP}\s*(?:Rp\.?|IDR)?\s*({_NUMBER_TOKEN})\b",
        currency_range,
        text,
        flags=re.IGNORECASE,
    )

    def scaled_range(match: re.Match[str]) -> str:
        left = _number_token_to_words(match.group(1))
        left_scale = _SCALE_ALIASES.get((match.group(2) or "").lower())
        right = _number_token_to_words(match.group(3))
        right_scale = _SCALE_ALIASES[match.group(4).lower()]
        if left_scale and left_scale != right_scale:
            return f"{left} {left_scale} hingga {right} {right_scale}"
        return f"{left} hingga {right} {right_scale}"

    text = re.sub(
        rf"\b({_NUMBER_TOKEN})\s*({_SCALE_PATTERN})?\s*{_RANGE_SEP}\s*({_NUMBER_TOKEN})\s*({_SCALE_PATTERN})\b",
        scaled_range,
        text,
        flags=re.IGNORECASE,
    )

    def percent_range(match: re.Match[str]) -> str:
        return f"{_number_token_to_words(match.group(1))} hingga {_number_token_to_words(match.group(2))} persen"

    text = re.sub(rf"\b({_NUMBER_TOKEN})\s*%\s*{_RANGE_SEP}\s*({_NUMBER_TOKEN})\s*%(?=\W|$)", percent_range, text, flags=re.IGNORECASE)
    text = re.sub(rf"\b({_NUMBER_TOKEN})\s*{_RANGE_SEP}\s*({_NUMBER_TOKEN})\s*%(?=\W|$)", percent_range, text, flags=re.IGNORECASE)

    def generic_range(match: re.Match[str]) -> str:
        unit = match.group(3) or ""
        return f"{_number_token_to_words(match.group(1))} hingga {_number_token_to_words(match.group(2))}{(' ' + unit) if unit else ''}"

    return re.sub(
        rf"\b({_NUMBER_TOKEN})\s*{_RANGE_SEP}\s*({_NUMBER_TOKEN})\s*(hari|bulan|tahun|minggu|orang|unit|produk|kali|x)?\b",
        generic_range,
        text,
        flags=re.IGNORECASE,
    )


def _normalize_spoken_numbers(text: str) -> str:
    text = _normalize_spoken_ranges(text)

    def currency(match: re.Match[str]) -> str:
        raw = match.group(1)
        amount = int(raw.replace(".", ""))
        return f"{_number_to_indonesian_words(amount)} rupiah"

    text = re.sub(r"\b(?:Rp\.?|IDR)\s*(\d{1,3}(?:\.\d{3})+)\b", currency, text, flags=re.IGNORECASE)
    text = re.sub(r"\b(\d{1,3}(?:\.\d{3})+)\s*(?:rupiah|idr)\b", currency, text, flags=re.IGNORECASE)

    def grouped_number(match: re.Match[str]) -> str:
        return _number_to_indonesian_words(int(match.group(0).replace(".", "")))

    text = re.sub(r"\b\d{1,3}(?:\.\d{3})+\b", grouped_number, text)

    def decimal_scale(match: re.Match[str]) -> str:
        return f"{_spoken_decimal_number(match.group(1))} {_SCALE_ALIASES[match.group(2).lower()]}"

    text = re.sub(rf"\b(\d+[,.]\d+)\s*({_SCALE_PATTERN})\b", decimal_scale, text, flags=re.IGNORECASE)

    def plain_scale(match: re.Match[str]) -> str:
        return f"{_number_to_indonesian_words(int(match.group(1)))} {_SCALE_ALIASES[match.group(2).lower()]}"

    text = re.sub(rf"\b(\d+)\s*({_SCALE_PATTERN})\b", plain_scale, text, flags=re.IGNORECASE)

    def large_plain(match: re.Match[str]) -> str:
        value = int(match.group(0))
        return _number_to_indonesian_words(value) if value >= 1000 else match.group(0)

    return re.sub(r"\b\d{4,15}\b", large_plain, text)


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
    text = _normalize_spoken_numbers(text)
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
