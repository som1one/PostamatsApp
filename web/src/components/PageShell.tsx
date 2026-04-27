import { AppHeader } from "./AppHeader";
import { Footer } from "./Footer";

export function PageShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-shell">
      <AppHeader />
      {children}
      <Footer />
    </div>
  );
}
