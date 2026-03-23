from __future__ import annotations

from fastapi import APIRouter

from ..config import get_settings
from ..database import ping_database
from ..redaction_jobs import get_redaction_runtime_status
from ..storage import get_object_store_status
from ..zkpt_runtime import check_zkpt_readiness

router = APIRouter(tags=["ops"])


@router.get("/health")
def health() -> dict[str, object]:
    settings = get_settings()
    zkpt_runtime = check_zkpt_readiness()
    storage_runtime = get_object_store_status()
    redaction_runtime = get_redaction_runtime_status()
    return {
        "status": "ok",
        "env": settings.app_env,
        "database": ping_database(),
        "zkpt_ready": zkpt_runtime["ready"],
        "storage_ready": storage_runtime["ready"],
        "redaction_engine_ready": redaction_runtime["redaction_engine_ready"],
        "storage_runtime": storage_runtime,
        "zkpt_runtime": zkpt_runtime,
        "redaction_runtime": redaction_runtime,
    }


@router.get("/status")
def status() -> dict[str, object]:
    settings = get_settings()
    zkpt_runtime = check_zkpt_readiness()
    storage_runtime = get_object_store_status()
    redaction_runtime = get_redaction_runtime_status()
    return {
        "app": settings.app_name,
        "env": settings.app_env,
        "proof_boundary": settings.proof_boundary,
        "zkpt_ready": zkpt_runtime["ready"],
        "storage_ready": storage_runtime["ready"],
        "redaction_engine_ready": redaction_runtime["redaction_engine_ready"],
        "artifact_version": zkpt_runtime["artifact"]["artifactVersion"],
        "storage_backend": storage_runtime["backend"],
        "storage_root": storage_runtime["root"],
        "storage_runtime": storage_runtime,
        "zkpt_runtime": zkpt_runtime,
        "redaction_runtime": redaction_runtime,
    }
