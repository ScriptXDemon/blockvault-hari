from __future__ import annotations

from blockvault_api.zkpt_witness import CircuitConfig, generate_circuit_witness


def test_generate_sparse_update_witness_uses_document_binding_commitment_and_modified_indices(monkeypatch):
    monkeypatch.setattr(
        "blockvault_api.zkpt_witness._derive_merkle_material",
        lambda **kwargs: {
            "originalRoot": "11",
            "redactedRoot": "22",
            "policyCommitment": "33",
            "originalPaths": [
                {"siblings": ["0", "0", "0", "0"], "directions": ["0", "0", "0", "0"]}
                for _ in kwargs["selected_indices"]
            ],
            "redactedPaths": [
                {"siblings": ["0", "0", "0", "0"], "directions": ["0", "0", "0", "0"]}
                for _ in kwargs["selected_indices"]
            ],
        },
    )

    config = CircuitConfig(num_segments=4, tree_depth=4, num_policy_rules=4, segment_size=4)
    witness_package = generate_circuit_witness(
        original_bytes=b"secraaaabbbbsecrccccdddd",
        redacted_bytes=(bytes([0]) * 4) + b"aaaabbbb" + (bytes([0]) * 4) + b"ccccdddd",
        policy_terms=["secr"],
        binding_value="123456789",
        binding_input_name="documentBindingCommitment",
        proof_model="sparse_update",
        selected_indices=[0, 3],
        config=config,
        segment_to_term={0: "secr", 3: "secr"},
    )

    witness = witness_package["witness"]
    metadata = witness_package["metadata"]
    verification_data = witness_package["verification_data"]

    assert "documentBindingCommitment" in witness
    assert "transformationId" not in witness
    assert witness["modifiedIndices"][:2] == ["0", "3"]
    assert witness["updateMask"][:2] == ["1", "1"]
    assert len(witness["modifiedIndices"]) == 4
    assert len(witness["updateMask"]) == 4
    assert metadata["selected_indices"] == [0, 3]
    assert metadata["active_update_count"] == 2
    assert metadata["proof_model"] == "sparse_update"
    assert verification_data["documentBindingCommitment"] == witness["documentBindingCommitment"]
