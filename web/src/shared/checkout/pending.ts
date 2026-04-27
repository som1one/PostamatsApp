export type PendingCheckout = {
  reservationId: string;
  paymentId: string;
  createdAt: string;
};

const STORAGE_KEY = "postamats-pending-checkout";

export function writePendingCheckout(value: PendingCheckout) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
}

export function readPendingCheckout(): PendingCheckout | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw) as PendingCheckout;
  } catch {
    window.localStorage.removeItem(STORAGE_KEY);
    return null;
  }
}

export function clearPendingCheckout() {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(STORAGE_KEY);
}
