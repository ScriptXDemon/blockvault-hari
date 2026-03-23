from __future__ import annotations

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient

from blockvault_api.config import reset_settings_cache
from blockvault_api.main import create_app


def test_nonce_generation(client):
    response = client.post("/api/auth/siwe/nonce", json={"walletAddress": "0x1000000000000000000000000000000000000001"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["domain"] == "127.0.0.1:5173"
    assert len(payload["nonce"]) >= 16


def test_test_login_sets_cookie_and_session(client):
    response = client.post(
        "/api/auth/test-login",
        json={"walletAddress": "0x1000000000000000000000000000000000000001", "displayName": "Playwright User"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["walletAddress"] == "0x1000000000000000000000000000000000000001"
    assert response.cookies.get("bv_session")

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["displayName"] == "Playwright User"


def test_test_login_uses_configured_cookie_security(monkeypatch):
    monkeypatch.setenv("BLOCKVAULT_SESSION_COOKIE_SECURE", "true")
    monkeypatch.setenv("BLOCKVAULT_SESSION_COOKIE_SAMESITE", "none")
    reset_settings_cache()

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/auth/test-login",
            json={"walletAddress": "0x1000000000000000000000000000000000000001", "displayName": "Hosted User"},
        )

        assert response.status_code == 200
        set_cookie = response.headers["set-cookie"].lower()
        assert "secure" in set_cookie
        assert "samesite=none" in set_cookie


def test_test_login_disabled_returns_404(client, monkeypatch):
    monkeypatch.setenv("BLOCKVAULT_ENABLE_TEST_AUTH", "false")
    reset_settings_cache()
    response = client.post(
        "/api/auth/test-login",
        json={"walletAddress": "0x1000000000000000000000000000000000000001"},
    )
    assert response.status_code == 404


def test_siwe_verify_sets_session_for_signed_message(client):
    account = Account.create()
    wallet_address = account.address
    nonce_response = client.post("/api/auth/siwe/nonce", json={"walletAddress": wallet_address})
    assert nonce_response.status_code == 200
    nonce_payload = nonce_response.json()

    message = (
        f"{nonce_payload['domain']} wants you to sign in with your Ethereum account:\n"
        f"{wallet_address}\n\n"
        "Sign in to BlockVault.\n\n"
        f"URI: {nonce_payload['uri']}\n"
        "Version: 1\n"
        f"Chain ID: {nonce_payload['chainId']}\n"
        f"Nonce: {nonce_payload['nonce']}\n"
        f"Issued At: {nonce_payload['issuedAt']}"
    )
    signature = Account.sign_message(encode_defunct(text=message), private_key=account.key).signature.hex()

    verify_response = client.post("/api/auth/siwe/verify", json={"message": message, "signature": signature})
    assert verify_response.status_code == 200
    assert verify_response.json()["user"]["walletAddress"] == wallet_address.lower()
    assert verify_response.cookies.get("bv_session")

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["user"]["walletAddress"] == wallet_address.lower()
