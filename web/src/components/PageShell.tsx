"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { AppHeader } from "./AppHeader";
import { Footer } from "./Footer";
import { SupportWidget } from "./SupportWidget";

export function PageShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const isAuthRoute = pathname.startsWith("/auth");

  return (
    <div className={`app-shell ${isAuthRoute ? "app-shell-auth-route" : ""}`}>
      <AppHeader />
      {children}
      <Footer />
      {!isAuthRoute ? <SupportWidget /> : null}
    </div>
  );
}
