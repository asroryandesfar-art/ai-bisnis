"""L-02 — Swagger/OpenAPI tidak terekspos secara default (produksi)."""
from fastapi.testclient import TestClient

import main


def test_docs_disabled_by_default():
    # cfg.enable_api_docs default False -> /docs, /redoc, /openapi.json 404
    assert main.cfg.enable_api_docs is False
    with TestClient(main.app) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404
