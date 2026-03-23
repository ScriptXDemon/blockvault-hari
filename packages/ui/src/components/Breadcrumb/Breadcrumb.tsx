import { Link } from "react-router-dom";
import styles from "./Breadcrumb.module.css";

export interface BreadcrumbItem {
  label: string;
  to?: string;
}

export function Breadcrumb({ items }: { items: BreadcrumbItem[] }) {
  return (
    <nav className={styles.breadcrumb} aria-label="Breadcrumb">
      {items.map((item, i) => (
        <span key={i} className={styles.item}>
          {i > 0 && <span className={styles.sep}>/</span>}
          {item.to ? (
            <Link to={item.to} className={styles.link}>{item.label}</Link>
          ) : (
            <span className={styles.current}>{item.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}
