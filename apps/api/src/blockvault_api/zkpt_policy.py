from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache
from statistics import median
from typing import Any

from eth_utils import keccak

from .config import get_settings
from .crypto import utcnow
from .database import get_database
from .zkpt_poseidon import BN254_PRIME

REDACTION_CLASSIFICATIONS = {
    "single_proof_ready",
    "verified_bundle_only",
    "unsupported_until_v4",
}
ONCHAIN_STATUSES = {
    "not_submitted",
    "submitted",
    "confirmed",
    "unsupported",
    "failed",
}
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


def _pack_digestish(value: str | None) -> bytes:
    if not value:
        return bytes(32)
    raw = value.strip()
    if raw.startswith("0x"):
        raw = raw[2:]
    if _HEX64.fullmatch(raw):
        return bytes.fromhex(raw)
    return hashlib.sha256(value.encode("utf-8")).digest()


def _source_mode_flag(source_text_mode: str | None) -> int:
    return 1 if source_text_mode == "ocr_assisted" else 0


def _fallback_single_proof_total_ms(profile_id: str) -> float:
    if profile_id == "v2":
        return 295_000.0
    if profile_id == "v3c":
        return 82_000.0
    return 79_000.0


def build_document_binding_commitment(
    *,
    original_sha256: str,
    redacted_sha256: str,
    canonical_original_sha256: str | None,
    canonical_redacted_sha256: str | None,
    source_text_mode: str | None,
) -> dict[str, object]:
    packed = b"".join(
        [
            _pack_digestish(original_sha256),
            _pack_digestish(redacted_sha256),
            _pack_digestish(canonical_original_sha256),
            _pack_digestish(canonical_redacted_sha256),
            bytes([_source_mode_flag(source_text_mode)]),
        ]
    )
    commitment_digest = keccak(packed)
    commitment_field = int.from_bytes(commitment_digest, "big") % BN254_PRIME
    return {
        "version": "document_binding_v1",
        "field": str(commitment_field),
        "hash": f"0x{commitment_digest.hex()}",
        "sourceTextMode": source_text_mode or "direct_pdf",
    }


def _profile_budget_seconds(profile_id: str, estimated_shards: int) -> int:
    settings = get_settings()
    if profile_id == "v2":
        return max(settings.zkpt_proof_timeout_seconds, settings.zkpt_multi_shard_timeout_seconds)
    if estimated_shards > 1:
        return max(settings.zkpt_multi_shard_timeout_seconds, settings.zkpt_single_proof_timeout_seconds)
    return settings.zkpt_single_proof_timeout_seconds


def record_zkpt_benchmark(
    *,
    profile_id: str,
    artifact_version: str,
    total_shards: int,
    classification: str,
    status: str,
    source_text_mode: str | None,
    onchain_eligible: bool,
    predicted_proof_ms: float,
    prove_ms: float,
    total_ms: float,
) -> None:
    db = get_database()
    db.zkpt_benchmarks.insert_one(
        {
            "profile_id": profile_id,
            "artifact_version": artifact_version,
            "total_shards": total_shards,
            "classification": classification,
            "status": status,
            "source_text_mode": source_text_mode,
            "onchain_eligible": onchain_eligible,
            "predicted_proof_ms": round(predicted_proof_ms, 3),
            "prove_ms": round(prove_ms, 3),
            "total_ms": round(total_ms, 3),
            "created_at": utcnow(),
        }
    )


def summarize_recent_single_proof_benchmark(profile_id: str) -> dict[str, object] | None:
    db = get_database()
    rows = list(
        db.zkpt_benchmarks.find(
            {
                "profile_id": profile_id,
                "status": "verified",
                "total_shards": 1,
            }
        ).sort("created_at", -1).limit(10)
    )
    if not rows:
        return None
    prove_values = [float(item.get("prove_ms") or 0.0) for item in rows]
    total_values = [float(item.get("total_ms") or 0.0) for item in rows]
    predicted_values = [float(item.get("predicted_proof_ms") or 0.0) for item in rows if item.get("predicted_proof_ms") is not None]
    return {
        "sampleCount": len(rows),
        "medianProveMs": round(median(prove_values), 3),
        "medianTotalMs": round(median(total_values), 3),
        "medianPredictedProofMs": round(median(predicted_values), 3) if predicted_values else None,
        "latestAt": rows[0]["created_at"].isoformat(),
    }


def estimate_redaction_preflight(
    *,
    projection_bytes_length: int,
    profile_id: str,
    segment_size: int,
    segments_per_shard: int,
    proof_model: str = "full_segment_windows",
    modified_segments_count: int | None = None,
) -> dict[str, object]:
    settings = get_settings()
    segment_count = max(1, math.ceil(max(projection_bytes_length, 1) / max(segment_size, 1)))
    proof_units = segment_count
    if proof_model == "sparse_update" and modified_segments_count is not None:
        proof_units = max(1, modified_segments_count)
    estimated_shards = max(1, math.ceil(proof_units / max(segments_per_shard, 1)))
    baseline = summarize_recent_single_proof_benchmark(profile_id)
    single_shard_total_ms = float(
        (baseline or {}).get("medianTotalMs") or _fallback_single_proof_total_ms(profile_id)
    )
    parallel_workers = max(1, min(estimated_shards, settings.zkpt_max_parallel_shards))
    predicted_proof_ms = math.ceil(estimated_shards / parallel_workers) * single_shard_total_ms
    multi_shard_budget_ms = settings.zkpt_multi_shard_timeout_seconds * 1000
    if estimated_shards > settings.zkpt_preflight_max_supported_shards and predicted_proof_ms > multi_shard_budget_ms:
        classification = "unsupported_until_v4"
    elif estimated_shards > 1 or predicted_proof_ms > (settings.zkpt_single_proof_target_seconds * 1000):
        classification = "verified_bundle_only"
    else:
        classification = "single_proof_ready"
    onchain_eligible = classification == "single_proof_ready"
    return {
        "classification": classification,
        "estimatedShards": estimated_shards,
        "predictedProofMs": round(predicted_proof_ms, 3),
        "parallelShardBatches": math.ceil(estimated_shards / parallel_workers),
        "runtimeBudgetSeconds": _profile_budget_seconds(profile_id, estimated_shards),
        "singleProofReady": classification == "single_proof_ready",
        "onchainEligible": onchain_eligible,
        "proofModel": proof_model,
        "proofUnits": proof_units,
        "recentSingleProofBenchmark": baseline,
    }


@lru_cache(maxsize=1)
def get_preflight_thresholds() -> dict[str, object]:
    settings = get_settings()
    return {
        "singleProofTargetSeconds": settings.zkpt_single_proof_target_seconds,
        "singleProofTimeoutSeconds": settings.zkpt_single_proof_timeout_seconds,
        "multiShardTimeoutSeconds": settings.zkpt_multi_shard_timeout_seconds,
        "maxParallelShards": max(1, settings.zkpt_max_parallel_shards),
        "maxSupportedShards": max(1, settings.zkpt_preflight_max_supported_shards),
        "directOnchainMaxShards": 1 if settings.zkpt_onchain_single_proof_only else max(1, settings.zkpt_preflight_max_supported_shards),
    }


def reset_zkpt_policy_cache() -> None:
    get_preflight_thresholds.cache_clear()
