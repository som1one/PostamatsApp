import { requestEnvelope, requestJson, requestWithAuth } from "./client";
import type {
  AppUser,
  City,
  ConfirmCodeResponse,
  FeaturedProduct,
  Locker,
  LockerAvailabilityItem,
  PaymentSummary,
  PreauthResponse,
  PresignUploadResponse,
  PricingQuote,
  ProductDetail,
  ProductListItem,
  RentalDetail,
  RentalListItem,
  RequestCodeResponse,
  ReservationQuote,
  ReservationSummary,
  UpcomingReservation,
  VerificationState,
} from "./types";

export async function requestCode(phone: string) {
  return requestJson<RequestCodeResponse>("/auth/request-code", {
    method: "POST",
    body: { phone },
  });
}

export async function confirmCode(verificationSessionId: string, code: string) {
  return requestJson<ConfirmCodeResponse>("/auth/confirm-code", {
    method: "POST",
    body: { verificationSessionId, code },
  });
}

// DEV: Instant login without SMS
export async function devLogin(phone: string) {
  return requestJson<ConfirmCodeResponse>("/auth/dev-login", {
    method: "POST",
    body: { phone },
  });
}

export async function logoutSession() {
  return requestWithAuth<{ message: string }>("/auth/logout", {
    method: "POST",
  });
}

export async function fetchMe() {
  const payload = await requestWithAuth<{ user: AppUser }>("/me");
  return payload.user;
}

export async function updateMe(payload: Partial<AppUser>) {
  const data = await requestWithAuth<{ user: AppUser }>("/me", {
    method: "PATCH",
    body: payload,
  });
  return data.user;
}

export async function fetchVerification() {
  const payload = await requestWithAuth<{ verification: VerificationState }>(
    "/me/verification",
  );
  return payload.verification;
}

export async function createVerification(payload: {
  firstName: string;
  lastName: string;
  birthDate: string;
  documentType: string;
  documentName?: string;
  documentNumber: string;
  documentIssueDate?: string;
  documentExpiryDate?: string;
  files: Array<{ fileKey: string; kind: "document_front" | "document_back" | "selfie" }>;
}) {
  const data = await requestWithAuth<{ verification: VerificationState }>(
    "/me/verification",
    {
      method: "POST",
      body: payload,
    },
  );
  return data.verification;
}

export async function deleteVerification(documentNumber: string) {
  const data = await requestWithAuth<{ verification: VerificationState }>(
    "/me/verification",
    {
      method: "DELETE",
      body: { documentNumber },
    },
  );
  return data.verification;
}

export async function presignUpload(payload: {
  fileName: string;
  mimeType: string;
  fileSize: number;
  kind: string;
}) {
  return requestWithAuth<PresignUploadResponse>("/uploads/presign", {
    method: "POST",
    body: payload,
  });
}

export async function fetchCities() {
  const payload = await requestJson<{ cities: City[] }>("/cities/");
  return payload.cities;
}

export async function fetchPublicStats() {
  const payload = await requestJson<{ stats: { users: number } }>("/public/stats");
  return payload.stats;
}

export async function fetchLockers(cityId?: string) {
  const params = new URLSearchParams();
  if (cityId) {
    params.set("cityId", cityId);
  }
  const query = params.toString() ? `?${params.toString()}` : "";
  const payload = await requestJson<{ lockers: Locker[] }>(`/lockers/${query}`);
  return payload.lockers;
}

async function fetchLockersPage(params?: {
  cityId?: string;
  page?: number;
  limit?: number;
}) {
  const query = new URLSearchParams();
  if (params?.cityId) {
    query.set("cityId", params.cityId);
  }
  if (params?.page) {
    query.set("page", String(params.page));
  }
  if (params?.limit) {
    query.set("limit", String(params.limit));
  }
  const qs = query.toString() ? `?${query.toString()}` : "";
  const payload = await requestEnvelope<{ lockers: Locker[] }>(`/lockers/${qs}`);
  return {
    lockers: payload.data.lockers,
    total: payload.meta?.total ?? payload.data.lockers.length,
  };
}

export async function fetchAllLockers(cityId?: string) {
  const pageSize = 100;
  const items: Locker[] = [];
  let page = 1;
  let total = 0;

  do {
    const response = await fetchLockersPage({ cityId, page, limit: pageSize });
    items.push(...response.lockers);
    total = response.total;
    if (!response.lockers.length) {
      break;
    }
    page += 1;
  } while (items.length < total);

  return items;
}

export async function fetchLockerAvailability(lockerId: string) {
  const payload = await requestJson<{
    lockerId: string;
    status: string;
    items: LockerAvailabilityItem[];
  }>(`/lockers/${lockerId}/availability`);
  return payload.items;
}

export async function fetchProducts(params?: {
  cityId?: string;
  lockerId?: string;
  categoryId?: string;
  search?: string;
  availableOnly?: boolean;
  limit?: number;
}) {
  const query = new URLSearchParams();
  if (params?.cityId) {
    query.set("cityId", params.cityId);
  }
  if (params?.lockerId) {
    query.set("lockerId", params.lockerId);
  }
  if (params?.categoryId) {
    query.set("categoryId", params.categoryId);
  }
  if (params?.search) {
    query.set("search", params.search);
  }
  if (params?.limit) {
    query.set("limit", String(params.limit));
  }
  query.set("availableOnly", params?.availableOnly === false ? "false" : "true");
  const qs = query.toString() ? `?${query.toString()}` : "";
  const payload = await requestJson<{ products: ProductListItem[] }>(`/products${qs}`);
  return payload.products;
}

export async function fetchFeaturedProduct(cityId?: string) {
  const query = cityId ? `?cityId=${encodeURIComponent(cityId)}` : "";
  return requestJson<FeaturedProduct>(`/products/featured${query}`);
}

export async function fetchProduct(productId: string, cityId?: string, reservationId?: string) {
  const params = new URLSearchParams();
  if (cityId) {
    params.set("cityId", cityId);
  }
  if (reservationId) {
    params.set("reservationId", reservationId);
  }
  const query = params.toString() ? `?${params.toString()}` : "";
  const payload = await requestJson<{ product: ProductDetail }>(
    `/products/${productId}${query}`,
  );
  return payload.product;
}

export async function resolveProductBySlugOrId(
  productRef: string,
  cityId?: string,
  reservationId?: string,
) {
  try {
    return await fetchProduct(productRef, cityId, reservationId);
  } catch (error) {
    if (productRef.length > 20 && /^[0-9a-f-]+$/i.test(productRef)) {
      throw error;
    }
  }

  const products = await fetchProducts({
    cityId,
    search: productRef,
    availableOnly: false,
    limit: 100,
  });
  const item =
    products.find((product) => product.slug === productRef) ??
    products.find((product) => product.id === productRef) ??
    products[0];

  if (!item) {
    return fetchProduct(productRef, cityId, reservationId);
  }

  return fetchProduct(item.id, cityId, reservationId);
}

export async function fetchProductPricing(
  productId: string,
  lockerId: string,
  durationType = "day",
  durationValue = 1,
  reservationId?: string,
) {
  const params = new URLSearchParams({
    lockerId,
    durationType,
    durationValue: String(durationValue),
  });
  if (reservationId) {
    params.set("reservationId", reservationId);
  }
  return requestJson<PricingQuote>(
    `/products/${productId}/pricing?${params.toString()}`,
  );
}

export async function createReservationQuote(payload: {
  productId: string;
  lockerId: string;
  durationType: string;
  durationValue: number;
}) {
  const data = await requestWithAuth<{ quote: ReservationQuote }>("/reservations/quote", {
    method: "POST",
    body: payload,
  });
  return data.quote;
}

export async function createReservation(payload: {
  productId: string;
  lockerId: string;
  durationType: string;
  durationValue: number;
  sourceReservationId?: string;
}) {
  const data = await requestWithAuth<{ reservation: ReservationSummary }>(
    "/reservations",
    {
      method: "POST",
      body: payload,
    },
  );
  return data.reservation;
}

export async function fetchReservation(reservationId: string) {
  const data = await requestWithAuth<{ reservation: ReservationSummary }>(
    `/reservations/${reservationId}`,
  );
  return data.reservation;
}

export async function createPaymentPreauth(payload: {
  reservationId: string;
  returnUrl?: string;
}) {
  return requestWithAuth<PreauthResponse>("/payments/preauth", {
    method: "POST",
    body: payload,
  });
}

export async function fetchPayment(paymentId: string) {
  const data = await requestWithAuth<{ payment: PaymentSummary }>(
    `/payments/${paymentId}`,
  );
  return data.payment;
}

export async function authorizePaymentDevStub(paymentId: string) {
  const data = await requestWithAuth<{ payment: PaymentSummary }>(
    `/payments/${paymentId}/authorize-dev-stub`,
    {
      method: "POST",
    },
  );
  return data.payment;
}

export async function confirmReservation(reservationId: string, paymentId?: string) {
  const data = await requestWithAuth<{
    rental: {
      id: string;
      status: string;
      pickupPin: string;
      pickupLockerId: string;
      plannedEndAt: string;
    };
  }>(`/reservations/${reservationId}/confirm`, {
    method: "POST",
    body: paymentId ? { paymentId } : {},
  });
  return data.rental;
}

export async function fetchRentals(status?: string) {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  const data = await requestWithAuth<{ rentals: RentalListItem[] }>(
    `/me/rentals${query}`,
  );
  return data.rentals;
}

export async function fetchRental(rentalId: string) {
  const data = await requestWithAuth<{ rental: RentalDetail }>(
    `/me/rentals/${rentalId}`,
  );
  return data.rental;
}

export async function fetchMyReservations() {
  const data = await requestWithAuth<{ reservations: UpcomingReservation[] }>("/me/reservations");
  return data.reservations;
}

export async function cancelReservation(reservationId: string) {
  return requestWithAuth<{
    reservation: {
      id: string;
      status: string;
      cancelledAt?: string | null;
    };
  }>(`/me/reservations/${reservationId}/cancel`, {
    method: "POST",
  });
}

export async function requestRentalReturn(rentalId: string, lockerId?: string) {
  return requestWithAuth<{
    return: {
      rentalId: string;
      status: string;
      lockerId: string;
      cellLabel?: string;
      instructions?: string;
    };
  }>(`/me/rentals/${rentalId}/return-request`, {
    method: "POST",
    body: lockerId ? { lockerId } : {},
  });
}

export async function openRentalCell(rentalId: string) {
  return requestWithAuth<{ rental: { id: string; status: string } }>(
    `/me/rentals/${rentalId}/open-cell`,
    { method: "POST" },
  );
}
