import { useState, type ReactNode } from "react";
import styles from "./Tooltip.module.css";

export function Tooltip({ content, children, position = "top" }: { content: ReactNode; children: ReactNode; position?: "top" | "bottom" | "left" | "right" }) {
  const [visible, setVisible] = useState(false);
  return (
    <span className={styles.wrapper} onMouseEnter={() => setVisible(true)} onMouseLeave={() => setVisible(false)}>
      {children}
      {visible && <span className={[styles.tip, styles[`tip--${position}`]].join(" ")}>{content}</span>}
    </span>
  );
}
