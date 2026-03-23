from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import time
from typing import Any

from .config import get_settings
from .crypto import sha256_hex, utcnow
from .redaction_jobs import _resolve_parallel_shard_workers, _split_projection_for_proof_model
from .zkpt_artifacts import ZKPTArtifactError, get_active_artifact_version
from .zkpt_policy import build_document_binding_commitment
from .zkpt_prover import SnarkjsPlonkProver, ZKPTProverError
from .zkpt_runtime import check_zkpt_readiness
from .zkpt_witness import CircuitConfig, build_text_redaction_projection, generate_circuit_witness

DEFAULT_PROBE_TEXT = (
    "BlockVault privileged legal memorandum. "
    "This confidential clause is included so the authoritative redaction probe "
    "has at least one deterministic searchable term."
)
DEFAULT_PROBE_TERMS = ["privileged", "confidential"]


def _normalize_terms(search_terms: list[str] | None) -> list[str]:
    terms = search_terms or list(DEFAULT_PROBE_TERMS)
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in terms:
        cleaned = str(raw or "").strip().lower()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def _summarize_artifact(artifact: Any) -> dict[str, Any]:
    return {
        "profileId": artifact.profile_id,
        "profileClass": artifact.profile_class,
        "artifactVersion": artifact.artifact_version_id,
        "proofBoundary": artifact.proof_boundary,
        "circuitId": artifact.circuit_id,
        "segmentSize": artifact.segment_size,
        "numSegments": artifact.max_segments,
        "treeDepth": artifact.tree_depth,
        "numPolicyRules": artifact.max_policy_rules,
        "artifactsDir": str(artifact.artifacts_dir),
        "proofModel": artifact.proof_model,
        "bindingInputName": artifact.binding_input_name,
    }


def _build_recommendations(
    *,
    runtime: dict[str, Any],
    status: str,
    error_code: str | None,
) -> list[str]:
    recommendations: list[str] = []
    warnings = runtime.get("warnings") or []
    if warnings:
        recommendations.extend(str(item) for item in warnings)

    if error_code == "unsupported-profile":
        recommendations.append("Select an authoritative ZKPT profile before expecting verified bundles.")
    elif error_code == "unsupported-proof-boundary":
        recommendations.append("Use an artifact profile that declares proof_boundary=canonical_segment_mask_v1.")
    elif error_code == "prover-timeout":
        recommendations.append("Increase the proof budget or provide a smaller authoritative profile to stay within the proof budget.")
    elif error_code == "artifact-invalid":
        recommendations.append("Repair the artifact manifest or missing files before testing authoritative proofs.")
    elif error_code == "projection-unsupported":
        recommendations.append("Use text and search terms that actually change at least one canonical segment.")

    if status != "verified" and runtime.get("proverBackend") == "snarkjs_fullprove":
        recommendations.append("snarkjs fullprove is the slow path; configure BLOCKVAULT_ZKPT_RAPIDSNARK_BIN for native proving.")
    if status != "verified" and runtime.get("proverBackend") == "snarkjs_wtns_plonk_prove":
        recommendations.append("Split PLONK witness/prove execution is already enabled; if timeouts persist, raise BLOCKVAULT_ZKPT_PROOF_TIMEOUT_SECONDS or ship a smaller authoritative profile.")

    deduped: list[str] = []
    seen: set[str] = set()
    for item in recommendations:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def run_zkpt_probe(
    *,
    source_text: str | None = None,
    search_terms: list[str] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    runtime = check_zkpt_readiness()
    started = time.perf_counter()
    normalized_terms = _normalize_terms(search_terms)
    text = (source_text or DEFAULT_PROBE_TEXT).strip()
    report: dict[str, Any] = {
        "generatedAt": utcnow().isoformat(),
        "proofBoundary": settings.proof_boundary,
        "runtime": runtime,
        "sample": {
            "sourceTextLength": len(text),
            "searchTerms": list(search_terms or DEFAULT_PROBE_TERMS),
            "normalizedTerms": normalized_terms,
        },
        "artifact": None,
        "probe": {
            "status": "failed",
            "error": None,
            "proverBackend": runtime.get("proverBackend"),
            "timings": {},
            "matchedSegments": [],
            "verificationData": None,
            "verifiedShards": 0,
            "totalShards": 0,
            "maxParallelShards": 1,
            "shardExecutionMode": "sequential",
        },
        "recommendations": [],
    }

    artifact = None
    try:
        artifact = get_active_artifact_version()
        report["artifact"] = _summarize_artifact(artifact)
        if artifact.profile_class != "authoritative":
            report["probe"]["status"] = "unsupported"
            report["probe"]["error"] = {
                "code": "unsupported-profile",
                "message": f"Selected ZKPT profile '{artifact.profile_id}' is '{artifact.profile_class}', not authoritative.",
            }
            return report
        if artifact.proof_boundary != settings.proof_boundary:
            report["probe"]["status"] = "unsupported"
            report["probe"]["error"] = {
                "code": "unsupported-proof-boundary",
                "message": (
                    f"Selected ZKPT profile proof boundary '{artifact.proof_boundary}' does not match "
                    f"'{settings.proof_boundary}'."
                ),
            }
            return report

        projection_started = time.perf_counter()
        projection = build_text_redaction_projection(
            source_text=text,
            policy_terms=normalized_terms,
            segment_size=artifact.segment_size,
        )
        report["probe"]["timings"]["projection_ms"] = round((time.perf_counter() - projection_started) * 1000, 3)
        report["probe"]["matchedSegments"] = list(projection.modified_indices)

        if not projection.modified_indices:
            raise ValueError("No canonical projection segments matched the requested probe terms.")

        config = CircuitConfig(
            num_segments=artifact.max_segments,
            tree_depth=artifact.tree_depth,
            num_policy_rules=artifact.max_policy_rules,
            segment_size=artifact.segment_size,
        )
        shard_payloads = _split_projection_for_proof_model(
            projection=projection,
            config=config,
            proof_model=artifact.proof_model,
        )
        total_shards = len(shard_payloads)
        max_parallel_shards = _resolve_parallel_shard_workers(total_shards)
        report["probe"]["totalShards"] = total_shards
        report["probe"]["maxParallelShards"] = max_parallel_shards
        report["probe"]["shardExecutionMode"] = "parallel" if max_parallel_shards > 1 else "sequential"
        report["probe"]["shardRanges"] = [shard["shard_range"] for shard in shard_payloads]

        def run_probe_shard(shard: dict[str, object]) -> dict[str, object]:
            original_bytes = shard["original_bytes"]
            redacted_bytes = shard["redacted_bytes"]
            binding = build_document_binding_commitment(
                original_sha256=sha256_hex(original_bytes),
                redacted_sha256=sha256_hex(redacted_bytes),
                canonical_original_sha256=sha256_hex(original_bytes),
                canonical_redacted_sha256=sha256_hex(redacted_bytes),
                source_text_mode="direct_pdf",
            )
            witness_package = generate_circuit_witness(
                original_bytes=original_bytes,
                redacted_bytes=redacted_bytes,
                policy_terms=normalized_terms,
                binding_value=str(binding["field"]),
                binding_input_name=artifact.binding_input_name,
                proof_model=str(shard.get("proof_model") or artifact.proof_model),
                selected_indices=shard.get("selected_indices"),
                config=config,
                segment_to_term=shard["segment_to_term"],
            )
            proof_execution = SnarkjsPlonkProver(
                artifact_version=artifact,
                timeout_seconds=settings.zkpt_proof_timeout_seconds,
            ).prove(witness_package["witness"])
            return {
                "verification_data": witness_package["verification_data"],
                "timings": proof_execution.timings,
                "witness_hash": proof_execution.witness_hash,
                "proof_hash": proof_execution.proof_hash,
                "public_signals_hash": proof_execution.public_signals_hash,
                "backend": proof_execution.backend,
                "shard_index": shard["shard_index"],
                "shard_range": shard["shard_range"],
                "document_binding_commitment": str(binding["field"]),
                "document_binding_hash": str(binding["hash"]),
            }

        execution_started = time.perf_counter()
        if max_parallel_shards == 1:
            proof_shards = [run_probe_shard(shard) for shard in shard_payloads]
        else:
            proof_shards: list[dict[str, object] | None] = [None] * total_shards
            with ThreadPoolExecutor(max_workers=max_parallel_shards, thread_name_prefix="zkpt-probe-shard") as executor:
                futures = [executor.submit(run_probe_shard, shard) for shard in shard_payloads]
                try:
                    for future in as_completed(futures):
                        shard_result = future.result()
                        proof_shards[int(shard_result["shard_index"])] = shard_result
                except Exception:
                    for future in futures:
                        future.cancel()
                    raise
            proof_shards = [item for item in proof_shards if item is not None]

        report["probe"]["timings"]["execution_wall_ms"] = round((time.perf_counter() - execution_started) * 1000, 3)
        report["probe"]["timings"]["witness_ms"] = round(
            sum(float((item.get("timings") or {}).get("witness_ms") or 0.0) for item in proof_shards),
            3,
        )
        report["probe"]["timings"]["prove_ms"] = round(
            sum(float((item.get("timings") or {}).get("prove_ms") or 0.0) for item in proof_shards),
            3,
        )
        report["probe"]["timings"]["verify_ms"] = round(
            sum(float((item.get("timings") or {}).get("verify_ms") or 0.0) for item in proof_shards),
            3,
        )
        report["probe"]["status"] = "verified"
        report["probe"]["verifiedShards"] = len(proof_shards)
        report["probe"]["proverBackend"] = str(proof_shards[0]["backend"]) if proof_shards else runtime.get("proverBackend")
        if len(proof_shards) == 1:
            report["probe"]["verificationData"] = proof_shards[0]["verification_data"]
            report["probe"]["proofHashes"] = {
                "witnessHash": proof_shards[0]["witness_hash"],
                "proofHash": proof_shards[0]["proof_hash"],
                "publicSignalsHash": proof_shards[0]["public_signals_hash"],
            }
            report["probe"]["documentBindingCommitment"] = proof_shards[0]["document_binding_commitment"]
            report["probe"]["documentBindingHash"] = proof_shards[0]["document_binding_hash"]
        else:
            report["probe"]["verificationData"] = None
            report["probe"]["proofShardHashes"] = [
                {
                    "shardIndex": item["shard_index"],
                    "shardRange": item["shard_range"],
                    "witnessHash": item["witness_hash"],
                    "proofHash": item["proof_hash"],
                    "publicSignalsHash": item["public_signals_hash"],
                    "documentBindingCommitment": item["document_binding_commitment"],
                    "documentBindingHash": item["document_binding_hash"],
                }
                for item in proof_shards
            ]
    except ZKPTArtifactError as exc:
        report["probe"]["status"] = "failed"
        report["probe"]["error"] = {"code": "artifact-invalid", "message": str(exc)}
    except ZKPTProverError as exc:
        report["probe"]["status"] = "failed"
        report["probe"]["error"] = {"code": exc.code, "message": exc.message}
    except ValueError as exc:
        report["probe"]["status"] = "failed"
        report["probe"]["error"] = {"code": "projection-unsupported", "message": str(exc)}
    except Exception as exc:
        report["probe"]["status"] = "failed"
        report["probe"]["error"] = {"code": "probe-runtime-error", "message": str(exc)}
    finally:
        report["probe"]["timings"]["total_ms"] = round((time.perf_counter() - started) * 1000, 3)
        if artifact and report["probe"]["proverBackend"] is None:
            report["probe"]["proverBackend"] = runtime.get("proverBackend")
        error_code = (report["probe"]["error"] or {}).get("code")
        report["recommendations"] = _build_recommendations(
            runtime=runtime,
            status=str(report["probe"]["status"]),
            error_code=str(error_code) if error_code else None,
        )

    return report
