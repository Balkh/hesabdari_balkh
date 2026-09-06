import type { ButtonHTMLAttributes } from "react";
import { tokens } from "../theme/tokens";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" };
export function Button({ variant = "primary", style, ...props }: Props) {
  const colors = { primary: tokens.colors.primary, secondary: tokens.colors.surface, danger: tokens.colors.danger };
  return <button {...props} style={{ border: `1px solid ${variant === "secondary" ? tokens.colors.border : colors[variant]}`, background: colors[variant], color: variant === "secondary" ? tokens.colors.text : "white", borderRadius: tokens.radius.md, padding: `${tokens.spacing.sm} ${tokens.spacing.md}`, cursor: "pointer", ...style }} />;
}
