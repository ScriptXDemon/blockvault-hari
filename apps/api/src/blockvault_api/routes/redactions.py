from __future__ import annotations

import io

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..config import Settings, get_settings
from ..crypto import seal_secret
from ..redaction_jobs import RedactionDispatchError, dispatch_redaction_job, normalize_terms
from ..database import get_database
from ..rate_limit import RateLimitPolicy, enforce_rate_limit
from ..repositories import append_custody_event, create_redaction_job
from ..schemas import CreateRedactionJobRequest
from ..security import SessionUser, current_user
from ..zkpt_bundle import build_bundle_export
from ..zkpt_onchain import ZKPTOnchainError, get_bundle_onchain_status, submit_verified_bundle_onchain

router = APIRouter(prefix="/api/v1", tags=["redactions"])


def _redaction_policy(settings: Settings) -> RateLimitPolicy:
    return RateLimitPolicy(
        name="redaction_submit",
        limit=settings.rate_limit_write_requests,
        window_seconds=settings.rate_limit_write_window_seconds,
        scope="wallet",
    )


@router.post("/redactions/jobs")
def submit_redaction_job(
    payload: CreateRedactionJobRequest,
    request: Request,
    user: SessionUser = Depends(current_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    enforce_rate_limit(request, policy=_redaction_policy(settings), wallet_address=user.wallet_address)
    normalized_terms = normalize_terms(payload.searchTerms)
    if not normalized_terms:
        raise HTTPException(status_code=400, detail="At least one search term is required")

    job = create_redaction_job(
        document_id=payload.documentId,
        owner_wallet=user.wallet_address,
        search_terms=normalized_terms,
        sealed_passphrase=seal_secret(payload.passphrase),
    )

    try:
        dispatch = dispatch_redaction_job(job["job_id"])
    except RedactionDispatchError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    db = get_database()
    current_job = db.redaction_jobs.find_one({"job_id": job["job_id"], "owner_wallet": user.wallet_address}) or job
    return {
        "jobId": current_job["job_id"],
        "status": current_job["status"],
        "stage": current_job["stage"],
        "executionMode": dispatch["execution_mode"],
        "estimatedShards": current_job.get("estimated_shards"),
        "predictedProofMs": current_job.get("predicted_proof_ms"),
        "classification": current_job.get("classification"),
        "onchainEligible": current_job.get("onchain_eligible"),
        "onchainStatus": current_job.get("onchain_status"),
        "documentBindingCommitment": current_job.get("document_binding_commitment"),
    }


@router.get("/redactions/jobs/{job_id}")
def get_redaction_job(job_id: str, user: SessionUser = Depends(current_user)) -> dict[str, object]:
    db = get_database()
    job = db.redaction_jobs.find_one({"job_id": job_id, "owner_wallet": user.wallet_address})
    if not job:
        raise HTTPException(status_code=404, detail="Redaction job not found")
    return {
        "jobId": job["job_id"],
        "status": job["status"],
        "stage": job["stage"],
        "errorCode": job.get("error_code"),
        "errorMessage": job.get("error_message"),
        "durationSeconds": job.get("duration_seconds"),
        "resultDocumentId": job.get("result_document_id"),
        "zkptBundleId": job.get("zkpt_bundle_id"),
        "workerTaskId": job.get("worker_task_id"),
        "sourceTextMode": job.get("source_text_mode"),
        "ocrUsed": job.get("ocr_used"),
        "ocrEngine": job.get("ocr_engine"),
        "ocrEngineVersion": job.get("ocr_engine_version"),
        "ocrLayoutSha256": job.get("ocr_layout_sha256"),
        "renderMode": job.get("render_mode"),
        "redactionEngine": job.get("redaction_engine"),
        "redactionEngineVersion": job.get("redaction_engine_version"),
        "estimatedShards": job.get("estimated_shards"),
        "predictedProofMs": job.get("predicted_proof_ms"),
        "classification": job.get("classification"),
        "onchainEligible": job.get("onchain_eligible"),
        "onchainStatus": job.get("onchain_status"),
        "documentBindingCommitment": job.get("document_binding_commitment"),
    }


@router.get("/redactions/jobs/{job_id}/result")
def get_redaction_job_result(job_id: str, user: SessionUser = Depends(current_user)) -> dict[str, object]:
    db = get_database()
    job = db.redaction_jobs.find_one({"job_id": job_id, "owner_wallet": user.wallet_address})
    if not job:
        raise HTTPException(status_code=404, detail="Redaction job not found")
    if job["status"] == "failed":
        raise HTTPException(status_code=409, detail=job.get("error_message") or "Redaction job failed")
    if job["status"] != "completed":
        raise HTTPException(status_code=409, detail="Redaction job is not complete")
    result_doc = db.documents.find_one({"document_id": job["result_document_id"], "owner_wallet": user.wallet_address})
    if not result_doc:
        raise HTTPException(status_code=404, detail="Result document not found")
    verification_passed = bool(result_doc["zkpt"] and result_doc["zkpt"]["status"] == "verified")
    return {
        "documentId": result_doc["document_id"],
        "originalSha256": result_doc["original_sha256"],
        "redactedSha256": result_doc["redacted_sha256"],
        "canonical_original_sha256": result_doc.get("canonical_original_sha256"),
        "canonical_redacted_sha256": result_doc.get("canonical_redacted_sha256"),
        "searchable_text_confirmed": result_doc.get("searchable_text_confirmed"),
        "source_text_mode": result_doc.get("source_text_mode"),
        "ocr_used": result_doc.get("ocr_used"),
        "ocr_engine": result_doc.get("ocr_engine"),
        "ocr_engine_version": result_doc.get("ocr_engine_version"),
        "ocr_layout_sha256": result_doc.get("ocr_layout_sha256"),
        "working_searchable_pdf_sha256": result_doc.get("working_searchable_pdf_sha256"),
        "render_mode": result_doc.get("render_mode"),
        "redaction_engine": result_doc.get("redaction_engine"),
        "redaction_engine_version": result_doc.get("redaction_engine_version"),
        "verification_passed": verification_passed,
        "zkpt": result_doc["zkpt"],
    }


@router.get("/zkpt/bundles/{bundle_id}")
def get_zkpt_bundle(bundle_id: str, user: SessionUser = Depends(current_user)) -> dict[str, object]:
    db = get_database()
    bundle = db.zkpt_bundles.find_one({"bundle_id": bundle_id, "owner_wallet": user.wallet_address})
    if not bundle:
        raise HTTPException(status_code=404, detail="ZKPT bundle not found")
    bundle["onchain"] = get_bundle_onchain_status(bundle)
    return bundle


@router.get("/zkpt/bundles/{bundle_id}/onchain-status")
def get_zkpt_bundle_onchain_status(bundle_id: str, user: SessionUser = Depends(current_user)) -> dict[str, object]:
    db = get_database()
    bundle = db.zkpt_bundles.find_one({"bundle_id": bundle_id, "owner_wallet": user.wallet_address})
    if not bundle:
        raise HTTPException(status_code=404, detail="ZKPT bundle not found")
    onchain = get_bundle_onchain_status(bundle)
    return {
        "bundleId": bundle_id,
        "status": onchain["status"],
        "onchain": onchain,
        "onchainEligible": bool((bundle.get("summary") or {}).get("onchainEligible")),
        "totalShards": int(bundle.get("total_shards") or 0),
        "profileId": (bundle.get("summary") or {}).get("profileId"),
    }


@router.post("/zkpt/bundles/{bundle_id}/submit-onchain")
def submit_zkpt_bundle_onchain(bundle_id: str, user: SessionUser = Depends(current_user)) -> dict[str, object]:
    db = get_database()
    bundle = db.zkpt_bundles.find_one({"bundle_id": bundle_id, "owner_wallet": user.wallet_address})
    if not bundle:
        raise HTTPException(status_code=404, detail="ZKPT bundle not found")

    try:
        onchain = submit_verified_bundle_onchain(bundle)
    except ZKPTOnchainError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc

    append_custody_event(
        subject_type="bundle",
        subject_id=bundle_id,
        event_type="zkpt.onchain_confirmed" if onchain["status"] == "confirmed" else "zkpt.onchain_submitted",
        actor_wallet=user.wallet_address,
        summary="Verified ZKPT bundle submitted to the on-chain receipt registry",
        metadata={
            "tx_hash": onchain.get("txHash"),
            "chain_id": onchain.get("chainId"),
            "registry_address": onchain.get("registryAddress"),
        },
    )
    return {
        "bundleId": bundle_id,
        "status": onchain["status"],
        "onchain": onchain,
    }


@router.get("/zkpt/bundles/{bundle_id}/export")
def export_zkpt_bundle(bundle_id: str, user: SessionUser = Depends(current_user)) -> StreamingResponse:
    db = get_database()
    bundle = db.zkpt_bundles.find_one({"bundle_id": bundle_id, "owner_wallet": user.wallet_address})
    if not bundle:
        raise HTTPException(status_code=404, detail="ZKPT bundle not found")
    if bundle.get("status") != "verified":
        raise HTTPException(status_code=409, detail="Only verified authoritative bundles can be exported")

    payload = io.BytesIO(build_bundle_export(bundle))
    return StreamingResponse(
        payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{bundle_id}.zip"'},
    )
