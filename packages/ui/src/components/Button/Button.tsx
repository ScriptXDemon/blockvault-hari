import type { ButtonHTMLAttributes, PropsWithChildren } from "react";
import styles from "./Button.module.css";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  fullWidth?: boolean;
}

export function Button({
  children,
  variant = "primary",
  size = "md",
  fullWidth = false,
  className,
  ...props
}: PropsWithChildren<ButtonProps>) {
  return (
    <button
      {...props}
      className={[
        styles.btn,
        styles[`btn--${variant}`],
        size === "sm" ? styles["btn--sm"] : "",
        fullWidth ? styles["btn--fullWidth"] : "",
        className ?? "",
      ].filter(Boolean).join(" ")}
    >
      {children}
    </button>
  );
}
