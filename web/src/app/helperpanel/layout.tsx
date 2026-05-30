import type { Metadata } from "next";
import type { ReactNode } from "react";
import { OperatorAuthProvider } from "./operator-auth-context";
import "./helperpanel.css";

// Панель оператора — отдельный интерфейс на маршруте /helperpanel
// (Requirement 7.1). Этот layout НАМЕРЕННО не оборачивает контент в
// PageShell/PageChrome, поэтому здесь нет клиентского AppHeader, Footer и
// SupportWidget — оператор-панель визуально отделена от клиентского сайта.
export const metadata: Metadata = {
  title: "Панель оператора — naprokatberu",
  robots: { index: false, follow: false },
};

export default function HelperPanelLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <OperatorAuthProvider>
      <div className="helperpanel-root">{children}</div>
    </OperatorAuthProvider>
  );
}
