import { apiRequest } from "@/lib/api";

const REDACTION_POLL_INTERVAL_MS = 1000;
const REDACTION_POLL_TIMEOUT_MS = 8 * 60 * 1000;

type RedactionJobSnapshot = {
  jobId: string;
  status: string;
  stage: string;
  errorCode?: string | null;
  errorMessage?: string | null;
  resultDocumentId?: string | null;
  sourceTextMode?: "direct_pdf" | "ocr_assisted" | null;
  ocrUsed?: boolean | null;
  ocrEngine?: string | null;
  ocrEngineVersion?: string | null;
  ocrLayoutSha256?: string | null;
  renderMode?: "text_reflow" | "raster_overlay" | null;
  estimatedShards?: number | null;
  predictedProofMs?: number | null;
  classification?: "single_proof_ready" | "verified_bundle_only" | "unsupported_until_v4" | null;
  onchainEligible?: boolean | null;
  onchainStatus?: "not_submitted" | "submitted" | "confirmed" | "unsupported" | "failed" | null;
  documentBindingCommitment?: string | null;
};

type RedactionResult = {
  documentId: string;
  originalSha256: string;
  redactedSha256: string;
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
  verification_passed: boolean;
  zkpt: {
    status: string;
    classification?: "single_proof_ready" | "verified_bundle_only" | "unsupported_until_v4";
    onchain_eligible?: boolean;
    onchain_status?: "not_submitted" | "submitted" | "confirmed" | "unsupported" | "failed";
    error?: {
      message: string;
    } | null;
  } | null;
};

type WaitForRedactionOptions = {
  timeoutMs?: number;
  onStatus?: (snapshot: RedactionJobSnapshot) => void;
};

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function isSessionStillActive() {
  try {
    await apiRequest<{ user: { walletAddress: string } }>("/api/auth/me");
    return true;
  } catch {
    return false;
  }
}

export async function waitForRedactionResult(jobId: string, options?: WaitForRedactionOptions) {
  const startedAt = Date.now();
  const timeoutMs = options?.timeoutMs ?? REDACTION_POLL_TIMEOUT_MS;
  let latestError: Error | null = null;
  let latestStage: string | null = null;

  while (Date.now() - startedAt < timeoutMs) {
    let snapshot: RedactionJobSnapshot;
    try {
      snapshot = await apiRequest<RedactionJobSnapshot>(`/api/v1/redactions/jobs/${jobId}`);
    } catch (error) {
      const requestError = error instanceof Error ? error : new Error("Failed to fetch redaction status.");
      latestError = requestError;
      if (/authentication required|session expired/i.test(requestError.message)) {
        if (!(await isSessionStillActive())) {
          throw new Error("Your session expired while the redaction job was running. Sign in again and retry.");
        }
      }
      await sleep(REDACTION_POLL_INTERVAL_MS);
      continue;
    }

    latestStage = snapshot.stage;
    options?.onStatus?.(snapshot);
    if (snapshot.status === "failed") {
      throw new Error(snapshot.errorMessage ?? "Redaction job failed.");
    }
    if (snapshot.status === "completed") {
      return apiRequest<RedactionResult>(`/api/v1/redactions/jobs/${jobId}/result`);
    }
    await sleep(REDACTION_POLL_INTERVAL_MS);
  }

  const stageSuffix = latestStage ? ` Current stage: ${latestStage}.` : "";
  if (latestError) {
    throw new Error(`${latestError.message}${stageSuffix}`);
  }
  throw new Error(`Timed out while waiting for the redaction job to finish.${stageSuffix}`);
}
