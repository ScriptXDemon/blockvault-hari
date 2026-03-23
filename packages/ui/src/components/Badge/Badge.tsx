import type { ReactNode } from "react";
import styles from "./Badge.module.css";

export type BadgeVariant = "default" | "success" | "warning" | "danger" | "info";

export interface BadgeProps {
  variant?: BadgeVariant;
  size?: "sm" | "md";
  dot?: boolean;
  pulseDot?: boolean;
  children: ReactNode;
}

export function Badge({ variant = "default", size = "md", dot, pulseDot, children }: BadgeProps) {
  return (
    <span className={[styles.badge, styles[`badge--${variant}`], size === "sm" ? styles["badge--sm"] : ""].filter(Boolean).join(" ")}>
      {(dot || pulseDot) && <span className={[styles.dot, pulseDot ? styles["dot--pulse"] : ""].filter(Boolean).join(" ")} />}
      {children}
    </span>
  );
}
