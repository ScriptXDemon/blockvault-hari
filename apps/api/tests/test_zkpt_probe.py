from __future__ import annotations

import threading
import time
from pathlib import Path

from blockvault_api.config import reset_settings_cache
from blockvault_api.zkpt_artifacts import ZKPTArtifactVersion
from blockvault_api.zkpt_probe import run_zkpt_probe
from blockvault_api.zkpt_prover import ProofExecutionResult


def _make_artifact(
    tmp_path: Path,
    *,
    profile_class: str = "authoritative",
    proof_boundary: str = "canonical_segment_mask_v1",
    segment_size: int = 1024,
    max_segments: int = 16,
) -> ZKPTArtifactVersion:
    artifacts_dir = tmp_path / "zkpt-artifacts"
    artifacts_dir.mkdir()
    verification_key_path = artifacts_dir / "verification_key.json"
    verification_key_path.write_text('{"protocol":"plonk","curve":"bn128"}', encoding="utf-8")
    wasm_path = artifacts_dir / "circuit.wasm"
    wasm_path.write_bytes(b"00")
    zkey_path = artifacts_dir / "circuit.zkey"
    zkey_path.write_bytes(b"11")
    snarkjs_path = artifacts_dir / "snarkjs.cmd"
    snarkjs_path.write_text("@echo off\r\n", encoding="utf-8")
    return ZKPTArtifactVersion(
        profile_id="probe-profile",
        profile_class=profile_class,
        proof_boundary=proof_boundary,
        proof_model="full_segment_windows",
        binding_input_name="transformationId",
        artifact_version_id="probe-v1",
        circuit_id="zkpt_redaction_v2",
        protocol="plonk",
        artifacts_dir=artifacts_dir,
        wasm_path=wasm_path,
        zkey_path=zkey_path,
        verification_key_path=verification_key_path,
        verification_key_hash="verification-key-hash",
        zkey_hash="zkey-hash",
        toolchain={"snarkjs": "0.7.6"},
        segment_size=segment_size,
        max_segments=max_segments,
        tree_depth=8,
        max_policy_rules=8,
        snarkjs_bin=snarkjs_path,
    )


def test_run_zkpt_probe_reports_verified_execution(monkeypatch, tmp_path):
    artifact = _make_artifact(tmp_path)
    monkeypatch.setattr(
        "blockvault_api.zkpt_probe.check_zkpt_readiness",
        lambda: {
            "ready": True,
            "proverBackend": "snarkjs_wtns_plonk_prove",
            "warnings": [],
        },
    )
    monkeypatch.setattr("blockvault_api.zkpt_probe.get_active_artifact_version", lambda: artifact)
    monkeypatch.setattr(
        "blockvault_api.zkpt_probe.generate_circuit_witness",
        lambda **_: {
            "witness": {
                "originalRoot": "11",
                "redactedRoot": "22",
                "policyCommitment": "33",
                "transformationId": "44",
            },
            "verification_data": {
                "originalRoot": "11",
                "redactedRoot": "22",
                "policyCommitment": "33",
                "transformationId": "44",
            },
        },
    )
    monkeypatch.setattr(
        "blockvault_api.zkpt_probe.SnarkjsPlonkProver.prove",
        lambda self, witness: ProofExecutionResult(
            proof_json={"protocol": "plonk"},
            public_signals=[
                witness["originalRoot"],
                witness["redactedRoot"],
                witness["policyCommitment"],
                witness["transformationId"],
            ],
            verified=True,
            witness_hash="witness-hash",
            proof_hash="proof-hash",
            public_signals_hash="public-signals-hash",
            timings={"prove_ms": 10.0, "verify_ms": 3.0},
            backend="snarkjs_wtns_plonk_prove",
            stdout="ok",
            stderr="",
        ),
    )

    report = run_zkpt_probe()

    assert report["probe"]["status"] == "verified"
    assert report["artifact"]["profileId"] == "probe-profile"
    assert report["probe"]["proverBackend"] == "snarkjs_wtns_plonk_prove"
    assert report["probe"]["verificationData"]["originalRoot"] == "11"
    assert report["probe"]["proofHashes"]["proofHash"] == "proof-hash"
    assert report["probe"]["documentBindingCommitment"]
    assert report["probe"]["documentBindingHash"].startswith("0x")
    assert report["recommendations"] == []


def test_run_zkpt_probe_supports_multi_shard_parallel_execution(monkeypatch, tmp_path):
    monkeypatch.setenv("BLOCKVAULT_ZKPT_MAX_PARALLEL_SHARDS", "2")
    reset_settings_cache()
    artifact = _make_artifact(tmp_path, segment_size=8, max_segments=1)
    monkeypatch.setattr(
        "blockvault_api.zkpt_probe.check_zkpt_readiness",
        lambda: {
            "ready": True,
            "proverBackend": "snarkjs_wtns_plonk_prove",
            "warnings": [],
        },
    )
    monkeypatch.setattr("blockvault_api.zkpt_probe.get_active_artifact_version", lambda: artifact)
    monkeypatch.setattr(
        "blockvault_api.zkpt_probe.generate_circuit_witness",
        lambda **kwargs: {
            "witness": {
                "originalRoot": kwargs["original_bytes"].hex(),
                "redactedRoot": kwargs["redacted_bytes"].hex(),
                "policyCommitment": "33",
                "transformationId": "44",
            },
            "verification_data": {
                "originalRoot": kwargs["original_bytes"].hex(),
                "redactedRoot": kwargs["redacted_bytes"].hex(),
                "policyCommitment": "33",
                "transformationId": "44",
            },
        },
    )

    lock = threading.Lock()
    active = {"count": 0, "peak": 0}

    def fake_prove(self, witness):
        with lock:
            active["count"] += 1
            active["peak"] = max(active["peak"], active["count"])
        try:
            time.sleep(0.05)
            return ProofExecutionResult(
                proof_json={"protocol": "plonk"},
                public_signals=[
                    witness["originalRoot"],
                    witness["redactedRoot"],
                    witness["policyCommitment"],
                    witness["transformationId"],
                ],
                verified=True,
                witness_hash=f"witness-{witness['originalRoot']}",
                proof_hash=f"proof-{witness['originalRoot']}",
                public_signals_hash=f"public-{witness['originalRoot']}",
                timings={"witness_ms": 1.0, "prove_ms": 50.0, "verify_ms": 2.0},
                backend="snarkjs_wtns_plonk_prove",
                stdout="ok",
                stderr="",
            )
        finally:
            with lock:
                active["count"] -= 1

    monkeypatch.setattr("blockvault_api.zkpt_probe.SnarkjsPlonkProver.prove", fake_prove)

    try:
        report = run_zkpt_probe(
            source_text="secret alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron",
            search_terms=["secret"],
        )
    finally:
        reset_settings_cache()

    assert report["probe"]["status"] == "verified"
    assert report["probe"]["verifiedShards"] == report["probe"]["totalShards"]
    assert report["probe"]["totalShards"] > 1
    assert report["probe"]["maxParallelShards"] == 2
    assert report["probe"]["shardExecutionMode"] == "parallel"
    assert len(report["probe"]["proofShardHashes"]) == report["probe"]["totalShards"]
    assert all(item["documentBindingCommitment"] for item in report["probe"]["proofShardHashes"])
    assert active["peak"] == 2


def test_run_zkpt_probe_reports_unsupported_profile(monkeypatch, tmp_path):
    artifact = _make_artifact(tmp_path, profile_class="smoke")
    monkeypatch.setattr(
        "blockvault_api.zkpt_probe.check_zkpt_readiness",
        lambda: {
            "ready": False,
            "proverBackend": "snarkjs_wtns_plonk_prove",
            "warnings": ["Large PLONK zkey detected; proving may exceed the configured timeout even with split witness/prove execution"],
        },
    )
    monkeypatch.setattr("blockvault_api.zkpt_probe.get_active_artifact_version", lambda: artifact)

    report = run_zkpt_probe()

    assert report["probe"]["status"] == "unsupported"
    assert report["probe"]["error"]["code"] == "unsupported-profile"
    assert any("authoritative ZKPT profile" in item.lower() or "authoritative" in item.lower() for item in report["recommendations"])
