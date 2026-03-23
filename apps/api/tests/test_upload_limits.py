from __future__ import annotations

from datetime import timedelta

from blockvault_api.config import reset_settings_cache
from blockvault_api.crypto import utcnow
from blockvault_api.database import get_database


def _login_cookie(client, wallet: str = "0x1000000000000000000000000000000000000001") -> None:
    db = get_database()
    db.users.insert_one(
        {
            "wallet_address": wallet.lower(),
            "display_name": "Upload Limit User",
            "created_at": utcnow(),
            "last_login_at": utcnow(),
        }
    )
    db.sessions.insert_one(
        {
            "session_id": "sess_upload_limit",
            "wallet_address": wallet.lower(),
            "created_at": utcnow(),
            "expires_at": utcnow() + timedelta(hours=1),
        }
    )
    client.cookies.set("bv_session", "sess_upload_limit")


def test_vault_init_upload_rejects_declared_size_over_limit(client, monkeypatch):
    monkeypatch.setenv("BLOCKVAULT_MAX_UPLOAD_BYTES", "8")
    reset_settings_cache()
    _login_cookie(client)

    response = client.post(
        "/api/v1/files/init-upload",
        json={"originalName": "oversized.bin", "contentType": "application/octet-stream", "size": 16},
    )

    assert response.status_code == 413


def test_document_complete_upload_rejects_payload_over_limit(client, monkeypatch):
    monkeypatch.setenv("BLOCKVAULT_MAX_UPLOAD_BYTES", "16")
    reset_settings_cache()
    _login_cookie(client)

    case_response = client.post("/api/v1/cases", json={"title": "Matter Limits", "description": "Upload limits"})
    case_id = case_response.json()["id"]

    init_response = client.post(
        f"/api/v1/documents/init-upload?caseId={case_id}",
        json={"originalName": "limited.pdf", "contentType": "application/pdf", "size": 8},
    )
    document_id = init_response.json()["documentId"]

    response = client.post(
        f"/api/v1/documents/{document_id}/complete-upload",
        files={"encrypted_file": ("limited.pdf.bv", b"x" * 32, "application/octet-stream")},
        data={
            "algorithm": "AES-GCM/PBKDF2-SHA256",
            "salt_b64": "c2FsdA==",
            "iv_b64": "aXY=",
        },
    )

    assert response.status_code == 413
