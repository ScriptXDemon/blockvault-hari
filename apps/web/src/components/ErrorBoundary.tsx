import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props { children: ReactNode; fallback?: ReactNode; }
interface State { hasError: boolean; error: Error | null; }

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("ErrorBoundary caught:", error, info);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div style={{ padding: "48px 24px", textAlign: "center", color: "var(--bv-ink-muted)" }}>
          <p style={{ fontFamily: "var(--bv-font-serif)", fontSize: "1.25rem", color: "var(--bv-accent-strong)", marginBottom: "8px" }}>
            Something went wrong
          </p>
          <p style={{ fontSize: "0.875rem", maxWidth: 320, margin: "0 auto" }}>
            {this.state.error?.message ?? "An unexpected error occurred."}
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}
