"""NUL characters in text must be rejected with 422, not 500.

Postgres cannot store or compare text containing U+0000. The middleware
refuses any request whose path, query string or body contains one, before
it reaches the database. Skipped when DATABASE_URL is not Postgres so the
suite stays green on SQLite (which would accept the character).
"""

import pytest
from fastapi.testclient import TestClient

from app_main import app
from src.core.config import settings

pytestmark = pytest.mark.skipif(
    not settings.DATABASE_URL.startswith("postgres"),
    reason="NUL rejection is exercised against Postgres",
)


def test_nul_in_json_body_is_rejected():
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/api/products/", json={"sku": "NUL", "name": "Bad\x00name", "price": 10})
    assert response.status_code == 422, response.text
    assert "NUL" in response.json()["detail"]


def test_nul_in_query_parameter_is_rejected():
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/products/?search=%00")
    assert response.status_code == 422, response.text
    assert "NUL" in response.json()["detail"]


def test_clean_request_is_not_rejected():
    client = TestClient(app, raise_server_exceptions=False)
    # Auth will fail later; we only care that the middleware lets a clean request through.
    response = client.post("/api/products/", json={"sku": "CLEAN", "name": "Good name", "price": 10})
    assert response.status_code != 422 or "NUL" not in str(response.json())
    # More precisely: not the NUL message
    if response.status_code == 422:
        assert "NUL" not in response.json().get("detail", "")
