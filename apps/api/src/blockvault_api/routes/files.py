from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from ..config import Settings, get_settings
from ..crypto import random_id, utcnow
from ..database import get_database
from ..rate_limit import RateLimitPolicy, enforce_rate_limit
from ..repositories import append_custody_event, create_pending_file
from ..schemas import InitUploadRequest, ShareRequest
from ..security import SessionUser, current_user
from ..storage import get_object_store

router = APIRouter(prefix="/api/v1", tags=["vault"])


def _owned_or_shared_file(file_id: str, wallet: str) -> dict[str, Any]:
    db = get_database()
    file_record = db.files.find_one({"file_id": file_id, "status": {"$ne": "deleted"}})
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    if file_record["owner_wallet"] == wallet:
        return file_record
    share = db.shares.find_one({"file_id": file_id, "recipient_wallet": wallet, "revoked_at": None})
    if not share:
        raise HTTPException(status_code=403, detail="Access denied")
    return file_record


def _write_policy(settings: Settings, *, name: str) -> RateLimitPolicy:
    return RateLimitPolicy(
        name=name,
        limit=settings.rate_limit_write_requests,
        window_seconds=settings.rate_limit_write_window_seconds,
        scope="wallet",
    )


def _enforce_upload_size_limit(size: int, settings: Settings) -> None:
    if size > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Upload exceeds the {settings.max_upload_bytes} byte limit",
        )


@router.post("/files/init-upload")
def init_upload(
    payload: InitUploadRequest,
    request: Request,
    user: SessionUser = Depends(current_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    enforce_rate_limit(request, policy=_write_policy(settings, name="vault_init_upload"), wallet_address=user.wallet_address)
    _enforce_upload_size_limit(payload.size, settings)
    record = create_pending_file(
        owner_wallet=user.wallet_address,
        original_name=payload.originalName,
        content_type=payload.contentType,
        size=payload.size,
        file_type="vault",
    )
    return {"fileId": record["file_id"]}


@router.post("/files/{file_id}/complete-upload")
async def complete_upload(
    file_id: str,
    encrypted_file: UploadFile = File(...),
    algorithm: str = Form(...),
    salt_b64: str = Form(...),
    iv_b64: str = Form(...),
    user: SessionUser = Depends(current_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    db = get_database()
    store = get_object_store()
    record = db.files.find_one({"file_id": file_id, "owner_wallet": user.wallet_address})
    if not record:
        raise HTTPException(status_code=404, detail="Pending file not found")
    payload = await encrypted_file.read()
    _enforce_upload_size_limit(len(payload), settings)
    storage_key = store.put_bytes("vault", f"{file_id}.bin", payload)
    db.files.update_one(
        {"file_id": file_id},
        {
            "$set": {
                "storage_key": storage_key,
                "status": "ready",
                "updated_at": utcnow(),
                "encryption": {
                    "algorithm": algorithm,
                    "salt_b64": salt_b64,
                    "iv_b64": iv_b64,
                },
            }
        },
    )
    append_custody_event(
        subject_type="file",
        subject_id=file_id,
        event_type="vault.uploaded",
        actor_wallet=user.wallet_address,
        summary=f"Vault file '{record['original_name']}' uploaded",
    )
    return {"success": True, "fileId": file_id}


@router.get("/files")
def list_files(user: SessionUser = Depends(current_user)) -> dict[str, object]:
    db = get_database()
    files = []
    for item in db.files.find({"owner_wallet": user.wallet_address, "file_type": "vault", "status": "ready"}):
        shares = list(db.shares.find({"file_id": item["file_id"], "revoked_at": None}))
        files.append(
            {
                "id": item["file_id"],
                "ownerWallet": item["owner_wallet"],
                "originalName": item["original_name"],
                "contentType": item["content_type"],
                "size": item["size"],
                "createdAt": item["created_at"].isoformat(),
                "sharedWith": [share["recipient_wallet"] for share in shares],
            }
        )
    return {"items": files}


@router.get("/files/{file_id}/download")
def download_file(file_id: str, user: SessionUser = Depends(current_user)) -> StreamingResponse:
    store = get_object_store()
    record = _owned_or_shared_file(file_id, user.wallet_address)
    blob = store.read_bytes(record["storage_key"])
    headers = {
        "X-BlockVault-Original-Name": record["original_name"],
        "X-BlockVault-Content-Type": record["content_type"],
        "X-BlockVault-Algorithm": record["encryption"]["algorithm"],
        "X-BlockVault-Salt": record["encryption"]["salt_b64"],
        "X-BlockVault-Iv": record["encryption"]["iv_b64"],
    }
    return StreamingResponse(iter([blob]), media_type="application/octet-stream", headers=headers)


@router.delete("/files/{file_id}")
def delete_file(file_id: str, user: SessionUser = Depends(current_user)) -> dict[str, bool]:
    db = get_database()
    result = db.files.update_one(
        {"file_id": file_id, "owner_wallet": user.wallet_address},
        {"$set": {"status": "deleted", "updated_at": utcnow()}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="File not found")
    db.shares.update_many(
        {"file_id": file_id, "owner_wallet": user.wallet_address, "revoked_at": None},
        {"$set": {"revoked_at": utcnow()}},
    )
    append_custody_event(
        subject_type="file",
        subject_id=file_id,
        event_type="vault.deleted",
        actor_wallet=user.wallet_address,
        summary="Vault file deleted",
    )
    return {"success": True}


@router.post("/files/{file_id}/share")
def share_file(file_id: str, payload: ShareRequest, user: SessionUser = Depends(current_user)) -> dict[str, object]:
    db = get_database()
    file_record = db.files.find_one({"file_id": file_id, "owner_wallet": user.wallet_address, "status": "ready"})
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    recipient_wallet = payload.recipientWallet.lower()
    if recipient_wallet == user.wallet_address:
        raise HTTPException(status_code=400, detail="You cannot share a file with the same wallet")

    existing_share = db.shares.find_one({"file_id": file_id, "recipient_wallet": recipient_wallet})
    share_id = existing_share["share_id"] if existing_share else random_id("share")
    share = {
        "share_id": share_id,
        "file_id": file_id,
        "owner_wallet": user.wallet_address,
        "recipient_wallet": recipient_wallet,
        "created_at": existing_share.get("created_at", utcnow()) if existing_share else utcnow(),
        "revoked_at": None,
        "original_name": file_record["original_name"],
    }
    db.shares.update_one(
        {"file_id": file_id, "recipient_wallet": recipient_wallet},
        {"$set": share},
        upsert=True,
    )
    append_custody_event(
        subject_type="file",
        subject_id=file_id,
        event_type="vault.shared",
        actor_wallet=user.wallet_address,
        summary=f"Vault file shared with {recipient_wallet}",
    )
    return {"success": True, "shareId": share["share_id"]}


@router.get("/shares/incoming")
def incoming_shares(user: SessionUser = Depends(current_user)) -> dict[str, object]:
    db = get_database()
    items = [
        {
            "id": item["share_id"],
            "fileId": item["file_id"],
            "ownerWallet": item["owner_wallet"],
            "recipientWallet": item["recipient_wallet"],
            "createdAt": item["created_at"].isoformat(),
            "originalName": item["original_name"],
        }
        for item in db.shares.find({"recipient_wallet": user.wallet_address, "revoked_at": None})
    ]
    return {"items": items}


@router.get("/shares/outgoing")
def outgoing_shares(user: SessionUser = Depends(current_user)) -> dict[str, object]:
    db = get_database()
    items = [
        {
            "id": item["share_id"],
            "fileId": item["file_id"],
            "ownerWallet": item["owner_wallet"],
            "recipientWallet": item["recipient_wallet"],
            "createdAt": item["created_at"].isoformat(),
            "originalName": item["original_name"],
        }
        for item in db.shares.find({"owner_wallet": user.wallet_address, "revoked_at": None})
    ]
    return {"items": items}


@router.delete("/shares/{share_id}")
def revoke_share(share_id: str, user: SessionUser = Depends(current_user)) -> dict[str, bool]:
    db = get_database()
    share = db.shares.find_one({"share_id": share_id, "owner_wallet": user.wallet_address, "revoked_at": None})
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")
    result = db.shares.update_one(
        {"share_id": share_id, "owner_wallet": user.wallet_address, "revoked_at": None},
        {"$set": {"revoked_at": utcnow()}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Share not found")
    append_custody_event(
        subject_type="file",
        subject_id=share["file_id"],
        event_type="vault.share_revoked",
        actor_wallet=user.wallet_address,
        summary=f"Vault share revoked for {share['recipient_wallet']}",
    )
    return {"success": True}
