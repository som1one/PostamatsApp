export function sanitizePhoneInput(value: string) {
  if (!value) {
    return "";
  }

  const filtered = value.replace(/[^\d+]/g, "");
  if (filtered.startsWith("+")) {
    return `+${filtered.slice(1).replace(/\+/g, "")}`;
  }
  return filtered.replace(/\+/g, "");
}

function normalizeRuByPhone(value: string) {
  const sanitized = sanitizePhoneInput(value);
  const digitsOnly = sanitized.replace(/\D/g, "");

  if (sanitized.startsWith("+")) {
    if (sanitized.startsWith("+375")) {
      if (digitsOnly.length !== 12) {
        return null;
      }
      return `+${digitsOnly}`;
    }

    if (sanitized.startsWith("+7")) {
      if (digitsOnly.length !== 11 || !digitsOnly.startsWith("7")) {
        return null;
      }
      return `+${digitsOnly}`;
    }

    return null;
  }

  if (digitsOnly.length === 10) {
    return `+7${digitsOnly}`;
  }

  if (digitsOnly.length === 11 && (digitsOnly.startsWith("7") || digitsOnly.startsWith("8"))) {
    return `+7${digitsOnly.slice(1)}`;
  }

  return null;
}

export function normalizePhoneForApi(value: string) {
  return normalizeRuByPhone(value) ?? "";
}

export function isPhoneReady(value: string) {
  return normalizePhoneForApi(value).length > 0;
}

export function formatOtpCountdown(seconds: number) {
  const safeSeconds = Math.max(0, seconds);
  const minutes = Math.floor(safeSeconds / 60)
    .toString()
    .padStart(2, "0");
  const secs = (safeSeconds % 60).toString().padStart(2, "0");
  return `${minutes}:${secs}`;
}
