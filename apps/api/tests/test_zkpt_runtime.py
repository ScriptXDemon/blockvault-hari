from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from blockvault_api.zkpt_runtime import check_zkpt_readiness, reset_zkpt_runtime_cache


def test_check_zkpt_readiness_caches_expensive_artifact_lookup(monkeypatch, tmp_path):
    calls = {"count": 0}
    node_path = tmp_path / "node"
    snarkjs_path = tmp_path / "snarkjs.cjs"
    zkey_path = tmp_path / "circuit.zkey"
    node_path.write_text("", encoding="utf-8")
    snarkjs_path.write_text("", encoding="utf-8")
    zkey_path.write_bytes(b"zkey")

    artifact = SimpleNamespace(
        snarkjs_bin=snarkjs_path,
        zkey_path=zkey_path,
        profile_class="authoritative",
        proof_boundary="canonical_segment_mask_v1",
        profile_id="v2",
        proof_model="full_segment_windows",
        binding_input_name="transformationId",
        artifact_version_id="v2",
        verification_key_hash="vk-hash",
        zkey_hash="zkey-hash",
        max_segments=16,
        segment_size=1024,
        tree_depth=8,
        max_policy_rules=8,
        artifacts_dir=Path(tmp_path),
    )

    def fake_get_active_artifact_version():
        calls["count"] += 1
        return artifact

    monkeypatch.setattr("blockvault_api.zkpt_runtime.get_active_artifact_version", fake_get_active_artifact_version)
    monkeypatch.setattr("blockvault_api.zkpt_runtime.list_available_artifact_profiles", lambda: [])
    monkeypatch.setattr(
        "blockvault_api.zkpt_runtime._resolve_binary",
        lambda configured, executable_name: node_path if executable_name == "node" else None,
    )
    monkeypatch.setattr("blockvault_api.zkpt_runtime._probe_version", lambda command: "test-version")
    monkeypatch.setattr(
        "blockvault_api.zkpt_runtime.get_merkle_helper_runtime_status",
        lambda: {"ready": True, "scriptPath": "derive_merkle_material.js", "dependency": "circomlibjs", "error": None},
    )

    reset_zkpt_runtime_cache()
    try:
        first = check_zkpt_readiness()
        second = check_zkpt_readiness()
    finally:
        reset_zkpt_runtime_cache()

    assert first["ready"] is True
    assert second["ready"] is True
    assert calls["count"] == 1
    assert first["proverBackend"] == "snarkjs_wtns_plonk_prove"
    assert first["artifact"]["proofModel"] == "full_segment_windows"
    assert first["artifact"]["bindingInputName"] == "transformationId"
    assert first["tooling"]["merkleHelper"]["ready"] is True
