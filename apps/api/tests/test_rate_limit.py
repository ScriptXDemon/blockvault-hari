from __future__ import annotations

from datetime import timedelta

from blockvault_api.config import reset_settings_cache
from blockvault_api.crypto import utcnow
from blockvault_api.database import get_database
from blockvault_api.rate_limit import reset_rate_limiter


def _login_cookie(client, wallet: str = "0x1000000000000000000000000000000000000001") -> None:
    db = get_database()
    db.users.insert_one(
        {
            "wallet_address": wallet.lower(),
            "display_name": "Rate Limit User",
            "created_at": utcnow(),
            "last_login_at": utcnow(),
        }
    )
    db.sessions.insert_one(
        {
            "session_id": "sess_rate_limit",
            "wallet_address": wallet.lower(),
            "created_at": utcnow(),
            "expires_at": utcnow() + timedelta(hours=1),
        }
    )
    client.cookies.set("bv_session", "sess_rate_limit")


def test_test_login_rate_limit(client, monkeypatch):
    reset_rate_limiter()
    monkeypatch.setenv("BLOCKVAULT_RATE_LIMIT_AUTH_REQUESTS", "2")
    monkeypatch.setenv("BLOCKVAULT_RATE_LIMIT_AUTH_WINDOW_SECONDS", "60")
    reset_settings_cache()

    payload = {"walletAddress": "0x1000000000000000000000000000000000000001"}
    assert client.post("/api/auth/test-login", json=payload).status_code == 200
    assert client.post("/api/auth/test-login", json=payload).status_code == 200
    limited = client.post("/api/auth/test-login", json=payload)
    assert limited.status_code == 429


def test_vault_init_upload_rate_limit(client, monkeypatch):
    reset_rate_limiter()
    monkeypatch.setenv("BLOCKVAULT_RATE_LIMIT_WRITE_REQUESTS", "2")
    monkeypatch.setenv("BLOCKVAULT_RATE_LIMIT_WRITE_WINDOW_SECONDS", "60")
    reset_settings_cache()
    _login_cookie(client)

    payload = {"originalName": "memo.pdf", "contentType": "application/pdf", "size": 32}
    assert client.post("/api/v1/files/init-upload", json=payload).status_code == 200
    assert client.post("/api/v1/files/init-upload", json=payload).status_code == 200
    limited = client.post("/api/v1/files/init-upload", json=payload)
    assert limited.status_code == 429
