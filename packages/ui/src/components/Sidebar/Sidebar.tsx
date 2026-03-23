import { type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import styles from "./Sidebar.module.css";

export interface SidebarItemDef {
  icon: ReactNode;
  label: string;
  to: string;
}

export interface SidebarProps {
  items: SidebarItemDef[];
  walletDisplay?: string;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  bottomActions?: ReactNode;
}

export function Sidebar({ items, walletDisplay, collapsed = false, onToggleCollapse, bottomActions }: SidebarProps) {
  return (
    <aside className={[styles.sidebar, collapsed ? styles["sidebar--collapsed"] : ""].filter(Boolean).join(" ")}>
      <div className={styles.brand}>
        <div className={styles.brandMark}>
          <div className={styles.brandIcon}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            </svg>
          </div>
          {!collapsed && (
            <div className={styles.brandText}>
              <div className={styles.brandName}>BlockVault</div>
              <div className={styles.brandVersion}>Legal Evidence Platform</div>
            </div>
          )}
        </div>
      </div>

      <nav className={styles.nav}>
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => [styles.navItem, isActive ? styles.active : ""].filter(Boolean).join(" ")}
          >
            <span className={styles.navIcon}>{item.icon}</span>
            {!collapsed && <span className={styles.navText}>{item.label}</span>}
          </NavLink>
        ))}
      </nav>

      <div className={styles.bottom}>
        {walletDisplay && !collapsed && (
          <div className={styles.walletChip}>
            <span className={styles.walletDot} />
            <span className={styles.walletAddr}>{walletDisplay}</span>
          </div>
        )}
        {bottomActions}
      </div>
    </aside>
  );
}
