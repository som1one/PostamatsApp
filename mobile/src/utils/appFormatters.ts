import type { AppUser, Locker } from "../types";

export type ToolArtworkKind = "drill" | "generator" | "welder" | "toolbox";

export function formatMoney(amount: number, currency = "RUB") {
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(amount / 100);
}

function pluralizeRu(count: number, one: string, few: string, many: string) {
  const mod10 = count % 10;
  const mod100 = count % 100;

  if (mod10 === 1 && mod100 !== 11) {
    return one;
  }

  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) {
    return few;
  }

  return many;
}

export function formatCountText(count: number, one: string, few: string, many: string) {
  return `${count} ${pluralizeRu(count, one, few, many)}`;
}

export function productMonogram(name: string) {
  return name
    .split(" ")
    .slice(0, 2)
    .map((chunk) => chunk[0]?.toUpperCase() ?? "")
    .join("");
}

export function statusLabel(status: Locker["status"]) {
  if (status === "online") return "Онлайн";
  if (status === "offline") return "Офлайн";
  if (status === "maintenance") return "Сервис";
  return "Нестабильно";
}

export function verificationLabel(status?: string) {
  if (status === "approved") return "Проверен";
  if (status === "pending_review") return "На проверке";
  if (status === "rejected") return "Отклонен";
  if (status === "blocked") return "Заблокирован";
  return "Нужна проверка";
}

export function formatCompactUserName(user: AppUser | null) {
  if (!user) {
    return "Пользователь";
  }

  const lastName = user.lastName?.trim();
  const firstInitial = user.firstName?.trim()?.charAt(0);
  const middleInitial = user.middleName?.trim()?.charAt(0);

  if (lastName && (firstInitial || middleInitial)) {
    return `${lastName} ${firstInitial ? `${firstInitial}.` : ""}${middleInitial ? `${middleInitial}.` : ""}`.trim();
  }

  if (user.firstName?.trim()) {
    return user.firstName.trim();
  }

  if (lastName) {
    return lastName;
  }

  return user.phone;
}

export function formatUserInitials(user: AppUser | null) {
  if (!user) {
    return "U";
  }

  const initials = [user.firstName?.trim()?.[0], user.lastName?.trim()?.[0]]
    .filter(Boolean)
    .join("")
    .toUpperCase();

  if (initials) {
    return initials;
  }

  const digits = user.phone.replace(/\D/g, "");
  return digits.slice(-2) || "U";
}

export function formatPriceTag(amount: number) {
  const value = new Intl.NumberFormat("ru-RU", {
    maximumFractionDigits: 0,
  }).format(amount / 100);
  return `от ${value} руб`;
}

export function inferToolArtwork(name: string): ToolArtworkKind {
  const normalized = name.toLowerCase();

  if (normalized.includes("генератор")) {
    return "generator";
  }

  if (normalized.includes("свар")) {
    return "welder";
  }

  if (
    normalized.includes("дрель") ||
    normalized.includes("шуруп") ||
    normalized.includes("перфорат")
  ) {
    return "drill";
  }

  return "toolbox";
}

export function formatRentalEta(expiresAt?: string) {
  if (!expiresAt) {
    return "Доступно сегодня";
  }

  const remainingMs = Date.parse(expiresAt) - Date.now();
  if (!Number.isFinite(remainingMs) || remainingMs <= 0) {
    return "Срок истек";
  }

  const hours = Math.max(1, Math.round(remainingMs / (60 * 60 * 1000)));
  const suffix =
    hours % 10 === 1 && hours % 100 !== 11
      ? "час"
      : hours % 10 >= 2 && hours % 10 <= 4 && (hours % 100 < 10 || hours % 100 >= 20)
        ? "часа"
        : "часов";

  return `${hours} ${suffix}`;
}
