from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from .config import get_settings

DEFAULT_ZKPT_PROFILES_ROOT = Path("circuits/zkpt")
DEFAULT_ZKPT_PROFILE = "v3a"
DEFAULT_ZKPT_ARTIFACTS_DIR = DEFAULT_ZKPT_PROFILES_ROOT / DEFAULT_ZKPT_PROFILE
LEGACY_DEFAULT_ZKPT_ARTIFACTS_DIR = DEFAULT_ZKPT_PROFILES_ROOT / "v2"


@dataclass(frozen=True)
class ZKPTArtifactVersion:
    profile_id: str
    profile_class: str
    proof_boundary: str
    proof_model: str
    binding_input_name: str
    artifact_version_id: str
    circuit_id: str
    protocol: str
    artifacts_dir: Path
    wasm_path: Path
    zkey_path: Path
    verification_key_path: Path
    verification_key_hash: str
    zkey_hash: str
    toolchain: dict[str, str]
    segment_size: int
    max_segments: int
    tree_depth: int
    max_policy_rules: int
    snarkjs_bin: Path


class ZKPTArtifactError(RuntimeError):
    pass


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_path(base: Path, raw: str | Path | None, fallback: str | None = None) -> Path | None:
    candidate = raw or fallback
    if not candidate:
        return None
    path = Path(candidate)
    if not path.is_absolute():
        path = (base / path).resolve()
    return path


def _resolve_profiles_root() -> Path:
    settings = get_settings()
    return _resolve_path(repo_root(), settings.zkpt_profiles_root) or (repo_root() / DEFAULT_ZKPT_PROFILES_ROOT).resolve()


def get_selected_artifact_profile() -> str:
    settings = get_settings()
    return settings.zkpt_profile or settings.zkpt_artifact_version or DEFAULT_ZKPT_PROFILE


def _resolve_active_artifacts_dir() -> Path:
    settings = get_settings()
    configured_dir = settings.zkpt_artifacts_dir
    if configured_dir in {DEFAULT_ZKPT_ARTIFACTS_DIR, LEGACY_DEFAULT_ZKPT_ARTIFACTS_DIR}:
        return (_resolve_profiles_root() / get_selected_artifact_profile()).resolve()
    return _resolve_path(repo_root(), configured_dir) or (repo_root() / DEFAULT_ZKPT_ARTIFACTS_DIR).resolve()


def _find_circuit_source_for_profile(profile_dir: Path) -> Path | None:
    for candidate in profile_dir.rglob("*.circom"):
        if candidate.is_file():
            return candidate.resolve()
    return None


@lru_cache(maxsize=1)
def list_available_artifact_profiles() -> list[dict[str, object]]:
    profiles_root = _resolve_profiles_root()
    selected_profile = get_selected_artifact_profile()
    profiles: list[dict[str, object]] = []
    if not profiles_root.exists():
        return profiles

    for candidate in sorted(path for path in profiles_root.iterdir() if path.is_dir()):
        manifest_path = candidate / "artifact-manifest.json"
        manifest = None
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                manifest = None
        profiles.append(
            {
                "id": candidate.name,
                "path": str(candidate),
                "selected": candidate.name == selected_profile,
                "manifestPresent": manifest_path.exists(),
                "artifactVersion": (manifest or {}).get("artifact_version_id"),
                "circuitId": (manifest or {}).get("circuit_id"),
                "profileClass": (manifest or {}).get("profile_class", "authoritative"),
                "proofBoundary": (manifest or {}).get("proof_boundary", "canonical_segment_mask_v1"),
                "proofModel": (manifest or {}).get("proof_model", "full_segment_windows"),
                "bindingInputName": (manifest or {}).get("binding_input_name", "transformationId"),
                "circuitSourcePresent": _find_circuit_source_for_profile(candidate) is not None,
                "circuitHash": ((manifest or {}).get("hashes") or {}).get("r1cs"),
            }
        )
    return profiles


def _resolve_snarkjs_path(configured: str | None) -> Path:
    root = repo_root()
    configured_path = _resolve_path(root, configured)
    candidates: list[Path] = []
    if configured_path:
        candidates.extend([configured_path, configured_path.with_suffix(".cmd")])
    candidates.extend(
        [
            (root / "node_modules" / "snarkjs" / "build" / "cli.cjs").resolve(),
            (root / "node_modules" / ".bin" / "snarkjs.cmd").resolve(),
            (root / "node_modules" / ".bin" / "snarkjs").resolve(),
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    discovered = shutil.which("snarkjs")
    if discovered:
        return Path(discovered).resolve()
    return candidates[-1]


@lru_cache(maxsize=1)
def _get_zkpt_artifact_s3_client():
    settings = get_settings()
    bucket = settings.resolved_zkpt_artifacts_s3_bucket
    if not settings.zkpt_artifacts_auto_download or not bucket:
        return None
    session = boto3.session.Session()
    return session.client(
        "s3",
        endpoint_url=settings.resolved_zkpt_artifacts_s3_endpoint_url,
        region_name=settings.resolved_zkpt_artifacts_s3_region,
        aws_access_key_id=settings.resolved_zkpt_artifacts_s3_access_key_id,
        aws_secret_access_key=settings.resolved_zkpt_artifacts_s3_secret_access_key,
        config=BotoConfig(s3={"addressing_style": "path" if settings.resolved_zkpt_artifacts_s3_force_path_style else "auto"}),
    )


def _artifact_storage_key(profile_id: str, relative_path: Path) -> str:
    settings = get_settings()
    prefix = settings.zkpt_artifacts_s3_prefix.strip("/")
    relative = relative_path.as_posix().lstrip("/")
    if prefix:
        return f"{prefix}/{profile_id}/{relative}"
    return f"{profile_id}/{relative}"


def _maybe_download_artifact_file(profile_id: str, artifacts_dir: Path, artifact_path: Path) -> None:
    if artifact_path.exists():
        return
    settings = get_settings()
    client = _get_zkpt_artifact_s3_client()
    bucket = settings.resolved_zkpt_artifacts_s3_bucket
    if not client or not bucket:
        return
    relative_path = artifact_path.resolve().relative_to(artifacts_dir.resolve())
    storage_key = _artifact_storage_key(profile_id, relative_path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        client.download_file(bucket, storage_key, str(artifact_path))
    except ClientError as exc:
        error_code = str(exc.response.get("Error", {}).get("Code", ""))
        if error_code in {"404", "NoSuchKey", "NotFound"}:
            return
        raise ZKPTArtifactError(f"Failed to download ZKPT artifact '{storage_key}' from S3: {exc}") from exc
    except BotoCoreError as exc:
        raise ZKPTArtifactError(f"Failed to download ZKPT artifact '{storage_key}' from S3: {exc}") from exc


@lru_cache(maxsize=8)
def get_artifact_version(profile_id: str | None = None) -> ZKPTArtifactVersion:
    settings = get_settings()
    if profile_id:
        artifacts_dir = (_resolve_profiles_root() / profile_id).resolve()
    else:
        artifacts_dir = _resolve_active_artifacts_dir()
    manifest_path = artifacts_dir / settings.zkpt_artifact_manifest
    if not manifest_path.exists():
        raise ZKPTArtifactError(f"ZKPT artifact manifest not found: {manifest_path}")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ZKPTArtifactError(f"Invalid ZKPT artifact manifest: {exc}") from exc

    files = manifest.get("files", {})
    circuit_cfg = manifest.get("circuit", {})
    wasm_path = _resolve_path(artifacts_dir, files.get("wasm"), "zkpt_redaction_v2_js/zkpt_redaction_v2.wasm")
    zkey_path = _resolve_path(artifacts_dir, files.get("zkey"), "circuit.zkey")
    verification_key_path = _resolve_path(artifacts_dir, files.get("verification_key"), "verification_key.json")
    snarkjs_bin = _resolve_snarkjs_path(settings.zkpt_snarkjs_bin)

    if wasm_path:
        _maybe_download_artifact_file(artifacts_dir.name, artifacts_dir, wasm_path)
    if zkey_path:
        _maybe_download_artifact_file(artifacts_dir.name, artifacts_dir, zkey_path)
    if verification_key_path:
        _maybe_download_artifact_file(artifacts_dir.name, artifacts_dir, verification_key_path)

    if not wasm_path or not wasm_path.exists():
        raise ZKPTArtifactError(f"Required ZKPT artifact missing (wasm): {wasm_path}")
    if not zkey_path or not zkey_path.exists():
        raise ZKPTArtifactError(f"Required ZKPT artifact missing (zkey): {zkey_path}")
    if not verification_key_path or not verification_key_path.exists():
        raise ZKPTArtifactError(f"Required ZKPT artifact missing (verification_key): {verification_key_path}")

    expected_hashes = manifest.get("hashes", {})
    verification_key_hash = sha256_file(verification_key_path)
    zkey_hash = sha256_file(zkey_path)
    if expected_hashes.get("verification_key") and expected_hashes["verification_key"] != verification_key_hash:
        raise ZKPTArtifactError("verification key hash does not match manifest")
    if expected_hashes.get("zkey") and expected_hashes["zkey"] != zkey_hash:
        raise ZKPTArtifactError("zkey hash does not match manifest")

    return ZKPTArtifactVersion(
        profile_id=manifest.get("profile_id", artifacts_dir.name),
        profile_class=manifest.get("profile_class", "authoritative"),
        proof_boundary=manifest.get("proof_boundary", "canonical_segment_mask_v1"),
        proof_model=manifest.get("proof_model", "full_segment_windows"),
        binding_input_name=manifest.get("binding_input_name", "transformationId"),
        artifact_version_id=manifest.get("artifact_version_id", settings.zkpt_artifact_version),
        circuit_id=manifest.get("circuit_id", "zkpt_redaction_v2"),
        protocol=manifest.get("protocol", "plonk"),
        artifacts_dir=artifacts_dir,
        wasm_path=wasm_path,
        zkey_path=zkey_path,
        verification_key_path=verification_key_path,
        verification_key_hash=verification_key_hash,
        zkey_hash=zkey_hash,
        toolchain={str(key): str(value) for key, value in (manifest.get("toolchain") or {}).items()},
        segment_size=int(circuit_cfg.get("segment_size", 1024)),
        max_segments=int(circuit_cfg.get("num_segments", 16)),
        tree_depth=int(circuit_cfg.get("tree_depth", 8)),
        max_policy_rules=int(circuit_cfg.get("num_policy_rules", 8)),
        snarkjs_bin=snarkjs_bin,
    )


def get_active_artifact_version() -> ZKPTArtifactVersion:
    return get_artifact_version(get_selected_artifact_profile())


def reset_zkpt_artifact_cache() -> None:
    list_available_artifact_profiles.cache_clear()
    get_artifact_version.cache_clear()
    _get_zkpt_artifact_s3_client.cache_clear()
