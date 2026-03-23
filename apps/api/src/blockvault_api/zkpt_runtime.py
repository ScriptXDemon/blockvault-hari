from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from .config import get_settings
from .zkpt_artifacts import (
    ZKPTArtifactError,
    get_active_artifact_version,
    get_selected_artifact_profile,
    list_available_artifact_profiles,
    repo_root,
)
from .zkpt_onchain import get_onchain_runtime_status
from .zkpt_policy import get_preflight_thresholds, summarize_recent_single_proof_benchmark
from .zkpt_witness import get_merkle_helper_runtime_status

LARGE_ZKEY_WARNING_BYTES = 1_000_000_000
RECOMMENDED_LARGE_ZKEY_TIMEOUT_SECONDS = 300


def _probe_version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=True)
        return (result.stdout or result.stderr).strip() or None
    except Exception:
        return None


def _resolve_configured_binary(configured: str | None) -> Path | None:
    if not configured:
        return None
    candidate = Path(configured)
    if not candidate.is_absolute():
        candidate = (repo_root() / candidate).resolve()
    return candidate.resolve() if candidate.exists() else None


def _resolve_binary(configured: str | None, executable_name: str) -> Path | None:
    configured_path = _resolve_configured_binary(configured)
    if configured_path:
        return configured_path
    discovered = shutil.which(executable_name)
    return Path(discovered).resolve() if discovered else None


@lru_cache(maxsize=1)
def check_zkpt_readiness() -> dict[str, object]:
    settings = get_settings()
    node_path = _resolve_binary(settings.zkpt_node_bin, "node")
    rapidsnark_path = _resolve_binary(settings.zkpt_rapidsnark_bin, "rapidsnark")
    snarkjs_path = None
    errors: list[str] = []
    warnings: list[str] = []
    helper_status = get_merkle_helper_runtime_status()
    protocol = "plonk"
    selected_profile = get_selected_artifact_profile()
    available_profiles = list_available_artifact_profiles()
    profile_circuit_counts: dict[str, int] = {}
    for profile in available_profiles:
        circuit_hash = profile.get("circuitHash")
        if circuit_hash:
            profile_circuit_counts[str(circuit_hash)] = profile_circuit_counts.get(str(circuit_hash), 0) + 1
    for profile in available_profiles:
        circuit_hash = profile.get("circuitHash")
        profile["distinctCircuit"] = bool(circuit_hash) and profile_circuit_counts.get(str(circuit_hash), 0) == 1
    artifact_details: dict[str, object] = {
        "selectedProfile": selected_profile,
        "profileClass": None,
        "artifactVersion": None,
        "proofBoundary": None,
        "verificationKeyHash": None,
        "zkeyHash": None,
        "zkeyBytes": None,
        "zkeyGiB": None,
        "numSegments": None,
        "segmentSize": None,
        "treeDepth": None,
        "numPolicyRules": None,
        "artifactsDir": None,
        "circuitSourcePresent": False,
    }

    try:
        artifact = get_active_artifact_version()
        snarkjs_path = str(artifact.snarkjs_bin)
        protocol = str(getattr(artifact, "protocol", "plonk") or "plonk").lower()
        zkey_bytes = artifact.zkey_path.stat().st_size
        artifact_details = {
            "selectedProfile": get_selected_artifact_profile(),
            "profileClass": artifact.profile_class,
            "artifactVersion": artifact.artifact_version_id,
            "proofBoundary": artifact.proof_boundary,
            "proofModel": artifact.proof_model,
            "bindingInputName": artifact.binding_input_name,
            "verificationKeyHash": artifact.verification_key_hash,
            "zkeyHash": artifact.zkey_hash,
            "zkeyBytes": zkey_bytes,
            "zkeyGiB": round(zkey_bytes / (1024 ** 3), 3),
            "numSegments": artifact.max_segments,
            "segmentSize": artifact.segment_size,
            "treeDepth": artifact.tree_depth,
            "numPolicyRules": artifact.max_policy_rules,
            "artifactsDir": str(artifact.artifacts_dir),
            "circuitSourcePresent": any(profile.get("selected") and profile.get("circuitSourcePresent") for profile in available_profiles),
        }
        recent_single_proof = summarize_recent_single_proof_benchmark(artifact.profile_id)
        if artifact.profile_class != "authoritative":
            errors.append(
                f"Selected ZKPT profile '{artifact.profile_id}' is '{artifact.profile_class}', not authoritative"
            )
        if artifact.proof_boundary != settings.proof_boundary:
            errors.append(
                f"Selected ZKPT profile proof boundary '{artifact.proof_boundary}' does not match '{settings.proof_boundary}'"
            )
        if not helper_status["ready"]:
            errors.append(f"ZKPT merkle helper runtime is not ready: {helper_status['error']}")
        if zkey_bytes >= LARGE_ZKEY_WARNING_BYTES and protocol == "groth16" and not rapidsnark_path:
            warnings.append("Large ZKPT zkey detected without rapidsnark; verified proving may exceed the configured timeout")
        if zkey_bytes >= LARGE_ZKEY_WARNING_BYTES and protocol == "plonk":
            warnings.append("Large PLONK zkey detected; proving may exceed the configured timeout even with split witness/prove execution")
        if zkey_bytes >= LARGE_ZKEY_WARNING_BYTES and settings.zkpt_proof_timeout_seconds < RECOMMENDED_LARGE_ZKEY_TIMEOUT_SECONDS:
            warnings.append(
                f"Configured ZKPT proof timeout ({settings.zkpt_proof_timeout_seconds}s) is aggressive for a {round(zkey_bytes / (1024 ** 3), 3)} GiB zkey"
            )
        if not artifact_details["circuitSourcePresent"]:
            warnings.append(
                "Circuit source is not present for the selected profile; a smaller authoritative profile cannot be generated from this workspace until the Circom source is recovered"
            )
        if artifact.profile_id == "v3b":
            warnings.append("Profile v3b reuses the same compiled circuit hash as v3a and should not be treated as a distinct tuning candidate.")
        artifact_ready = True
    except ZKPTArtifactError as exc:
        errors.append(str(exc))
        artifact_ready = False
        recent_single_proof = None

    if not node_path:
        errors.append("Node.js executable not found")
    if not snarkjs_path or not Path(snarkjs_path).exists():
        errors.append("snarkjs executable not found")

    if protocol == "plonk":
        prover_backend = "snarkjs_wtns_plonk_prove"
    elif protocol == "groth16" and rapidsnark_path:
        prover_backend = "snarkjs_wtns_rapidsnark"
    else:
        prover_backend = "snarkjs_fullprove"
    snarkjs_version = None
    if snarkjs_path:
        snarkjs_target = Path(snarkjs_path)
        if node_path and snarkjs_target.suffix.lower() in {".js", ".cjs", ".mjs"}:
            snarkjs_version = _probe_version([str(node_path), snarkjs_path, "--version"])
        else:
            snarkjs_version = _probe_version([snarkjs_path, "--version"])

    return {
        "ready": artifact_ready and not errors,
        "mode": settings.zkpt_mode,
        "proofBoundary": settings.proof_boundary,
        "proverBackend": prover_backend,
        "artifact": artifact_details,
        "availableProfiles": available_profiles,
        "limits": {
            "proofTimeoutSeconds": settings.zkpt_proof_timeout_seconds,
            "targetProofSeconds": settings.zkpt_target_proof_seconds,
            "maxParallelShards": max(1, settings.zkpt_max_parallel_shards),
            "singleProofTimeoutSeconds": settings.zkpt_single_proof_timeout_seconds,
            "singleProofTargetSeconds": settings.zkpt_single_proof_target_seconds,
            "multiShardTimeoutSeconds": settings.zkpt_multi_shard_timeout_seconds,
        },
        "recentSingleProofBenchmark": recent_single_proof,
        "preflightThresholds": get_preflight_thresholds(),
        "onchain": get_onchain_runtime_status(),
        "tooling": {
            "nodePath": str(node_path) if node_path else None,
            "nodeVersion": _probe_version([str(node_path), "--version"]) if node_path else None,
            "snarkjsPath": snarkjs_path,
            "snarkjsVersion": snarkjs_version,
            "rapidsnarkPath": str(rapidsnark_path) if rapidsnark_path else None,
            "rapidsnarkVersion": _probe_version([str(rapidsnark_path), "--version"]) if rapidsnark_path else None,
            "merkleHelper": helper_status,
        },
        "artifactStore": {
            "autoDownload": settings.zkpt_artifacts_auto_download,
            "bucket": settings.resolved_zkpt_artifacts_s3_bucket,
            "prefix": settings.zkpt_artifacts_s3_prefix,
            "endpointUrl": settings.resolved_zkpt_artifacts_s3_endpoint_url,
        },
        "warnings": warnings,
        "errors": errors,
    }


def reset_zkpt_runtime_cache() -> None:
    check_zkpt_readiness.cache_clear()
