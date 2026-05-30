"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { ApiError } from "@/shared/api/client";
import {
  clearOperatorSession,
  fetchOperatorMe,
  operatorHasAccess,
  operatorLogin,
  operatorLogout,
  readOperatorSession,
  refreshOperatorSession,
  subscribeOperatorSession,
  writeOperatorSession,
  type OperatorSession,
} from "./operator-auth";

type OperatorAuthContextValue = {
  session: OperatorSession | null;
  isReady: boolean;
  isAuthed: boolean;
  login: (login: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const OperatorAuthContext = createContext<OperatorAuthContextValue | null>(null);

export function OperatorAuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<OperatorSession | null>(null);
  const [isReady, setIsReady] = useState(false);

  const syncFromStorage = useCallback(() => {
    setSession(readOperatorSession());
  }, []);

  // На монтировании восстанавливаем сессию и валидируем токен через /me.
  // Если access-токен протух — пытаемся обновить по refresh (Requirement 7.4).
  useEffect(() => {
    let cancelled = false;

    async function restore() {
      const stored = readOperatorSession();
      if (!stored) {
        if (!cancelled) {
          setIsReady(true);
        }
        return;
      }

      try {
        const admin = await fetchOperatorMe(stored.accessToken);
        if (!cancelled) {
          const next = { ...stored, admin };
          writeOperatorSession(next);
          setSession(next);
        }
      } catch (error) {
        if (error instanceof ApiError && error.status === 401 && stored.refreshToken) {
          try {
            const refreshed = await refreshOperatorSession(stored.refreshToken);
            if (!cancelled) {
              writeOperatorSession(refreshed);
              setSession(refreshed);
            }
          } catch {
            clearOperatorSession();
            if (!cancelled) {
              setSession(null);
            }
          }
        } else {
          clearOperatorSession();
          if (!cancelled) {
            setSession(null);
          }
        }
      } finally {
        if (!cancelled) {
          setIsReady(true);
        }
      }
    }

    void restore();
    const unsubscribe = subscribeOperatorSession(syncFromStorage);
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [syncFromStorage]);

  const login = useCallback(async (loginValue: string, password: string) => {
    const data = await operatorLogin(loginValue, password);
    if (!operatorHasAccess(data.admin.role)) {
      // У аккаунта нет роли оператора/супер-админа — доступ запрещён
      // (Requirement 7.6). Не сохраняем токены.
      throw new ApiError(
        "У этого аккаунта нет доступа к панели оператора",
        403,
        "OPERATOR_FORBIDDEN",
      );
    }
    const next: OperatorSession = {
      accessToken: data.accessToken,
      refreshToken: data.refreshToken,
      admin: data.admin,
    };
    writeOperatorSession(next);
    setSession(next);
  }, []);

  const logout = useCallback(async () => {
    const current = readOperatorSession();
    if (current?.accessToken) {
      try {
        await operatorLogout(current.accessToken);
      } catch {
        // Игнорируем сетевые/серверные ошибки при логауте — локальную
        // сессию всё равно очищаем.
      }
    }
    clearOperatorSession();
    setSession(null);
  }, []);

  const value = useMemo<OperatorAuthContextValue>(
    () => ({
      session,
      isReady,
      isAuthed: Boolean(session?.accessToken),
      login,
      logout,
    }),
    [isReady, login, logout, session],
  );

  return (
    <OperatorAuthContext.Provider value={value}>
      {children}
    </OperatorAuthContext.Provider>
  );
}

export function useOperatorAuth() {
  const value = useContext(OperatorAuthContext);
  if (!value) {
    throw new Error("useOperatorAuth must be used inside OperatorAuthProvider");
  }
  return value;
}
