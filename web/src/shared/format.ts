export function formatMoney(amount?: number | null, currency = "RUB") {
  const value = Number(amount || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(value);
  } catch {
    return `${value.toFixed(0)} ${currency}`;
  }
}

export function formatDateTime(value?: string | null) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function statusLabel(status?: string | null) {
  const key = status || "unknown";
  const labels: Record<string, string> = {
    online: "онлайн",
    offline: "офлайн",
    maintenance: "обслуживание",
    degraded: "нестабильно",
    draft: "черновик",
    not_started: "не начата",
    pending_review: "на проверке",
    approved: "одобрено",
    rejected: "отклонено",
    blocked: "заблокировано",
    awaiting_payment: "ожидает оплаты",
    payment_authorized: "оплата готова",
    confirmed: "подтверждена",
    pickup_ready: "готово к выдаче",
    active: "активна",
    return_in_progress: "возврат",
    completed: "завершена",
    cancelled: "отменена",
    incident: "инцидент",
  };
  return labels[key] ?? key.replaceAll("_", " ");
}

export function normalizePhoneInput(value: string) {
  return value.replace(/[^\d+]/g, "").slice(0, 16);
}

export function normalizePhoneForApi(value: string) {
  const raw = value.replace(/[^\d+]/g, "");
  if (raw.startsWith("+")) {
    return raw;
  }
  if (raw.startsWith("8") && raw.length === 11) {
    return `+7${raw.slice(1)}`;
  }
  if (raw.startsWith("7") && raw.length === 11) {
    return `+${raw}`;
  }
  if (raw.startsWith("375")) {
    return `+${raw}`;
  }
  return raw;
}

export function isPhoneReady(value: string) {
  const normalized = normalizePhoneForApi(value);
  return /^\+7\d{10}$/.test(normalized) || /^\+375\d{9}$/.test(normalized);
}
