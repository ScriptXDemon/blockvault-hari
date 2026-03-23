from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import Depends, HTTPException, Request, Response, status

from .config import Settings, get_settings
from .crypto import random_id, random_nonce, utcnow
from .database import get_database


SIWE_URI_RE = re.compile(r"^URI:\s*(?P<value>.+)$", re.MULTILINE)
SIWE_NONCE_RE = re.compile(r"^Nonce:\s*(?P<value>.+)$", re.MULTILINE)
SIWE_CHAIN_RE = re.compile(r"^Chain ID:\s*(?P<value>\d+)$", re.MULTILINE)
ETH_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


@dataclass(frozen=True)
class SessionUser:
    wallet_address: str
    display_name: str


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def issue_nonce(wallet_address: str, settings: Settings) -> dict[str, object]:
    db = get_database()
    nonce = random_nonce()
    expires_at = utcnow() + timedelta(minutes=settings.nonce_ttl_minutes)
    db.nonces.update_one(
        {"wallet_address": wallet_address.lower()},
        {
            "$set": {
                "wallet_address": wallet_address.lower(),
                "nonce": nonce,
                "expires_at": expires_at,
                "created_at": utcnow(),
            }
        },
        upsert=True,
    )
    return {
        "nonce": nonce,
        "issuedAt": utcnow().isoformat(),
        "domain": settings.siwe_domain,
        "uri": settings.siwe_uri,
        "chainId": settings.siwe_chain_id,
    }


def _match(pattern: re.Pattern[str], message: str, label: str) -> str:
    match = pattern.search(message)
    if not match:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Missing {label} in SIWE message")
    return match.group("value").strip()


def verify_siwe_message(message: str, signature: str, settings: Settings) -> SessionUser:
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    if len(lines) < 3:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed SIWE message")

    stated_domain = lines[0].replace(" wants you to sign in with your Ethereum account:", "").strip()
    wallet_line = lines[1]
    if not ETH_ADDRESS_RE.fullmatch(wallet_line):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed SIWE wallet address")
    wallet_address = wallet_line.lower()
    uri = _match(SIWE_URI_RE, message, "URI")
    nonce = _match(SIWE_NONCE_RE, message, "nonce")
    chain_id = int(_match(SIWE_CHAIN_RE, message, "chain id"))

    if stated_domain != settings.siwe_domain:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unexpected SIWE domain")
    if uri != settings.siwe_uri:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unexpected SIWE URI")
    if chain_id != settings.siwe_chain_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unexpected chain id")

    db = get_database()
    nonce_record = db.nonces.find_one({"wallet_address": wallet_address})
    if not nonce_record or nonce_record["nonce"] != nonce or _coerce_utc(nonce_record["expires_at"]) < utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nonce expired or invalid")

    recovered = Account.recover_message(encode_defunct(text=message), signature=signature).lower()
    if recovered != wallet_address:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Signature does not match wallet")

    db.nonces.delete_one({"wallet_address": wallet_address})
    db.users.update_one(
        {"wallet_address": wallet_address},
        {
            "$set": {
                "wallet_address": wallet_address,
                "display_name": f"{wallet_address[:6]}...{wallet_address[-4:]}",
                "last_login_at": utcnow(),
            },
            "$setOnInsert": {"created_at": utcnow()},
        },
        upsert=True,
    )
    user = db.users.find_one({"wallet_address": wallet_address}) or {}
    return SessionUser(wallet_address=wallet_address, display_name=user.get("display_name", wallet_address))


def create_session(response: Response, user: SessionUser, settings: Settings) -> None:
    db = get_database()
    session_id = random_id("sess")
    expires_at = utcnow() + timedelta(hours=settings.session_ttl_hours)
    db.sessions.insert_one(
        {
            "session_id": session_id,
            "wallet_address": user.wallet_address,
            "created_at": utcnow(),
            "expires_at": expires_at,
        }
    )
    cookie_kwargs: dict[str, object] = {
        "key": settings.session_cookie_name,
        "value": session_id,
        "httponly": True,
        "secure": settings.session_cookie_secure,
        "samesite": settings.session_cookie_samesite,
        "max_age": settings.session_ttl_hours * 3600,
        "path": "/",
    }
    if settings.session_cookie_domain:
        cookie_kwargs["domain"] = settings.session_cookie_domain
    response.set_cookie(**cookie_kwargs)


def clear_session(session_id: str | None) -> None:
    if not session_id:
        return
    db = get_database()
    db.sessions.delete_one({"session_id": session_id})


def current_user(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> SessionUser:
    db = get_database()
    session_id = request.cookies.get(settings.session_cookie_name)
    if not session_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    session = db.sessions.find_one({"session_id": session_id})
    if not session or _coerce_utc(session["expires_at"]) < utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    user = db.users.find_one({"wallet_address": session["wallet_address"]})
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown session user")
    return SessionUser(wallet_address=user["wallet_address"], display_name=user.get("display_name", user["wallet_address"]))
