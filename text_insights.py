from __future__ import annotations

import re


_WORD_RE = re.compile(r"[a-zA-Z0-9_]+", re.UNICODE)

_STOPWORDS_ID = {
    "yang", "dan", "atau", "di", "ke", "dari", "pada", "untuk", "dengan", "tanpa",
    "ini", "itu", "saya", "kamu", "anda", "dia", "mereka", "kami",
    "aku", "gue", "lu", "nya",
    "apa", "kenapa", "mengapa", "bagaimana", "kapan", "dimana", "di mana",
    "tolong", "mohon", "please",
    "ya", "iya", "tidak", "nggak", "ga", "gak",
    "jadi", "karena", "kalau", "jika", "bila",
    "bisa", "dapat", "mau", "ingin",
}

_NEGATIVE = {
    "gagal", "error", "eror", "rusak", "parah", "lama", "lelet", "macet",
    "tidak", "nggak", "gak", "ga", "belum", "refused", "500", "503", "404",
    "capek", "kesal", "marah", "kecewa", "bingung", "pusing",
}

_POSITIVE = {"makasih", "terima", "thanks", "sip", "mantap", "berhasil", "oke", "ok"}


def tokenize(text: str) -> list[str]:
    words = [w.lower() for w in _WORD_RE.findall(text or "")]
    return [w for w in words if w and w not in _STOPWORDS_ID]


def infer_topics(text: str) -> list[str]:
    t = (text or "").lower()
    topics: list[str] = []
    mapping = [
        ("login", ["login", "masuk", "signin", "sign-in"]),
        ("daftar", ["daftar", "register", "signup", "sign-up"]),
        ("pembayaran", ["bayar", "pembayaran", "payment", "tagihan", "invoice"]),
        ("refund", ["refund", "uang kembali", "pengembalian", "retur", "cancel"]),
        ("pengiriman", ["kirim", "pengiriman", "shipping", "resi", "kurir"]),
        ("akun", ["akun", "password", "kata sandi", "reset"]),
        ("teknis", ["bug", "error", "eror", "500", "503", "timeout", "server"]),
        ("harga", ["harga", "biaya", "pricing", "paket", "plan"]),
        ("dokumen", ["dokumen", "upload", "pdf", "doc", "docx", "file"]),
    ]
    for topic, keys in mapping:
        if any(k in t for k in keys):
            topics.append(topic)
    return topics[:6]


def sentiment_from_text(text: str) -> dict:
    toks = tokenize(text)
    neg = sum(1 for t in toks if t in _NEGATIVE)
    pos = sum(1 for t in toks if t in _POSITIVE)
    score = 0.0
    label = "neutral"
    emotions: list[str] = []
    if neg > pos and neg > 0:
        label = "negative"
        score = max(-1.0, -0.2 * neg)
        if any(k in (text or "").lower() for k in ["capek", "kesal", "marah"]):
            emotions.append("frustrated")
        if any(k in (text or "").lower() for k in ["bingung", "pusing"]):
            emotions.append("confused")
    elif pos > neg and pos > 0:
        label = "positive"
        score = min(1.0, 0.2 * pos)
        emotions.append("satisfied")
    return {"label": label, "score": float(score), "emotions": emotions}


def intent_from_text(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ["login", "masuk", "signin", "sign-in"]):
        return "auth_login_issue"
    if any(k in t for k in ["daftar", "register", "signup", "sign-up"]):
        return "auth_register_issue"
    if any(k in t for k in ["refund", "uang kembali", "pengembalian", "retur"]):
        return "complaint_refund"
    if any(k in t for k in ["pengiriman", "resi", "kurir", "kirim"]):
        return "shipping_status"
    if any(k in t for k in ["harga", "pricing", "plan", "paket", "biaya"]):
        return "pricing_question"
    if any(k in t for k in ["error", "eror", "bug", "500", "503", "timeout", "refused", "connection refused"]):
        return "technical_issue"
    return "general_question"


def summarize_conversation(user_message: str, bot_response: str) -> str:
    um = (user_message or "").strip().replace("\n", " ")
    br = (bot_response or "").strip().replace("\n", " ")
    if len(um) > 140:
        um = um[:140] + "..."
    if len(br) > 140:
        br = br[:140] + "..."
    if um and br:
        return f"User menanyakan: {um}. Bot menjawab: {br}"
    if um:
        return f"User menanyakan: {um}"
    return ""
