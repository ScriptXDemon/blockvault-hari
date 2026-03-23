import type { ButtonHTMLAttributes, CSSProperties, PropsWithChildren } from "react";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  fullWidth?: boolean;
}

const variants: Record<ButtonVariant, CSSProperties> = {
  primary: {
    background: "var(--bv-accent)",
    color: "white",
    border: "1px solid var(--bv-accent-strong)",
  },
  secondary: {
    background: "var(--bv-surface-strong)",
    color: "var(--bv-ink)",
    border: "1px solid var(--bv-border)",
  },
  ghost: {
    background: "transparent",
    color: "var(--bv-accent)",
    border: "1px solid transparent",
  },
  danger: {
    background: "var(--bv-danger)",
    color: "white",
    border: "1px solid color-mix(in srgb, var(--bv-danger) 82%, black)",
  },
};

export function Button({
  children,
  style,
  variant = "primary",
  fullWidth = false,
  ...props
}: PropsWithChildren<ButtonProps>) {
  return (
    <button
      {...props}
      style={{
        ...variants[variant],
        width: fullWidth ? "100%" : undefined,
        borderRadius: 999,
        padding: "0.9rem 1.3rem",
        fontWeight: 600,
        fontSize: "0.95rem",
        cursor: props.disabled ? "not-allowed" : "pointer",
        opacity: props.disabled ? 0.65 : 1,
        transition: "transform 160ms ease, opacity 160ms ease, background 160ms ease",
        ...style,
      }}
    >
      {children}
    </button>
  );
}
