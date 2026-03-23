from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
API_SRC = REPO_ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

from blockvault_api.config import reset_settings_cache
from blockvault_api.zkpt_artifacts import get_active_artifact_version, repo_root
from blockvault_api.zkpt_runtime import reset_zkpt_runtime_cache

_CONTRACT_RE = re.compile(r"\bcontract\s+([A-Za-z_][A-Za-z0-9_]*)\b")


def _resolve_node_bin() -> Path | None:
    configured = os.environ.get("BLOCKVAULT_ZKPT_NODE_BIN")
    if configured:
        candidate = Path(configured)
        if not candidate.is_absolute():
            candidate = (repo_root() / candidate).resolve()
        if candidate.exists():
            return candidate.resolve()
    from shutil import which

    discovered = which("node")
    return Path(discovered).resolve() if discovered else None


def _resolve_snarkjs_command(snarkjs_bin: Path) -> list[str]:
    if snarkjs_bin.suffix.lower() in {".js", ".cjs", ".mjs"}:
        node_bin = _resolve_node_bin()
        if node_bin is None:
            raise RuntimeError("Node.js is required to export the Solidity verifier from the active zkey")
        return [str(node_bin), str(snarkjs_bin)]
    return [str(snarkjs_bin)]


def _extract_contract_name(source: str) -> str:
    for match in _CONTRACT_RE.finditer(source):
        name = match.group(1)
        if name != "Pairing":
            return name
    raise RuntimeError("Unable to detect verifier contract name in exported Solidity source")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the active ZKPT verifier Solidity contract.")
    parser.add_argument("--profile", help="Optional BLOCKVAULT_ZKPT_PROFILE override before export.")
    parser.add_argument("--output-dir", help="Optional output directory for the generated verifier source.")
    args = parser.parse_args()

    if args.profile:
        os.environ["BLOCKVAULT_ZKPT_PROFILE"] = args.profile
        reset_settings_cache()
        reset_zkpt_runtime_cache()

    artifact = get_active_artifact_version()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else (
        REPO_ROOT / "contracts" / "zkpt" / "generated" / artifact.profile_id
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    verifier_path = output_dir / "PlonkVerifier.sol"
    metadata_path = output_dir / "verifier-export.json"

    command = [
        *_resolve_snarkjs_command(artifact.snarkjs_bin),
        "zkey",
        "export",
        "solidityverifier",
        str(artifact.zkey_path),
        str(verifier_path),
    ]
    subprocess.run(command, cwd=str(REPO_ROOT), check=True, timeout=120)

    source = verifier_path.read_text(encoding="utf-8")
    contract_name = _extract_contract_name(source)
    metadata = {
        "profileId": artifact.profile_id,
        "artifactVersion": artifact.artifact_version_id,
        "proofBoundary": artifact.proof_boundary,
        "zkeyPath": str(artifact.zkey_path),
        "verificationKeyPath": str(artifact.verification_key_path),
        "verifierSourcePath": str(verifier_path),
        "contractName": contract_name,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
