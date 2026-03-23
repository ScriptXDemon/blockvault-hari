import type { PropsWithChildren } from "react";

export function Shell({ children }: PropsWithChildren) {
  return <div className="bv-shell">{children}</div>;
}
