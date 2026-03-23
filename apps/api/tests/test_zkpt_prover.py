from __future__ import annotations

import json
import subprocess
from pathlib import Path

from blockvault_api.config import reset_settings_cache
from blockvault_api.zkpt_artifacts import ZKPTArtifactVersion
from blockvault_api.zkpt_prover import SnarkjsPlonkProver


def _make_artifact(tmp_path: Path, *, binding_input_name: str = "transformationId") -> ZKPTArtifactVersion:
    artifacts_dir = tmp_path / "zkpt-artifacts"
    artifacts_dir.mkdir()
    verification_key_path = artifacts_dir / "verification_key.json"
    verification_key_path.write_text('{"protocol":"plonk","curve":"bn128"}', encoding="utf-8")
    wasm_path = artifacts_dir / "circuit.wasm"
    wasm_path.write_bytes(b"00")
    zkey_path = artifacts_dir / "circuit.zkey"
    zkey_path.write_bytes(b"11")
    snarkjs_path = artifacts_dir / "cli.cjs"
    snarkjs_path.write_text("console.log('snarkjs mock')\n", encoding="utf-8")
    return ZKPTArtifactVersion(
        profile_id="test-v2",
        profile_class="authoritative",
        proof_boundary="canonical_segment_mask_v1",
        proof_model="full_segment_windows",
        binding_input_name=binding_input_name,
        artifact_version_id="test-v2",
        circuit_id="zkpt_redaction_v2",
        protocol="plonk",
        artifacts_dir=artifacts_dir,
        wasm_path=wasm_path,
        zkey_path=zkey_path,
        verification_key_path=verification_key_path,
        verification_key_hash="verification-key-hash",
        zkey_hash="zkey-hash",
        toolchain={"snarkjs": "0.7.6"},
        segment_size=1024,
        max_segments=16,
        tree_depth=8,
        max_policy_rules=8,
        snarkjs_bin=snarkjs_path,
    )


def test_snarkjs_plonk_prover_uses_split_plonk_prove(monkeypatch, tmp_path):
    artifact = _make_artifact(tmp_path)
    node_bin = tmp_path / "node.exe"
    node_bin.write_text("", encoding="utf-8")
    monkeypatch.setenv("BLOCKVAULT_ZKPT_NODE_BIN", str(node_bin))
    monkeypatch.delenv("BLOCKVAULT_ZKPT_RAPIDSNARK_BIN", raising=False)
    reset_settings_cache()

    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append([str(part) for part in command])
        if "wtns" in command:
            Path(command[-1]).write_bytes(b"wtns")
            return subprocess.CompletedProcess(command, 0, "wtns ok", "")
        if "prove" in command:
            Path(command[-2]).write_text(json.dumps({"pi_a": ["1", "2"], "protocol": "plonk"}), encoding="utf-8")
            Path(command[-1]).write_text(json.dumps(["11", "22", "33", "44"]), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "prove ok", "")
        if "verify" in command:
            return subprocess.CompletedProcess(command, 0, "OK!\n", "")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("blockvault_api.zkpt_prover.subprocess.run", fake_run)

    try:
        prover = SnarkjsPlonkProver(artifact, timeout_seconds=30)
        result = prover.prove(
            {
                "originalRoot": "11",
                "redactedRoot": "22",
                "policyCommitment": "33",
                "transformationId": "44",
            }
        )
    finally:
        reset_settings_cache()

    assert result.verified is True
    assert result.backend == "snarkjs_wtns_plonk_prove"
    assert len(commands) == 3
    assert "wtns" in commands[0]
    assert "calculate" in commands[0]
    assert "plonk" in commands[1]
    assert "prove" in commands[1]
    assert "verify" in commands[2]



def test_snarkjs_plonk_prover_ignores_rapidsnark_for_plonk(monkeypatch, tmp_path):
    artifact = _make_artifact(tmp_path)
    node_bin = tmp_path / "node.exe"
    node_bin.write_text("", encoding="utf-8")
    rapidsnark_bin = tmp_path / "rapidsnark.exe"
    rapidsnark_bin.write_text("", encoding="utf-8")
    monkeypatch.setenv("BLOCKVAULT_ZKPT_NODE_BIN", str(node_bin))
    monkeypatch.setenv("BLOCKVAULT_ZKPT_RAPIDSNARK_BIN", str(rapidsnark_bin))
    reset_settings_cache()

    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append([str(part) for part in command])
        if "wtns" in command:
            Path(command[-1]).write_bytes(b"wtns")
            return subprocess.CompletedProcess(command, 0, "wtns ok", "")
        if "prove" in command:
            Path(command[-2]).write_text(json.dumps({"pi_a": ["1", "2"], "protocol": "plonk"}), encoding="utf-8")
            Path(command[-1]).write_text(json.dumps(["11", "22", "33", "44"]), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "prove ok", "")
        if "verify" in command:
            return subprocess.CompletedProcess(command, 0, "OK!\n", "")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("blockvault_api.zkpt_prover.subprocess.run", fake_run)

    try:
        prover = SnarkjsPlonkProver(artifact, timeout_seconds=30)
        result = prover.prove(
            {
                "originalRoot": "11",
                "redactedRoot": "22",
                "policyCommitment": "33",
                "transformationId": "44",
            }
        )
    finally:
        reset_settings_cache()

    assert result.verified is True
    assert result.backend == "snarkjs_wtns_plonk_prove"
    assert len(commands) == 3
    assert "wtns" in commands[0]
    assert "calculate" in commands[0]
    assert "plonk" in commands[1]
    assert "prove" in commands[1]
    assert all(part != str(rapidsnark_bin) for command in commands for part in command)



def test_snarkjs_plonk_prover_uses_document_binding_commitment_when_profile_requires_it(monkeypatch, tmp_path):
    artifact = _make_artifact(tmp_path, binding_input_name="documentBindingCommitment")
    node_bin = tmp_path / "node.exe"
    node_bin.write_text("", encoding="utf-8")
    monkeypatch.setenv("BLOCKVAULT_ZKPT_NODE_BIN", str(node_bin))
    reset_settings_cache()

    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append([str(part) for part in command])
        if "wtns" in command:
            Path(command[-1]).write_bytes(b"wtns")
            return subprocess.CompletedProcess(command, 0, "wtns ok", "")
        if "prove" in command:
            Path(command[-2]).write_text(json.dumps({"pi_a": ["1", "2"], "protocol": "plonk"}), encoding="utf-8")
            Path(command[-1]).write_text(json.dumps(["11", "22", "33", "44"]), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "prove ok", "")
        if "verify" in command:
            return subprocess.CompletedProcess(command, 0, "OK!\n", "")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("blockvault_api.zkpt_prover.subprocess.run", fake_run)

    try:
        prover = SnarkjsPlonkProver(artifact, timeout_seconds=30)
        result = prover.prove(
            {
                "originalRoot": "11",
                "redactedRoot": "22",
                "policyCommitment": "33",
                "documentBindingCommitment": "44",
            }
        )
    finally:
        reset_settings_cache()

    assert result.verified is True
    assert result.public_signals == ["11", "22", "33", "44"]
    assert len(commands) == 3
    assert "prove" in commands[1]
