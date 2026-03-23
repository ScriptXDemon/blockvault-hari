# BlockVault Product Spec

## Core users

- individual professionals storing sensitive private files
- legal practitioners managing matter-based document workflows
- reviewers verifying exported evidence bundles and ZKPT material

## Primary surfaces

- `/`: public landing page and wallet connect
- `/app/vault`: encrypted private vault
- `/app/cases`: case listing and creation
- `/app/cases/:caseId`: case detail and associated legal documents
- `/app/documents/:documentId`: document detail, notarization state, redaction actions, custody events
- `/app/evidence/:bundleId`: evidence bundle and proof export viewer

## Core workflows

1. Connect wallet and establish a cookie-backed authenticated session.
2. Upload a private file encrypted client-side with a passphrase.
3. Share a vault file with another wallet address.
4. Create a legal case and upload a legal PDF.
5. Notarize the legal PDF and export the evidence bundle.
6. Submit a redaction job for an extractable PDF.
7. Inspect the redaction result, proof boundary, and bundle export.
8. Review the server-backed chain-of-custody timeline.

## Non-goals for v1

- semantic OCR reconstruction
- AI-generated analysis
- BCDN bundle workflows
- signature orchestration
- experimental proof aggregation or selective disclosure
