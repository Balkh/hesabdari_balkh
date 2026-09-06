import type { PropsWithChildren } from "react";
import { tokens } from "../theme/tokens";
export function Card({ children }: PropsWithChildren) { return <section style={{ background: tokens.colors.surface, border: `1px solid ${tokens.colors.border}`, borderRadius: tokens.radius.md, padding: tokens.spacing.lg, boxShadow: "0 8px 30px #17304214" }}>{children}</section>; }
