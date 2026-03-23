import type { ReactNode } from "react";
import styles from "./Timeline.module.css";

export function Timeline({ children }: { children: ReactNode }) {
  return <div className={styles.timeline}>{children}</div>;
}

export interface TimelineEntryProps {
  title: string;
  description?: string;
  timestamp?: string;
  actor?: string;
  variant?: "default" | "success" | "warning" | "danger";
}

export function TimelineEntry({ title, description, timestamp, actor, variant = "default" }: TimelineEntryProps) {
  return (
    <div className={styles.entry}>
      <div className={[styles.dot, styles[`dot--${variant}`]].join(" ")} />
      <div className={styles.content}>
        <div className={styles.header}>
          <p className={styles.title}>{title}</p>
          {timestamp && <span className={styles.timestamp}>{timestamp}</span>}
        </div>
        {actor && <div className={styles.actor}>{actor}</div>}
        {description && <p className={styles.description}>{description}</p>}
      </div>
    </div>
  );
}
