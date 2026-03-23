from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import queue
import threading
import time
from dataclasses import asdict
from functools import lru_cache
from typing import Any

from celery import Celery

from .config import get_settings
from .crypto import open_secret, random_id, sha256_hex, utcnow
from .database import get_database
from .ocr import OcrProcessingError, extract_searchable_pdf_layout, get_ocr_runtime_status, ocr_pdf_to_searchable
from .redaction_engine import RedactionEngineError, get_redaction_engine_status, has_extractable_text, run_rust_redaction_engine
from .repositories import append_custody_event
from .storage import get_object_store
from .zkpt_artifacts import ZKPTArtifactError, get_active_artifact_version, get_artifact_version, get_selected_artifact_profile
from .zkpt_bundle import create_verified_bundle
from .zkpt_onchain import default_onchain_status
from .zkpt_policy import (
    build_document_binding_commitment,
    estimate_redaction_preflight,
    get_preflight_thresholds,
)
from .zkpt_prover import SnarkjsPlonkProver, ZKPTProverError
from .zkpt_witness import CircuitConfig, build_text_redaction_projection, generate_circuit_witness, normalize_policy_terms

TASK_NAME = "blockvault.redactions.run"
_RUNTIME_STATUS_CACHE: dict[str, object] | None = None
_RUNTIME_STATUS_CACHE_AT = 0.0


class RedactionDispatchError(RuntimeError):
    pass


class UnsupportedZKPTProfileError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _normalize_terms(search_terms: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for term in search_terms:
        cleaned = term.strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        output.append(cleaned)
    return output


def normalize_terms(search_terms: list[str]) -> list[str]:
    return _normalize_terms(search_terms)


def _canonical_projection_bytes(text: str) -> bytes:
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _build_segment_term_map(source_text: str, normalized_terms: list[str], segment_size: int) -> dict[int, str]:
    if not normalized_terms:
        return {}

    mapping: dict[int, str] = {}
    source_bytes = _canonical_projection_bytes(source_text)
    for index, offset in enumerate(range(0, len(source_bytes), segment_size)):
        segment = source_bytes[offset:offset + segment_size].decode("utf-8", errors="ignore").lower()
        for term in normalized_terms:
            if term in segment:
                mapping[index] = term
                break
    return mapping


def _persist_inline_ocr_artifacts(*, job_id: str, ocr_result: Any, store: Any) -> dict[str, object]:
    layout_payload = _canonical_json_bytes(ocr_result.layout or {})
    layout_key = store.put_bytes("redaction-artifacts", f"{job_id}/ocr/layout.json", layout_payload)
    working_pdf_key = store.put_bytes(
        "redaction-artifacts",
        f"{job_id}/ocr/working-searchable.pdf",
        ocr_result.searchable_pdf_bytes,
    )
    page_keys: list[dict[str, object]] = []
    for page in ocr_result.page_images:
        content_type = getattr(page, "content_type", "image/png")
        suffix = ".jpg" if content_type.endswith(("jpeg", "jpg")) else ".png"
        storage_key = store.put_bytes(
            "redaction-artifacts",
            f"{job_id}/ocr/pages/page-{page.page_index:04d}{suffix}",
            page.image_bytes,
        )
        page_keys.append(
            {
                "pageIndex": page.page_index,
                "storageKey": storage_key,
                "contentType": content_type,
                "imageWidth": page.image_width,
                "imageHeight": page.image_height,
            }
        )
    return {
        "layout_storage_key": layout_key,
        "working_searchable_pdf_storage_key": working_pdf_key,
        "page_image_storage_keys": page_keys,
    }


def _split_window_projection_into_shards(
    *,
    projection: Any,
    config: CircuitConfig,
) -> list[dict[str, object]]:
    original_segments = [
        projection.original_bytes[offset:offset + config.segment_size]
        for offset in range(0, len(projection.original_bytes), config.segment_size)
    ]
    redacted_segments = [
        projection.redacted_bytes[offset:offset + config.segment_size]
        for offset in range(0, len(projection.redacted_bytes), config.segment_size)
    ]
    if len(original_segments) != len(redacted_segments):
        raise ValueError("Canonical projection segment counts do not match")

    shards: list[dict[str, object]] = []
    for shard_index, start in enumerate(range(0, len(original_segments), config.num_segments)):
        stop = min(start + config.num_segments, len(original_segments))
        global_indices = list(range(start, stop))
        segment_to_term = {
            local_index: projection.segment_to_term[global_index]
            for local_index, global_index in enumerate(global_indices)
            if global_index in projection.segment_to_term
        }
        modified_global = [index for index in projection.modified_indices if start <= index < stop]
        shards.append(
            {
                "shard_index": shard_index,
                "shard_range": {
                    "startSegment": start,
                    "endSegmentExclusive": stop,
                },
                "original_bytes": b"".join(original_segments[start:stop]),
                "redacted_bytes": b"".join(redacted_segments[start:stop]),
                "segment_to_term": segment_to_term,
                "modified_indices": [index - start for index in modified_global],
                "global_modified_indices": modified_global,
                "proof_model": "full_segment_windows",
            }
        )
    return shards


def _split_sparse_projection_shards(
    *,
    projection: Any,
    config: CircuitConfig,
) -> list[dict[str, object]]:
    if not projection.modified_indices:
        raise ValueError("Sparse proof generation requires at least one modified segment")

    shards: list[dict[str, object]] = []
    modified_indices = list(projection.modified_indices)
    for shard_index, start in enumerate(range(0, len(modified_indices), config.num_segments)):
        selected_indices = modified_indices[start:start + config.num_segments]
        shards.append(
            {
                "shard_index": shard_index,
                "shard_range": {
                    "startSegment": selected_indices[0],
                    "endSegmentExclusive": selected_indices[-1] + 1,
                },
                "original_bytes": projection.original_bytes,
                "redacted_bytes": projection.redacted_bytes,
                "segment_to_term": projection.segment_to_term,
                "selected_indices": selected_indices,
                "modified_indices": selected_indices,
                "global_modified_indices": selected_indices,
                "proof_model": "sparse_update",
            }
        )
    return shards


def _split_projection_for_proof_model(
    *,
    projection: Any,
    config: CircuitConfig,
    proof_model: str,
) -> list[dict[str, object]]:
    if proof_model == "sparse_update":
        return _split_sparse_projection_shards(projection=projection, config=config)
    return _split_window_projection_into_shards(projection=projection, config=config)


def _build_failed_zkpt_payload(
    code: str,
    message: str,
    artifact_version: str | None = None,
    *,
    classification: str = "verified_bundle_only",
    estimated_shards: int = 0,
    predicted_proof_ms: float | None = None,
    onchain_eligible: bool = False,
    onchain_status: str | None = None,
    document_binding_commitment: str | None = None,
) -> dict[str, object]:
    settings = get_settings()
    return {
        "mode": settings.zkpt_mode,
        "status": "failed",
        "bundle_id": None,
        "artifact_version": artifact_version,
        "profile_id": get_selected_artifact_profile(),
        "profile_class": None,
        "proof_boundary": settings.proof_boundary,
        "verified_shards": 0,
        "total_shards": 0,
        "estimated_shards": estimated_shards,
        "predicted_proof_ms": predicted_proof_ms,
        "classification": classification,
        "onchain_eligible": onchain_eligible,
        "onchain_status": onchain_status or ("unsupported" if not onchain_eligible else "not_submitted"),
        "document_binding_commitment": document_binding_commitment,
        "fallback_mode": False,
        "prover_backend": None,
        "error": {
            "code": code,
            "message": message,
        },
    }


def _build_unsupported_zkpt_payload(
    code: str,
    message: str,
    artifact_version: str | None = None,
    *,
    classification: str = "unsupported_until_v4",
    estimated_shards: int = 0,
    predicted_proof_ms: float | None = None,
    onchain_eligible: bool = False,
    onchain_status: str = "unsupported",
    document_binding_commitment: str | None = None,
) -> dict[str, object]:
    settings = get_settings()
    return {
        "mode": settings.zkpt_mode,
        "status": "unsupported",
        "bundle_id": None,
        "artifact_version": artifact_version,
        "profile_id": get_selected_artifact_profile(),
        "profile_class": None,
        "proof_boundary": settings.proof_boundary,
        "verified_shards": 0,
        "total_shards": 0,
        "estimated_shards": estimated_shards,
        "predicted_proof_ms": predicted_proof_ms,
        "classification": classification,
        "onchain_eligible": onchain_eligible,
        "onchain_status": onchain_status,
        "document_binding_commitment": document_binding_commitment,
        "fallback_mode": False,
        "prover_backend": None,
        "error": {
            "code": code,
            "message": message,
        },
    }


def _validate_artifact_contract(artifact: Any, settings: Any) -> None:
    if artifact.profile_class != "authoritative":
        raise UnsupportedZKPTProfileError(
            "unsupported-profile",
            f"Selected ZKPT profile '{artifact.profile_id}' is '{artifact.profile_class}' and cannot satisfy authoritative verification"
        )
    if artifact.proof_boundary != settings.proof_boundary:
        raise UnsupportedZKPTProfileError(
            "unsupported-proof-boundary",
            f"Selected ZKPT profile proof boundary '{artifact.proof_boundary}' does not match '{settings.proof_boundary}'"
        )


def _resolve_parallel_shard_workers(total_shards: int) -> int:
    if total_shards <= 1:
        return 1
    return max(1, min(total_shards, get_settings().zkpt_max_parallel_shards))


def _build_circuit_config(artifact: Any) -> CircuitConfig:
    return CircuitConfig(
        num_segments=artifact.max_segments,
        tree_depth=artifact.tree_depth,
        num_policy_rules=artifact.max_policy_rules,
        segment_size=artifact.segment_size,
    )


def _plan_artifact_execution(
    *,
    artifact: Any,
    original_text: str,
    search_terms: list[str],
    document_binding: dict[str, object],
    redaction_manifest: dict[str, object] | None = None,
) -> dict[str, object]:
    settings = get_settings()
    _validate_artifact_contract(artifact, settings)
    config = _build_circuit_config(artifact)
    normalized_terms = normalize_policy_terms(search_terms)
    projection = build_text_redaction_projection(
        source_text=original_text,
        policy_terms=normalized_terms,
        segment_size=config.segment_size,
    )
    if not projection.modified_indices:
        raise ValueError("No canonical projection segments matched the requested redaction terms")
    preflight = estimate_redaction_preflight(
        projection_bytes_length=len(projection.original_bytes),
        profile_id=artifact.profile_id,
        segment_size=config.segment_size,
        segments_per_shard=config.num_segments,
        proof_model=artifact.proof_model,
        modified_segments_count=len(projection.modified_indices),
    )
    shard_payloads = _split_projection_for_proof_model(
        projection=projection,
        config=config,
        proof_model=artifact.proof_model,
    )
    total_shards = len(shard_payloads)
    onchain_safe_profile = settings.zkpt_onchain_safe_profile
    classification = str(preflight["classification"])
    if artifact.profile_id != onchain_safe_profile and classification == "single_proof_ready":
        classification = "verified_bundle_only"
    onchain_eligible = classification == "single_proof_ready"
    onchain_state = default_onchain_status(onchain_eligible)
    return {
        "artifact": artifact,
        "config": config,
        "normalized_terms": normalized_terms,
        "projection": projection,
        "preflight": {
            **preflight,
            "classification": classification,
            "estimatedShards": total_shards,
            "onchainEligible": onchain_eligible,
            "onchainStatus": onchain_state["status"],
        },
        "shard_payloads": shard_payloads,
        "total_shards": total_shards,
        "document_binding": document_binding,
        "source_text_mode": (redaction_manifest or {}).get("source_text_mode"),
    }


def select_authoritative_plan(
    *,
    original_text: str,
    search_terms: list[str],
    document_binding: dict[str, object],
    redaction_manifest: dict[str, object] | None = None,
    artifact_profile_id: str | None = None,
) -> dict[str, object]:
    settings = get_settings()
    if artifact_profile_id:
        return _plan_artifact_execution(
            artifact=get_artifact_version(artifact_profile_id),
            original_text=original_text,
            search_terms=search_terms,
            document_binding=document_binding,
            redaction_manifest=redaction_manifest,
        )

    default_plan = _plan_artifact_execution(
        artifact=get_active_artifact_version(),
        original_text=original_text,
        search_terms=search_terms,
        document_binding=document_binding,
        redaction_manifest=redaction_manifest,
    )

    onchain_safe_profile = settings.zkpt_onchain_safe_profile
    if (
        not onchain_safe_profile
        or onchain_safe_profile == default_plan["artifact"].profile_id
        or default_plan["artifact"].proof_model != "sparse_update"
    ):
        return default_plan

    try:
        onchain_plan = _plan_artifact_execution(
            artifact=get_artifact_version(onchain_safe_profile),
            original_text=original_text,
            search_terms=search_terms,
            document_binding=document_binding,
            redaction_manifest=redaction_manifest,
        )
    except (ZKPTArtifactError, UnsupportedZKPTProfileError, ValueError):
        return default_plan

    if onchain_plan["preflight"]["classification"] == "single_proof_ready":
        return onchain_plan
    return default_plan


def _prove_projection_shard(
    *,
    shard: dict[str, object],
    artifact: Any,
    config: CircuitConfig,
    normalized_terms: list[str],
    document_binding_commitment: str,
    timeout_seconds: int,
) -> dict[str, object]:
    shard_original_bytes = shard["original_bytes"]
    shard_redacted_bytes = shard["redacted_bytes"]
    witness_package = generate_circuit_witness(
        original_bytes=shard_original_bytes,
        redacted_bytes=shard_redacted_bytes,
        policy_terms=normalized_terms,
        binding_value=document_binding_commitment,
        binding_input_name=artifact.binding_input_name,
        proof_model=str(shard.get("proof_model") or artifact.proof_model),
        selected_indices=shard.get("selected_indices"),
        config=config,
        segment_to_term=shard["segment_to_term"],
    )
    proof_execution = SnarkjsPlonkProver(
        artifact_version=artifact,
        timeout_seconds=timeout_seconds,
    ).prove(witness_package["witness"])
    proof_payload = asdict(proof_execution)
    proof_payload["verification_data"] = witness_package["verification_data"]
    proof_payload["timings"] = {
        **proof_payload.get("timings", {}),
        "witness_ms": witness_package.get("metadata", {}).get("witness_ms", 0.0),
        "projection_ms": 0.0,
    }
    proof_payload["shard_index"] = shard["shard_index"]
    proof_payload["shard_range"] = shard["shard_range"]
    proof_payload["modified_indices"] = shard["global_modified_indices"]
    return proof_payload


def _prove_projection_shards(
    *,
    shard_payloads: list[dict[str, object]],
    artifact: Any,
    config: CircuitConfig,
    normalized_terms: list[str],
    document_binding_commitment: str,
    timeout_seconds: int,
) -> tuple[list[dict[str, object]], int]:
    total_shards = len(shard_payloads)
    max_parallel_shards = _resolve_parallel_shard_workers(total_shards)
    if max_parallel_shards == 1:
        return (
            [
                _prove_projection_shard(
                    shard=shard,
                    artifact=artifact,
                    config=config,
                    normalized_terms=normalized_terms,
                    document_binding_commitment=document_binding_commitment,
                    timeout_seconds=timeout_seconds,
                )
                for shard in shard_payloads
            ],
            max_parallel_shards,
        )

    proof_payloads: list[dict[str, object] | None] = [None] * total_shards
    with ThreadPoolExecutor(max_workers=max_parallel_shards, thread_name_prefix="zkpt-shard") as executor:
        futures = [
            executor.submit(
                _prove_projection_shard,
                shard=shard,
                artifact=artifact,
                config=config,
                normalized_terms=normalized_terms,
                document_binding_commitment=document_binding_commitment,
                timeout_seconds=timeout_seconds,
            )
            for shard in shard_payloads
        ]
        try:
            for future in as_completed(futures):
                proof_payload = future.result()
                proof_payloads[int(proof_payload["shard_index"])] = proof_payload
        except Exception:
            for future in futures:
                future.cancel()
            raise

    return ([payload for payload in proof_payloads if payload is not None], max_parallel_shards)


def attempt_authoritative_proof(
    *,
    original_text: str,
    masked_text: str,
    original_sha256: str,
    redacted_sha256: str,
    redacted_document_id: str,
    redaction_job_id: str,
    owner_wallet: str,
    search_terms: list[str],
    redaction_manifest: dict[str, object] | None = None,
    artifact_profile_id: str | None = None,
) -> tuple[dict[str, object], str | None]:
    settings = get_settings()
    artifact = None
    preflight_metadata: dict[str, object] = {
        "classification": "verified_bundle_only",
        "estimatedShards": 0,
        "predictedProofMs": None,
        "onchainEligible": False,
        "onchainStatus": "unsupported",
        "documentBindingCommitment": None,
    }
    try:
        artifact = get_artifact_version(artifact_profile_id) if artifact_profile_id else get_active_artifact_version()
        canonical_original_sha256 = (redaction_manifest or {}).get("canonical_original_sha256") or sha256_hex(
            _canonical_projection_bytes(original_text)
        )
        canonical_redacted_sha256 = (redaction_manifest or {}).get("canonical_redacted_sha256") or sha256_hex(
            _canonical_projection_bytes(masked_text)
        )
        source_text_mode = (redaction_manifest or {}).get("source_text_mode")
        document_binding = build_document_binding_commitment(
            original_sha256=original_sha256,
            redacted_sha256=redacted_sha256,
            canonical_original_sha256=canonical_original_sha256,
            canonical_redacted_sha256=canonical_redacted_sha256,
            source_text_mode=source_text_mode,
        )
        plan = select_authoritative_plan(
            original_text=original_text,
            search_terms=search_terms,
            document_binding=document_binding,
            redaction_manifest=redaction_manifest,
            artifact_profile_id=artifact_profile_id,
        )
        artifact = plan["artifact"]
        config = plan["config"]
        normalized_terms = plan["normalized_terms"]
        projection = plan["projection"]
        preflight = plan["preflight"]
        shard_payloads = plan["shard_payloads"]
        total_shards = int(plan["total_shards"])
        onchain_state = default_onchain_status(bool(preflight["onchainEligible"]))
        original_projection = projection.original_bytes
        redacted_projection = projection.redacted_bytes
        preflight_metadata = {
            **preflight_metadata,
            "classification": preflight["classification"],
            "estimatedShards": total_shards,
            "predictedProofMs": preflight["predictedProofMs"],
            "onchainEligible": preflight["onchainEligible"],
            "onchainStatus": onchain_state["status"],
            "documentBindingCommitment": document_binding["field"],
        }
        if preflight["classification"] == "unsupported_until_v4":
            payload = _build_unsupported_zkpt_payload(
                "unsupported-until-v4",
                "Current authoritative profile would require a sparse-proof upgrade for this document size",
                artifact.artifact_version_id,
                classification=str(preflight["classification"]),
                estimated_shards=total_shards,
                predicted_proof_ms=float(preflight["predictedProofMs"]),
                onchain_eligible=bool(preflight["onchainEligible"]),
                onchain_status=onchain_state["status"],
                document_binding_commitment=str(document_binding["field"]),
            )
            payload["profile_id"] = artifact.profile_id
            payload["profile_class"] = artifact.profile_class
            payload["total_shards"] = total_shards
            return payload, None
        proof_payloads, max_parallel_shards = _prove_projection_shards(
            shard_payloads=shard_payloads,
            artifact=artifact,
            config=config,
            normalized_terms=normalized_terms,
            document_binding_commitment=str(document_binding["field"]),
            timeout_seconds=int(preflight["runtimeBudgetSeconds"]),
        )
        projection_metadata = {
            "representation": projection.representation,
            "projectionEncoding": "utf-8",
            "originalProjectionSha256": sha256_hex(original_projection),
            "redactedProjectionSha256": sha256_hex(redacted_projection),
            "canonicalOriginalSha256": canonical_original_sha256,
            "canonicalRedactedSha256": canonical_redacted_sha256,
            "sourceTextMode": source_text_mode,
            "ocrUsed": (redaction_manifest or {}).get("ocr_used"),
            "ocrEngine": (redaction_manifest or {}).get("ocr_engine"),
            "ocrEngineVersion": (redaction_manifest or {}).get("ocr_engine_version"),
            "ocrLayoutSha256": (redaction_manifest or {}).get("ocr_layout_sha256"),
            "workingSearchablePdfSha256": (redaction_manifest or {}).get("working_searchable_pdf_sha256"),
            "renderMode": (redaction_manifest or {}).get("render_mode"),
            "redactionEngine": (redaction_manifest or {}).get("engine_name"),
            "redactionEngineVersion": (redaction_manifest or {}).get("engine_version"),
            "normalizedTerms": normalized_terms,
            "modifiedIndices": projection.modified_indices,
            "estimatedShards": total_shards,
            "predictedProofMs": preflight["predictedProofMs"],
            "classification": preflight["classification"],
            "onchainEligible": preflight["onchainEligible"],
            "onchainStatus": onchain_state["status"],
            "documentBindingCommitment": document_binding["field"],
            "proofModel": artifact.proof_model,
            "bindingInputName": artifact.binding_input_name,
            "proofUnits": preflight["proofUnits"],
            "documentBindingHash": document_binding["hash"],
            "shards": [
                {
                    "shardIndex": shard["shard_index"],
                    "shardRange": shard["shard_range"],
                    "modifiedIndices": shard["global_modified_indices"],
                }
                for shard in shard_payloads
            ],
            "totalShards": total_shards,
            "maxParallelShards": max_parallel_shards,
            "shardExecutionMode": "parallel" if max_parallel_shards > 1 else "sequential",
            "runtimeBudgetSeconds": preflight["runtimeBudgetSeconds"],
            "recentSingleProofBenchmark": preflight["recentSingleProofBenchmark"],
        }
        bundle = create_verified_bundle(
            document_id=redacted_document_id,
            redaction_job_id=redaction_job_id,
            owner_wallet=owner_wallet,
            artifact=artifact,
            projection_metadata=projection_metadata,
            proof_executions=proof_payloads,
            original_sha256=original_sha256,
            redacted_sha256=redacted_sha256,
        )
        return (
            {
                "mode": settings.zkpt_mode,
                "status": "verified",
                "bundle_id": bundle["bundle_id"],
                "artifact_version": artifact.artifact_version_id,
                "profile_id": artifact.profile_id,
                "profile_class": artifact.profile_class,
                "proof_boundary": settings.proof_boundary,
                "verified_shards": bundle["verified_shards"],
                "total_shards": bundle["total_shards"],
                "estimated_shards": total_shards,
                "predicted_proof_ms": preflight["predictedProofMs"],
                "classification": preflight["classification"],
                "onchain_eligible": preflight["onchainEligible"],
                "onchain_status": bundle["onchain"]["status"],
                "document_binding_commitment": document_binding["field"],
                "proof_model": artifact.proof_model,
                "binding_input_name": artifact.binding_input_name,
                "fallback_mode": bundle["fallback_mode"],
                "prover_backend": proof_payloads[0].get("backend"),
                "error": None,
            },
            bundle["bundle_id"],
        )
    except ZKPTArtifactError as exc:
        return _build_failed_zkpt_payload(
            "artifact-invalid",
            str(exc),
            settings.zkpt_artifact_version,
            classification=str(preflight_metadata["classification"]),
            estimated_shards=int(preflight_metadata["estimatedShards"]),
            predicted_proof_ms=preflight_metadata["predictedProofMs"],
            onchain_eligible=bool(preflight_metadata["onchainEligible"]),
            onchain_status=str(preflight_metadata["onchainStatus"]),
            document_binding_commitment=preflight_metadata["documentBindingCommitment"],
        ), None
    except UnsupportedZKPTProfileError as exc:
        artifact_version = artifact.artifact_version_id if artifact else settings.zkpt_artifact_version
        payload = _build_unsupported_zkpt_payload(
            exc.code,
            exc.message,
            artifact_version,
            classification=str(preflight_metadata["classification"]),
            estimated_shards=int(preflight_metadata["estimatedShards"]),
            predicted_proof_ms=preflight_metadata["predictedProofMs"],
            onchain_eligible=bool(preflight_metadata["onchainEligible"]),
            onchain_status=str(preflight_metadata["onchainStatus"]),
            document_binding_commitment=preflight_metadata["documentBindingCommitment"],
        )
        if artifact:
            payload["profile_id"] = artifact.profile_id
            payload["profile_class"] = artifact.profile_class
        return payload, None
    except ZKPTProverError as exc:
        artifact_version = artifact.artifact_version_id if artifact else settings.zkpt_artifact_version
        payload = _build_failed_zkpt_payload(
            exc.code,
            exc.message,
            artifact_version,
            classification=str(preflight_metadata["classification"]),
            estimated_shards=int(preflight_metadata["estimatedShards"]),
            predicted_proof_ms=preflight_metadata["predictedProofMs"],
            onchain_eligible=bool(preflight_metadata["onchainEligible"]),
            onchain_status=str(preflight_metadata["onchainStatus"]),
            document_binding_commitment=preflight_metadata["documentBindingCommitment"],
        )
        if artifact:
            payload["profile_id"] = artifact.profile_id
            payload["profile_class"] = artifact.profile_class
            payload["total_shards"] = int(preflight_metadata["estimatedShards"])
        return payload, None
    except ValueError as exc:
        artifact_version = artifact.artifact_version_id if artifact else settings.zkpt_artifact_version
        payload = _build_failed_zkpt_payload(
            "projection-unsupported",
            str(exc),
            artifact_version,
            classification=str(preflight_metadata["classification"]),
            estimated_shards=int(preflight_metadata["estimatedShards"]),
            predicted_proof_ms=preflight_metadata["predictedProofMs"],
            onchain_eligible=bool(preflight_metadata["onchainEligible"]),
            onchain_status=str(preflight_metadata["onchainStatus"]),
            document_binding_commitment=preflight_metadata["documentBindingCommitment"],
        )
        if artifact:
            payload["profile_id"] = artifact.profile_id
            payload["profile_class"] = artifact.profile_class
        return payload, None
    except Exception:
        artifact_version = artifact.artifact_version_id if artifact else settings.zkpt_artifact_version
        payload = _build_failed_zkpt_payload(
            "prover-runtime-error",
            "Authoritative proof generation failed during runtime execution",
            artifact_version,
            classification=str(preflight_metadata["classification"]),
            estimated_shards=int(preflight_metadata["estimatedShards"]),
            predicted_proof_ms=preflight_metadata["predictedProofMs"],
            onchain_eligible=bool(preflight_metadata["onchainEligible"]),
            onchain_status=str(preflight_metadata["onchainStatus"]),
            document_binding_commitment=preflight_metadata["documentBindingCommitment"],
        )
        if artifact:
            payload["profile_id"] = artifact.profile_id
            payload["profile_class"] = artifact.profile_class
            payload["total_shards"] = int(preflight_metadata["estimatedShards"])
        return payload, None


def attempt_authoritative_proof_with_deadline(*, timeout_seconds: int | None = None, **kwargs: Any) -> tuple[dict[str, object], str | None]:
    settings = get_settings()
    result_queue: queue.Queue[tuple[dict[str, object], str | None]] = queue.Queue(maxsize=1)
    artifact_profile_id = kwargs.get("artifact_profile_id")

    def runner() -> None:
        result_queue.put(attempt_authoritative_proof(**kwargs))

    proof_thread = threading.Thread(target=runner, daemon=True, name=f"zkpt-proof-{kwargs.get('redaction_job_id', 'job')}")
    proof_thread.start()
    effective_timeout = timeout_seconds or settings.zkpt_proof_timeout_seconds
    proof_thread.join(timeout=effective_timeout)
    if proof_thread.is_alive():
        timeout_artifact_version = settings.zkpt_artifact_version
        if artifact_profile_id:
            try:
                timeout_artifact_version = get_artifact_version(artifact_profile_id).artifact_version_id
            except Exception:
                timeout_artifact_version = artifact_profile_id
        return _build_failed_zkpt_payload(
            "prover-timeout",
            f"Authoritative proof exceeded the {effective_timeout}s runtime budget",
            timeout_artifact_version,
            classification="verified_bundle_only",
            onchain_eligible=False,
            onchain_status="unsupported",
        ), None
    return result_queue.get_nowait()


def _get_document_and_file(document_id: str, wallet: str) -> tuple[dict[str, Any], dict[str, Any]]:
    db = get_database()
    document = db.documents.find_one({"document_id": document_id, "owner_wallet": wallet, "status": {"$ne": "deleted"}})
    if not document:
        raise LookupError("Document not found")
    file_record = db.files.find_one({"file_id": document["file_id"], "owner_wallet": wallet})
    if not file_record:
        raise LookupError("Backing file not found")
    return document, file_record


@lru_cache(maxsize=1)
def get_celery_client() -> Celery | None:
    settings = get_settings()
    if not settings.celery_broker_url:
        return None
    client = Celery(
        "blockvault_api",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend or settings.celery_broker_url,
    )
    client.conf.task_serializer = "json"
    client.conf.result_serializer = "json"
    client.conf.accept_content = ["json"]
    return client


def reset_redaction_runtime_cache() -> None:
    global _RUNTIME_STATUS_CACHE, _RUNTIME_STATUS_CACHE_AT
    get_celery_client.cache_clear()
    _RUNTIME_STATUS_CACHE = None
    _RUNTIME_STATUS_CACHE_AT = 0.0


def _worker_ping(client: Celery) -> bool:
    timeout = max(get_settings().celery_ping_timeout_seconds, 0.1)
    try:
        inspector = client.control.inspect(timeout=timeout)
        response = inspector.ping() if inspector is not None else None
        if response:
            return True
    except Exception:
        pass
    try:
        return bool(client.control.ping(timeout=timeout))
    except Exception:
        return False


def get_redaction_runtime_status(*, force_refresh: bool = False) -> dict[str, object]:
    global _RUNTIME_STATUS_CACHE, _RUNTIME_STATUS_CACHE_AT
    settings = get_settings()
    ttl_seconds = max(settings.redaction_runtime_status_ttl_seconds, 0.0)
    if not force_refresh and _RUNTIME_STATUS_CACHE is not None and (time.monotonic() - _RUNTIME_STATUS_CACHE_AT) < ttl_seconds:
        return dict(_RUNTIME_STATUS_CACHE)

    configured = bool(settings.celery_broker_url)
    worker_ready = False
    if configured:
        client = get_celery_client()
        if client is not None:
            worker_ready = _worker_ping(client)
    fallback_enabled = settings.allow_inline_redaction_fallback
    effective_mode = "worker" if worker_ready else "inline_fallback"
    engine_status = get_redaction_engine_status()
    ocr_status = get_ocr_runtime_status()
    ready = (worker_ready or fallback_enabled) and engine_status["ready"]
    status = {
        "configured": configured,
        "worker_ready": worker_ready,
        "fallback_enabled": fallback_enabled,
        "effective_mode": effective_mode,
        "ready": ready,
        "task_name": TASK_NAME,
        "redaction_engine_ready": engine_status["ready"],
        "redaction_engine_version": engine_status["version"],
        "redaction_engine_path": engine_status["path"],
        "redaction_engine_mode": engine_status["mode"],
        "redaction_engine_error": engine_status["error"],
        "ocr_fallback_enabled": settings.ocr_enabled,
        "ocr_runtime_ready": ocr_status["ready"],
        "ocr_engine": ocr_status["engine"],
        "ocr_engine_version": ocr_status["version"],
        "ocr_error": ocr_status["error"],
        "redaction_source_modes": ["direct_pdf", "ocr_assisted"],
        "zkpt_max_parallel_shards": max(1, settings.zkpt_max_parallel_shards),
        "preflight_thresholds": get_preflight_thresholds(),
    }
    _RUNTIME_STATUS_CACHE = status
    _RUNTIME_STATUS_CACHE_AT = time.monotonic()
    return dict(status)


def dispatch_redaction_job(job_id: str) -> dict[str, object]:
    db = get_database()
    settings = get_settings()
    runtime = get_redaction_runtime_status(force_refresh=True)

    if runtime["worker_ready"]:
        client = get_celery_client()
        if client is None:
            raise RedactionDispatchError("Redaction worker misconfigured")
        try:
            task = client.send_task(TASK_NAME, args=[job_id])
        except Exception as exc:
            if not settings.allow_inline_redaction_fallback:
                db.redaction_jobs.update_one(
                    {"job_id": job_id},
                    {
                        "$set": {
                            "status": "failed",
                            "stage": "dispatch_failed",
                            "error_code": "redaction-dispatch-failed",
                            "error_message": "Unable to enqueue the redaction job",
                            "updated_at": utcnow(),
                        }
                    },
                )
                raise RedactionDispatchError("Unable to enqueue redaction job") from exc
        else:
            db.redaction_jobs.update_one(
                {"job_id": job_id},
                {"$set": {"stage": "queued_worker", "worker_task_id": task.id, "updated_at": utcnow()}},
            )
            return {"execution_mode": "worker", "task_id": task.id}

    if not settings.allow_inline_redaction_fallback:
        raise RedactionDispatchError("No redaction worker is ready and inline fallback is disabled")

    db.redaction_jobs.update_one(
        {"job_id": job_id},
        {"$set": {"stage": "queued_inline", "updated_at": utcnow()}},
    )
    launch_inline_redaction_job(job_id)
    return {"execution_mode": "inline_fallback", "task_id": None}


def launch_inline_redaction_job(job_id: str) -> None:
    thread = threading.Thread(target=run_redaction_job, args=(job_id,), daemon=True, name=f"redaction-{job_id}")
    thread.start()


def _mark_failed(job_id: str, owner_wallet: str | None, stage: str, code: str, message: str, started: float) -> None:
    db = get_database()
    db.redaction_jobs.update_one(
        {"job_id": job_id},
        {
            "$set": {
                "status": "failed",
                "stage": stage,
                "error_code": code,
                "error_message": message,
                "duration_seconds": round(time.perf_counter() - started, 3),
                "updated_at": utcnow(),
            }
        },
    )
    if owner_wallet:
        append_custody_event(
            subject_type="redaction_job",
            subject_id=job_id,
            event_type="redaction.failed",
            actor_wallet=owner_wallet,
            summary=message,
        )


def run_redaction_job(job_id: str) -> None:
    db = get_database()
    settings = get_settings()
    job = db.redaction_jobs.find_one({"job_id": job_id})
    if not job:
        return

    started = time.perf_counter()
    owner_wallet = job.get("owner_wallet")
    db.redaction_jobs.update_one(
        {"job_id": job_id},
        {"$set": {"status": "processing", "stage": "decrypting", "updated_at": utcnow()}},
    )

    try:
        document, file_record = _get_document_and_file(job["document_id"], job["owner_wallet"])
        store = get_object_store()
        encrypted_bytes = store.read_bytes(file_record["storage_key"])
        passphrase = open_secret(job["sealed_passphrase"])
        from .crypto import decrypt_bytes

        plaintext = decrypt_bytes(
            encrypted_bytes,
            passphrase,
            salt_b64=file_record["encryption"]["salt_b64"],
            iv_b64=file_record["encryption"]["iv_b64"],
        )
        db.redaction_jobs.update_one(
            {"job_id": job_id},
            {"$set": {"stage": "detecting_text", "updated_at": utcnow()}},
        )
        source_pdf_sha256 = sha256_hex(plaintext)
        normalized_terms = normalize_policy_terms(job["search_terms"])
        source_text_mode = "direct_pdf" if has_extractable_text(plaintext) else "ocr_assisted"
        ocr_artifacts: dict[str, object] | None = None
        engine_kwargs: dict[str, Any] = {
            "pdf_bytes": plaintext,
            "normalized_terms": normalized_terms,
            "source_pdf_sha256": source_pdf_sha256,
        }
        if source_text_mode == "ocr_assisted":
            db.redaction_jobs.update_one(
                {"job_id": job_id},
                {"$set": {"stage": "ocr_preprocessing", "updated_at": utcnow()}},
            )
            ocr_runtime = get_ocr_runtime_status()
            if not ocr_runtime["enabled"]:
                raise OcrProcessingError("ocr-disabled", "OCR support is disabled for scanned-PDF redaction")
            if not ocr_runtime["ready"]:
                raise OcrProcessingError("ocr-runtime-unavailable", "OCR runtime is unavailable for scanned-PDF redaction")
            ocr_result = ocr_pdf_to_searchable(plaintext)
            ocr_artifacts = _persist_inline_ocr_artifacts(job_id=job_id, ocr_result=ocr_result, store=store)
            engine_kwargs.update(
                {
                    "source_mode": "ocr_layout",
                    "ocr_layout": ocr_result.layout,
                    "page_images": [
                        {
                            "page_index": page.page_index,
                            "image_bytes": page.image_bytes,
                            "image_width": page.image_width,
                            "image_height": page.image_height,
                            "content_type": page.content_type,
                        }
                        for page in ocr_result.page_images
                    ],
                    "working_searchable_pdf_bytes": ocr_result.searchable_pdf_bytes,
                }
            )
            db.redaction_jobs.update_one(
                {"job_id": job_id},
                {
                    "$set": {
                        "ocr_engine": ocr_result.engine_name,
                        "ocr_engine_version": ocr_result.engine_version,
                        "ocr_layout_sha256": ocr_result.layout_sha256,
                        "working_searchable_pdf_sha256": ocr_result.working_searchable_pdf_sha256,
                        "ocr_artifacts": ocr_artifacts,
                        "updated_at": utcnow(),
                    }
                },
            )
        if source_text_mode == "direct_pdf":
            direct_layout = extract_searchable_pdf_layout(plaintext)
            engine_kwargs.update(
                {
                    "searchable_layout": direct_layout.layout,
                    "page_images": [
                        {
                            "page_index": page.page_index,
                            "image_bytes": page.image_bytes,
                            "image_width": page.image_width,
                            "image_height": page.image_height,
                            "content_type": page.content_type,
                        }
                        for page in direct_layout.page_images
                    ],
                }
            )
        db.redaction_jobs.update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "stage": "redacting",
                    "source_text_mode": source_text_mode,
                    "ocr_used": source_text_mode == "ocr_assisted",
                    "updated_at": utcnow(),
                }
            },
        )
        engine_output = run_rust_redaction_engine(**engine_kwargs)
        db.redaction_jobs.update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "redaction_engine": engine_output.manifest["engine_name"],
                    "redaction_engine_version": engine_output.manifest["engine_version"],
                    "source_text_mode": engine_output.manifest.get("source_text_mode"),
                    "ocr_used": engine_output.manifest.get("ocr_used"),
                    "ocr_engine": engine_output.manifest.get("ocr_engine"),
                    "ocr_engine_version": engine_output.manifest.get("ocr_engine_version"),
                    "ocr_layout_sha256": engine_output.manifest.get("ocr_layout_sha256"),
                    "working_searchable_pdf_sha256": engine_output.manifest.get("working_searchable_pdf_sha256"),
                    "render_mode": engine_output.manifest.get("render_mode"),
                    "updated_at": utcnow(),
                }
            },
        )
        extracted_text = engine_output.canonical_original_text
        masked_text = engine_output.canonical_redacted_text
        redacted_pdf = engine_output.redacted_pdf_bytes
        redacted_document_id = random_id("docr")
        storage_key = store.put_bytes("redactions", f"{redacted_document_id}.pdf", redacted_pdf)
        redacted_sha256 = sha256_hex(redacted_pdf)
        original_sha256 = source_pdf_sha256
        proof_deadline_seconds = max(settings.zkpt_proof_timeout_seconds, settings.zkpt_multi_shard_timeout_seconds)
        selected_artifact_profile_id: str | None = None
        try:
            document_binding = build_document_binding_commitment(
                original_sha256=original_sha256,
                redacted_sha256=redacted_sha256,
                canonical_original_sha256=engine_output.manifest.get("canonical_original_sha256"),
                canonical_redacted_sha256=engine_output.manifest.get("canonical_redacted_sha256"),
                source_text_mode=engine_output.manifest.get("source_text_mode"),
            )
            selected_plan = select_authoritative_plan(
                original_text=extracted_text,
                search_terms=job["search_terms"],
                document_binding=document_binding,
                redaction_manifest=engine_output.manifest,
            )
            selected_artifact = selected_plan["artifact"]
            current_active_profile_id = get_active_artifact_version().profile_id
            selected_artifact_profile_id = (
                selected_artifact.profile_id if selected_artifact.profile_id != current_active_profile_id else None
            )
            selected_preflight = selected_plan["preflight"]
            proof_deadline_seconds = int(selected_preflight["runtimeBudgetSeconds"])
            db.redaction_jobs.update_one(
                {"job_id": job_id},
                {
                    "$set": {
                        "stage": "preflight_estimation",
                        "artifact_profile_id": selected_artifact.profile_id,
                        "artifact_version": selected_artifact.artifact_version_id,
                        "estimated_shards": selected_preflight["estimatedShards"],
                        "predicted_proof_ms": selected_preflight["predictedProofMs"],
                        "classification": selected_preflight["classification"],
                        "onchain_eligible": selected_preflight["onchainEligible"],
                        "onchain_status": selected_preflight["onchainStatus"],
                        "document_binding_commitment": document_binding["field"],
                        "proof_model": selected_artifact.proof_model,
                        "binding_input_name": selected_artifact.binding_input_name,
                        "updated_at": utcnow(),
                    }
                },
            )
        except Exception:
            pass
        db.redaction_jobs.update_one(
            {"job_id": job_id},
            {"$set": {"stage": "building_witness", "updated_at": utcnow()}},
        )
        zkpt_payload, zkpt_bundle_id = attempt_authoritative_proof_with_deadline(
            timeout_seconds=proof_deadline_seconds,
            original_text=extracted_text,
            masked_text=masked_text,
            original_sha256=original_sha256,
            redacted_sha256=redacted_sha256,
            redacted_document_id=redacted_document_id,
            redaction_job_id=job_id,
            owner_wallet=job["owner_wallet"],
            search_terms=job["search_terms"],
            redaction_manifest=engine_output.manifest,
            artifact_profile_id=selected_artifact_profile_id,
        )
        db.redaction_jobs.update_one(
            {"job_id": job_id},
            {"$set": {"stage": "verifying" if zkpt_payload["status"] == "verified" else "proving", "updated_at": utcnow()}},
        )
        now = utcnow()
        result = {
            "document_id": redacted_document_id,
            "case_id": document["case_id"],
            "file_id": document["file_id"],
            "owner_wallet": document["owner_wallet"],
            "source_document_id": document["document_id"],
            "latest_redaction_result_id": None,
            "original_name": f"redacted-{document['original_name']}",
            "status": "redacted_unverified",
            "created_at": now,
            "updated_at": now,
            "anchor_receipt": document.get("anchor_receipt"),
            "original_sha256": original_sha256,
            "redacted_sha256": redacted_sha256,
            "canonical_original_sha256": engine_output.manifest["canonical_original_sha256"],
            "canonical_redacted_sha256": engine_output.manifest["canonical_redacted_sha256"],
            "searchable_text_confirmed": engine_output.manifest["searchable_text_confirmed"],
            "source_text_mode": engine_output.manifest.get("source_text_mode"),
            "ocr_used": engine_output.manifest.get("ocr_used"),
            "ocr_engine": engine_output.manifest.get("ocr_engine"),
            "ocr_engine_version": engine_output.manifest.get("ocr_engine_version"),
            "ocr_layout_sha256": engine_output.manifest.get("ocr_layout_sha256"),
            "working_searchable_pdf_sha256": engine_output.manifest.get("working_searchable_pdf_sha256"),
            "render_mode": engine_output.manifest.get("render_mode"),
            "redaction_engine": engine_output.manifest["engine_name"],
            "redaction_engine_version": engine_output.manifest["engine_version"],
            "evidence_bundle_id": document.get("evidence_bundle_id"),
            "storage_key": storage_key,
            "content_type": "application/pdf",
            "proof_boundary": settings.proof_boundary,
            "ocr_artifacts": ocr_artifacts,
            "zkpt": zkpt_payload,
        }
        db.documents.insert_one(result)
        db.documents.update_one(
            {"document_id": document["document_id"]},
            {
                "$set": {
                    "redacted_sha256": redacted_sha256,
                    "latest_redaction_result_id": redacted_document_id,
                    "updated_at": now,
                    }
                },
            )
        db.redaction_jobs.update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "status": "completed",
                    "stage": "result_ready",
                    "result_document_id": redacted_document_id,
                    "zkpt_bundle_id": zkpt_bundle_id,
                    "error_code": None,
                    "error_message": None,
                    "source_text_mode": engine_output.manifest.get("source_text_mode"),
                    "ocr_used": engine_output.manifest.get("ocr_used"),
                    "ocr_engine": engine_output.manifest.get("ocr_engine"),
                    "ocr_engine_version": engine_output.manifest.get("ocr_engine_version"),
                    "ocr_layout_sha256": engine_output.manifest.get("ocr_layout_sha256"),
                    "working_searchable_pdf_sha256": engine_output.manifest.get("working_searchable_pdf_sha256"),
                    "render_mode": engine_output.manifest.get("render_mode"),
                    "estimated_shards": zkpt_payload.get("estimated_shards"),
                    "predicted_proof_ms": zkpt_payload.get("predicted_proof_ms"),
                    "classification": zkpt_payload.get("classification"),
                    "onchain_eligible": zkpt_payload.get("onchain_eligible"),
                    "onchain_status": zkpt_payload.get("onchain_status"),
                    "document_binding_commitment": zkpt_payload.get("document_binding_commitment"),
                    "duration_seconds": round(time.perf_counter() - started, 3),
                    "updated_at": utcnow(),
                }
            },
        )
        append_custody_event(
            subject_type="document",
            subject_id=redacted_document_id,
            event_type="redaction.completed",
            actor_wallet=job["owner_wallet"],
            summary=(
                "Redacted canonical-text PDF generated with authoritative verification bundle"
                if zkpt_payload["status"] == "verified"
                else (
                    "Redacted canonical-text PDF generated; authoritative verification unsupported for selected profile"
                    if zkpt_payload["status"] == "unsupported"
                    else "Redacted canonical-text PDF generated; authoritative proof failed closed"
                )
            ),
            metadata={
                "job_id": job_id,
                "proof_boundary": settings.proof_boundary,
                "zkpt_status": zkpt_payload["status"],
                "zkpt_bundle_id": zkpt_bundle_id,
                "source_text_mode": engine_output.manifest.get("source_text_mode"),
                "ocr_used": engine_output.manifest.get("ocr_used"),
                "ocr_engine": engine_output.manifest.get("ocr_engine"),
                "ocr_engine_version": engine_output.manifest.get("ocr_engine_version"),
                "ocr_layout_sha256": engine_output.manifest.get("ocr_layout_sha256"),
                "working_searchable_pdf_sha256": engine_output.manifest.get("working_searchable_pdf_sha256"),
                "render_mode": engine_output.manifest.get("render_mode"),
                "redaction_engine": engine_output.manifest["engine_name"],
                "redaction_engine_version": engine_output.manifest["engine_version"],
                "classification": zkpt_payload.get("classification"),
                "estimated_shards": zkpt_payload.get("estimated_shards"),
                "predicted_proof_ms": zkpt_payload.get("predicted_proof_ms"),
                "onchain_eligible": zkpt_payload.get("onchain_eligible"),
                "onchain_status": zkpt_payload.get("onchain_status"),
                "document_binding_commitment": zkpt_payload.get("document_binding_commitment"),
            },
        )
    except LookupError as exc:
        _mark_failed(job_id, owner_wallet, "lookup", "redaction-source-missing", str(exc), started)
    except OcrProcessingError as exc:
        _mark_failed(job_id, owner_wallet, "ocr_preprocessing", exc.code, exc.message, started)
    except RedactionEngineError as exc:
        _mark_failed(job_id, owner_wallet, "redacting", exc.code, exc.message, started)
    except Exception:
        _mark_failed(
            job_id,
            owner_wallet,
            "processing",
            "redaction-processing-error",
            "Redaction job failed during processing",
            started,
        )
