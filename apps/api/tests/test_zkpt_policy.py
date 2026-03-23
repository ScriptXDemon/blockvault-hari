from __future__ import annotations

from blockvault_api.zkpt_policy import estimate_redaction_preflight


def test_sparse_update_preflight_scales_with_modified_segments():
    report = estimate_redaction_preflight(
        projection_bytes_length=8192,
        profile_id="v4_sparse",
        segment_size=256,
        segments_per_shard=4,
        proof_model="sparse_update",
        modified_segments_count=2,
    )

    assert report["proofModel"] == "sparse_update"
    assert report["proofUnits"] == 2
    assert report["estimatedShards"] == 1
    assert report["classification"] == "single_proof_ready"
