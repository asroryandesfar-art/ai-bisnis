"""
Knowledge Base retrieval sebelumnya cuma punya satu provider embedding: hash
lokal (SHA1 feature-hashing) di main.py::_text_to_embedding -- cukup untuk
pengelompokan kasar, tapi tidak menangkap kemiripan makna sungguhan.

kb_embeddings.py menambah provider OpenAI text-embedding-3-small (opsional,
graceful-degradation seperti image_providers.py/web_search_agent.py) dan
main.py::_generate_kb_embedding memilih provider mana yang dipakai. Karena
chunk lama (hash) dan baru (OpenAI) hidup di vector space berbeda walau
dimensinya sama, main.py::_score_kb_candidate membandingkan model tag tiap
chunk sebelum menghitung cosine similarity-nya.
"""
import asyncio

import pytest

import kb_embeddings as kbe
import main


class _FakeResponse:
    def __init__(self, status_code, json_data=None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data


class _FakeAsyncClient:
    def __init__(self, response, captured):
        self._response = response
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        self._captured.append((url, json, headers))
        return self._response


def _patch_httpx(monkeypatch, response):
    captured = []
    monkeypatch.setattr(kbe, "httpx", type("M", (), {
        "AsyncClient": lambda timeout=None: _FakeAsyncClient(response, captured),
    }))
    return captured


# ─────────────────────────────────────────────────────────────────
# kb_embeddings.generate_openai_embedding
# ─────────────────────────────────────────────────────────────────

def test_generate_openai_embedding_returns_none_without_api_key():
    result = asyncio.run(kbe.generate_openai_embedding("halo dunia", "", 256))
    assert result is None


def test_generate_openai_embedding_returns_none_for_empty_text():
    result = asyncio.run(kbe.generate_openai_embedding("   ", "sk-test", 256))
    assert result is None


def test_generate_openai_embedding_success(monkeypatch):
    fake_vec = [0.1, 0.2, 0.3]
    response = _FakeResponse(200, {"data": [{"embedding": fake_vec}]})
    captured = _patch_httpx(monkeypatch, response)

    result = asyncio.run(kbe.generate_openai_embedding("halo dunia", "sk-test", 256))
    assert result == fake_vec
    assert captured[0][1]["model"] == kbe.OPENAI_EMBEDDING_MODEL
    assert captured[0][1]["dimensions"] == 256
    assert captured[0][2]["Authorization"] == "Bearer sk-test"


def test_generate_openai_embedding_returns_none_on_http_error(monkeypatch):
    response = _FakeResponse(401, {})
    _patch_httpx(monkeypatch, response)

    result = asyncio.run(kbe.generate_openai_embedding("halo dunia", "sk-bad", 256))
    assert result is None


# ─────────────────────────────────────────────────────────────────
# main._generate_kb_embedding — pemilihan provider
# ─────────────────────────────────────────────────────────────────

def test_generate_kb_embedding_falls_back_to_hash_without_openai_key(monkeypatch):
    monkeypatch.setattr(main.cfg, "openai_api_key", "")
    vec, model = asyncio.run(main._generate_kb_embedding("contoh teks"))
    assert model == f"hash-emb-{main.cfg.kb_embedding_dim or main.KB_EMBED_DIM}"
    assert vec == main._text_to_embedding("contoh teks")


def test_generate_kb_embedding_uses_openai_when_key_present_and_call_succeeds(monkeypatch):
    monkeypatch.setattr(main.cfg, "openai_api_key", "sk-test")

    async def fake_generate(text, api_key, dim):
        return [0.5] * dim

    monkeypatch.setattr(kbe, "generate_openai_embedding", fake_generate)
    vec, model = asyncio.run(main._generate_kb_embedding("contoh teks"))
    assert model == kbe.OPENAI_EMBEDDING_TAG
    assert vec[0] == 0.5


def test_generate_kb_embedding_falls_back_to_hash_when_openai_call_fails(monkeypatch):
    monkeypatch.setattr(main.cfg, "openai_api_key", "sk-test")

    async def fake_generate_fails(text, api_key, dim):
        return None

    monkeypatch.setattr(kbe, "generate_openai_embedding", fake_generate_fails)
    vec, model = asyncio.run(main._generate_kb_embedding("contoh teks"))
    assert model.startswith("hash-emb-")
    assert vec == main._text_to_embedding("contoh teks")


# ─────────────────────────────────────────────────────────────────
# main._score_kb_candidate — embedding score lintas-provider diabaikan
# ─────────────────────────────────────────────────────────────────

def test_score_kb_candidate_uses_embedding_when_model_tags_match():
    vec = main._text_to_embedding("kucing makan ikan")
    score = main._score_kb_candidate(
        ["kucing"], vec, "kucing makan ikan", vec,
        query_model="hash-emb-256", chunk_model="hash-emb-256",
    )
    # vektor identik -> cosine similarity 1.0, kontribusi embedding 0.78 + keyword 0.22
    assert score == pytest.approx(1.0, abs=1e-6)


def test_score_kb_candidate_skips_embedding_when_model_tags_differ():
    vec = main._text_to_embedding("kucing makan ikan")
    score = main._score_kb_candidate(
        ["kucing"], vec, "kucing makan ikan", vec,
        query_model="openai:text-embedding-3-small", chunk_model="hash-emb-256",
    )
    # model tag beda -> emb_score dipaksa 0, cuma keyword match (1/1 token cocok) * 0.22
    assert score == pytest.approx(0.22, abs=1e-6)


def test_score_kb_candidate_computes_embedding_when_model_tags_unknown():
    vec = main._text_to_embedding("kucing makan ikan")
    score = main._score_kb_candidate(["kucing"], vec, "kucing makan ikan", vec)
    assert score == pytest.approx(1.0, abs=1e-6)
