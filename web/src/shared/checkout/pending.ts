export type PendingCheckout = {
  reservationId: string;
  paymentId: string;
  userId: string;
  createdAt: string;
};

const STORAGE_KEY = "postamats-pending-checkout";

/** Максимальное время жизни pending-записи (3 часа). */
const MAX_AGE_MS = 3 * 60 * 60 * 1000;

export function writePendingCheckout(value: PendingCheckout) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
}

/**
 * Читает pending checkout. Возвращает null если:
 * - запись отсутствует
 * - userId не совпадает с текущим
 * - запись старше MAX_AGE_MS
 */
export function readPendingCheckout(currentUserId?: string): PendingCheckout | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as PendingCheckout;

    // Протухание по времени
    if (parsed.createdAt) {
      const age = Date.now() - new Date(parsed.createdAt).getTime();
      if (age > MAX_AGE_MS) {
        window.localStorage.removeItem(STORAGE_KEY);
        return null;
      }
    }

    // Проверка userId — если передан currentUserId и он не совпадает,
    // значит pending от другого пользователя/сессии
    if (currentUserId && parsed.userId && parsed.userId !== currentUserId) {
      window.localStorage.removeItem(STORAGE_KEY);
      return null;
    }

    return parsed;
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
