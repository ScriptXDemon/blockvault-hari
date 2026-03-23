import styles from "./Skeleton.module.css";

export interface SkeletonProps {
  variant?: "text" | "rect" | "circle";
  width?: string | number;
  height?: string | number;
  count?: number;
}

export function Skeleton({ variant = "rect", width, height, count = 1 }: SkeletonProps) {
  const style = {
    width: width ?? (variant === "circle" ? height : "100%"),
    height: height ?? (variant === "text" ? "1em" : variant === "circle" ? width : "48px"),
  };
  const el = <div className={[styles.skeleton, styles[`skeleton--${variant}`]].join(" ")} style={style} />;
  if (count === 1) return el;
  return <>{Array.from({ length: count }, (_, i) => <div key={i} style={{ marginBottom: "8px" }}>{el}</div>)}</>;
}
