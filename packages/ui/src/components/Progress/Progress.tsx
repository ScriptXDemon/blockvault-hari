import styles from "./Progress.module.css";

export interface ProgressProps {
  value?: number;
  indeterminate?: boolean;
  label?: string;
}

export function Progress({ value, indeterminate = false, label }: ProgressProps) {
  const pct = value != null ? Math.max(0, Math.min(100, value)) : undefined;
  return (
    <div className={styles.wrapper}>
      {label && (
        <div className={styles.label}>
          <span>{label}</span>
          {pct != null && !indeterminate && <span>{pct}%</span>}
        </div>
      )}
      <div className={styles.track}>
        <div
          className={[styles.bar, indeterminate ? styles["bar--indeterminate"] : ""].filter(Boolean).join(" ")}
          style={{ width: pct != null && !indeterminate ? `${pct}%` : undefined }}
        />
      </div>
    </div>
  );
}
