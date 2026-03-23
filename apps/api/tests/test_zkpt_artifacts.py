from __future__ import annotations

import json
from pathlib import Path

from blockvault_api.config import reset_settings_cache
from blockvault_api.zkpt_artifacts import get_active_artifact_version, list_available_artifact_profiles


def _write_manifest(profile_dir: Path, *, artifact_version_id: str, profile_class: str = "authoritative") -> None:
    (profile_dir / 'zkpt_redaction_v2_js').mkdir(parents=True, exist_ok=True)
    (profile_dir / 'zkpt_redaction_v2_js' / 'zkpt_redaction_v2.wasm').write_bytes(b'00')
    (profile_dir / 'circuit.zkey').write_bytes(b'11')
    (profile_dir / 'verification_key.json').write_text('{"protocol":"plonk","curve":"bn128"}', encoding='utf-8')
    (profile_dir / 'artifact-manifest.json').write_text(
        json.dumps(
            {
                'profile_id': profile_dir.name,
                'profile_class': profile_class,
                'proof_boundary': 'canonical_segment_mask_v1',
                'proof_model': 'full_segment_windows',
                'binding_input_name': 'transformationId',
                'artifact_version_id': artifact_version_id,
                'circuit_id': 'zkpt_redaction_v2',
                'protocol': 'plonk',
                'circuit': {
                    'num_policy_rules': 8,
                    'num_segments': 16,
                    'segment_size': 1024,
                    'tree_depth': 8,
                },
                'files': {
                    'verification_key': 'verification_key.json',
                    'wasm': 'zkpt_redaction_v2_js/zkpt_redaction_v2.wasm',
                    'zkey': 'circuit.zkey',
                },
                'hashes': {},
            }
        ),
        encoding='utf-8',
    )


def test_active_artifact_profile_uses_selected_profile(monkeypatch, tmp_path):
    profiles_root = tmp_path / 'zkpt-profiles'
    fast_dir = profiles_root / 'fast-local'
    v2_dir = profiles_root / 'v2'
    _write_manifest(fast_dir, artifact_version_id='fast-local')
    _write_manifest(v2_dir, artifact_version_id='v2')

    monkeypatch.setenv('BLOCKVAULT_ZKPT_PROFILES_ROOT', str(profiles_root))
    monkeypatch.setenv('BLOCKVAULT_ZKPT_PROFILE', 'fast-local')
    monkeypatch.setenv('BLOCKVAULT_ZKPT_ARTIFACTS_DIR', 'circuits/zkpt/v2')
    reset_settings_cache()

    try:
        artifact = get_active_artifact_version()
        profiles = list_available_artifact_profiles()
    finally:
        reset_settings_cache()

    assert artifact.artifact_version_id == 'fast-local'
    assert artifact.profile_id == 'fast-local'
    assert artifact.profile_class == 'authoritative'
    assert artifact.proof_boundary == 'canonical_segment_mask_v1'
    assert artifact.artifacts_dir == fast_dir.resolve()
    selected = next(profile for profile in profiles if profile['id'] == 'fast-local')
    assert selected['selected'] is True
    assert selected['profileClass'] == 'authoritative'
    assert selected['proofBoundary'] == 'canonical_segment_mask_v1'
    assert selected['proofModel'] == 'full_segment_windows'
    assert selected['bindingInputName'] == 'transformationId'
    assert artifact.proof_model == 'full_segment_windows'
    assert artifact.binding_input_name == 'transformationId'
    assert any(profile['id'] == 'v2' for profile in profiles)


def test_artifact_version_downloads_missing_files_from_s3(monkeypatch, tmp_path):
    profiles_root = tmp_path / 'zkpt-profiles'
    profile_dir = profiles_root / 'v4_sparse'
    _write_manifest(profile_dir, artifact_version_id='v4_sparse')
    zkey_path = profile_dir / 'circuit.zkey'
    zkey_path.unlink()

    uploaded_payload = b'fresh-zkey'

    class FakeS3Client:
        def download_file(self, bucket: str, key: str, destination: str) -> None:
            assert bucket == 'blockvault-artifacts'
            assert key == 'zkpt-artifacts/v4_sparse/circuit.zkey'
            Path(destination).write_bytes(uploaded_payload)

    monkeypatch.setenv('BLOCKVAULT_ZKPT_PROFILES_ROOT', str(profiles_root))
    monkeypatch.setenv('BLOCKVAULT_ZKPT_PROFILE', 'v4_sparse')
    monkeypatch.setenv('BLOCKVAULT_ZKPT_ARTIFACTS_AUTO_DOWNLOAD', 'true')
    monkeypatch.setenv('BLOCKVAULT_ZKPT_ARTIFACTS_S3_BUCKET', 'blockvault-artifacts')
    reset_settings_cache()
    monkeypatch.setattr('blockvault_api.zkpt_artifacts._get_zkpt_artifact_s3_client', lambda: FakeS3Client())

    try:
        artifact = get_active_artifact_version()
    finally:
        reset_settings_cache()

    assert artifact.zkey_path.read_bytes() == uploaded_payload
