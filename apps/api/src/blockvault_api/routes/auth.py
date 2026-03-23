from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi import HTTPException, status

from ..config import Settings, get_settings
from ..database import get_database
from ..crypto import utcnow
from ..rate_limit import RateLimitPolicy, enforce_rate_limit
from ..schemas import NonceRequest, TestLoginRequest, VerifyRequest
from ..security import SessionUser, clear_session, create_session, current_user, issue_nonce, verify_siwe_message

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _auth_policy(settings: Settings) -> RateLimitPolicy:
    return RateLimitPolicy(
        name="auth",
        limit=settings.rate_limit_auth_requests,
        window_seconds=settings.rate_limit_auth_window_seconds,
    )


@router.post("/siwe/nonce")
def siwe_nonce(payload: NonceRequest, request: Request, settings: Settings = Depends(get_settings)) -> dict[str, object]:
    enforce_rate_limit(request, policy=_auth_policy(settings))
    return issue_nonce(payload.walletAddress, settings)


@router.post("/siwe/verify")
def siwe_verify(
    payload: VerifyRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    enforce_rate_limit(request, policy=_auth_policy(settings))
    user = verify_siwe_message(payload.message, payload.signature, settings)
    create_session(response, user, settings)
    return {"user": {"walletAddress": user.wallet_address, "displayName": user.display_name}}


@router.post("/test-login")
def test_login(
    payload: TestLoginRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    if not settings.enable_test_auth or settings.app_env == "production":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test auth is disabled")
    enforce_rate_limit(request, policy=_auth_policy(settings))

    wallet_address = payload.walletAddress.lower()
    display_name = payload.displayName or f"{wallet_address[:6]}...{wallet_address[-4:]}"
    db = get_database()
    db.users.update_one(
        {"wallet_address": wallet_address},
        {
            "$set": {
                "wallet_address": wallet_address,
                "display_name": display_name,
                "last_login_at": utcnow(),
            },
            "$setOnInsert": {"created_at": utcnow()},
        },
        upsert=True,
    )
    user = SessionUser(wallet_address=wallet_address, display_name=display_name)
    create_session(response, user, settings)
    return {"user": {"walletAddress": user.wallet_address, "displayName": user.display_name}}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    user: SessionUser = Depends(current_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, bool]:
    del user
    session_id = request.cookies.get(settings.session_cookie_name)
    clear_session(session_id)
    delete_kwargs: dict[str, object] = {
        "key": settings.session_cookie_name,
        "path": "/",
        "secure": settings.session_cookie_secure,
        "samesite": settings.session_cookie_samesite,
    }
    if settings.session_cookie_domain:
        delete_kwargs["domain"] = settings.session_cookie_domain
    response.delete_cookie(**delete_kwargs)
    return {"success": True}


@router.get("/me")
def me(user: SessionUser = Depends(current_user)) -> dict[str, object]:
    return {"user": {"walletAddress": user.wallet_address, "displayName": user.display_name}}
