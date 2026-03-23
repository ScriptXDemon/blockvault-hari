from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]


def repo_root() -> Path:
    return REPO_ROOT


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_binary(name: str, configured: str | None) -> str:
    if configured:
        return str(Path(configured).resolve())
    discovered = shutil.which(name)
    if not discovered:
        raise RuntimeError(f"Required executable not found: {name}")
    return discovered


def run(command: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=str(cwd) if cwd else None, check=True)


def write_manifest(
    *,
    profile_dir: Path,
    profile_id: str,
    source_path: Path,
    num_segments: int,
    segment_size: int,
    tree_depth: int,
    num_policy_rules: int,
    protocol: str = "plonk",
    proof_model: str = "full_segment_windows",
    binding_input_name: str = "transformationId",
) -> Path:
    circuit_id = source_path.stem
    r1cs_path = profile_dir / f"{circuit_id}.r1cs"
    wasm_path = profile_dir / f"{circuit_id}_js" / f"{circuit_id}.wasm"
    zkey_path = profile_dir / "circuit.zkey"
    verification_key_path = profile_dir / "verification_key.json"
    verifier_path = profile_dir / "solidity_verifier.sol"
    manifest = {
        "profile_id": profile_id,
        "profile_class": "authoritative",
        "proof_boundary": "canonical_segment_mask_v1",
        "proof_model": proof_model,
        "binding_input_name": binding_input_name,
        "artifact_version_id": profile_id,
        "build_timestamp": datetime.now(timezone.utc).isoformat(),
        "circuit": {
            "id": circuit_id,
            "num_policy_rules": num_policy_rules,
            "num_segments": num_segments,
            "segment_size": segment_size,
            "tree_depth": tree_depth,
        },
        "circuit_id": circuit_id,
        "files": {
            "r1cs": r1cs_path.name,
            "solidity_verifier": verifier_path.name,
            "verification_key": verification_key_path.name,
            "wasm": f"{circuit_id}_js/{circuit_id}.wasm",
            "zkey": zkey_path.name,
            "source": str(source_path.relative_to(profile_dir)),
        },
        "hashes": {
            "r1cs": sha256_file(r1cs_path),
            "solidity_verifier": sha256_file(verifier_path),
            "verification_key": sha256_file(verification_key_path),
            "wasm": sha256_file(wasm_path),
            "zkey": sha256_file(zkey_path),
        },
        "protocol": protocol,
    }
    manifest_path = profile_dir / "artifact-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def render_profile_source(
    *,
    source_text: str,
    num_segments: int,
    tree_depth: int,
    num_policy_rules: int,
) -> str:
    patterns = [
        (
            r"component\s+main\s+\{public\s+\[originalRoot,\s*redactedRoot,\s*policyCommitment,\s*transformationId\]\}\s*=\s*ZKPTRedaction\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)\s*;",
            "component main {public [originalRoot, redactedRoot, policyCommitment, transformationId]} = "
            f"ZKPTRedaction({num_segments}, {tree_depth}, {num_policy_rules});",
        ),
        (
            r"component\s+main\s+\{public\s+\[originalRoot,\s*redactedRoot,\s*policyCommitment,\s*documentBindingCommitment\]\}\s*=\s*ZKPTRedactionSparse\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)\s*;",
            "component main {public [originalRoot, redactedRoot, policyCommitment, documentBindingCommitment]} = "
            f"ZKPTRedactionSparse({num_segments}, {tree_depth}, {num_policy_rules});",
        ),
    ]
    for pattern, replacement in patterns:
        rendered, count = re.subn(pattern, replacement, source_text)
        if count == 1:
            return rendered
    raise RuntimeError("Could not locate the top-level ZKPT circuit instantiation in the source file.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a BlockVault ZKPT profile from restored Circom source.")
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--source", required=True, help="Path to the .circom source file")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--ptau", required=True)
    parser.add_argument("--num-segments", type=int, required=True)
    parser.add_argument("--segment-size", type=int, required=True)
    parser.add_argument("--tree-depth", type=int, required=True)
    parser.add_argument("--num-policy-rules", type=int, required=True)
    parser.add_argument("--circom-bin")
    parser.add_argument("--snarkjs-bin")
    parser.add_argument("--proof-model", default="full_segment_windows")
    parser.add_argument("--binding-input-name", default="transformationId")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    source_path = Path(args.source).resolve()
    ptau_path = Path(args.ptau).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    build_dir = output_dir

    circom_bin = resolve_binary("circom", args.circom_bin)
    snarkjs_bin = resolve_binary("snarkjs", args.snarkjs_bin)
    include_dir = (repo_root() / "circuits" / "node_modules").resolve()
    if not include_dir.exists():
        raise RuntimeError("circuits/node_modules is missing. Run `npm install --prefix circuits` first.")

    rendered_source_dir = build_dir / "src"
    rendered_source_dir.mkdir(parents=True, exist_ok=True)
    rendered_source_path = rendered_source_dir / source_path.name
    rendered_source_path.write_text(
        render_profile_source(
            source_text=source_path.read_text(encoding="utf-8"),
            num_segments=args.num_segments,
            tree_depth=args.tree_depth,
            num_policy_rules=args.num_policy_rules,
        ),
        encoding="utf-8",
    )

    run(
        [
            circom_bin,
            str(rendered_source_path),
            "--r1cs",
            "--wasm",
            "--sym",
            "--O2",
            "-o",
            str(build_dir),
            "-l",
            str(include_dir),
        ]
    )

    circuit_id = source_path.stem
    r1cs_path = build_dir / f"{circuit_id}.r1cs"
    zkey_path = build_dir / "circuit.zkey"
    verification_key_path = build_dir / "verification_key.json"
    verifier_path = build_dir / "solidity_verifier.sol"

    run([snarkjs_bin, "plonk", "setup", str(r1cs_path), str(ptau_path), str(zkey_path)])
    run([snarkjs_bin, "zkey", "export", "verificationkey", str(zkey_path), str(verification_key_path)])
    run([snarkjs_bin, "zkey", "export", "solidityverifier", str(zkey_path), str(verifier_path)])

    manifest_path = write_manifest(
        profile_dir=build_dir,
        profile_id=args.profile_id,
        source_path=rendered_source_path,
        num_segments=args.num_segments,
        segment_size=args.segment_size,
        tree_depth=args.tree_depth,
        num_policy_rules=args.num_policy_rules,
        proof_model=args.proof_model,
        binding_input_name=args.binding_input_name,
    )
    print(f"Wrote manifest to {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
