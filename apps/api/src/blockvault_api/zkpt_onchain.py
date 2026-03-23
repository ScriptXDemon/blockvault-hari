from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib import request

from eth_account import Account
from eth_utils import function_signature_to_4byte_selector, keccak, to_checksum_address

from .config import get_settings
from .crypto import utcnow
from .database import get_database
from .zkpt_artifacts import get_active_artifact_version, get_artifact_version, get_selected_artifact_profile, repo_root

_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
_SUBMIT_SIGNATURE = (
    "submitVerifiedBundle(uint256[24],uint256[4],(bytes32,bytes32,bytes32,bytes32,bytes32,uint256,string,string,string,uint8))"
)


class ZKPTOnchainError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _get_onchain_verifier_profile() -> str:
    settings = get_settings()
    configured = (settings.zkpt_onchain_safe_profile or "").strip()
    return configured or get_selected_artifact_profile()


def _resolve_snarkjs_command(artifact_profile_id: str | None = None) -> list[str]:
    artifact = get_artifact_version(artifact_profile_id) if artifact_profile_id else get_active_artifact_version()
    if artifact.snarkjs_bin.suffix.lower() in {".js", ".cjs", ".mjs"}:
        node_bin = get_settings().zkpt_node_bin
        resolved_node = None
        if node_bin:
            candidate = Path(node_bin)
            if not candidate.is_absolute():
                candidate = (repo_root() / candidate).resolve()
            if candidate.exists():
                resolved_node = candidate
        if resolved_node is None:
            resolved_node = Path(os.environ.get("COMSPEC", "")).parent.parent / "nodejs" / "node.exe"
            if not resolved_node.exists():
                from shutil import which

                discovered = which("node")
                if discovered:
                    resolved_node = Path(discovered)
        if not resolved_node or not resolved_node.exists():
            raise ZKPTOnchainError("onchain-snarkjs-missing", "Node.js is required to prepare verifier calldata")
        return [str(resolved_node.resolve()), str(artifact.snarkjs_bin)]
    return [str(artifact.snarkjs_bin)]


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


def default_onchain_status(onchain_eligible: bool) -> dict[str, object]:
    return {
        "status": "not_submitted" if onchain_eligible else "unsupported",
        "chainId": get_settings().zkpt_onchain_chain_id,
        "registryAddress": get_settings().zkpt_onchain_receipt_registry_address,
        "txHash": None,
        "receiptId": None,
        "submittedAt": None,
        "confirmedAt": None,
        "error": None,
    }


def get_bundle_onchain_status(bundle: dict[str, Any]) -> dict[str, object]:
    stored = bundle.get("onchain")
    if isinstance(stored, dict) and stored:
        return stored
    eligible = bool((bundle.get("summary") or {}).get("onchainEligible"))
    return default_onchain_status(eligible)


def _rpc(url: str, method: str, params: list[Any]) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
    req = request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    if data.get("error"):
        raise ZKPTOnchainError("onchain-rpc-error", str(data["error"]))
    return data["result"]


def _parse_hex_int(value: str | int) -> int:
    if isinstance(value, int):
        return value
    if value.startswith("0x"):
        return int(value, 16)
    return int(value)


def _encode_submit_call(
    *,
    proof_words: list[int],
    public_signals: list[int],
    bundle: dict[str, Any],
) -> bytes:
    try:
        from eth_abi import encode
    except Exception as exc:
        raise ZKPTOnchainError("onchain-abi-missing", "eth_abi is required for on-chain submission") from exc

    summary = bundle.get("summary") or {}
    manifest = bundle.get("manifest") or {}
    payload = encode(
        [
            "uint256[24]",
            "uint256[4]",
            "(bytes32,bytes32,bytes32,bytes32,bytes32,uint256,string,string,string,uint8)",
        ],
        [
            proof_words,
            public_signals,
            (
                _pack_digestish(bundle.get("manifest_hash")),
                _pack_digestish(summary.get("originalSha256")),
                _pack_digestish(summary.get("redactedSha256")),
                _pack_digestish(summary.get("canonicalOriginalSha256")),
                _pack_digestish(summary.get("canonicalRedactedSha256")),
                int(summary.get("documentBindingCommitment") or 0),
                str(manifest.get("bundleId") or bundle.get("bundle_id") or ""),
                str(summary.get("artifactVersion") or bundle.get("artifact_version") or ""),
                str(summary.get("profileId") or ""),
                _source_mode_flag(summary.get("sourceTextMode")),
            ),
        ],
    )
    return function_signature_to_4byte_selector(_SUBMIT_SIGNATURE) + payload


def _prepare_solidity_calldata(bundle: dict[str, Any]) -> tuple[list[int], list[int]]:
    if int(bundle.get("total_shards") or 0) != 1:
        raise ZKPTOnchainError("onchain-multishard-unsupported", "The first on-chain release only supports single-proof bundles")
    proof_json = bundle.get("proof_json")
    public_signals = bundle.get("public_signals")
    if not proof_json or not public_signals:
        raise ZKPTOnchainError("onchain-proof-missing", "Bundle does not contain single-proof verifier artifacts")

    artifact_profile_id = (
        (bundle.get("summary") or {}).get("profileId")
        or bundle.get("artifact_version")
        or bundle.get("profile_id")
    )
    command = _resolve_snarkjs_command(str(artifact_profile_id) if artifact_profile_id else None)
    with tempfile.TemporaryDirectory(prefix="blockvault-onchain-") as tmp_dir_name:
        tmp_dir = Path(tmp_dir_name)
        public_path = tmp_dir / "public.json"
        proof_path = tmp_dir / "proof.json"
        public_path.write_text(json.dumps(public_signals), encoding="utf-8")
        proof_path.write_text(json.dumps(proof_json), encoding="utf-8")
        completed = subprocess.run(
            [*command, "zkey", "export", "soliditycalldata", str(public_path), str(proof_path)],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )

    raw = (completed.stdout or "").strip()
    if not raw:
        raise ZKPTOnchainError("onchain-calldata-empty", "snarkjs did not return Solidity calldata")
    try:
        decoder = json.JSONDecoder()
        proof_values, offset = decoder.raw_decode(raw)
        public_values, _ = decoder.raw_decode(raw[offset:].lstrip())
    except Exception as exc:
        raise ZKPTOnchainError("onchain-calldata-parse-failed", "Unable to parse snarkjs Solidity calldata output") from exc

    proof_words = [_parse_hex_int(item) for item in proof_values]
    public_words = [_parse_hex_int(item) for item in public_values]
    if len(proof_words) != 24 or len(public_words) != 4:
        raise ZKPTOnchainError(
            "onchain-calldata-shape-invalid",
            f"Expected 24 proof words and 4 public signals, received {len(proof_words)} and {len(public_words)}",
        )
    return proof_words, public_words


def _wait_for_receipt(url: str, tx_hash: str, confirmations: int) -> dict[str, Any]:
    deadline = time.time() + 120
    while time.time() < deadline:
        receipt = _rpc(url, "eth_getTransactionReceipt", [tx_hash])
        if receipt and receipt.get("blockNumber"):
            if confirmations <= 1:
                return receipt
            latest = _parse_hex_int(_rpc(url, "eth_blockNumber", []))
            if latest - _parse_hex_int(receipt["blockNumber"]) + 1 >= confirmations:
                return receipt
        time.sleep(3)
    raise ZKPTOnchainError("onchain-receipt-timeout", "Timed out while waiting for the on-chain receipt confirmation")


@lru_cache(maxsize=1)
def get_onchain_runtime_status() -> dict[str, object]:
    settings = get_settings()
    contract_path = (repo_root() / "contracts" / "zkpt" / "ZKPTReceiptRegistry.sol").resolve()
    default_proof_profile = get_selected_artifact_profile()
    verifier_profile = _get_onchain_verifier_profile()
    generated_dir = (repo_root() / "contracts" / "zkpt" / "generated" / verifier_profile).resolve()
    verifier_source_path = generated_dir / "PlonkVerifier.sol"
    verifier_metadata_path = generated_dir / "verifier-export.json"
    deployment_manifest_path = (repo_root() / "contracts" / "zkpt" / "deployments" / f"blockvaultTestnet-{verifier_profile}.json").resolve()
    verifier_contract_name = None
    deployment_manifest: dict[str, Any] | None = None
    if verifier_metadata_path.exists():
        try:
            verifier_contract_name = json.loads(verifier_metadata_path.read_text(encoding="utf-8")).get("contractName")
        except Exception:
            verifier_contract_name = None
    if deployment_manifest_path.exists():
        try:
            deployment_manifest = json.loads(deployment_manifest_path.read_text(encoding="utf-8"))
        except Exception:
            deployment_manifest = None
    return {
        "enabled": settings.zkpt_onchain_enabled,
        "singleProofOnly": settings.zkpt_onchain_single_proof_only,
        "chainId": settings.zkpt_onchain_chain_id,
        "selectedProfile": verifier_profile,
        "verifierProfile": verifier_profile,
        "defaultProofProfile": default_proof_profile,
        "rpcUrlConfigured": bool(settings.zkpt_onchain_rpc_url),
        "registryAddress": settings.zkpt_onchain_receipt_registry_address,
        "relayerConfigured": bool(settings.zkpt_onchain_relayer_private_key),
        "contractSourcePath": str(contract_path) if contract_path.exists() else None,
        "verifierSourcePath": str(verifier_source_path) if verifier_source_path.exists() else None,
        "verifierMetadataPath": str(verifier_metadata_path) if verifier_metadata_path.exists() else None,
        "verifierContractName": verifier_contract_name,
        "deploymentManifestPath": str(deployment_manifest_path) if deployment_manifest_path.exists() else None,
        "deployedVerifierAddress": (deployment_manifest or {}).get("verifierAddress"),
        "deployedRegistryAddress": (deployment_manifest or {}).get("registryAddress"),
        "deploymentReady": bool(
            settings.zkpt_onchain_enabled
            and settings.zkpt_onchain_rpc_url
            and settings.zkpt_onchain_receipt_registry_address
            and settings.zkpt_onchain_relayer_private_key
        ),
    }


def submit_verified_bundle_onchain(bundle: dict[str, Any]) -> dict[str, object]:
    runtime = get_onchain_runtime_status()
    settings = get_settings()
    if not runtime["deploymentReady"]:
        raise ZKPTOnchainError("onchain-not-configured", "On-chain verifier submission is not configured for the selected profile")
    if bundle.get("status") != "verified":
        raise ZKPTOnchainError("onchain-bundle-not-verified", "Only verified bundles can be submitted on-chain")
    if not bool((bundle.get("summary") or {}).get("onchainEligible")):
        raise ZKPTOnchainError("onchain-not-eligible", "This bundle is not eligible for the first on-chain verification release")
    verifier_profile = str(runtime["selectedProfile"])
    verifier_artifact = get_artifact_version(verifier_profile)
    bundle_artifact_version = str(bundle.get("artifact_version") or "")
    if bundle_artifact_version != verifier_artifact.artifact_version_id:
        raise ZKPTOnchainError("onchain-profile-mismatch", "Bundle artifact version does not match the active deployed verifier profile")

    proof_words, public_words = _prepare_solidity_calldata(bundle)
    relayer = Account.from_key(settings.zkpt_onchain_relayer_private_key)
    registry_address = to_checksum_address(str(settings.zkpt_onchain_receipt_registry_address))
    rpc_url = str(settings.zkpt_onchain_rpc_url)
    calldata = _encode_submit_call(proof_words=proof_words, public_signals=public_words, bundle=bundle)
    nonce = _parse_hex_int(_rpc(rpc_url, "eth_getTransactionCount", [relayer.address, "pending"]))
    gas_price = _parse_hex_int(_rpc(rpc_url, "eth_gasPrice", []))
    gas_limit = _parse_hex_int(
        _rpc(
            rpc_url,
            "eth_estimateGas",
            [
                {
                    "from": relayer.address,
                    "to": registry_address,
                    "data": f"0x{calldata.hex()}",
                }
            ],
        )
    )
    transaction = {
        "chainId": settings.zkpt_onchain_chain_id,
        "nonce": nonce,
        "to": registry_address,
        "value": 0,
        "gas": gas_limit + 25_000,
        "gasPrice": gas_price,
        "data": calldata,
    }
    signed = Account.sign_transaction(transaction, settings.zkpt_onchain_relayer_private_key)
    tx_hash = _rpc(rpc_url, "eth_sendRawTransaction", [signed.raw_transaction.hex()])
    submitted_at = utcnow().isoformat()

    db = get_database()
    db.zkpt_bundles.update_one(
        {"bundle_id": bundle["bundle_id"]},
        {
            "$set": {
                "onchain": {
                    "status": "submitted",
                    "chainId": settings.zkpt_onchain_chain_id,
                    "registryAddress": registry_address,
                    "txHash": tx_hash,
                    "receiptId": None,
                    "submittedAt": submitted_at,
                    "confirmedAt": None,
                    "error": None,
                }
            }
        },
    )
    db.documents.update_one(
        {"document_id": bundle["document_id"], "owner_wallet": bundle["owner_wallet"]},
        {"$set": {"zkpt.onchain_status": "submitted"}},
    )
    receipt = _wait_for_receipt(rpc_url, tx_hash, max(settings.zkpt_onchain_confirmations, 1))
    if _parse_hex_int(receipt.get("status", "0x0")) != 1:
        error_payload = {
            "status": "failed",
            "chainId": settings.zkpt_onchain_chain_id,
            "registryAddress": registry_address,
            "txHash": tx_hash,
            "receiptId": None,
            "submittedAt": submitted_at,
            "confirmedAt": None,
            "error": "On-chain verifier transaction reverted",
        }
        db.zkpt_bundles.update_one({"bundle_id": bundle["bundle_id"]}, {"$set": {"onchain": error_payload}})
        db.documents.update_one(
            {"document_id": bundle["document_id"], "owner_wallet": bundle["owner_wallet"]},
            {"$set": {"zkpt.onchain_status": "failed"}},
        )
        raise ZKPTOnchainError("onchain-verify-reverted", "On-chain verifier transaction reverted")

    receipt_id = f"0x{keccak((bundle['bundle_id'] + tx_hash).encode('utf-8')).hex()}"
    confirmed_payload = {
        "status": "confirmed",
        "chainId": settings.zkpt_onchain_chain_id,
        "registryAddress": registry_address,
        "txHash": tx_hash,
        "receiptId": receipt_id,
        "submittedAt": submitted_at,
        "confirmedAt": utcnow().isoformat(),
        "error": None,
        "blockNumber": _parse_hex_int(receipt["blockNumber"]),
    }
    db.zkpt_bundles.update_one({"bundle_id": bundle["bundle_id"]}, {"$set": {"onchain": confirmed_payload}})
    db.documents.update_one(
        {"document_id": bundle["document_id"], "owner_wallet": bundle["owner_wallet"]},
        {"$set": {"zkpt.onchain_status": "confirmed"}},
    )
    return confirmed_payload


def reset_zkpt_onchain_cache() -> None:
    get_onchain_runtime_status.cache_clear()
