import Constants from "expo-constants";
import { Platform } from "react-native";
import type {
  AppUser,
  City,
  ConfirmCodeResponse,
  Locker,
  LockerAvailabilityItem,
  PricingQuote,
  ProductDetail,
  ProductListItem,
  RequestCodeResponse,
  ReservationQuote,
  ReservationSummary,
  VerificationState,
} from "./types";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function resolveApiBaseUrl(): string {
  const fromEnv = process.env.EXPO_PUBLIC_API_BASE_URL?.trim();
  if (fromEnv) {
    return fromEnv.replace(/\/$/, "");
  }
  const hostUri = Constants.expoConfig?.hostUri;
  if (hostUri) {
    const host = hostUri.split(":")[0];
    if (host) {
      return `http://${host}:8000`;
    }
  }
  return "http://127.0.0.1:8000";
}

type ApiEnvelope<T> = {
  data: T;
  meta?: Record<string, unknown>;
};

type RequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  token?: string;
  body?: unknown;
  headers?: Record<string, string>;
};

async function requestJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    "x-platform": Platform.OS,
    ...options.headers,
  };

  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  if (options.token) {
    headers.Authorization = `Bearer ${options.token}`;
  }

  const base = resolveApiBaseUrl();
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    });
  } catch {
    throw new Error(
      `Сервер недоступен (${base}). На телефоне укажите EXPO_PUBLIC_API_BASE_URL — IP компьютера, где запущен API (порт 8000), а не 127.0.0.1.`,
    );
  }

  const payload = (await response.json().catch(() => ({}))) as
    | ApiEnvelope<T>
    | { detail?: string; error?: { message?: string; code?: string } };

  if (!response.ok) {
    const message =
      ("detail" in payload && typeof payload.detail === "string" && payload.detail) ||
      ("error" in payload && payload.error?.message) ||
      "API request failed";
    throw new ApiError(message, response.status);
  }

  return (payload as ApiEnvelope<T>).data;
}

export function isUnauthorizedError(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 401;
}

export function isForbiddenError(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 403;
}

export async function requestCode(phone: string): Promise<RequestCodeResponse> {
  return requestJson<RequestCodeResponse>("/auth/request-code", {
    method: "POST",
    body: { phone },
  });
}

export async function confirmCode(
  verificationSessionId: string,
  code: string,
): Promise<ConfirmCodeResponse> {
  return requestJson<ConfirmCodeResponse>("/auth/confirm-code", {
    method: "POST",
    body: { verificationSessionId, code },
  });
}

export async function refreshAuthSession(refreshToken: string): Promise<ConfirmCodeResponse> {
  return requestJson<ConfirmCodeResponse>("/auth/refresh", {
    method: "POST",
    token: refreshToken,
  });
}

export async function logoutAuthSession(accessToken: string): Promise<void> {
  await requestJson<{ message: string }>("/auth/logout", {
    method: "POST",
    token: accessToken,
  });
}

export async function fetchMe(token: string): Promise<AppUser> {
  const payload = await requestJson<{ user: AppUser }>("/me", { token });
  return payload.user;
}

export async function fetchVerification(token: string): Promise<VerificationState> {
  const payload = await requestJson<{ verification: VerificationState }>("/me/verification", { token });
  return payload.verification;
}

export async function fetchCities(): Promise<City[]> {
  const payload = await requestJson<{ cities: City[] }>("/cities/");
  return payload.cities;
}

export async function fetchLockers(cityId?: string): Promise<Locker[]> {
  const params = new URLSearchParams();
  if (cityId) {
    params.set("cityId", cityId);
  }
  const query = params.toString() ? `?${params.toString()}` : "";
  const payload = await requestJson<{ lockers: Locker[] }>(`/lockers/${query}`);
  return payload.lockers;
}

export async function fetchLockerAvailability(lockerId: string): Promise<LockerAvailabilityItem[]> {
  const payload = await requestJson<{
    lockerId: string;
    status: string;
    items: LockerAvailabilityItem[];
  }>(`/lockers/${lockerId}/availability`);
  return payload.items;
}

export async function fetchProducts(cityId?: string): Promise<ProductListItem[]> {
  const params = new URLSearchParams();
  if (cityId) {
    params.set("cityId", cityId);
  }
  params.set("availableOnly", "true");
  const query = params.toString() ? `?${params.toString()}` : "";
  const payload = await requestJson<{ products: ProductListItem[] }>(`/products${query}`);
  return payload.products;
}

export async function fetchProduct(productId: string, cityId?: string): Promise<ProductDetail> {
  const params = new URLSearchParams();
  if (cityId) {
    params.set("cityId", cityId);
  }
  const query = params.toString() ? `?${params.toString()}` : "";
  const payload = await requestJson<{ product: ProductDetail }>(`/products/${productId}${query}`);
  return payload.product;
}

export async function fetchProductPricing(
  productId: string,
  lockerId: string,
  durationType = "day",
  durationValue = 1,
): Promise<PricingQuote> {
  const params = new URLSearchParams({
    lockerId,
    durationType,
    durationValue: String(durationValue),
  });
  return requestJson<PricingQuote>(`/products/${productId}/pricing?${params.toString()}`);
}

export async function createReservationQuote(
  token: string,
  payload: {
    productId: string;
    lockerId: string;
    durationType: string;
    durationValue: number;
  },
): Promise<ReservationQuote> {
  const data = await requestJson<{ quote: ReservationQuote }>("/reservations/quote", {
    method: "POST",
    token,
    body: payload,
  });
  return data.quote;
}

export async function createReservation(
  token: string,
  payload: {
    productId: string;
    lockerId: string;
    durationType: string;
    durationValue: number;
    pickupWindowMinutes: number;
  },
): Promise<ReservationSummary> {
  const data = await requestJson<{ reservation: ReservationSummary }>("/reservations", {
    method: "POST",
    token,
    body: payload,
  });
  return data.reservation;
}

export async function fetchReservation(
  token: string,
  reservationId: string,
): Promise<ReservationSummary> {
  const data = await requestJson<{ reservation: ReservationSummary }>(
    `/reservations/${reservationId}`,
    { token },
  );
  return data.reservation;
}
