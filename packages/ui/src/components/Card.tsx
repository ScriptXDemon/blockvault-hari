import type { HTMLAttributes, PropsWithChildren } from "react";

export function Card({ children, style, ...props }: PropsWithChildren<HTMLAttributes<HTMLDivElement>>) {
  return (
    <div
      {...props}
      className={`bv-card ${props.className ?? ""}`.trim()}
      style={{
        padding: "1.5rem",
        ...style,
      }}
    >
      {children}
    </div>
  );
}
