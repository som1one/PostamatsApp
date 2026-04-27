import type { ReactNode } from "react";
import { PageShell } from "./PageShell";

export function PageChrome({
  children,
  compact = false,
}: {
  children: ReactNode;
  compact?: boolean;
}) {
  return (
    <PageShell>
      <main className={`container ${compact ? "page-compact" : "page"}`}>{children}</main>
    </PageShell>
  );
}
