import type { LegalDocumentRecord } from "@blockvault/contracts";
import styles from "./DocumentLifecycleStepper.module.css";

const STEPS = [
  { id: "upload",    label: "Uploaded",   statuses: ["uploaded", "notarized", "redaction_pending", "redaction_failed", "redacted", "redacted_unverified"] as LegalDocumentRecord["status"][] },
  { id: "notarize",  label: "Notarized",  statuses: ["notarized", "redaction_pending", "redaction_failed", "redacted", "redacted_unverified"] as LegalDocumentRecord["status"][] },
  { id: "redact",    label: "Redacted",   statuses: ["redacted", "redacted_unverified"] as LegalDocumentRecord["status"][] },
  { id: "export",    label: "Evidence",   statuses: [] as LegalDocumentRecord["status"][], checkBundle: true },
] as const;

function getStepState(stepIndex: number, status: LegalDocumentRecord["status"], hasBundle: boolean): "completed" | "current" | "pending" | "failed" {
  const step = STEPS[stepIndex];
  if (step.id === "export") {
    return hasBundle ? "completed" : (["redacted", "redacted_unverified"].includes(status) ? "current" : "pending");
  }
  if (step.statuses.includes(status)) return "completed";
  if (step.id === "redact" && (status === "redaction_pending" || status === "redaction_failed")) {
    return status === "redaction_failed" ? "failed" : "current";
  }
  if (step.id === "notarize" && status === "uploaded") return "current";
  return "pending";
}

export function DocumentLifecycleStepper({ status, hasBundle }: { status: LegalDocumentRecord["status"]; hasBundle?: boolean }) {
  return (
    <div className={styles.stepper}>
      {STEPS.map((step, i) => {
        const state = getStepState(i, status, !!hasBundle);
        return (
          <div key={step.id} className={[styles.step, styles[`step--${state}`]].join(" ")}>
            <div className={styles.circle}>
              {state === "completed" ? (
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="2,7 5.5,10.5 12,3" />
                </svg>
              ) : state === "failed" ? (
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                  <line x1="2" y1="2" x2="10" y2="10"/><line x1="10" y1="2" x2="2" y2="10"/>
                </svg>
              ) : (
                <span className={styles.stepNum}>{i + 1}</span>
              )}
            </div>
            <span className={styles.label}>{step.label}</span>
            {i < STEPS.length - 1 && <div className={[styles.connector, state === "completed" ? styles["connector--done"] : ""].join(" ")} />}
          </div>
        );
      })}
    </div>
  );
}
