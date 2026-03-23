# ZKPT artifacts

This directory contains the authoritative proving artifacts retained for the fresh rebuild.

Current expected layout:

- `zkpt/v2/artifact-manifest.json`
- `zkpt/v2/verification_key.json`
- `zkpt/v2/circuit.zkey`
- `zkpt/v2/zkpt_redaction_v2_js/zkpt_redaction_v2.wasm`

These artifacts were preserved from the legacy archive and are only used to reattach the authoritative proof runtime.

Each profile manifest should now declare:

- `profile_id`
- `profile_class`
- `proof_boundary`

For the production slice, only profiles with `profile_class: "authoritative"` and `proof_boundary: "canonical_segment_mask_v1"` are allowed to produce verified ZKPT bundles.
