from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_build_profile_module():
    module_path = Path(__file__).resolve().parents[3] / "scripts" / "zkpt" / "build_profile.py"
    spec = importlib.util.spec_from_file_location("build_profile", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_render_profile_source_rewrites_main_instantiation():
    module = _load_build_profile_module()
    source = """
pragma circom 2.1.6;
component main {public [originalRoot, redactedRoot, policyCommitment, transformationId]} = ZKPTRedaction(16, 8, 8);
"""
    rendered = module.render_profile_source(
        source_text=source,
        num_segments=4,
        tree_depth=6,
        num_policy_rules=4,
    )

    assert "ZKPTRedaction(4, 6, 4);" in rendered
    assert "ZKPTRedaction(16, 8, 8);" not in rendered


def test_render_profile_source_rewrites_sparse_main_instantiation():
    module = _load_build_profile_module()
    source = """
pragma circom 2.1.6;
component main {public [originalRoot, redactedRoot, policyCommitment, documentBindingCommitment]} = ZKPTRedactionSparse(4, 8, 8);
"""
    rendered = module.render_profile_source(
        source_text=source,
        num_segments=2,
        tree_depth=5,
        num_policy_rules=3,
    )

    assert "ZKPTRedactionSparse(2, 5, 3);" in rendered
    assert "ZKPTRedactionSparse(4, 8, 8);" not in rendered
