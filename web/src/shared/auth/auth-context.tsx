"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ConfirmCodeResponse } from "@/shared/api/types";
import {
  clearStoredSession,
  readStoredSession,
  type StoredSession,
  writeStoredSession,
} from "./session";

type AuthContextValue = {
  session: StoredSession | null;
  isReady: boolean;
  isAuthed: boolean;
  setSessionFromLogin: (result: ConfirmCodeResponse) => void;
  clearSession: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<StoredSession | null>(null);
  const [isReady, setIsReady] = useState(false);

  const syncFromStorage = useCallback(() => {
    setSession(readStoredSession());
  }, []);

  useEffect(() => {
    syncFromStorage();
    setIsReady(true);
    window.addEventListener("storage", syncFromStorage);
    window.addEventListener("postamats-auth-changed", syncFromStorage);
    return () => {
      window.removeEventListener("storage", syncFromStorage);
      window.removeEventListener("postamats-auth-changed", syncFromStorage);
    };
  }, [syncFromStorage]);

  const setSessionFromLogin = useCallback((result: ConfirmCodeResponse) => {
    const next = {
      accessToken: result.accessToken,
      refreshToken: result.refreshToken,
      user: result.user,
    };
    writeStoredSession(next);
    setSession(next);
  }, []);

  const clearSession = useCallback(() => {
    clearStoredSession();
    setSession(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      isReady,
      isAuthed: Boolean(session?.accessToken),
      setSessionFromLogin,
      clearSession,
    }),
    [clearSession, isReady, session, setSessionFromLogin],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return value;
}
