from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .config import get_settings


PBKDF2_ITERATIONS = 600_000


@dataclass(frozen=True)
class EncryptionEnvelope:
    algorithm: str
    salt_b64: str
    iv_b64: str


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def random_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(12)}"


def random_nonce(length: int = 16) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt_bytes(plaintext: bytes, passphrase: str) -> tuple[bytes, EncryptionEnvelope]:
    salt = secrets.token_bytes(16)
    iv = secrets.token_bytes(12)
    key = _derive_key(passphrase, salt)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(iv, plaintext, None)
    return ciphertext, EncryptionEnvelope(
        algorithm="AES-GCM/PBKDF2-SHA256",
        salt_b64=base64.b64encode(salt).decode("utf-8"),
        iv_b64=base64.b64encode(iv).decode("utf-8"),
    )


def decrypt_bytes(ciphertext: bytes, passphrase: str, *, salt_b64: str, iv_b64: str) -> bytes:
    salt = base64.b64decode(salt_b64)
    iv = base64.b64decode(iv_b64)
    key = _derive_key(passphrase, salt)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(iv, ciphertext, None)


def make_fernet() -> Fernet:
    digest = hashlib.sha256(get_settings().secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal_secret(secret: str) -> str:
    return make_fernet().encrypt(secret.encode("utf-8")).decode("utf-8")


def open_secret(token: str) -> str:
    return make_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
