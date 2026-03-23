export type ProofStatus = "verified" | "failed" | "unsupported";
export type ProofClassification = "single_proof_ready" | "verified_bundle_only" | "unsupported_until_v4";
export type OnchainStatus = "not_submitted" | "submitted" | "confirmed" | "unsupported" | "failed";

export interface ZkptStatus {
  mode: string;
  status: ProofStatus;
  bundle_id: string | null;
  artifact_version: string | null;
  profile_id: string | null;
  profile_class: string | null;
  proof_boundary: "canonical_segment_mask_v1";
  verified_shards: number;
  total_shards: number;
  estimated_shards: number;
  predicted_proof_ms: number | null;
  classification: ProofClassification;
  onchain_eligible: boolean;
  onchain_status: OnchainStatus;
  document_binding_commitment: string | null;
  fallback_mode: boolean;
  prover_backend: string | null;
  error: {
    code: string;
    message: string;
  } | null;
}

export interface RedactionResultMetadata {
  canonical_original_sha256: string | null;
  canonical_redacted_sha256: string | null;
  searchable_text_confirmed: boolean | null;
  source_text_mode: "direct_pdf" | "ocr_assisted" | null;
  ocr_used: boolean | null;
  ocr_engine: string | null;
  ocr_engine_version: string | null;
  ocr_layout_sha256: string | null;
  working_searchable_pdf_sha256: string | null;
  render_mode: "text_reflow" | "raster_overlay" | null;
  redaction_engine: string | null;
  redaction_engine_version: string | null;
}

export interface SessionUser {
  walletAddress: string;
  displayName: string;
}

export interface VaultFileRecord {
  id: string;
  ownerWallet: string;
  originalName: string;
  contentType: string;
  size: number;
  createdAt: string;
  sharedWith: string[];
}

export interface ShareRecord {
  id: string;
  fileId: string;
  ownerWallet: string;
  recipientWallet: string;
  createdAt: string;
  originalName: string;
}

export interface CaseRecord {
  id: string;
  title: string;
  description: string;
  createdAt: string;
}

export interface AnchorReceipt {
  txHash: string;
  network: string;
  anchoredAt: string;
  receiptType: "local-dev" | "ethereum";
}

export interface LegalDocumentRecord {
  id: string;
  caseId: string;
  fileId: string;
  ownerWallet: string;
  originalName: string;
  status: "uploaded" | "notarized" | "redaction_pending" | "redaction_failed" | "redacted" | "redacted_unverified";
  createdAt: string;
  anchorReceipt: AnchorReceipt | null;
  originalSha256: string | null;
  redactedSha256: string | null;
  canonicalOriginalSha256: string | null;
  canonicalRedactedSha256: string | null;
  searchableTextConfirmed: boolean | null;
  sourceTextMode: "direct_pdf" | "ocr_assisted" | null;
  ocrUsed: boolean | null;
  ocrEngine: string | null;
  ocrEngineVersion: string | null;
  ocrLayoutSha256: string | null;
  workingSearchablePdfSha256: string | null;
  renderMode: "text_reflow" | "raster_overlay" | null;
  redactionEngine: string | null;
  redactionEngineVersion: string | null;
  evidenceBundleId: string | null;
  sourceDocumentId: string | null;
  redactionResultId: string | null;
  zkpt: ZkptStatus | null;
}

export interface ChainOfCustodyEvent {
  id: string;
  subjectType: "file" | "document" | "bundle" | "redaction_job" | "case";
  subjectId: string;
  eventType: string;
  actorWallet: string | null;
  createdAt: string;
  summary: string;
}

export interface EvidenceBundleRecord {
  bundleId: string;
  documentId: string;
  documentOriginalName: string;
  createdAt: string;
  originalSha256: string;
  redactedSha256: string | null;
  canonicalOriginalSha256: string | null;
  canonicalRedactedSha256: string | null;
  searchableTextConfirmed: boolean | null;
  sourceTextMode: "direct_pdf" | "ocr_assisted" | null;
  ocrUsed: boolean | null;
  ocrEngine: string | null;
  ocrEngineVersion: string | null;
  ocrLayoutSha256: string | null;
  workingSearchablePdfSha256: string | null;
  renderMode: "text_reflow" | "raster_overlay" | null;
  redactionEngine: string | null;
  redactionEngineVersion: string | null;
  anchorReceipt: AnchorReceipt;
  proofBoundary: "canonical_segment_mask_v1";
  zkpt: ZkptStatus | null;
  chainOfCustody: ChainOfCustodyEvent[];
}
