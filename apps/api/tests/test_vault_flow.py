from __future__ import annotations

import base64
from datetime import timedelta

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from fastapi.testclient import TestClient

from blockvault_api.crypto import utcnow
from blockvault_api.database import get_database
from blockvault_api.main import create_app


def _encrypt_payload(payload: bytes, passphrase: str) -> tuple[bytes, str, str]:
    salt = b"0123456789abcdef"
    iv = b"vault-file-doc"
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600_000)
    key = kdf.derive(passphrase.encode("utf-8"))
    ciphertext = AESGCM(key).encrypt(iv, payload, None)
    return (
        ciphertext,
        base64.b64encode(salt).decode("utf-8"),
        base64.b64encode(iv).decode("utf-8"),
    )


def _make_authenticated_client(wallet: str, session_id: str) -> TestClient:
    client = TestClient(create_app())
    db = get_database()
    db.users.insert_one(
        {
            "wallet_address": wallet.lower(),
            "display_name": wallet.lower(),
            "created_at": utcnow(),
            "last_login_at": utcnow(),
        }
    )
    db.sessions.insert_one(
        {
            "session_id": session_id,
            "wallet_address": wallet.lower(),
            "created_at": utcnow(),
            "expires_at": utcnow() + timedelta(hours=1),
        }
    )
    client.cookies.set("bv_session", session_id)
    return client


def test_vault_upload_share_revoke_and_access_control():
    owner_wallet = "0x1000000000000000000000000000000000000001"
    recipient_wallet = "0x2000000000000000000000000000000000000002"
    owner = _make_authenticated_client(owner_wallet, "sess_owner")
    recipient = _make_authenticated_client(recipient_wallet, "sess_recipient")

    payload = b"blockvault private vault content"
    passphrase = "correct horse battery staple"
    encrypted_bytes, salt_b64, iv_b64 = _encrypt_payload(payload, passphrase)

    init_response = owner.post(
        "/api/v1/files/init-upload",
        json={"originalName": "vault.txt", "contentType": "text/plain", "size": len(payload)},
    )
    assert init_response.status_code == 200
    file_id = init_response.json()["fileId"]

    complete_response = owner.post(
        f"/api/v1/files/{file_id}/complete-upload",
        files={"encrypted_file": ("vault.txt.bv", encrypted_bytes, "application/octet-stream")},
        data={
            "algorithm": "AES-GCM/PBKDF2-SHA256",
            "salt_b64": salt_b64,
            "iv_b64": iv_b64,
        },
    )
    assert complete_response.status_code == 200

    self_share_response = owner.post(
        f"/api/v1/files/{file_id}/share",
        json={"recipientWallet": owner_wallet},
    )
    assert self_share_response.status_code == 400

    share_response = owner.post(
        f"/api/v1/files/{file_id}/share",
        json={"recipientWallet": recipient_wallet},
    )
    assert share_response.status_code == 200
    share_id = share_response.json()["shareId"]

    outgoing = owner.get("/api/v1/shares/outgoing")
    assert outgoing.status_code == 200
    outgoing_items = outgoing.json()["items"]
    assert len(outgoing_items) == 1
    assert outgoing_items[0]["id"] == share_id

    incoming = recipient.get("/api/v1/shares/incoming")
    assert incoming.status_code == 200
    incoming_items = incoming.json()["items"]
    assert len(incoming_items) == 1
    assert incoming_items[0]["fileId"] == file_id

    shared_download = recipient.get(f"/api/v1/files/{file_id}/download")
    assert shared_download.status_code == 200
    assert shared_download.content == encrypted_bytes

    revoke_response = owner.delete(f"/api/v1/shares/{share_id}")
    assert revoke_response.status_code == 200

    outgoing_after_revoke = owner.get("/api/v1/shares/outgoing")
    assert outgoing_after_revoke.status_code == 200
    assert outgoing_after_revoke.json()["items"] == []

    incoming_after_revoke = recipient.get("/api/v1/shares/incoming")
    assert incoming_after_revoke.status_code == 200
    assert incoming_after_revoke.json()["items"] == []

    revoked_download = recipient.get(f"/api/v1/files/{file_id}/download")
    assert revoked_download.status_code == 403

    db = get_database()
    revoked_share = db.shares.find_one({"share_id": share_id})
    assert revoked_share is not None
    assert revoked_share["revoked_at"] is not None


def test_vault_delete_revokes_active_shares_and_blocks_future_access():
    owner_wallet = "0x1000000000000000000000000000000000000001"
    recipient_wallet = "0x2000000000000000000000000000000000000002"
    owner = _make_authenticated_client(owner_wallet, "sess_owner_delete")
    recipient = _make_authenticated_client(recipient_wallet, "sess_recipient_delete")

    payload = b"blockvault delete workflow content"
    passphrase = "correct horse battery staple"
    encrypted_bytes, salt_b64, iv_b64 = _encrypt_payload(payload, passphrase)

    init_response = owner.post(
        "/api/v1/files/init-upload",
        json={"originalName": "vault-delete.txt", "contentType": "text/plain", "size": len(payload)},
    )
    assert init_response.status_code == 200
    file_id = init_response.json()["fileId"]

    complete_response = owner.post(
        f"/api/v1/files/{file_id}/complete-upload",
        files={"encrypted_file": ("vault-delete.txt.bv", encrypted_bytes, "application/octet-stream")},
        data={
            "algorithm": "AES-GCM/PBKDF2-SHA256",
            "salt_b64": salt_b64,
            "iv_b64": iv_b64,
        },
    )
    assert complete_response.status_code == 200

    share_response = owner.post(
        f"/api/v1/files/{file_id}/share",
        json={"recipientWallet": recipient_wallet},
    )
    assert share_response.status_code == 200
    share_id = share_response.json()["shareId"]

    delete_response = owner.delete(f"/api/v1/files/{file_id}")
    assert delete_response.status_code == 200

    owner_files = owner.get("/api/v1/files")
    assert owner_files.status_code == 200
    assert owner_files.json()["items"] == []

    outgoing = owner.get("/api/v1/shares/outgoing")
    assert outgoing.status_code == 200
    assert outgoing.json()["items"] == []

    incoming = recipient.get("/api/v1/shares/incoming")
    assert incoming.status_code == 200
    assert incoming.json()["items"] == []

    shared_download = recipient.get(f"/api/v1/files/{file_id}/download")
    assert shared_download.status_code == 404

    db = get_database()
    revoked_share = db.shares.find_one({"share_id": share_id})
    assert revoked_share is not None
    assert revoked_share["revoked_at"] is not None
