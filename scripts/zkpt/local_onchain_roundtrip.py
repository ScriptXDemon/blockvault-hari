from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from shutil import which
from typing import Any
from urllib import request


REPO_ROOT = Path(__file__).resolve().parents[2]
API_SRC = REPO_ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

HARDHAT_RPC_URL = "http://127.0.0.1:8545"
HARDHAT_RPC_URL_CONTAINER = "http://host.docker.internal:8545"
HARDHAT_CHAIN_ID = 31337
HARDHAT_RELAYER_PRIVATE_KEY = (
    "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
)


def _default_output_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return REPO_ROOT / "output" / "zkpt" / f"local-onchain-roundtrip-{timestamp}.json"


def _run_command(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout_seconds: int = 600,
) -> str:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=True,
    )
    return (completed.stdout or "").strip()


def _resolve_tool(*names: str) -> str:
    for name in names:
        resolved = which(name)
        if resolved:
            return resolved
    raise RuntimeError(f"Required tool not found: {', '.join(names)}")


def _parse_trailing_json(stdout: str) -> dict[str, Any]:
    for start in range(len(stdout) - 1, -1, -1):
        if stdout[start] != "{":
            continue
        candidate = stdout[start:].strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise RuntimeError(f"Could not find JSON payload in command output: {stdout[:500]}")


def _rpc(method: str, params: list[Any]) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
    req = request.Request(HARDHAT_RPC_URL, data=payload, headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=5) as response:
        data = json.loads(response.read().decode("utf-8"))
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    return data["result"]


def _wait_for_rpc(timeout_seconds: int = 30) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            chain_id = int(str(_rpc("eth_chainId", [])), 16)
            if chain_id == HARDHAT_CHAIN_ID:
                return True
        except Exception:
            time.sleep(1)
    return False


def _start_hardhat_node(log_path: Path) -> subprocess.Popen[str] | None:
    try:
        chain_id = int(str(_rpc("eth_chainId", [])), 16)
        if chain_id == HARDHAT_CHAIN_ID:
            return None
    except Exception:
        pass

    npx_bin = which("npx") or which("npx.cmd")
    if not npx_bin:
        raise RuntimeError("npx not found; cannot start local Hardhat node")

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [npx_bin, "hardhat", "node", "--hostname", "127.0.0.1", "--port", "8545"],
        cwd=str(REPO_ROOT / "contracts"),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if not _wait_for_rpc():
        process.terminate()
        raise RuntimeError(f"Hardhat node did not become ready; see {log_path}")
    return process


def _export_verifier(profile: str) -> dict[str, Any]:
    stdout = _run_command(
        ["python", "scripts/zkpt/export_verifier.py", "--profile", profile],
        cwd=REPO_ROOT,
        env={**os.environ, "BLOCKVAULT_ZKPT_PROFILE": profile},
        timeout_seconds=300,
    )
    return _parse_trailing_json(stdout)


def _deploy_contracts(profile: str) -> dict[str, Any]:
    deployment_path = REPO_ROOT / "contracts" / "zkpt" / "deployments" / f"blockvaultTestnet-{profile}.json"
    if deployment_path.exists():
        deployment_path.unlink()

    env = {
        **os.environ,
        "BLOCKVAULT_ZKPT_PROFILE": profile,
        "BLOCKVAULT_ZKPT_ONCHAIN_RPC_URL": HARDHAT_RPC_URL,
        "BLOCKVAULT_ZKPT_ONCHAIN_CHAIN_ID": str(HARDHAT_CHAIN_ID),
        "BLOCKVAULT_ZKPT_ONCHAIN_RELAYER_PRIVATE_KEY": HARDHAT_RELAYER_PRIVATE_KEY,
    }
    npm_bin = _resolve_tool("npm", "npm.cmd")
    _run_command([npm_bin, "run", "deploy:testnet"], cwd=REPO_ROOT / "contracts", env=env, timeout_seconds=600)
    return json.loads(deployment_path.read_text(encoding="utf-8"))


def _run_live_workflow(profile: str) -> dict[str, Any]:
    stdout = _run_command(
        ["python", "scripts/zkpt/live_workflow.py", "--stdout-only"],
        cwd=REPO_ROOT,
        env={**os.environ, "BLOCKVAULT_ZKPT_PROFILE": profile},
        timeout_seconds=600,
    )
    return json.loads(stdout)


def _submit_bundle_onchain(*, profile: str, registry_address: str, bundle_id: str) -> dict[str, Any]:
    docker_bin = _resolve_tool("docker", "docker.exe")
    snippet = (
        "import json;"
        "from blockvault_api.config import reset_settings_cache;"
        "from blockvault_api.database import reset_database_cache,get_database;"
        "from blockvault_api.zkpt_onchain import reset_zkpt_onchain_cache,submit_verified_bundle_onchain;"
        "from blockvault_api.zkpt_runtime import reset_zkpt_runtime_cache;"
        "reset_settings_cache();reset_database_cache();reset_zkpt_onchain_cache();reset_zkpt_runtime_cache();"
        f"db=get_database();bundle=db.zkpt_bundles.find_one({{'bundle_id': '{bundle_id}'}});"
        f"assert bundle is not None, 'Bundle {bundle_id} not found in API container database';"
        "result=submit_verified_bundle_onchain(bundle);"
        "persisted=db.zkpt_bundles.find_one({'bundle_id': bundle['bundle_id']}) or {};"
        "document=db.documents.find_one({'document_id': bundle['document_id']}) or {};"
        "print(json.dumps({'submission': result,'persistedBundleOnchain': persisted.get('onchain'),'documentOnchainStatus': ((document.get('zkpt') or {}).get('onchain_status'))}, default=str))"
    )
    command = [
        docker_bin,
        "exec",
        "-e",
        f"BLOCKVAULT_ZKPT_PROFILE={profile}",
        "-e",
        "BLOCKVAULT_ZKPT_ONCHAIN_ENABLED=true",
        "-e",
        f"BLOCKVAULT_ZKPT_ONCHAIN_RPC_URL={HARDHAT_RPC_URL_CONTAINER}",
        "-e",
        f"BLOCKVAULT_ZKPT_ONCHAIN_CHAIN_ID={HARDHAT_CHAIN_ID}",
        "-e",
        f"BLOCKVAULT_ZKPT_ONCHAIN_RECEIPT_REGISTRY_ADDRESS={registry_address}",
        "-e",
        f"BLOCKVAULT_ZKPT_ONCHAIN_RELAYER_PRIVATE_KEY={HARDHAT_RELAYER_PRIVATE_KEY}",
        "-e",
        "BLOCKVAULT_ZKPT_ONCHAIN_CONFIRMATIONS=1",
        "blockvault-api",
        "python",
        "-c",
        snippet,
    ]
    stdout = _run_command(command, cwd=REPO_ROOT, timeout_seconds=600)
    return _parse_trailing_json(stdout)


def run_local_onchain_roundtrip(*, profile: str) -> dict[str, Any]:
    started = time.perf_counter()
    log_path = REPO_ROOT / "output" / "zkpt" / "hardhat-node.log"
    node_process = _start_hardhat_node(log_path)
    try:
        verifier = _export_verifier(profile)
        deployment = _deploy_contracts(profile)
        workflow = _run_live_workflow(profile)
        bundle_id = workflow["redactionResult"]["zkpt"]["bundle_id"]
        onchain = _submit_bundle_onchain(
            profile=profile,
            registry_address=deployment["registryAddress"],
            bundle_id=bundle_id,
        )
        return {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "profileId": profile,
            "hardhatNode": {
                "rpcUrl": HARDHAT_RPC_URL,
                "containerRpcUrl": HARDHAT_RPC_URL_CONTAINER,
                "chainId": HARDHAT_CHAIN_ID,
                "startedByScript": node_process is not None,
                "logPath": str(log_path),
            },
            "verifierExport": verifier,
            "deployment": deployment,
            "workflow": workflow,
            "onchain": onchain,
            "timings": {
                "totalMs": round((time.perf_counter() - started) * 1000, 3),
            },
        }
    finally:
        if node_process is not None:
            node_process.terminate()
            try:
                node_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                node_process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local Hardhat on-chain verifier roundtrip for a real verified bundle.")
    parser.add_argument("--profile", default=os.environ.get("BLOCKVAULT_ZKPT_PROFILE") or "v4_sparse")
    parser.add_argument("--output")
    parser.add_argument("--stdout-only", action="store_true")
    args = parser.parse_args()

    report = run_local_onchain_roundtrip(profile=args.profile)
    payload = json.dumps(report, indent=2)
    if args.stdout_only:
        print(payload)
        return 0

    output_path = Path(args.output).resolve() if args.output else _default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(payload + "\n", encoding="utf-8")
    print(f"Wrote local on-chain roundtrip report to {output_path}")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
