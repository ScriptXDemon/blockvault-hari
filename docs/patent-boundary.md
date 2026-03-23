# Patent Boundary

The filing-ready engineering boundary in the fresh BlockVault rebuild is limited to the authoritative redaction proof core:

- canonical extracted-text segment masking
- normalized policy commitment binding
- shard witness derivation
- PLONK prove and verify
- linkage to original and redacted document hashes
- exportable verification material tied to evidence bundles

The following areas are not part of the initial patentable implementation:

- OCR reconstruction claims
- recursive aggregation
- semantic preservation claims beyond the canonical text projection
- distributed proof orchestration
- BCDN, AI analysis, signatures, or other auxiliary workflows

The UI and API must never imply proof guarantees beyond `canonical_segment_mask_v1`.
