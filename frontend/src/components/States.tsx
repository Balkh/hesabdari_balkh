import { tokens } from "../theme/tokens";
export function LoadingState() { return <p style={{ color: tokens.colors.muted }}>Loading…</p>; }
export function ErrorState({ message }: { message: string }) { return <p role="alert" style={{ color: tokens.colors.danger }}>{message}</p>; }
export function EmptyState({ message }: { message: string }) { return <p style={{ color: tokens.colors.muted }}>{message}</p>; }
