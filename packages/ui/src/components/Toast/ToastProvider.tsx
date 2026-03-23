import { createPortal } from "react-dom";
import { useState, useCallback, type ReactNode } from "react";
import { ToastContext, type ToastItem, type ToastVariant } from "./useToast";
import styles from "./Toast.module.css";

function genId() { return Math.random().toString(36).slice(2); }

function ToastIcon({ variant }: { variant: ToastVariant }) {
  const cls = `${styles.icon} ${styles[`icon--${variant}`]}`;
  if (variant === "success") return (
    <div className={cls}>
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="2,6 5,9 10,3" />
      </svg>
    </div>
  );
  if (variant === "error") return (
    <div className={cls}>
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
        <line x1="2" y1="2" x2="10" y2="10" /><line x1="10" y1="2" x2="2" y2="10" />
      </svg>
    </div>
  );
  if (variant === "warning") return (
    <div className={cls}>
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
        <line x1="6" y1="2" x2="6" y2="7" /><circle cx="6" cy="10" r="0.5" fill="currentColor"/>
      </svg>
    </div>
  );
  return (
    <div className={cls}>
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
        <circle cx="6" cy="6" r="5"/><line x1="6" y1="4" x2="6" y2="6"/><circle cx="6" cy="8.5" r="0.5" fill="currentColor"/>
      </svg>
    </div>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const remove = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const add = useCallback((message: string, variant: ToastVariant) => {
    const id = genId();
    setToasts((prev) => [...prev, { id, message, variant }]);
    setTimeout(() => remove(id), 5200);
  }, [remove]);

  const ctx = {
    success: (m: string) => add(m, "success"),
    error: (m: string) => add(m, "error"),
    warning: (m: string) => add(m, "warning"),
    info: (m: string) => add(m, "info"),
  };

  return (
    <ToastContext.Provider value={ctx}>
      {children}
      {createPortal(
        <div className={styles.container}>
          {toasts.map((t) => (
            <div key={t.id} className={`${styles.toast} ${styles[`toast--${t.variant}`]}`}>
              <ToastIcon variant={t.variant} />
              <div className={styles.content}>
                <p className={styles.message}>{t.message}</p>
                <div className={styles.progress}>
                  <div className={styles.progressBar} />
                </div>
              </div>
              <button className={styles.closeBtn} onClick={() => remove(t.id)} aria-label="Dismiss">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <line x1="1" y1="1" x2="13" y2="13" /><line x1="13" y1="1" x2="1" y2="13" />
                </svg>
              </button>
            </div>
          ))}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}
