from __future__ import annotations

from typing import Any

from .crypto import random_id, sha256_hex, utcnow
from .database import get_database


def append_custody_event(
    *,
    subject_type: str,
    subject_id: str,
    event_type: str,
    actor_wallet: str | None,
    summary: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db = get_database()
    event = {
        "event_id": random_id("evt"),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "event_type": event_type,
        "actor_wallet": actor_wallet,
        "summary": summary,
        "metadata": metadata or {},
        "created_at": utcnow(),
    }
    db.custody_events.insert_one(event)
    return event


def list_custody_events(subject_id: str) -> list[dict[str, Any]]:
    db = get_database()
    return list(db.custody_events.find({"subject_id": subject_id}).sort("created_at", 1))


def create_pending_file(*, owner_wallet: str, original_name: str, content_type: str, size: int, file_type: str) -> dict[str, Any]:
    db = get_database()
    record = {
        "file_id": random_id("file"),
        "owner_wallet": owner_wallet,
        "original_name": original_name,
        "content_type": content_type,
        "size": size,
        "file_type": file_type,
        "status": "pending_upload",
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }
    db.files.insert_one(record)
    return record


def create_case(*, owner_wallet: str, title: str, description: str) -> dict[str, Any]:
    db = get_database()
    record = {
        "case_id": random_id("case"),
        "owner_wallet": owner_wallet,
        "title": title,
        "description": description,
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }
    db.cases.insert_one(record)
    append_custody_event(
        subject_type="case",
        subject_id=record["case_id"],
        event_type="case.created",
        actor_wallet=owner_wallet,
        summary=f"Case '{title}' created",
    )
    return record


def create_document(*, owner_wallet: str, case_id: str, original_name: str, file_id: str) -> dict[str, Any]:
    db = get_database()
    record = {
        "document_id": random_id("doc"),
        "case_id": case_id,
        "file_id": file_id,
        "owner_wallet": owner_wallet,
        "original_name": original_name,
        "status": "uploaded",
        "created_at": utcnow(),
        "updated_at": utcnow(),
        "anchor_receipt": None,
        "original_sha256": None,
        "redacted_sha256": None,
        "canonical_original_sha256": None,
        "canonical_redacted_sha256": None,
        "searchable_text_confirmed": None,
        "source_text_mode": None,
        "ocr_used": None,
        "ocr_engine": None,
        "ocr_engine_version": None,
        "ocr_layout_sha256": None,
        "working_searchable_pdf_sha256": None,
        "render_mode": None,
        "redaction_engine": None,
        "redaction_engine_version": None,
        "evidence_bundle_id": None,
        "source_document_id": None,
        "latest_redaction_result_id": None,
        "zkpt": None,
    }
    db.documents.insert_one(record)
    append_custody_event(
        subject_type="document",
        subject_id=record["document_id"],
        event_type="document.uploaded",
        actor_wallet=owner_wallet,
        summary=f"Document '{original_name}' uploaded",
        metadata={"case_id": case_id, "file_id": file_id},
    )
    return record


def create_evidence_bundle(*, document_id: str, owner_wallet: str, original_sha256: str, anchor_receipt: dict[str, Any]) -> dict[str, Any]:
    db = get_database()
    record = {
        "bundle_id": random_id("evidence"),
        "document_id": document_id,
        "owner_wallet": owner_wallet,
        "original_sha256": original_sha256,
        "anchor_receipt": anchor_receipt,
        "created_at": utcnow(),
    }
    db.evidence_bundles.insert_one(record)
    append_custody_event(
        subject_type="bundle",
        subject_id=record["bundle_id"],
        event_type="evidence.created",
        actor_wallet=owner_wallet,
        summary="Evidence bundle created",
        metadata={"document_id": document_id},
    )
    return record


def create_redaction_job(*, document_id: str, owner_wallet: str, search_terms: list[str], sealed_passphrase: str) -> dict[str, Any]:
    db = get_database()
    job = {
        "job_id": random_id("redact"),
        "document_id": document_id,
        "owner_wallet": owner_wallet,
        "search_terms": search_terms,
        "sealed_passphrase": sealed_passphrase,
        "status": "queued",
        "stage": "queued",
        "created_at": utcnow(),
        "updated_at": utcnow(),
        "result_document_id": None,
        "zkpt_bundle_id": None,
        "worker_task_id": None,
        "source_text_mode": None,
        "ocr_used": None,
        "ocr_engine": None,
        "ocr_engine_version": None,
        "ocr_layout_sha256": None,
        "working_searchable_pdf_sha256": None,
        "render_mode": None,
        "redaction_engine": None,
        "redaction_engine_version": None,
        "estimated_shards": None,
        "predicted_proof_ms": None,
        "classification": None,
        "onchain_eligible": None,
        "onchain_status": None,
        "document_binding_commitment": None,
        "error_code": None,
        "error_message": None,
        "duration_seconds": None,
    }
    db.redaction_jobs.insert_one(job)
    append_custody_event(
        subject_type="redaction_job",
        subject_id=job["job_id"],
        event_type="redaction.queued",
        actor_wallet=owner_wallet,
        summary="Redaction job queued",
        metadata={"document_id": document_id, "search_terms": search_terms},
    )
    return job


def build_anchor_receipt(payload: bytes) -> dict[str, Any]:
    digest = sha256_hex(payload)
    return {
        "txHash": f"0x{digest}",
        "network": "local-dev",
        "receiptType": "local-dev",
        "anchoredAt": utcnow().isoformat(),
    }
