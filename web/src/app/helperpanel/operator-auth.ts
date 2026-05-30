import { requestEnvelope } from "@/shared/api/client";

// Оператор-панель (/helperpanel) переиспользует существующую админскую
// аутентификацию (`/api/admin/auth/*`), но хранит токены ОТДЕЛЬНО от
// клиентской пользовательской сессии, чтобы вход оператора не затирал
// сессию клиента веб-приложения и наоборот.

export type OperatorAdmin = {
  id: string;
  name: string;
  login: string;
  role: string;
};

export type OperatorSession = {
  accessToken: string;
  refreshToken: string;
  admin: OperatorAdmin;
};

type AdminAuthData = {
  accessToken: string;
  refreshToken: string;
  admin: OperatorAdmin;
};

// Изолированный от клиентской сессии ключ хранилища и событие.
const OPERATOR_STORAGE_KEY = "helperpanel-operator-auth";
const OPERATOR_AUTH_EVENT = "helperpanel-auth-changed";

/** Роли админ-аккаунта, которым разрешён доступ к оператор-панели. */
const OPERATOR_ROLES = new Set(["operator", "super_admin"]);

export function operatorHasAccess(role: string | undefined | null): boolean {
  return typeof role === "string" && OPERATOR_ROLES.has(role);
}

function canUseStorage() {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

export function readOperatorSession(): OperatorSession | null {
  if (!canUseStorage()) {
    return null;
  }

  const raw = window.localStorage.getItem(OPERATOR_STORAGE_KEY);
  if (!raw) {
    return null;
  }

  try {
    const parsed = JSON.parse(raw) as OperatorSession;
    if (!parsed.accessToken || !parsed.refreshToken || !parsed.admin) {
      return null;
    }
    return parsed;
  } catch {
    window.localStorage.removeItem(OPERATOR_STORAGE_KEY);
    return null;
  }
}

export function writeOperatorSession(session: OperatorSession) {
  if (!canUseStorage()) {
    return;
  }
  window.localStorage.setItem(OPERATOR_STORAGE_KEY, JSON.stringify(session));
  window.dispatchEvent(new Event(OPERATOR_AUTH_EVENT));
}

export function clearOperatorSession() {
  if (!canUseStorage()) {
    return;
  }
  window.localStorage.removeItem(OPERATOR_STORAGE_KEY);
  window.dispatchEvent(new Event(OPERATOR_AUTH_EVENT));
}

export function subscribeOperatorSession(listener: () => void): () => void {
  if (typeof window === "undefined") {
    return () => {};
  }
  window.addEventListener("storage", listener);
  window.addEventListener(OPERATOR_AUTH_EVENT, listener);
  return () => {
    window.removeEventListener("storage", listener);
    window.removeEventListener(OPERATOR_AUTH_EVENT, listener);
  };
}

/** POST /api/admin/auth/login — Requirements 7.2, 7.3. */
export async function operatorLogin(
  login: string,
  password: string,
): Promise<AdminAuthData> {
  const payload = await requestEnvelope<AdminAuthData>("/api/admin/auth/login", {
    method: "POST",
    body: { login, password },
  });
  return payload.data;
}

/** POST /api/admin/auth/refresh — Requirement 7.4. */
export async function refreshOperatorSession(
  refreshToken: string,
): Promise<AdminAuthData> {
  const payload = await requestEnvelope<AdminAuthData>("/api/admin/auth/refresh", {
    method: "POST",
    token: refreshToken,
  });
  return payload.data;
}

/** GET /api/admin/auth/me — used to validate a restored access token. */
export async function fetchOperatorMe(accessToken: string): Promise<OperatorAdmin> {
  const payload = await requestEnvelope<{ admin: OperatorAdmin }>(
    "/api/admin/auth/me",
    { token: accessToken },
  );
  return payload.data.admin;
}

/** POST /api/admin/auth/logout — Requirement 7.5. */
export async function operatorLogout(accessToken: string): Promise<void> {
  await requestEnvelope<{ message: string }>("/api/admin/auth/logout", {
    method: "POST",
    token: accessToken,
  });
}
