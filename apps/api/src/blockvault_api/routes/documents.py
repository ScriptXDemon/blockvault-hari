from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from ..config import get_settings
from ..crypto import decrypt_bytes, encrypt_bytes, sha256_hex, utcnow
from ..database import get_database
from ..ocr import OcrProcessingError, ocr_pdf_to_searchable
from ..repositories import (
    append_custody_event,
    build_anchor_receipt,
    create_document,
    create_evidence_bundle,
    create_pending_file,
    list_custody_events,
)
from ..schemas import InitUploadRequest, NotarizeRequest
from ..security import SessionUser, current_user
from ..storage import get_object_store

router = APIRouter(prefix="/api/v1", tags=["documents"])


def _serialize_custody_event(event: dict[str, Any]) -> dict[str, object]:
    return {
        "id": event["event_id"],
        "subjectType": event["subject_type"],
        "subjectId": event["subject_id"],
        "eventType": event["event_type"],
        "actorWallet": event["actor_wallet"],
        "createdAt": event["created_at"].isoformat(),
        "summary": event["summary"],
    }


def _serialize_document(item: dict[str, Any]) -> dict[str, object]:
    return {
        "id": item["document_id"],
        "caseId": item["case_id"],
        "fileId": item["file_id"],
        "ownerWallet": item["owner_wallet"],
        "originalName": item["original_name"],
        "status": item["status"],
        "createdAt": item["created_at"].isoformat(),
        "anchorReceipt": item["anchor_receipt"],
        "originalSha256": item["original_sha256"],
        "redactedSha256": item["redacted_sha256"],
        "canonicalOriginalSha256": item.get("canonical_original_sha256"),
        "canonicalRedactedSha256": item.get("canonical_redacted_sha256"),
        "searchableTextConfirmed": item.get("searchable_text_confirmed"),
        "sourceTextMode": item.get("source_text_mode"),
        "ocrUsed": item.get("ocr_used"),
        "ocrEngine": item.get("ocr_engine"),
        "ocrEngineVersion": item.get("ocr_engine_version"),
        "ocrLayoutSha256": item.get("ocr_layout_sha256"),
        "workingSearchablePdfSha256": item.get("working_searchable_pdf_sha256"),
        "renderMode": item.get("render_mode"),
        "redactionEngine": item.get("redaction_engine"),
        "redactionEngineVersion": item.get("redaction_engine_version"),
        "evidenceBundleId": item["evidence_bundle_id"],
        "sourceDocumentId": item.get("source_document_id"),
        "redactionResultId": item.get("latest_redaction_result_id"),
        "zkpt": item.get("zkpt"),
    }


def _document_query(document_id: str, wallet: str, *, include_deleted: bool = False) -> dict[str, Any]:
    query: dict[str, Any] = {"document_id": document_id, "owner_wallet": wallet}
    if not include_deleted:
        query["status"] = {"$ne": "deleted"}
    return query


def _document_or_404(document_id: str, wallet: str, *, include_deleted: bool = False) -> dict[str, Any]:
    db = get_database()
    record = db.documents.find_one(_document_query(document_id, wallet, include_deleted=include_deleted))
    if not record:
        raise HTTPException(status_code=404, detail="Document not found")
    return record


def _enforce_upload_size_limit(size: int) -> None:
    max_upload_bytes = get_settings().max_upload_bytes
    if size > max_upload_bytes:
        raise HTTPException(status_code=413, detail=f"Upload exceeds the {max_upload_bytes} byte limit")


def _backing_file_or_404(document: dict[str, Any], wallet: str) -> dict[str, Any]:
    db = get_database()
    file_record = db.files.find_one({"file_id": document["file_id"], "owner_wallet": wallet})
    if not file_record:
        raise HTTPException(status_code=404, detail="Backing file not found")
    if "storage_key" not in file_record:
        raise HTTPException(status_code=409, detail="Document binary not available")
    return file_record


def _ocr_copy_name(original_name: str) -> str:
    path = Path(original_name)
    suffix = path.suffix if path.suffix.lower() == ".pdf" else ".pdf"
    return f"{path.stem}-ocr{suffix}"


@router.post("/documents/init-upload")
def init_document_upload(
    payload: InitUploadRequest,
    caseId: str = Query(..., alias="caseId"),
    user: SessionUser = Depends(current_user),
) -> dict[str, object]:
    db = get_database()
    case = db.cases.find_one({"case_id": caseId, "owner_wallet": user.wallet_address})
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    _enforce_upload_size_limit(payload.size)
    file_record = create_pending_file(
        owner_wallet=user.wallet_address,
        original_name=payload.originalName,
        content_type=payload.contentType,
        size=payload.size,
        file_type="document",
    )
    document = create_document(
        owner_wallet=user.wallet_address,
        case_id=caseId,
        original_name=payload.originalName,
        file_id=file_record["file_id"],
    )
    return {"documentId": document["document_id"], "fileId": file_record["file_id"]}


@router.post("/documents/{document_id}/complete-upload")
async def complete_document_upload(
    document_id: str,
    encrypted_file: UploadFile = File(...),
    algorithm: str = Form(...),
    salt_b64: str = Form(...),
    iv_b64: str = Form(...),
    user: SessionUser = Depends(current_user),
) -> dict[str, object]:
    db = get_database()
    store = get_object_store()
    document = _document_or_404(document_id, user.wallet_address)
    file_record = db.files.find_one({"file_id": document["file_id"], "owner_wallet": user.wallet_address})
    if not file_record:
        raise HTTPException(status_code=404, detail="Backing file not found")
    payload = await encrypted_file.read()
    _enforce_upload_size_limit(len(payload))
    storage_key = store.put_bytes("documents", f"{document_id}.bin", payload)
    db.files.update_one(
        {"file_id": document["file_id"]},
        {
            "$set": {
                "storage_key": storage_key,
                "status": "ready",
                "encryption": {
                    "algorithm": algorithm,
                    "salt_b64": salt_b64,
                    "iv_b64": iv_b64,
                },
            }
        },
    )
    append_custody_event(
        subject_type="document",
        subject_id=document_id,
        event_type="document.file_stored",
        actor_wallet=user.wallet_address,
        summary=f"Encrypted binary stored for {document['original_name']}",
    )
    return {"success": True, "documentId": document_id}


@router.get("/documents")
def list_documents(caseId: str | None = Query(default=None, alias="caseId"), user: SessionUser = Depends(current_user)) -> dict[str, object]:
    db = get_database()
    query: dict[str, Any] = {"owner_wallet": user.wallet_address, "status": {"$ne": "deleted"}}
    if caseId:
        query["case_id"] = caseId
    items = [_serialize_document(item) for item in db.documents.find(query).sort("created_at", -1)]
    return {"items": items}


@router.get("/documents/{document_id}")
def get_document(document_id: str, user: SessionUser = Depends(current_user)) -> dict[str, object]:
    item = _document_or_404(document_id, user.wallet_address)
    payload = _serialize_document(item)
    payload["chainOfCustody"] = [_serialize_custody_event(event) for event in list_custody_events(document_id)]
    return payload


@router.post("/documents/{document_id}/ocr")
def create_ocr_document(document_id: str, payload: NotarizeRequest, user: SessionUser = Depends(current_user)) -> dict[str, object]:
    if get_settings().app_env == "production":
        raise HTTPException(status_code=404, detail="OCR copy route is not available in production")
    db = get_database()
    store = get_object_store()
    document = _document_or_404(document_id, user.wallet_address)
    file_record = _backing_file_or_404(document, user.wallet_address)
    encrypted_bytes = store.read_bytes(file_record["storage_key"])
    plaintext = decrypt_bytes(
        encrypted_bytes,
        payload.passphrase,
        salt_b64=file_record["encryption"]["salt_b64"],
        iv_b64=file_record["encryption"]["iv_b64"],
    )
    try:
        ocr_result = ocr_pdf_to_searchable(plaintext)
    except OcrProcessingError as exc:
        status_code = 422 if exc.code in {"ocr-no-text-detected", "ocr-output-not-searchable"} else 503
        raise HTTPException(status_code=status_code, detail=exc.message) from exc

    searchable_pdf_sha256 = sha256_hex(ocr_result.searchable_pdf_bytes)
    encrypted_searchable_bytes, envelope = encrypt_bytes(ocr_result.searchable_pdf_bytes, payload.passphrase)
    _enforce_upload_size_limit(len(encrypted_searchable_bytes))

    new_name = _ocr_copy_name(document["original_name"])
    new_file = create_pending_file(
        owner_wallet=user.wallet_address,
        original_name=new_name,
        content_type="application/pdf",
        size=len(encrypted_searchable_bytes),
        file_type="document",
    )
    new_document = create_document(
        owner_wallet=user.wallet_address,
        case_id=document["case_id"],
        original_name=new_name,
        file_id=new_file["file_id"],
    )
    storage_key = store.put_bytes("documents", f"{new_document['document_id']}.bin", encrypted_searchable_bytes)
    now = utcnow()
    db.files.update_one(
        {"file_id": new_file["file_id"]},
        {
            "$set": {
                "storage_key": storage_key,
                "status": "ready",
                "updated_at": now,
                "encryption": {
                    "algorithm": envelope.algorithm,
                    "salt_b64": envelope.salt_b64,
                    "iv_b64": envelope.iv_b64,
                },
            }
        },
    )
    db.documents.update_one(
        {"document_id": new_document["document_id"]},
        {
            "$set": {
                "updated_at": now,
                "searchable_text_confirmed": True,
                "source_text_mode": "ocr_assisted",
                "ocr_used": True,
                "ocr_source_document_id": document_id,
                "ocr_engine": ocr_result.engine_name,
                "ocr_engine_version": ocr_result.engine_version,
                "ocr_text_sha256": ocr_result.canonical_text_sha256 or sha256_hex(ocr_result.extracted_text.encode("utf-8")),
                "ocr_layout_sha256": ocr_result.layout_sha256,
                "working_searchable_pdf_sha256": searchable_pdf_sha256,
                "ocr_output_sha256": searchable_pdf_sha256,
            }
        },
    )
    append_custody_event(
        subject_type="document",
        subject_id=document_id,
        event_type="document.ocr_requested",
        actor_wallet=user.wallet_address,
        summary=f"OCR copy created for {document['original_name']}",
        metadata={"ocr_document_id": new_document["document_id"]},
    )
    append_custody_event(
        subject_type="document",
        subject_id=new_document["document_id"],
        event_type="document.ocr_generated",
        actor_wallet=user.wallet_address,
        summary=f"Searchable OCR copy generated from {document['original_name']}",
        metadata={
            "source_document_id": document_id,
            "ocr_engine": ocr_result.engine_name,
            "ocr_engine_version": ocr_result.engine_version,
            "page_count": ocr_result.page_count,
        },
    )
    created_document = _document_or_404(new_document["document_id"], user.wallet_address)
    return {
        "documentId": created_document["document_id"],
        "originalName": created_document["original_name"],
        "searchableTextConfirmed": True,
    }


@router.get("/documents/{document_id}/download")
def download_document(document_id: str, user: SessionUser = Depends(current_user)) -> StreamingResponse:
    db = get_database()
    store = get_object_store()
    item = _document_or_404(document_id, user.wallet_address)

    if item.get("storage_key"):
        blob = store.read_bytes(item["storage_key"])
        headers = {"Content-Disposition": f'attachment; filename="{item["original_name"]}"'}
        return StreamingResponse(iter([blob]), media_type=item.get("content_type", "application/pdf"), headers=headers)

    file_record = _backing_file_or_404(item, user.wallet_address)
    blob = store.read_bytes(file_record["storage_key"])
    headers = {
        "Content-Disposition": f'attachment; filename="{item["original_name"]}.bv"',
        "X-BlockVault-Original-Name": item["original_name"],
        "X-BlockVault-Content-Type": file_record["content_type"],
        "X-BlockVault-Algorithm": file_record["encryption"]["algorithm"],
        "X-BlockVault-Salt": file_record["encryption"]["salt_b64"],
        "X-BlockVault-Iv": file_record["encryption"]["iv_b64"],
    }
    return StreamingResponse(iter([blob]), media_type="application/octet-stream", headers=headers)


@router.delete("/documents/{document_id}")
def delete_document(document_id: str, user: SessionUser = Depends(current_user)) -> dict[str, object]:
    db = get_database()
    document = _document_or_404(document_id, user.wallet_address)
    deleted_at = utcnow()

    target_ids = [document_id]
    if not document.get("source_document_id"):
        target_ids.extend(
            item["document_id"]
            for item in db.documents.find(
                {
                    "source_document_id": document_id,
                    "owner_wallet": user.wallet_address,
                    "status": {"$ne": "deleted"},
                }
            )
        )

    db.documents.update_many(
        {
            "document_id": {"$in": target_ids},
            "owner_wallet": user.wallet_address,
            "status": {"$ne": "deleted"},
        },
        {"$set": {"status": "deleted", "deleted_at": deleted_at, "updated_at": deleted_at}},
    )

    if document.get("source_document_id"):
        source_document_id = document["source_document_id"]
        latest_remaining_redaction = next(
            db.documents.find(
                {
                    "source_document_id": source_document_id,
                    "owner_wallet": user.wallet_address,
                    "status": {"$ne": "deleted"},
                }
            ).sort("created_at", -1),
            None,
        )
        db.documents.update_one(
            {
                "document_id": source_document_id,
                "owner_wallet": user.wallet_address,
                "status": {"$ne": "deleted"},
            },
            {
                "$set": {
                    "latest_redaction_result_id": latest_remaining_redaction["document_id"] if latest_remaining_redaction else None,
                    "redacted_sha256": latest_remaining_redaction["redacted_sha256"] if latest_remaining_redaction else None,
                    "updated_at": deleted_at,
                }
            },
        )

    for target_id in target_ids:
        append_custody_event(
            subject_type="document",
            subject_id=target_id,
            event_type="document.deleted",
            actor_wallet=user.wallet_address,
            summary="Document deleted" if target_id == document_id else "Derived redaction result deleted with source document",
            metadata={"deleted_by_document_id": document_id},
        )
    return {"success": True, "deletedDocumentIds": target_ids}


@router.get("/evidence/{bundle_id}")
def get_evidence_bundle(bundle_id: str, user: SessionUser = Depends(current_user)) -> dict[str, object]:
    db = get_database()
    bundle = db.evidence_bundles.find_one({"bundle_id": bundle_id, "owner_wallet": user.wallet_address})
    if not bundle:
        raise HTTPException(status_code=404, detail="Evidence bundle not found")
    document = db.documents.find_one({"document_id": bundle["document_id"], "owner_wallet": user.wallet_address})
    if not document:
        raise HTTPException(status_code=404, detail="Related document not found")

    related_events = list_custody_events(bundle["document_id"]) + list_custody_events(bundle["bundle_id"])
    related_events.sort(key=lambda event: event["created_at"])

    return {
        "bundleId": bundle["bundle_id"],
        "documentId": document["document_id"],
        "documentOriginalName": document["original_name"],
        "createdAt": bundle["created_at"].isoformat(),
        "originalSha256": bundle["original_sha256"],
        "redactedSha256": document.get("redacted_sha256"),
        "canonicalOriginalSha256": document.get("canonical_original_sha256"),
        "canonicalRedactedSha256": document.get("canonical_redacted_sha256"),
        "searchableTextConfirmed": document.get("searchable_text_confirmed"),
        "sourceTextMode": document.get("source_text_mode"),
        "ocrUsed": document.get("ocr_used"),
        "ocrEngine": document.get("ocr_engine"),
        "ocrEngineVersion": document.get("ocr_engine_version"),
        "ocrLayoutSha256": document.get("ocr_layout_sha256"),
        "workingSearchablePdfSha256": document.get("working_searchable_pdf_sha256"),
        "renderMode": document.get("render_mode"),
        "redactionEngine": document.get("redaction_engine"),
        "redactionEngineVersion": document.get("redaction_engine_version"),
        "anchorReceipt": bundle["anchor_receipt"],
        "proofBoundary": get_settings().proof_boundary,
        "zkpt": document.get("zkpt"),
        "chainOfCustody": [_serialize_custody_event(event) for event in related_events],
    }


@router.post("/documents/{document_id}/notarize")
def notarize_document(document_id: str, payload: NotarizeRequest, user: SessionUser = Depends(current_user)) -> dict[str, object]:
    db = get_database()
    store = get_object_store()
    document = _document_or_404(document_id, user.wallet_address)
    file_record = db.files.find_one({"file_id": document["file_id"], "owner_wallet": user.wallet_address})
    if not file_record or "storage_key" not in file_record:
        raise HTTPException(status_code=409, detail="Document binary not available")
    encrypted_bytes = store.read_bytes(file_record["storage_key"])
    plaintext = decrypt_bytes(
        encrypted_bytes,
        payload.passphrase,
        salt_b64=file_record["encryption"]["salt_b64"],
        iv_b64=file_record["encryption"]["iv_b64"],
    )
    original_sha256 = sha256_hex(plaintext)
    anchor_receipt = build_anchor_receipt(plaintext)
    evidence = create_evidence_bundle(
        document_id=document_id,
        owner_wallet=user.wallet_address,
        original_sha256=original_sha256,
        anchor_receipt=anchor_receipt,
    )
    db.documents.update_one(
        {"document_id": document_id},
        {
            "$set": {
                "status": "notarized",
                "original_sha256": original_sha256,
                "anchor_receipt": anchor_receipt,
                "evidence_bundle_id": evidence["bundle_id"],
            }
        },
    )
    append_custody_event(
        subject_type="document",
        subject_id=document_id,
        event_type="document.notarized",
        actor_wallet=user.wallet_address,
        summary="Document notarized and evidence bundle issued",
        metadata={"evidence_bundle_id": evidence["bundle_id"], "original_sha256": original_sha256},
    )
    return {
        "success": True,
        "anchorReceipt": anchor_receipt,
        "evidenceBundleId": evidence["bundle_id"],
        "originalSha256": original_sha256,
    }


@router.get("/evidence/{bundle_id}/export")
def export_evidence_bundle(bundle_id: str, user: SessionUser = Depends(current_user)) -> StreamingResponse:
    db = get_database()
    bundle = db.evidence_bundles.find_one({"bundle_id": bundle_id, "owner_wallet": user.wallet_address})
    if not bundle:
        raise HTTPException(status_code=404, detail="Evidence bundle not found")
    document = db.documents.find_one({"document_id": bundle["document_id"], "owner_wallet": user.wallet_address})
    if not document:
        raise HTTPException(status_code=404, detail="Related document not found")
    related_events = list_custody_events(bundle["document_id"]) + list_custody_events(bundle["bundle_id"])
    related_events.sort(key=lambda event: event["created_at"])

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bundle_manifest.json", json.dumps({"bundleId": bundle_id, "documentId": bundle["document_id"]}, indent=2))
        archive.writestr("anchor_receipt.json", json.dumps(bundle["anchor_receipt"], indent=2))
        archive.writestr(
            "document_summary.json",
            json.dumps(
                {
                    "documentId": document["document_id"],
                    "originalName": document["original_name"],
                    "originalSha256": document["original_sha256"],
                    "redactedSha256": document["redacted_sha256"],
                    "proofBoundary": get_settings().proof_boundary,
                },
                indent=2,
            ),
        )
        archive.writestr(
            "chain_of_custody.json",
            json.dumps([_serialize_custody_event(event) for event in related_events], indent=2),
        )
    payload.seek(0)
    return StreamingResponse(
        payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{bundle_id}.zip"'},
    )
