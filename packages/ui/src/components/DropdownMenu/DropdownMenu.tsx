import { useState, useRef, useEffect, type ReactNode } from "react";
import styles from "./DropdownMenu.module.css";

export interface DropdownItem {
  label: string;
  onClick: () => void;
  icon?: ReactNode;
  variant?: "default" | "danger";
  disabled?: boolean;
  divider?: boolean;
}

export interface DropdownMenuProps {
  trigger: ReactNode;
  items: DropdownItem[];
}

export function DropdownMenu({ trigger, items }: DropdownMenuProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div className={styles.wrapper} ref={ref}>
      <div onClick={() => setOpen((v) => !v)}>{trigger}</div>
      {open && (
        <div className={styles.menu}>
          {items.map((item, i) => (
            item.divider ? (
              <div key={i} className={styles.divider} />
            ) : (
              <button
                key={i}
                className={[styles.item, item.variant === "danger" ? styles["item--danger"] : ""].filter(Boolean).join(" ")}
                disabled={item.disabled}
                onClick={() => { item.onClick(); setOpen(false); }}
              >
                {item.icon}
                {item.label}
              </button>
            )
          ))}
        </div>
      )}
    </div>
  );
}
