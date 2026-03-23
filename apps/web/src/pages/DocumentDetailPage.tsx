import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";

import { type ChainOfCustodyEvent, type ZkptStatus, type LegalDocumentRecord } from "@blockvault/contracts";
import {
  Button, Card, Breadcrumb, StatusIndicator, Badge, CopyButton,
  Input, Progress, Timeline, TimelineEntry, useToast, Modal, ModalBody, ModalFooter,
} from "@blockvault/ui";

import { PageHeader } from "@/components/PageHeader";
import { DocumentLifecycleStepper } from "@/components/DocumentLifecycleStepper";
import { queryClient } from "@/app/queryClient";
import { apiBinary, apiRequest } from "@/lib/api";
import { decryptBlob, downloadBlob } from "@/lib/crypto";
import { waitForRedactionResult } from "@/lib/redactions";
import { fetchRuntimeStatus, getRedactionPollingTimeoutMs, getZkptRuntimeBanner } from "@/lib/runtime";
import { formatDate, truncateHash, truncateWallet } from "@/lib/formatters";
import styles from "./DocumentDetailPage.module.css";

type DocumentDetailRecord = LegalDocumentRecord & {
  chainOfCustody: ChainOfCustodyEvent[];
};

const DEFAULT_ZKPT: ZkptStatus = {
  mode: "authoritative", status: "unsupported", bundle_id: null, artifact_version: null,
  profile_id: null, profile_class: null, proof_boundary: "canonical_segment_mask_v1",
  verified_shards: 0, total_shards: 0, estimated_shards: 0, predicted_proof_ms: null,
  classification: "verified_bundle_only", onchain_eligible: false, onchain_status: "unsupported",
  document_binding_commitment: null, fallback_mode: false, prover_backend: null, error: null,
};

function zkptVariant(status: ZkptStatus["status"]): "success" | "warning" | "danger" {
  if (status === "verified") return "success";
  if (status === "unsupported") return "warning";
  return "danger";
}

function ShieldIcon({ variant }: { variant: "success" | "warning" | "danger" }) {
  const colors = { success: "var(--bv-accent)", warning: "var(--bv-highlight)", danger: "var(--bv-danger)" };
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={colors[variant]} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      {variant === "success" && <polyline points="9 12 11 14 15 10" />}
    </svg>
  );
}

function custodyVariant(eventType: string): "success" | "warning" | "danger" | "default" {
  if (eventType.includes("notariz") || eventType.includes("upload")) return "success";
  if (eventType.includes("redact")) return "warning";
  if (eventType.includes("fail") || eventType.includes("error")) return "danger";
  return "default";
}

function formatStageLabel(stage: string | null) {
  if (!stage) {
    return "queued";
  }
  return stage.replaceAll("_", " ");
}

function formatProofClassification(classification: ZkptStatus["classification"]) {
  if (classification === "single_proof_ready") {
    return "Direct on-chain eligible";
  }
  if (classification === "unsupported_until_v4") {
    return "Unsupported until sparse-proof upgrade";
  }
  return "Verified bundle only";
}

function formatOnchainStatus(status: ZkptStatus["onchain_status"]) {
  if (status === "confirmed") return "Verified on-chain";
  if (status === "submitted") return "On-chain pending";
  if (status === "failed") return "On-chain failed";
  if (status === "not_submitted") return "Not submitted on-chain";
  return "Not eligible on-chain";
}

export function DocumentDetailPage() {
  const { documentId = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [passphrase, setPassphrase] = useState("");
  const [termInput, setTermInput] = useState("");
  const [terms, setTerms] = useState<string[]>([]);
  const [redactionStage, setRedactionStage] = useState<string | null>(null);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [showRawZkpt, setShowRawZkpt] = useState(false);

  const documentQuery = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => apiRequest<DocumentDetailRecord>(`/api/v1/documents/${documentId}`),
  });
  const runtimeQuery = useQuery({ queryKey: ["runtime-status"], queryFn: fetchRuntimeStatus, staleTime: 30_000 });

  const notarizeMutation = useMutation({
    mutationFn: async () => {
      if (!passphrase) throw new Error("Enter the document passphrase before notarizing.");
      await apiRequest(`/api/v1/documents/${documentId}/notarize`, { method: "POST", body: JSON.stringify({ passphrase }) });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["document", documentId] });
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      toast.success("Document notarized and linked to a fresh evidence bundle.");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const redactionMutation = useMutation({
    mutationFn: async () => {
      if (!passphrase) throw new Error("Enter the document passphrase before starting redaction.");
      const allTerms = [...terms];
      if (termInput.trim()) allTerms.push(termInput.trim());
      if (!allTerms.length) throw new Error("Add at least one redaction term.");
      const job = await apiRequest<{ jobId: string }>("/api/v1/redactions/jobs", {
        method: "POST",
        body: JSON.stringify({ documentId, passphrase, searchTerms: allTerms }),
      });
      setRedactionStage("queued");
      return waitForRedactionResult(job.jobId, {
        timeoutMs: getRedactionPollingTimeoutMs(runtimeQuery.data),
        onStatus: (snapshot) => setRedactionStage(snapshot.stage),
      });
    },
    onSuccess: async (result) => {
      setRedactionStage(null);
      await queryClient.invalidateQueries({ queryKey: ["document", documentId] });
      await queryClient.invalidateQueries({ queryKey: ["document", result.documentId] });
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      const msg = result.zkpt?.status === "verified"
        ? "Redaction completed with authoritative verification."
        : result.zkpt?.error?.message ?? "Redaction completed.";
      toast.success(msg);
      navigate(`/app/documents/${result.documentId}`);
    },
    onError: (e: Error) => {
      setRedactionStage(null);
      toast.error(e.message);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => apiRequest(`/api/v1/documents/${documentId}`, { method: "DELETE" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      toast.success("Document deleted.");
      navigate(doc?.caseId ? `/app/cases/${doc.caseId}` : "/app/documents");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const onchainMutation = useMutation({
    mutationFn: async () => {
      if (!zkpt.bundle_id) {
        throw new Error("No verified bundle is available for on-chain submission.");
      }
      return apiRequest<{ status: string; onchain: { txHash?: string | null } }>(`/api/v1/zkpt/bundles/${zkpt.bundle_id}/submit-onchain`, {
        method: "POST",
      });
    },
    onSuccess: async (payload) => {
      await queryClient.invalidateQueries({ queryKey: ["document", documentId] });
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      toast.success(
        payload.status === "confirmed"
          ? "Bundle verified and confirmed on-chain."
          : "Bundle submitted to the on-chain verifier.",
      );
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const downloadMutation = useMutation({
    mutationFn: async () => {
      const response = await apiBinary(`/api/v1/documents/${documentId}/download`);
      const encryptedSalt = response.headers.get("X-BlockVault-Salt");
      if (encryptedSalt) {
        if (!passphrase) throw new Error("Enter the document passphrase before downloading.");
        const decrypted = await decryptBlob(await response.blob(), passphrase, encryptedSalt, response.headers.get("X-BlockVault-Iv") ?? "");
        downloadBlob(decrypted, response.headers.get("X-BlockVault-Original-Name") ?? "document.pdf");
        return;
      }
      const blob = await response.blob();
      const cd = response.headers.get("Content-Disposition") ?? "";
      const match = /filename="?([^"]+)"?/i.exec(cd);
      downloadBlob(blob, match?.[1] ?? doc?.originalName ?? "document.pdf");
    },
    onSuccess: () => toast.success("Document download prepared."),
    onError: (e: Error) => toast.error(e.message),
  });

  const doc = documentQuery.data;
  const isDerived = Boolean(doc?.sourceDocumentId);
  const zkpt = doc?.zkpt ?? DEFAULT_ZKPT;
  const zkptJson = useMemo(() => JSON.stringify(doc?.zkpt ?? DEFAULT_ZKPT, null, 2), [doc?.zkpt]);
  const runtimeBanner = runtimeQuery.data ? getZkptRuntimeBanner(runtimeQuery.data) : null;

  function addTerm() {
    const t = termInput.trim();
    if (t && !terms.includes(t)) { setTerms((prev) => [...prev, t]); }
    setTermInput("");
  }

  return (
    <div>
      <Breadcrumb items={[
        ...(doc?.caseId ? [{ label: "Cases", to: "/app/cases" }, { label: "Case", to: `/app/cases/${doc.caseId}` }] : [{ label: "Documents", to: "/app/documents" }]),
        { label: doc?.originalName ?? "Document" },
      ]} />

      <PageHeader
        title={doc?.originalName ?? "Loading..."}
        description="Notarization, redaction, evidence handoff, and chain-of-custody timeline."
        actions={
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            {doc?.status && <StatusIndicator status={doc.status} />}
            <Button variant="secondary" size="sm" onClick={() => void downloadMutation.mutateAsync()} disabled={downloadMutation.isPending}>
              {downloadMutation.isPending ? "Preparing..." : "Download"}
            </Button>
            {doc?.evidenceBundleId && (
              <Button variant="secondary" size="sm" onClick={() => navigate(`/app/evidence/${doc.evidenceBundleId}`)}>
                Evidence
              </Button>
            )}
            <Button variant="danger" size="sm" onClick={() => setDeleteConfirmOpen(true)}>Delete</Button>
          </div>
        }
      />

      {doc?.status && (
        <DocumentLifecycleStepper status={doc.status} hasBundle={!!doc.evidenceBundleId} />
      )}

      <div className={styles.twoCol}>
        {/* Left column */}
        <div className={styles.stack}>
          <Card>
            <h3 className={styles.cardTitle}>Document State</h3>
            <dl className={styles.detailList}>
              <div>
                <dt>Created</dt>
                <dd>{doc?.createdAt ? formatDate(doc.createdAt) : "\u2014"}</dd>
              </div>
              {doc?.originalSha256 && (
                <div>
                  <dt>Original SHA-256</dt>
                  <dd className={styles.hashRow}>
                    <span className={styles.mono}>{truncateHash(doc.originalSha256)}</span>
                    <CopyButton value={doc.originalSha256} />
                  </dd>
                </div>
              )}
              {doc?.redactedSha256 && (
                <div>
                  <dt>Redacted SHA-256</dt>
                  <dd className={styles.hashRow}>
                    <span className={styles.mono}>{truncateHash(doc.redactedSha256)}</span>
                    <CopyButton value={doc.redactedSha256} />
                  </dd>
                </div>
              )}
              {doc?.anchorReceipt?.txHash && (
                <div>
                  <dt>Anchor receipt</dt>
                  <dd className={styles.hashRow}>
                    <span className={styles.mono}>{truncateHash(doc.anchorReceipt.txHash)}</span>
                    <CopyButton value={doc.anchorReceipt.txHash} />
                  </dd>
                </div>
              )}
              <div>
                <dt>Proof boundary</dt>
                <dd>canonical_segment_mask_v1</dd>
              </div>
              {doc?.sourceTextMode && (
                <div>
                  <dt>Source text mode</dt>
                  <dd>{doc.sourceTextMode === "ocr_assisted" ? "OCR assisted" : "Direct PDF text"}</dd>
                </div>
              )}
              {doc?.renderMode && (
                <div>
                  <dt>Render mode</dt>
                  <dd>{doc.renderMode === "raster_overlay" ? "Raster overlay" : "Text reflow"}</dd>
                </div>
              )}
              {typeof doc?.ocrUsed === "boolean" && (
                <div>
                  <dt>OCR used</dt>
                  <dd>{doc.ocrUsed ? "Yes" : "No"}</dd>
                </div>
              )}
              {doc?.ocrEngine && (
                <div>
                  <dt>OCR engine</dt>
                  <dd className={styles.mono}>
                    {doc.ocrEngine}{doc.ocrEngineVersion ? ` ${doc.ocrEngineVersion}` : ""}
                  </dd>
                </div>
              )}
              {doc?.sourceDocumentId && (
                <div>
                  <dt>Source document</dt>
                  <dd>
                    <Button variant="ghost" size="sm" onClick={() => navigate(`/app/documents/${doc.sourceDocumentId}`)}>
                      View source
                    </Button>
                  </dd>
                </div>
              )}
            </dl>
          </Card>

          <Card>
            <div className={styles.zkptHeader}>
              <ShieldIcon variant={zkptVariant(zkpt.status)} />
              <div>
                <h3 className={styles.cardTitle} style={{ margin: 0 }}>ZKPT Verification</h3>
                <Badge variant={zkptVariant(zkpt.status)} size="sm" dot>
                  {zkpt.status === "verified" ? "Verified" : zkpt.status === "unsupported" ? "Unsupported" : "Failed"}
                </Badge>
              </div>
            </div>
            <dl className={styles.detailList}>
              {zkpt.profile_id && <div><dt>Profile</dt><dd className={styles.mono}>{zkpt.profile_id}</dd></div>}
              <div><dt>Verification mode</dt><dd>{formatProofClassification(zkpt.classification)}</dd></div>
              {zkpt.profile_class && <div><dt>Profile class</dt><dd>{zkpt.profile_class}</dd></div>}
              {zkpt.prover_backend && <div><dt>Prover backend</dt><dd className={styles.mono}>{zkpt.prover_backend}</dd></div>}
              {zkpt.artifact_version && <div><dt>Artifact version</dt><dd className={styles.mono}>{zkpt.artifact_version}</dd></div>}
              {zkpt.total_shards > 0 && (
                <div>
                  <dt>Shards</dt>
                  <dd>{zkpt.verified_shards}/{zkpt.total_shards} verified</dd>
                </div>
              )}
              {zkpt.predicted_proof_ms !== null && (
                <div>
                  <dt>Predicted proof time</dt>
                  <dd>{Math.round(zkpt.predicted_proof_ms / 1000)}s</dd>
                </div>
              )}
              <div>
                <dt>On-chain status</dt>
                <dd>{formatOnchainStatus(zkpt.onchain_status)}</dd>
              </div>
              {zkpt.document_binding_commitment && (
                <div>
                  <dt>Binding commitment</dt>
                  <dd className={styles.hashRow}>
                    <span className={styles.mono}>{truncateHash(zkpt.document_binding_commitment)}</span>
                    <CopyButton value={zkpt.document_binding_commitment} />
                  </dd>
                </div>
              )}
              {zkpt.error && <div><dt>Error</dt><dd style={{ color: "var(--bv-danger)", fontSize: "var(--bv-text-sm)" }}>{zkpt.error.message}</dd></div>}
            </dl>
            {zkpt.status === "verified" && zkpt.bundle_id && (
              <div className={styles.actionGroup} style={{ marginTop: "16px" }}>
                <p className={styles.groupHint} style={{ margin: 0 }}>
                  {zkpt.onchain_eligible
                    ? "This proof fits the first on-chain verifier release and can be submitted directly."
                    : "This bundle remains exportable and verified off-chain, but the first on-chain release accepts single-proof bundles only."}
                </p>
                {zkpt.onchain_eligible && zkpt.onchain_status !== "confirmed" && (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => void onchainMutation.mutateAsync()}
                    disabled={onchainMutation.isPending}
                  >
                    {onchainMutation.isPending ? "Submitting..." : "Submit On-Chain"}
                  </Button>
                )}
              </div>
            )}
            <button className={styles.toggleBtn} onClick={() => setShowRawZkpt((v) => !v)}>
              {showRawZkpt ? "Hide" : "Show"} raw JSON
            </button>
            {showRawZkpt && <pre className={styles.jsonPreview}>{zkptJson}</pre>}
          </Card>
        </div>

        {/* Right column — Action workspace */}
        {!isDerived && (
          <Card>
            <h3 className={styles.cardTitle}>Action Workspace</h3>

            {runtimeBanner && (
              <div className={[styles.banner, styles[`banner--${runtimeBanner.tone}`]].join(" ")} style={{ marginBottom: "16px" }}>
                <strong>{runtimeBanner.summary}</strong>
                {runtimeBanner.detail && <span>{" — "}{runtimeBanner.detail}</span>}
              </div>
            )}

            <div className={styles.actionForm}>
              <Input
                label="Document passphrase"
                type="password"
                value={passphrase}
                onChange={(e) => setPassphrase(e.target.value)}
                placeholder="Required to decrypt the original upload"
                hint="Used for both notarize and redact operations."
              />

              <div className={styles.actionBtn}>
                <Button
                  fullWidth
                  onClick={() => void notarizeMutation.mutateAsync()}
                  disabled={notarizeMutation.isPending || !passphrase}
                >
                  {notarizeMutation.isPending ? "Notarizing..." : "Notarize Document"}
                </Button>
              </div>

              <div className={styles.divider} />

              <div className={styles.termsSection}>
                <label className={styles.fieldLabel}>Redaction terms</label>
                <div className={styles.termInput}>
                  <input
                    className={styles.termField}
                    value={termInput}
                    onChange={(e) => setTermInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTerm(); } }}
                    placeholder="Type a term and press Enter..."
                  />
                  <Button variant="secondary" size="sm" onClick={addTerm} disabled={!termInput.trim()}>Add</Button>
                </div>
                {terms.length > 0 && (
                  <div className={styles.termChips}>
                    {terms.map((t) => (
                      <span key={t} className={styles.termChip}>
                        {t}
                        <button className={styles.termRemove} onClick={() => setTerms((prev) => prev.filter((x) => x !== t))}>
                          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                            <line x1="1" y1="1" x2="9" y2="9"/><line x1="9" y1="1" x2="1" y2="9"/>
                          </svg>
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {redactionMutation.isPending && (
                <>
                  <Progress indeterminate label={`Generating ZKPT proof: ${formatStageLabel(redactionStage)}...`} />
                  <p style={{ fontSize: "var(--bv-text-xs)", color: "var(--bv-ink-muted)", margin: 0 }}>
                    Current stage: {formatStageLabel(redactionStage)}.
                  </p>
                </>
              )}

              <div className={styles.actionBtn}>
                <Button
                  variant="secondary"
                  fullWidth
                  onClick={() => void redactionMutation.mutateAsync()}
                  disabled={redactionMutation.isPending || !passphrase || (terms.length === 0 && !termInput.trim())}
                >
                  {redactionMutation.isPending ? "Redacting..." : "Create Redaction"}
                </Button>
              </div>

              <p style={{ fontSize: "var(--bv-text-xs)", color: "var(--bv-ink-muted)", margin: 0 }}>
                Searchable PDFs use direct text redaction. Scanned or image-only PDFs are OCR-processed automatically and then redacted with the same authoritative proof boundary.
              </p>
              <p style={{ fontSize: "var(--bv-text-xs)", color: "var(--bv-ink-muted)", margin: 0 }}>
                Current policy: single-proof jobs under the runtime budget are direct on-chain candidates; multi-shard jobs remain verified bundle only until the sparse-proof upgrade lands.
              </p>
            </div>
          </Card>
        )}
      </div>

      <Card style={{ marginTop: "24px" }}>
        <h3 className={styles.cardTitle}>Chain of Custody</h3>
        {doc?.chainOfCustody?.length ? (
          <Timeline>
            {doc.chainOfCustody.map((event) => (
              <TimelineEntry
                key={event.id}
                title={event.summary}
                description={event.eventType}
                timestamp={formatDate(event.createdAt)}
                actor={event.actorWallet ? truncateWallet(event.actorWallet) : undefined}
                variant={custodyVariant(event.eventType)}
              />
            ))}
          </Timeline>
        ) : (
          <p style={{ color: "var(--bv-ink-muted)", fontSize: "var(--bv-text-sm)" }}>No custody events recorded yet.</p>
        )}
      </Card>

      {/* Delete confirmation modal */}
      <Modal open={deleteConfirmOpen} onClose={() => setDeleteConfirmOpen(false)} title="Delete Document?" size="sm">
        <ModalBody>
          <p style={{ margin: 0, color: "var(--bv-ink-muted)" }}>
            This will permanently delete <strong>{doc?.originalName}</strong> and all associated records. This action cannot be undone.
          </p>
        </ModalBody>
        <ModalFooter>
          <Button variant="secondary" onClick={() => setDeleteConfirmOpen(false)}>Cancel</Button>
          <Button variant="danger" disabled={deleteMutation.isPending} onClick={() => void deleteMutation.mutateAsync()}>
            {deleteMutation.isPending ? "Deleting..." : "Delete permanently"}
          </Button>
        </ModalFooter>
      </Modal>
    </div>
  );
}
