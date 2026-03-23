from __future__ import annotations

from datetime import timedelta

from eth_account import Account

from blockvault_api.config import reset_settings_cache
from blockvault_api.crypto import utcnow
from blockvault_api.database import get_database
from blockvault_api.zkpt_onchain import _prepare_solidity_calldata, reset_zkpt_onchain_cache, submit_verified_bundle_onchain


HARDHAT_TEST_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"


def test_submit_verified_bundle_onchain_updates_bundle_and_document(monkeypatch):
    monkeypatch.setenv("BLOCKVAULT_ZKPT_ONCHAIN_ENABLED", "true")
    monkeypatch.setenv("BLOCKVAULT_ZKPT_ONCHAIN_RPC_URL", "http://127.0.0.1:8545")
    monkeypatch.setenv("BLOCKVAULT_ZKPT_ONCHAIN_CHAIN_ID", "31337")
    monkeypatch.setenv("BLOCKVAULT_ZKPT_ONCHAIN_RECEIPT_REGISTRY_ADDRESS", "0x0000000000000000000000000000000000000001")
    monkeypatch.setenv("BLOCKVAULT_ZKPT_ONCHAIN_RELAYER_PRIVATE_KEY", HARDHAT_TEST_KEY)
    monkeypatch.setenv("BLOCKVAULT_ZKPT_PROFILE", "v4_sparse")
    monkeypatch.setenv("BLOCKVAULT_ZKPT_ONCHAIN_SAFE_PROFILE", "v4_sparse")
    reset_settings_cache()
    reset_zkpt_onchain_cache()

    wallet = "0x1000000000000000000000000000000000000001"
    document_id = "docr_onchain_real"
    bundle_id = "zkptbundle_onchain_real"
    db = get_database()
    db.documents.insert_one(
        {
            "document_id": document_id,
            "owner_wallet": wallet,
            "original_name": "redacted-proof.pdf",
            "status": "redacted",
            "created_at": utcnow(),
            "updated_at": utcnow(),
            "zkpt": {
                "mode": "authoritative",
                "status": "verified",
                "bundle_id": bundle_id,
                "artifact_version": "v4_sparse",
                "profile_id": "v4_sparse",
                "profile_class": "authoritative",
                "proof_boundary": "canonical_segment_mask_v1",
                "verified_shards": 1,
                "total_shards": 1,
                "estimated_shards": 1,
                "predicted_proof_ms": 80000.0,
                "classification": "single_proof_ready",
                "onchain_eligible": True,
                "onchain_status": "not_submitted",
                "document_binding_commitment": "123456789",
                "fallback_mode": False,
                "prover_backend": "snarkjs_wtns_plonk_prove",
                "error": None,
            },
        }
    )
    db.zkpt_bundles.insert_one(
        {
            "bundle_id": bundle_id,
            "document_id": document_id,
            "owner_wallet": wallet,
            "artifact_version": "v4_sparse",
            "status": "verified",
            "total_shards": 1,
            "proof_json": {"protocol": "plonk"},
            "public_signals": ["1", "2", "3", "4"],
            "manifest_hash": "aa" * 32,
            "summary": {
                "onchainEligible": True,
                "profileId": "v4_sparse",
                "artifactVersion": "v4_sparse",
                "documentBindingCommitment": "123456789",
                "originalSha256": "bb" * 32,
                "redactedSha256": "cc" * 32,
                "canonicalOriginalSha256": "dd" * 32,
                "canonicalRedactedSha256": "ee" * 32,
                "sourceTextMode": "direct_pdf",
            },
            "manifest": {
                "bundleId": bundle_id,
                "artifactVersion": "v4_sparse",
                "profileId": "v4_sparse",
            },
            "onchain": {
                "status": "not_submitted",
                "chainId": 31337,
                "registryAddress": "0x0000000000000000000000000000000000000001",
                "txHash": None,
                "receiptId": None,
                "submittedAt": None,
                "confirmedAt": None,
                "error": None,
            },
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }
    )

    artifact = type(
        "Artifact",
        (),
        {
            "artifact_version_id": "v4_sparse",
            "snarkjs_bin": type("Bin", (), {"suffix": ".cmd"})(),
        },
    )()
    monkeypatch.setattr("blockvault_api.zkpt_onchain.get_active_artifact_version", lambda: artifact)
    monkeypatch.setattr("blockvault_api.zkpt_onchain.get_artifact_version", lambda profile_id=None: artifact)
    monkeypatch.setattr(
        "blockvault_api.zkpt_onchain._prepare_solidity_calldata",
        lambda bundle: ([1] * 24, [11, 22, 33, 44]),
    )

    send_state = {"nonce": 0}

    def fake_rpc(url: str, method: str, params: list[object]):
        if method == "eth_getTransactionCount":
            return hex(send_state["nonce"])
        if method == "eth_gasPrice":
            return hex(1_000_000_000)
        if method == "eth_estimateGas":
            return hex(250_000)
        if method == "eth_sendRawTransaction":
            send_state["nonce"] += 1
            return "0xabc123"
        raise AssertionError(f"unexpected rpc method {method}")

    monkeypatch.setattr("blockvault_api.zkpt_onchain._rpc", fake_rpc)
    monkeypatch.setattr(
        "blockvault_api.zkpt_onchain._wait_for_receipt",
        lambda url, tx_hash, confirmations: {"status": "0x1", "blockNumber": hex(12345)},
    )

    bundle = db.zkpt_bundles.find_one({"bundle_id": bundle_id})
    assert bundle is not None
    result = submit_verified_bundle_onchain(bundle)

    assert result["status"] == "confirmed"
    assert result["txHash"] == "0xabc123"
    assert result["blockNumber"] == 12345

    updated_bundle = db.zkpt_bundles.find_one({"bundle_id": bundle_id})
    updated_document = db.documents.find_one({"document_id": document_id})
    assert updated_bundle is not None
    assert updated_document is not None
    assert updated_bundle["onchain"]["status"] == "confirmed"
    assert updated_document["zkpt"]["onchain_status"] == "confirmed"


def test_submit_verified_bundle_onchain_rejects_ineligible_bundle(monkeypatch):
    monkeypatch.setenv("BLOCKVAULT_ZKPT_ONCHAIN_ENABLED", "true")
    monkeypatch.setenv("BLOCKVAULT_ZKPT_ONCHAIN_RPC_URL", "http://127.0.0.1:8545")
    monkeypatch.setenv("BLOCKVAULT_ZKPT_ONCHAIN_CHAIN_ID", "31337")
    monkeypatch.setenv("BLOCKVAULT_ZKPT_ONCHAIN_RECEIPT_REGISTRY_ADDRESS", "0x0000000000000000000000000000000000000001")
    monkeypatch.setenv("BLOCKVAULT_ZKPT_ONCHAIN_RELAYER_PRIVATE_KEY", HARDHAT_TEST_KEY)
    monkeypatch.setenv("BLOCKVAULT_ZKPT_PROFILE", "v4_sparse")
    monkeypatch.setenv("BLOCKVAULT_ZKPT_ONCHAIN_SAFE_PROFILE", "v4_sparse")
    reset_settings_cache()
    reset_zkpt_onchain_cache()

    wallet = "0x1000000000000000000000000000000000000001"
    db = get_database()
    bundle = {
        "bundle_id": "zkptbundle_not_eligible",
        "document_id": "docr_not_eligible",
        "owner_wallet": wallet,
        "artifact_version": "v4_sparse",
        "status": "verified",
        "total_shards": 2,
        "proof_json": {"protocol": "plonk"},
        "public_signals": ["1", "2", "3", "4"],
        "summary": {
            "onchainEligible": False,
            "profileId": "v4_sparse",
            "artifactVersion": "v4_sparse",
            "documentBindingCommitment": "123456789",
        },
        "manifest": {"bundleId": "zkptbundle_not_eligible"},
        "created_at": utcnow(),
        "updated_at": utcnow() + timedelta(seconds=1),
    }
    db.zkpt_bundles.insert_one(bundle)

    from blockvault_api.zkpt_onchain import ZKPTOnchainError

    try:
        submit_verified_bundle_onchain(bundle)
    except ZKPTOnchainError as exc:
        assert exc.code == "onchain-not-eligible"
    else:
        raise AssertionError("expected on-chain submission to reject an ineligible bundle")


def test_prepare_solidity_calldata_parses_adjacent_plonk_arrays(monkeypatch):
    artifact = type("Artifact", (), {"artifact_version_id": "v4_sparse", "snarkjs_bin": type("Bin", (), {"suffix": ".cmd"})()})()
    monkeypatch.setattr("blockvault_api.zkpt_onchain.get_active_artifact_version", lambda: artifact)
    monkeypatch.setattr("blockvault_api.zkpt_onchain._resolve_snarkjs_command", lambda *args, **kwargs: ["snarkjs"])

    class Completed:
        stdout = (
            "["
            + ",".join(f'"0x{i:02x}"' for i in range(1, 25))
            + "]"
            + "["
            + ",".join(f'"0x{i:02x}"' for i in range(25, 29))
            + "]"
        )

    monkeypatch.setattr("blockvault_api.zkpt_onchain.subprocess.run", lambda *args, **kwargs: Completed())

    bundle = {
        "artifact_version": "v4_sparse",
        "summary": {"profileId": "v4_sparse"},
        "total_shards": 1,
        "proof_json": {"protocol": "plonk"},
        "public_signals": ["1", "2", "3", "4"],
    }
    proof_words, public_words = _prepare_solidity_calldata(bundle)

    assert len(proof_words) == 24
    assert len(public_words) == 4
    assert proof_words[:2] == [1, 2]
    assert public_words == [25, 26, 27, 28]
