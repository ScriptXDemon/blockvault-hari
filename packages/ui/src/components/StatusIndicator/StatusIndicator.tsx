import type { LegalDocumentRecord } from "@blockvault/contracts";
import { Badge } from "../Badge/Badge";

const STATUS_MAP: Record<LegalDocumentRecord["status"], { label: string; variant: "default" | "success" | "warning" | "danger"; pulse?: boolean }> = {
  uploaded:           { label: "Uploaded",           variant: "default" },
  notarized:          { label: "Notarized",           variant: "success" },
  redaction_pending:  { label: "Redaction Pending",   variant: "warning", pulse: true },
  redaction_failed:   { label: "Redaction Failed",    variant: "danger" },
  redacted:           { label: "Redacted",            variant: "success" },
  redacted_unverified:{ label: "Redacted (Unverified)", variant: "warning" },
};

export function StatusIndicator({ status }: { status: LegalDocumentRecord["status"] }) {
  const { label, variant, pulse } = STATUS_MAP[status] ?? { label: status, variant: "default" };
  return <Badge variant={variant} dot pulseDot={pulse}>{label}</Badge>;
}
