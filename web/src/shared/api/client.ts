import {
  clearStoredSession,
  readStoredSession,
  writeStoredSession,
} from "@/shared/auth/session";
import type { ApiEnvelope, ConfirmCodeResponse } from "./types";

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export function apiBaseUrl() {
  const fromEnv = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (fromEnv) {
    return fromEnv.replace(/\/$/, "");
  }

  if (typeof window !== "undefined") {
    const { protocol, hostname } = window.location;
    if (hostname === "localhost" || hostname === "127.0.0.1") {
      return "http://127.0.0.1:8000";
    }
    return `${protocol}//${hostname}`;
  }

  return "http://127.0.0.1:8000";
}

type RequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  token?: string;
  body?: unknown;
  headers?: Record<string, string>;
};

async function parseError(response: Response) {
  const payload = await response.json().catch(() => null);
  if (payload && typeof payload.detail === "string") {
    return { message: payload.detail, code: payload.detail };
  }
  if (payload?.error?.message) {
    return {
      message: String(payload.error.message),
      code: payload.error.code ? String(payload.error.code) : undefined,
    };
  }
  if (Array.isArray(payload?.detail) && payload.detail[0]?.msg) {
    return { message: String(payload.detail[0].msg), code: "VALIDATION_ERROR" };
  }
  return { message: "Не удалось выполнить запрос", code: undefined };
}

export async function requestJson<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    "x-platform": "web",
    "x-app-version": "0.1.0",
    ...options.headers,
  };

  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  if (options.token) {
    headers.Authorization = `Bearer ${options.token}`;
  }

  const normalized = path.startsWith("/") ? path : `/${path}`;
  const response = await fetch(`${apiBaseUrl()}${normalized}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (!response.ok) {
    const error = await parseError(response);
    throw new ApiError(error.message, response.status, error.code);
  }

  const payload = (await response.json().catch(() => ({}))) as ApiEnvelope<T>;
  return payload.data;
}

async function refreshSession(refreshToken: string): Promise<ConfirmCodeResponse> {
  return requestJson<ConfirmCodeResponse>("/auth/refresh", {
    method: "POST",
    token: refreshToken,
  });
}

export async function requestWithAuth<T>(
  path: string,
  options: Omit<RequestOptions, "token"> = {},
): Promise<T> {
  const session = readStoredSession();
  if (!session?.accessToken) {
    throw new ApiError("Нужен вход в аккаунт", 401, "UNAUTHORIZED");
  }

  try {
    return await requestJson<T>(path, { ...options, token: session.accessToken });
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401 || !session.refreshToken) {
      throw error;
    }

    try {
      const refreshed = await refreshSession(session.refreshToken);
      writeStoredSession({
        accessToken: refreshed.accessToken,
        refreshToken: refreshed.refreshToken,
        user: refreshed.user,
      });
      return await requestJson<T>(path, { ...options, token: refreshed.accessToken });
    } catch (refreshError) {
      clearStoredSession();
      throw refreshError;
    }
  }
}
