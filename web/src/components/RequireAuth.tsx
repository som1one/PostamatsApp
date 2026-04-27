"use client";

import Link from "next/link";
import { LockKeyhole } from "lucide-react";
import { EmptyState } from "./EmptyState";
import { useAuth } from "@/shared/auth/auth-context";

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { isReady, isAuthed } = useAuth();

  if (!isReady) {
    return <div className="loader">Проверяем сессию</div>;
  }

  if (!isAuthed) {
    return (
      <EmptyState
        icon={<LockKeyhole size={34} />}
        title="Нужен вход"
        action={
          <Link className="button button-primary" href="/auth">
            Войти по телефону
          </Link>
        }
      />
    );
  }

  return <>{children}</>;
}
