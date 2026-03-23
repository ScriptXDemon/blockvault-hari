import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";

import { type EvidenceBundleRecord } from "@blockvault/contracts";
import { Badge, Breadcrumb, Button, Card, CopyButton, Timeline, TimelineEntry, useToast } from "@blockvault/ui";

import { PageHeader } from "@/components/PageHeader";
import { apiBinary, apiRequest } from "@/lib/api";
import { formatDate, truncateHash, truncateWallet } from "@/lib/formatters";
import styles from "./EvidencePage.module.css";

function custodyVariant(eventType: string): "success" | "warning" | "danger" | "default" {
  if (eventType.includes("notariz") || eventType.includes("upload")) return "success";
  if (eventType.includes("redact")) return "warning";
  if (eventType.includes("fail") || eventType.includes("error")) return "danger";
  return "default";
}

export function EvidencePage() {
  const { bundleId = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();

  const bundleQuery = useQuery({
    queryKey: ["evidence-bundle", bundleId],
    queryFn: () => apiRequest<EvidenceBundleRecord>(`/api/v1/evidence/${bundleId}`),
  });

  const bundle = bundleQuery.data;

  async function downloadZip() {
    try {
      const response = await apiBinary(`/api/v1/evidence/${bundleId}/export`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `evidence-${bundleId}.zip`;
      link.click();
      URL.revokeObjectURL(url);
      toast.success("Evidence bundle downloaded.");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  async function downloadJson() {
    try {
      const data = await apiRequest<EvidenceBundleRecord>(`/api/v1/evidence/${bundleId}`);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `evidence-${bundleId}.json`;
      link.click();
      URL.revokeObjectURL(url);
      toast.success("Evidence JSON downloaded.");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div>
      <Breadcrumb items={[
        { label: "Documents", to: "/app/documents" },
        { label: bundle?.documentOriginalName ?? "Evidence Bundle" },
      ]} />

      <PageHeader
        eyebrow="Evidence Bundle"
        title={bundle?.documentOriginalName ?? `Bundle ${bundleId}`}
        description="Anchor receipts, manifest data, and document hash linkage for downstream verification."
        actions={
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            {bundle?.documentId && (
              <Button variant="secondary" size="sm" onClick={() => navigate(`/app/documents/${bundle.documentId}`)}>
                Source document
              </Button>
            )}
            <Button variant="secondary" size="sm" onClick={() => void downloadJson()}>Export JSON</Button>
            <Button size="sm" onClick={() => void downloadZip()}>Download ZIP</Button>
          </div>
        }
      />

      <div className={styles.twoCol}>
        {/* Bundle Summary */}
        <Card>
          <h3 className={styles.cardTitle}>Bundle Summary</h3>
          <dl className={styles.detailList}>
            <div>
              <dt>Bundle ID</dt>
              <dd className={styles.hashRow}>
                <span className={styles.mono}>{truncateHash(bundleId, 16)}</span>
                <CopyButton value={bundleId} />
              </dd>
            </div>
            <div>
              <dt>Document</dt>
              <dd>{bundle?.documentOriginalName ?? "\u2014"}</dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>{bundle?.createdAt ? formatDate(bundle.createdAt) : "\u2014"}</dd>
            </div>
            <div>
              <dt>Proof boundary</dt>
              <dd className={styles.mono}>{bundle?.proofBoundary ?? "canonical_segment_mask_v1"}</dd>
            </div>
            {bundle?.redactionEngine && (
              <div>
                <dt>Redaction engine</dt>
                <dd className={styles.mono}>{bundle.redactionEngine}{bundle.redactionEngineVersion ? ` v${bundle.redactionEngineVersion}` : ""}</dd>
              </div>
            )}
            {bundle?.searchableTextConfirmed !== null && bundle?.searchableTextConfirmed !== undefined && (
              <div>
                <dt>Searchable text confirmed</dt>
                <dd>
                  <Badge variant={bundle.searchableTextConfirmed ? "success" : "warning"} size="sm">
                    {bundle.searchableTextConfirmed ? "Yes" : "No"}
                  </Badge>
                </dd>
              </div>
            )}
          </dl>
        </Card>

        {/* Hash Verification */}
        <Card>
          <h3 className={styles.cardTitle}>Hash Verification</h3>
          <dl className={styles.detailList}>
            <div>
              <dt>Original SHA-256</dt>
              <dd className={styles.hashRow}>
                {bundle?.originalSha256 ? (
                  <>
                    <span className={styles.mono}>{truncateHash(bundle.originalSha256)}</span>
                    <CopyButton value={bundle.originalSha256} />
                  </>
                ) : <span style={{ color: "var(--bv-ink-faint)" }}>\u2014</span>}
              </dd>
            </div>
            <div>
              <dt>Canonical original</dt>
              <dd className={styles.hashRow}>
                {bundle?.canonicalOriginalSha256 ? (
                  <>
                    <span className={styles.mono}>{truncateHash(bundle.canonicalOriginalSha256)}</span>
                    <CopyButton value={bundle.canonicalOriginalSha256} />
                  </>
                ) : <span style={{ color: "var(--bv-ink-faint)" }}>\u2014</span>}
              </dd>
            </div>
            <div>
              <dt>Redacted SHA-256</dt>
              <dd className={styles.hashRow}>
                {bundle?.redactedSha256 ? (
                  <>
                    <span className={styles.mono}>{truncateHash(bundle.redactedSha256)}</span>
                    <CopyButton value={bundle.redactedSha256} />
                  </>
                ) : <span style={{ color: "var(--bv-ink-faint)" }}>No redaction recorded</span>}
              </dd>
            </div>
            <div>
              <dt>Canonical redacted</dt>
              <dd className={styles.hashRow}>
                {bundle?.canonicalRedactedSha256 ? (
                  <>
                    <span className={styles.mono}>{truncateHash(bundle.canonicalRedactedSha256)}</span>
                    <CopyButton value={bundle.canonicalRedactedSha256} />
                  </>
                ) : <span style={{ color: "var(--bv-ink-faint)" }}>\u2014</span>}
              </dd>
            </div>
          </dl>
        </Card>
      </div>

      {/* Anchor Receipt */}
      <Card style={{ marginTop: "var(--bv-space-4)" }}>
        <div className={styles.receiptHeader}>
          <h3 className={styles.cardTitle} style={{ margin: 0 }}>Anchor Receipt</h3>
          {bundle?.anchorReceipt?.receiptType && (
            <Badge variant={bundle.anchorReceipt.receiptType === "ethereum" ? "success" : "default"} size="sm">
              {bundle.anchorReceipt.receiptType === "ethereum" ? "Ethereum" : "Local Dev"}
            </Badge>
          )}
        </div>
        {bundle?.anchorReceipt ? (
          <dl className={styles.detailList}>
            <div>
              <dt>Transaction hash</dt>
              <dd className={styles.hashRow}>
                <span className={styles.mono}>{truncateHash(bundle.anchorReceipt.txHash, 16)}</span>
                <CopyButton value={bundle.anchorReceipt.txHash} />
              </dd>
            </div>
            <div>
              <dt>Network</dt>
              <dd className={styles.mono}>{bundle.anchorReceipt.network}</dd>
            </div>
            <div>
              <dt>Anchored at</dt>
              <dd>{formatDate(bundle.anchorReceipt.anchoredAt)}</dd>
            </div>
          </dl>
        ) : (
          <p style={{ color: "var(--bv-ink-muted)", fontSize: "var(--bv-text-sm)", margin: 0 }}>Anchor receipt not available.</p>
        )}
      </Card>

      {/* Chain of Custody */}
      <Card style={{ marginTop: "var(--bv-space-4)" }}>
        <h3 className={styles.cardTitle}>Chain of Custody</h3>
        {bundle?.chainOfCustody?.length ? (
          <Timeline>
            {bundle.chainOfCustody.map((event) => (
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
          <p style={{ color: "var(--bv-ink-muted)", fontSize: "var(--bv-text-sm)", margin: 0 }}>No custody events recorded for this bundle.</p>
        )}
      </Card>
    </div>
  );
}
