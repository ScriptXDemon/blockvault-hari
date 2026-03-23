from __future__ import annotations


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "zkpt_ready" in payload
    assert payload["zkpt_ready"] == payload["zkpt_runtime"]["ready"]
    assert payload["storage_ready"] == payload["storage_runtime"]["ready"]
    assert payload["storage_runtime"]["backend"] == "local"
    assert payload["storage_runtime"]["root"]
    assert payload["zkpt_runtime"]["proofBoundary"] == "canonical_segment_mask_v1"
    assert payload["zkpt_runtime"]["proverBackend"] in {"snarkjs_fullprove", "snarkjs_wtns_rapidsnark", "snarkjs_wtns_plonk_prove"}
    assert isinstance(payload["zkpt_runtime"]["availableProfiles"], list)
    assert payload["zkpt_runtime"]["artifact"]["selectedProfile"]
    assert "profileClass" in payload["zkpt_runtime"]["artifact"]
    assert "proofBoundary" in payload["zkpt_runtime"]["artifact"]
    assert "circuitSourcePresent" in payload["zkpt_runtime"]["artifact"]
    assert isinstance(payload["zkpt_runtime"]["warnings"], list)
    assert payload["zkpt_runtime"]["limits"]["maxParallelShards"] > 0
    assert payload["zkpt_runtime"]["limits"]["singleProofTimeoutSeconds"] > 0
    assert payload["zkpt_runtime"]["limits"]["multiShardTimeoutSeconds"] > 0
    assert payload["zkpt_runtime"]["preflightThresholds"]["directOnchainMaxShards"] == 1
    assert payload["zkpt_runtime"]["onchain"]["singleProofOnly"] is True
    assert "verifierSourcePath" in payload["zkpt_runtime"]["onchain"]
    assert "verifierMetadataPath" in payload["zkpt_runtime"]["onchain"]
    assert "verifierContractName" in payload["zkpt_runtime"]["onchain"]
    assert "deploymentManifestPath" in payload["zkpt_runtime"]["onchain"]
    assert "deployedVerifierAddress" in payload["zkpt_runtime"]["onchain"]
    assert "deployedRegistryAddress" in payload["zkpt_runtime"]["onchain"]
    if payload["zkpt_runtime"]["ready"]:
        assert payload["zkpt_runtime"]["artifact"]["zkeyBytes"] > 0
        assert payload["zkpt_runtime"]["artifact"]["artifactsDir"]
        assert payload["zkpt_runtime"]["artifact"]["profileClass"] == "authoritative"
        assert payload["zkpt_runtime"]["artifact"]["proofBoundary"] == "canonical_segment_mask_v1"
    else:
        assert payload["zkpt_runtime"]["artifact"]["zkeyBytes"] is None
        assert payload["zkpt_runtime"]["errors"]
    assert payload["redaction_runtime"]["effective_mode"] == "inline_fallback"
    assert "redaction_engine_ready" in payload["redaction_runtime"]
    assert "redaction_engine_version" in payload["redaction_runtime"]
    assert "redaction_engine_mode" in payload["redaction_runtime"]
    assert "ocr_fallback_enabled" in payload["redaction_runtime"]
    assert "ocr_runtime_ready" in payload["redaction_runtime"]
    assert payload["redaction_runtime"]["redaction_source_modes"] == ["direct_pdf", "ocr_assisted"]
    assert payload["redaction_runtime"]["zkpt_max_parallel_shards"] > 0
    assert payload["redaction_runtime"]["preflight_thresholds"]["singleProofTargetSeconds"] > 0
    assert payload["redaction_engine_ready"] == payload["redaction_runtime"]["redaction_engine_ready"]
    assert "merkleHelper" in payload["zkpt_runtime"]["tooling"]



def test_status(client):
    response = client.get("/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["proof_boundary"] == "canonical_segment_mask_v1"
    assert payload["zkpt_ready"] == payload["zkpt_runtime"]["ready"]
    assert payload["storage_ready"] == payload["storage_runtime"]["ready"]
    assert payload["storage_backend"] == "local"
    assert payload["storage_root"] == payload["storage_runtime"]["root"]
    assert "artifactVersion" in payload["zkpt_runtime"]["artifact"]
    assert payload["zkpt_runtime"]["artifact"]["selectedProfile"]
    assert "profileClass" in payload["zkpt_runtime"]["artifact"]
    assert payload["zkpt_runtime"]["limits"]["proofTimeoutSeconds"] > 0
    assert payload["zkpt_runtime"]["limits"]["targetProofSeconds"] > 0
    assert payload["zkpt_runtime"]["limits"]["maxParallelShards"] > 0
    assert payload["zkpt_runtime"]["preflightThresholds"]["singleProofTimeoutSeconds"] > 0
    assert "onchain" in payload["zkpt_runtime"]
    assert "verifierSourcePath" in payload["zkpt_runtime"]["onchain"]
    assert "verifierMetadataPath" in payload["zkpt_runtime"]["onchain"]
    assert "verifierContractName" in payload["zkpt_runtime"]["onchain"]
    assert payload["redaction_runtime"]["task_name"] == "blockvault.redactions.run"
    assert "ocr_fallback_enabled" in payload["redaction_runtime"]
    assert "ocr_runtime_ready" in payload["redaction_runtime"]
    assert payload["redaction_runtime"]["redaction_source_modes"] == ["direct_pdf", "ocr_assisted"]
    assert payload["redaction_engine_ready"] == payload["redaction_runtime"]["redaction_engine_ready"]
