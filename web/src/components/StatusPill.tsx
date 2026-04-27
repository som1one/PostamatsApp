import { statusLabel } from "@/shared/format";

export function StatusPill({ status }: { status?: string | null }) {
  const normalized = status || "unknown";
  return (
    <span className={`status status-${normalized}`}>
      <span>{statusLabel(normalized)}</span>
    </span>
  );
}
