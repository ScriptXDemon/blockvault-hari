import type { ReactNode } from "react";
import styles from "./Tabs.module.css";

export interface TabDef {
  id: string;
  label: string;
  badge?: number | string;
}

export interface TabsProps {
  tabs: TabDef[];
  activeTab: string;
  onChange: (id: string) => void;
}

export function Tabs({ tabs, activeTab, onChange }: TabsProps) {
  return (
    <div className={styles.tabList} role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          aria-selected={tab.id === activeTab}
          className={[styles.tab, tab.id === activeTab ? styles["tab--active"] : ""].filter(Boolean).join(" ")}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
          {tab.badge !== undefined && <span className={styles.badge}>{tab.badge}</span>}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({ id, activeTab, children }: { id: string; activeTab: string; children: ReactNode }) {
  if (id !== activeTab) return null;
  return <div role="tabpanel">{children}</div>;
}
