import { type ReactNode, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Sidebar, Button } from "@blockvault/ui";
import { buildMeta } from "@/lib/buildMeta";
import { fetchRuntimeStatus, getZkptRuntimeBanner } from "@/lib/runtime";
import { useAuth } from "@/state/AuthContext";
import { truncateWallet } from "@/lib/formatters";
import styles from "./AppShell.module.css";

const NAV_ITEMS = [
  {
    to: "/app/vault",
    label: "Vault",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
      </svg>
    ),
  },
  {
    to: "/app/cases",
    label: "Cases",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/>
      </svg>
    ),
  },
  {
    to: "/app/documents",
    label: "Documents",
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>
        <line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>
      </svg>
    ),
  },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const [collapsed, setCollapsed] = useState(false);

  const runtimeQuery = useQuery({
    queryKey: ["runtime-status"],
    queryFn: fetchRuntimeStatus,
    staleTime: 30_000,
  });
  const runtimeBanner = runtimeQuery.data ? getZkptRuntimeBanner(runtimeQuery.data) : null;

  return (
    <div className={styles.frame}>
      <Sidebar
        items={NAV_ITEMS}
        walletDisplay={user ? truncateWallet(user.walletAddress) : undefined}
        collapsed={collapsed}
        bottomActions={
          <div className={styles.bottomMeta}>
            <Button variant="secondary" size="sm" fullWidth onClick={() => void logout()}>
              {collapsed ? (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>
                </svg>
              ) : "Logout"}
            </Button>
            {!collapsed && (
              <div
                className={styles.buildStamp}
                data-testid="build-id"
                title={`Commit ${buildMeta.gitSha} · source ${buildMeta.sourceHash} · built ${buildMeta.builtAt}`}
              >
                Build {buildMeta.buildId}
              </div>
            )}
          </div>
        }
      />

      <div className={styles.content}>
        {runtimeBanner && (
          <div className={[styles.banner, styles[`banner--${runtimeBanner.tone}`]].join(" ")}>
            <strong>{runtimeBanner.summary}</strong>
            {runtimeBanner.detail && <span>{runtimeBanner.detail}</span>}
          </div>
        )}
        <main className={styles.main}>
          {children}
        </main>
      </div>

      <button
        className={styles.collapseBtn}
        onClick={() => setCollapsed((v) => !v)}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        style={{ left: collapsed ? "calc(var(--sidebar-collapsed-width) - 12px)" : "calc(var(--sidebar-width) - 12px)" }}
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
          {collapsed ? <polyline points="4,2 8,6 4,10" /> : <polyline points="8,2 4,6 8,10" />}
        </svg>
      </button>
    </div>
  );
}
