import type { ReactNode } from "react";

export function Surface({
  children,
  className = "",
  tight = false,
}: {
  children: ReactNode;
  className?: string;
  tight?: boolean;
}) {
  return <section className={`surface ${tight ? "surface-tight" : ""} ${className}`}>{children}</section>;
}
