from __future__ import annotations

import hashlib
import io
import json
import zipfile
from typing import Any

from .crypto import random_id, utcnow
from .database import get_database
from .zkpt_onchain import default_onchain_status
from .zkpt_policy import record_zkpt_benchmark
from .zkpt_artifacts import ZKPTArtifactVersion


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def create_verified_bundle(
    *,
    document_id: str,
    redaction_job_id: str,
    owner_wallet: str,
    artifact: ZKPTArtifactVersion,
    projection_metadata: dict[str, Any],
    proof_executions: list[dict[str, Any]],
    original_sha256: str,
    redacted_sha256: str,
) -> dict[str, Any]:
    db = get_database()
    bundle_id = random_id("zkptbundle")
    created_at = utcnow()
    if not proof_executions:
        raise ValueError("At least one proof execution is required")
    shard_count = len(proof_executions)
    shard_ranges = [item.get("shard_range") for item in proof_executions]
    total_prove_ms = round(sum(float((item.get("timings") or {}).get("prove_ms") or 0.0) for item in proof_executions), 3)
    total_verify_ms = round(sum(float((item.get("timings") or {}).get("verify_ms") or 0.0) for item in proof_executions), 3)
    total_witness_ms = round(sum(float((item.get("timings") or {}).get("witness_ms") or 0.0) for item in proof_executions), 3)
    total_projection_ms = round(sum(float((item.get("timings") or {}).get("projection_ms") or 0.0) for item in proof_executions), 3)
    first_execution = proof_executions[0]

    manifest = {
        "bundleId": bundle_id,
        "documentId": document_id,
        "redactionJobId": redaction_job_id,
        "profileId": artifact.profile_id,
        "profileClass": artifact.profile_class,
        "artifactVersion": artifact.artifact_version_id,
        "proofBoundary": artifact.proof_boundary,
        "proofModel": artifact.proof_model,
        "bindingInputName": artifact.binding_input_name,
        "shardCount": shard_count,
        "shardRanges": shard_ranges,
        "originalSha256": original_sha256,
        "redactedSha256": redacted_sha256,
        "sourceTextMode": projection_metadata.get("sourceTextMode"),
        "ocrUsed": projection_metadata.get("ocrUsed"),
        "ocrEngine": projection_metadata.get("ocrEngine"),
        "ocrEngineVersion": projection_metadata.get("ocrEngineVersion"),
        "ocrLayoutSha256": projection_metadata.get("ocrLayoutSha256"),
        "workingSearchablePdfSha256": projection_metadata.get("workingSearchablePdfSha256"),
        "renderMode": projection_metadata.get("renderMode"),
        "verificationData": first_execution["verification_data"] if shard_count == 1 else None,
        "proverBackend": first_execution.get("backend"),
        "redactionEngine": projection_metadata.get("redactionEngine"),
        "redactionEngineVersion": projection_metadata.get("redactionEngineVersion"),
        "canonicalOriginalSha256": projection_metadata.get("canonicalOriginalSha256"),
        "canonicalRedactedSha256": projection_metadata.get("canonicalRedactedSha256"),
        "documentBindingCommitment": projection_metadata.get("documentBindingCommitment"),
        "documentBindingHash": projection_metadata.get("documentBindingHash"),
        "classification": projection_metadata.get("classification"),
        "estimatedShards": projection_metadata.get("estimatedShards"),
        "predictedProofMs": projection_metadata.get("predictedProofMs"),
        "onchainEligible": projection_metadata.get("onchainEligible"),
        "onchainStatus": projection_metadata.get("onchainStatus"),
    }
    onchain_status = default_onchain_status(bool(projection_metadata.get("onchainEligible")))
    bundle = {
        "bundle_id": bundle_id,
        "document_id": document_id,
        "owner_wallet": owner_wallet,
        "redaction_job_id": redaction_job_id,
        "artifact_version": artifact.artifact_version_id,
        "status": "verified",
        "proof_boundary": artifact.proof_boundary,
        "verified_shards": shard_count,
        "total_shards": shard_count,
        "fallback_mode": False,
        "manifest_hash": hashlib.sha256(canonical_json_bytes(manifest)).hexdigest(),
        "manifest": manifest,
        "summary": {
            "bundleId": bundle_id,
            "documentId": document_id,
            "status": "verified",
            "profileId": artifact.profile_id,
            "profileClass": artifact.profile_class,
            "artifactVersion": artifact.artifact_version_id,
            "proofBoundary": artifact.proof_boundary,
            "proofModel": artifact.proof_model,
            "bindingInputName": artifact.binding_input_name,
            "verifiedShards": shard_count,
            "totalShards": shard_count,
            "shardRanges": shard_ranges,
            "originalSha256": original_sha256,
            "redactedSha256": redacted_sha256,
            "sourceTextMode": projection_metadata.get("sourceTextMode"),
            "ocrUsed": projection_metadata.get("ocrUsed"),
            "ocrEngine": projection_metadata.get("ocrEngine"),
            "ocrEngineVersion": projection_metadata.get("ocrEngineVersion"),
            "ocrLayoutSha256": projection_metadata.get("ocrLayoutSha256"),
            "workingSearchablePdfSha256": projection_metadata.get("workingSearchablePdfSha256"),
            "renderMode": projection_metadata.get("renderMode"),
            "timings": {
                "projection_ms": total_projection_ms,
                "witness_ms": total_witness_ms,
                "prove_ms": total_prove_ms,
                "verify_ms": total_verify_ms,
            },
            "proverBackend": first_execution.get("backend"),
            "redactionEngine": projection_metadata.get("redactionEngine"),
            "redactionEngineVersion": projection_metadata.get("redactionEngineVersion"),
            "canonicalOriginalSha256": projection_metadata.get("canonicalOriginalSha256"),
            "canonicalRedactedSha256": projection_metadata.get("canonicalRedactedSha256"),
            "documentBindingCommitment": projection_metadata.get("documentBindingCommitment"),
            "documentBindingHash": projection_metadata.get("documentBindingHash"),
            "classification": projection_metadata.get("classification"),
            "estimatedShards": projection_metadata.get("estimatedShards"),
            "predictedProofMs": projection_metadata.get("predictedProofMs"),
            "onchainEligible": projection_metadata.get("onchainEligible"),
            "onchainStatus": onchain_status["status"],
        },
        "verification_key": json.loads(artifact.verification_key_path.read_text(encoding="utf-8")),
        "proof_shards": proof_executions,
        "proof_json": first_execution["proof_json"] if shard_count == 1 else None,
        "public_signals": first_execution["public_signals"] if shard_count == 1 else None,
        "proof_hash": first_execution["proof_hash"] if shard_count == 1 else None,
        "public_signals_hash": first_execution["public_signals_hash"] if shard_count == 1 else None,
        "witness_hash": first_execution["witness_hash"] if shard_count == 1 else None,
        "projection_metadata": projection_metadata,
        "verification_data": first_execution["verification_data"] if shard_count == 1 else None,
        "onchain": onchain_status,
        "created_at": created_at,
    }
    db.zkpt_bundles.insert_one(bundle)
    record_zkpt_benchmark(
        profile_id=artifact.profile_id,
        artifact_version=artifact.artifact_version_id,
        total_shards=shard_count,
        classification=str(projection_metadata.get("classification") or "verified_bundle_only"),
        status="verified",
        source_text_mode=projection_metadata.get("sourceTextMode"),
        onchain_eligible=bool(projection_metadata.get("onchainEligible")),
        predicted_proof_ms=float(projection_metadata.get("predictedProofMs") or 0.0),
        prove_ms=total_prove_ms,
        total_ms=round(total_projection_ms + total_witness_ms + total_prove_ms + total_verify_ms, 3),
    )
    return bundle


def build_bundle_export(bundle: dict[str, Any]) -> bytes:
    payload = io.BytesIO()
    proof_shards = bundle.get("proof_shards") or []
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bundle_manifest.json", json.dumps(bundle["manifest"], indent=2))
        archive.writestr("bundle_summary.json", json.dumps(bundle["summary"], indent=2))
        archive.writestr("verification_key.json", json.dumps(bundle["verification_key"], indent=2))
        if len(proof_shards) <= 1:
            archive.writestr("proof.json", json.dumps(bundle["proof_json"], indent=2))
            archive.writestr("public_signals.json", json.dumps(bundle["public_signals"], indent=2))
            archive.writestr(
                "hashes.json",
                json.dumps(
                    {
                        "witnessHash": bundle["witness_hash"],
                        "proofHash": bundle["proof_hash"],
                        "publicSignalsHash": bundle["public_signals_hash"],
                    },
                    indent=2,
                ),
            )
        else:
            shard_index_payload = []
            for item in proof_shards:
                shard_index = int(item["shard_index"])
                shard_prefix = f"proofs/shard-{shard_index:03d}"
                archive.writestr(f"{shard_prefix}-proof.json", json.dumps(item["proof_json"], indent=2))
                archive.writestr(f"{shard_prefix}-public-signals.json", json.dumps(item["public_signals"], indent=2))
                archive.writestr(f"{shard_prefix}-verification-data.json", json.dumps(item["verification_data"], indent=2))
                archive.writestr(
                    f"{shard_prefix}-hashes.json",
                    json.dumps(
                        {
                            "witnessHash": item["witness_hash"],
                            "proofHash": item["proof_hash"],
                            "publicSignalsHash": item["public_signals_hash"],
                            "shardIndex": item["shard_index"],
                            "shardRange": item["shard_range"],
                        },
                        indent=2,
                    ),
                )
                shard_index_payload.append(
                    {
                        "shardIndex": item["shard_index"],
                        "shardRange": item["shard_range"],
                        "proofHash": item["proof_hash"],
                        "publicSignalsHash": item["public_signals_hash"],
                        "witnessHash": item["witness_hash"],
                    }
                )
            archive.writestr("proofs/shards.json", json.dumps(shard_index_payload, indent=2))
        archive.writestr("projection_metadata.json", json.dumps(bundle["projection_metadata"], indent=2))
    payload.seek(0)
    return payload.read()
