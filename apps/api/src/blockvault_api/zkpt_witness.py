from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .zkpt_merkle import PoseidonMerkleTree, hash_segment
from .zkpt_poseidon import BN254_PRIME

PLACEHOLDER_BYTE = 0


@dataclass(frozen=True)
class CircuitConfig:
    num_segments: int = 16
    tree_depth: int = 8
    num_policy_rules: int = 8
    segment_size: int = 1024


@dataclass(frozen=True)
class ProjectionData:
    representation: str
    original_bytes: bytes
    redacted_bytes: bytes
    segment_to_term: dict[int, str]
    modified_indices: list[int]
    normalized_terms: list[str]


def normalize_policy_terms(policy_terms: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for term in policy_terms:
        cleaned = str(term or "").strip().lower()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return sorted(normalized)


def encode_policy_rules(policy_terms: list[str], num_rules: int) -> list[int]:
    if len(policy_terms) > num_rules:
        raise ValueError(f"Policy term count {len(policy_terms)} exceeds circuit capacity {num_rules}")
    rules: list[int] = []
    for term in policy_terms:
        digest = hashlib.sha256(term.encode("utf-8")).digest()
        rules.append(int.from_bytes(digest, "big") % BN254_PRIME)
    while len(rules) < num_rules:
        rules.append(0)
    return rules


def _pad_fixed_segments(data: bytes, segment_size: int) -> list[bytes]:
    if not data:
        return [bytes([PLACEHOLDER_BYTE]) * segment_size]
    segments: list[bytes] = []
    for offset in range(0, len(data), segment_size):
        chunk = data[offset:offset + segment_size]
        if len(chunk) < segment_size:
            chunk = chunk.ljust(segment_size, bytes([PLACEHOLDER_BYTE]))
        segments.append(chunk)
    return segments


def _build_tree_from_segments(segments: list[bytes], tree_depth: int) -> tuple[PoseidonMerkleTree, list[int]]:
    hashes = [hash_segment(segment) for segment in segments]
    leaf_capacity = 2 ** tree_depth
    if len(hashes) > leaf_capacity:
        raise ValueError(f"Segment count {len(hashes)} exceeds tree capacity {leaf_capacity}")
    padded_hashes = list(hashes) + ([0] * (leaf_capacity - len(hashes)))
    return PoseidonMerkleTree(padded_hashes), hashes


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _resolve_node_executable() -> str:
    settings_bin = os.getenv("BLOCKVAULT_ZKPT_NODE_BIN")
    if settings_bin:
        candidate = Path(settings_bin)
        if candidate.exists():
            return str(candidate.resolve())
    discovered = shutil.which("node")
    if discovered:
        return discovered
    raise RuntimeError("Node.js executable not found for ZKPT witness generation")


def _node_module_search_paths() -> list[Path]:
    root = _repo_root()
    return [
        (root / "scripts" / "zkpt" / "node_modules").resolve(),
        (root / "node_modules").resolve(),
    ]


def build_node_helper_env() -> dict[str, str]:
    env = dict(os.environ)
    node_modules_bin = _repo_root() / "node_modules" / ".bin"
    env["PATH"] = f"{node_modules_bin}{os.pathsep}{env.get('PATH', '')}"

    search_paths = [str(path) for path in _node_module_search_paths() if path.exists()]
    existing_node_path = env.get("NODE_PATH")
    if existing_node_path:
        search_paths.append(existing_node_path)
    if search_paths:
        deduped: list[str] = []
        seen: set[str] = set()
        for item in search_paths:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        env["NODE_PATH"] = os.pathsep.join(deduped)
    return env


def get_merkle_helper_runtime_status() -> dict[str, Any]:
    script_path = _repo_root() / "scripts" / "zkpt" / "derive_merkle_material.js"
    if not script_path.exists():
        return {
            "ready": False,
            "scriptPath": str(script_path),
            "dependency": "circomlibjs",
            "error": f"Merkle material helper not found: {script_path}",
        }

    try:
        completed = subprocess.run(
            [
                _resolve_node_executable(),
                "-e",
                "require.resolve('circomlibjs'); process.stdout.write('ok')",
            ],
            text=True,
            capture_output=True,
            check=True,
            env=build_node_helper_env(),
            cwd=str(script_path.parent),
        )
        return {
            "ready": True,
            "scriptPath": str(script_path),
            "dependency": "circomlibjs",
            "error": None,
            "stdout": completed.stdout.strip() or None,
        }
    except Exception as exc:
        return {
            "ready": False,
            "scriptPath": str(script_path),
            "dependency": "circomlibjs",
            "error": str(exc),
        }


def _derive_merkle_material(
    *,
    original_leaf_hashes: list[int],
    redacted_leaf_hashes: list[int],
    policy_rules: list[int],
    selected_indices: list[int],
    tree_depth: int,
) -> dict[str, object]:
    script_path = _repo_root() / "scripts" / "zkpt" / "derive_merkle_material.js"
    if not script_path.exists():
        raise RuntimeError(f"Merkle material helper not found: {script_path}")

    payload = {
        "originalLeafHashes": [str(value) for value in original_leaf_hashes],
        "redactedLeafHashes": [str(value) for value in redacted_leaf_hashes],
        "policyRules": [str(value) for value in policy_rules],
        "selectedIndices": selected_indices,
        "treeDepth": tree_depth,
    }
    env = build_node_helper_env()
    completed = subprocess.run(
        [_resolve_node_executable(), str(script_path)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        env=env,
        cwd=str(script_path.parent),
    )
    return json.loads(completed.stdout)


def _pad_selected_indices(selected_indices: list[int], config: CircuitConfig, tree_leaf_count: int, actual_segment_count: int) -> list[int]:
    if len(selected_indices) > config.num_segments:
        raise ValueError(f"Selected segment count {len(selected_indices)} exceeds circuit capacity {config.num_segments}")

    padded = list(selected_indices)
    filler_pool = [index for index in range(tree_leaf_count) if index not in padded]
    if not filler_pool and len(padded) < config.num_segments:
        raise ValueError("Could not pad selected indices without reusing a tree position")
    cursor = 0
    while len(padded) < config.num_segments:
        padded.append(filler_pool[cursor % len(filler_pool)])
        cursor += 1
    return padded


def assign_policy_selectors(selected_indices: list[int], mask: list[int], policy_terms: list[str], segment_to_term: dict[int, str] | None, num_policy_rules: int) -> list[int]:
    segment_to_term = segment_to_term or {}
    term_to_index = {term: index for index, term in enumerate(policy_terms[:num_policy_rules])}
    selectors = [0] * len(selected_indices)
    for idx, segment_index in enumerate(selected_indices):
        if not mask[idx]:
            continue
        term = segment_to_term.get(segment_index)
        if term is None:
            raise ValueError(f"No policy selector found for modified segment {segment_index}")
        selectors[idx] = term_to_index[term]
    return selectors


def build_text_redaction_projection(*, source_text: str, policy_terms: list[str], segment_size: int) -> ProjectionData:
    normalized_terms = normalize_policy_terms(policy_terms)
    canonical_text = source_text.replace("\r\n", "\n").replace("\r", "\n")
    original_segments = _pad_fixed_segments(canonical_text.encode("utf-8"), segment_size)
    placeholder_segment = bytes([PLACEHOLDER_BYTE]) * segment_size
    redacted_segments: list[bytes] = []
    segment_to_term: dict[int, str] = {}
    modified_indices: list[int] = []

    for index, segment in enumerate(original_segments):
        lowered = segment.decode("utf-8", errors="ignore").lower()
        matched_term = next((term for term in normalized_terms if term in lowered), None)
        if matched_term is None:
            redacted_segments.append(segment)
            continue
        modified_indices.append(index)
        segment_to_term[index] = matched_term
        redacted_segments.append(placeholder_segment)

    return ProjectionData(
        representation="canonical_segment_mask_v1",
        original_bytes=b"".join(original_segments),
        redacted_bytes=b"".join(redacted_segments),
        segment_to_term=segment_to_term,
        modified_indices=modified_indices,
        normalized_terms=normalized_terms,
    )


def _normalize_binding_value(binding_value: str) -> str:
    if binding_value.isdigit():
        return str(int(binding_value) % BN254_PRIME)
    binding_digest = hashlib.sha256(binding_value.encode("utf-8")).digest()
    return str(int.from_bytes(binding_digest, "big") % BN254_PRIME)


def _build_projection_trees(
    *,
    original_bytes: bytes,
    redacted_bytes: bytes,
    config: CircuitConfig,
) -> tuple[list[bytes], list[bytes], PoseidonMerkleTree, PoseidonMerkleTree, list[int], list[int], list[int]]:
    original_segments = _pad_fixed_segments(original_bytes, config.segment_size)
    redacted_segments = _pad_fixed_segments(redacted_bytes, config.segment_size)
    original_tree, original_hashes = _build_tree_from_segments(original_segments, config.tree_depth)
    redacted_tree, redacted_hashes = _build_tree_from_segments(redacted_segments, config.tree_depth)
    modified_indices = [
        index for index, (old_hash, new_hash) in enumerate(zip(original_hashes, redacted_hashes)) if old_hash != new_hash
    ]
    return (
        original_segments,
        redacted_segments,
        original_tree,
        redacted_tree,
        original_hashes,
        redacted_hashes,
        modified_indices,
    )


def _collect_path_signals(
    *,
    padded_indices: list[int],
    original_tree: PoseidonMerkleTree,
    redacted_tree: PoseidonMerkleTree,
    merkle_material: dict[str, object],
) -> tuple[list[str], list[str], list[list[str]], list[list[str]], list[list[str]], list[list[str]]]:
    original_hash_signals: list[str] = []
    redacted_hash_signals: list[str] = []
    orig_siblings: list[list[str]] = []
    orig_directions: list[list[str]] = []
    red_siblings: list[list[str]] = []
    red_directions: list[list[str]] = []

    for index in padded_indices:
        original_hash_signals.append(str(original_tree.get_leaf(index)))
        redacted_hash_signals.append(str(redacted_tree.get_leaf(index)))
        material_index = len(orig_siblings)
        original_path = merkle_material["originalPaths"][material_index]
        redacted_path = merkle_material["redactedPaths"][material_index]
        orig_siblings.append([str(sibling) for sibling in original_path["siblings"]])
        orig_directions.append([str(direction) for direction in original_path["directions"]])
        red_siblings.append([str(sibling) for sibling in redacted_path["siblings"]])
        red_directions.append([str(direction) for direction in redacted_path["directions"]])

    return (
        original_hash_signals,
        redacted_hash_signals,
        orig_siblings,
        orig_directions,
        red_siblings,
        red_directions,
    )


def _build_verification_data(witness: dict[str, object], binding_input_name: str) -> dict[str, str]:
    return {
        "originalRoot": str(witness["originalRoot"]),
        "redactedRoot": str(witness["redactedRoot"]),
        "policyCommitment": str(witness["policyCommitment"]),
        binding_input_name: str(witness[binding_input_name]),
    }


def generate_circuit_witness(
    *,
    original_bytes: bytes,
    redacted_bytes: bytes,
    policy_terms: list[str],
    transformation_id: str | None = None,
    config: CircuitConfig,
    segment_to_term: dict[int, str] | None = None,
    binding_value: str | None = None,
    binding_input_name: str = "transformationId",
    proof_model: str = "full_segment_windows",
    selected_indices: list[int] | None = None,
) -> dict[str, object]:
    normalized_terms = normalize_policy_terms(policy_terms)
    policy_rules = encode_policy_rules(normalized_terms, config.num_policy_rules)
    binding_raw = str(binding_value if binding_value is not None else transformation_id or "").strip()
    if not binding_raw:
        raise ValueError("A binding input value is required for witness generation")
    binding_field_value = _normalize_binding_value(binding_raw)

    (
        original_segments,
        _redacted_segments,
        original_tree,
        redacted_tree,
        original_hashes,
        redacted_hashes,
        modified_indices,
    ) = _build_projection_trees(
        original_bytes=original_bytes,
        redacted_bytes=redacted_bytes,
        config=config,
    )

    placeholder_segment = bytes([PLACEHOLDER_BYTE]) * config.segment_size
    placeholder_hash = hash_segment(placeholder_segment)

    if proof_model == "full_segment_windows":
        if len(original_hashes) > config.num_segments:
            raise ValueError(f"Document projection spans {len(original_hashes)} segments; explicit sharding is required")

        selected_window = selected_indices or list(range(min(len(original_hashes), config.num_segments)))
        padded_indices = _pad_selected_indices(selected_window, config, original_tree.leaf_count, len(original_hashes))
        mask = [1 if index in modified_indices else 0 for index in padded_indices]
        merkle_material = _derive_merkle_material(
            original_leaf_hashes=original_hashes,
            redacted_leaf_hashes=redacted_hashes,
            policy_rules=policy_rules,
            selected_indices=padded_indices,
            tree_depth=config.tree_depth,
        )
        (
            original_hash_signals,
            redacted_hash_signals,
            orig_siblings,
            orig_directions,
            red_siblings,
            red_directions,
        ) = _collect_path_signals(
            padded_indices=padded_indices,
            original_tree=original_tree,
            redacted_tree=redacted_tree,
            merkle_material=merkle_material,
        )
        policy_selectors = assign_policy_selectors(
            padded_indices,
            mask,
            normalized_terms,
            segment_to_term,
            config.num_policy_rules,
        )

        witness = {
            "originalRoot": str(merkle_material["originalRoot"]),
            "redactedRoot": str(merkle_material["redactedRoot"]),
            "policyCommitment": str(merkle_material["policyCommitment"]),
            binding_input_name: binding_field_value,
            "originalHashes": original_hash_signals,
            "redactedHashes": redacted_hash_signals,
            "mask": [str(bit) for bit in mask],
            "origSiblings": orig_siblings,
            "origDirections": orig_directions,
            "redSiblings": red_siblings,
            "redDirections": red_directions,
            "placeholderHash": str(placeholder_hash),
            "policyRules": [str(rule) for rule in policy_rules],
            "policySelector": [str(selector) for selector in policy_selectors],
        }
        return {
            "witness": witness,
            "metadata": {
                "selected_indices": selected_window,
                "padded_indices": padded_indices,
                "modified_indices": modified_indices,
                "policy_terms_normalized": normalized_terms,
                "proof_projection": "canonical_segment_mask_v1",
                "proof_model": proof_model,
            },
            "verification_data": _build_verification_data(witness, binding_input_name),
        }

    if proof_model == "sparse_update":
        active_indices = list(selected_indices or modified_indices)
        if not active_indices:
            raise ValueError("Sparse proof generation requires at least one modified segment")
        if any(index not in modified_indices for index in active_indices):
            raise ValueError("Sparse proof selected indices must refer only to modified segments")
        padded_indices = _pad_selected_indices(active_indices, config, original_tree.leaf_count, len(original_segments))
        update_mask = [1 if index in active_indices else 0 for index in padded_indices]
        merkle_material = _derive_merkle_material(
            original_leaf_hashes=original_hashes,
            redacted_leaf_hashes=redacted_hashes,
            policy_rules=policy_rules,
            selected_indices=padded_indices,
            tree_depth=config.tree_depth,
        )
        (
            original_leaf_hash_signals,
            redacted_leaf_hash_signals,
            orig_siblings,
            orig_directions,
            red_siblings,
            red_directions,
        ) = _collect_path_signals(
            padded_indices=padded_indices,
            original_tree=original_tree,
            redacted_tree=redacted_tree,
            merkle_material=merkle_material,
        )
        policy_selectors = assign_policy_selectors(
            padded_indices,
            update_mask,
            normalized_terms,
            segment_to_term,
            config.num_policy_rules,
        )
        witness = {
            "originalRoot": str(merkle_material["originalRoot"]),
            "redactedRoot": str(merkle_material["redactedRoot"]),
            "policyCommitment": str(merkle_material["policyCommitment"]),
            binding_input_name: binding_field_value,
            "modifiedIndices": [str(index) for index in padded_indices],
            "updateMask": [str(bit) for bit in update_mask],
            "originalLeafHashes": original_leaf_hash_signals,
            "redactedLeafHashes": redacted_leaf_hash_signals,
            "origSiblings": orig_siblings,
            "origDirections": orig_directions,
            "redSiblings": red_siblings,
            "redDirections": red_directions,
            "placeholderHash": str(placeholder_hash),
            "policyRules": [str(rule) for rule in policy_rules],
            "policySelector": [str(selector) for selector in policy_selectors],
        }
        return {
            "witness": witness,
            "metadata": {
                "selected_indices": active_indices,
                "padded_indices": padded_indices,
                "modified_indices": modified_indices,
                "policy_terms_normalized": normalized_terms,
                "proof_projection": "canonical_segment_mask_v1",
                "proof_model": proof_model,
                "active_update_count": len(active_indices),
            },
            "verification_data": _build_verification_data(witness, binding_input_name),
        }

    raise ValueError(f"Unsupported proof model '{proof_model}'")
