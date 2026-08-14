import type { RentalListItem, UpcomingReservation } from "@/shared/api/types";
import { formatCountRu, formatDateTime } from "@/shared/format";
import { isRentalFinished } from "@/shared/rentalStatus";

/**
 * Дедлайн-плашки бронирований и аренд («До отмены брони», «Просрочено на…»).
 * Вынесено из RentalsClient.tsx, чтобы мобильное приложение использовало
 * ровно ту же логику (файл копируется в mobile/src/shared байт-идентично).
 * Поэтому здесь нет JSX и компонентов иконок — только нейтральные имена.
 */
export type DeadlineTone = "warn" | "danger" | "success";

/** Имя иконки: web маппит на lucide-react, mobile — на lucide-react-native. */
export type DeadlineIconName = "alert-triangle" | "check-circle" | "clock";

export type DeadlineMeta = {
  tone: DeadlineTone;
  title: string;
  text: string;
  icon: DeadlineIconName;
};

export function formatDurationLabel(diffMs: number) {
  const totalMinutes = Math.max(1, Math.ceil(Math.abs(diffMs) / 60_000));
  const days = Math.floor(totalMinutes / (60 * 24));
  const hours = Math.floor((totalMinutes % (60 * 24)) / 60);
  const minutes = totalMinutes % 60;
  const parts: string[] = [];

  if (days > 0) {
    parts.push(formatCountRu(days, ["день", "дня", "дней"]));
  }
  if (hours > 0) {
    parts.push(formatCountRu(hours, ["час", "часа", "часов"]));
  }
  if (days === 0 && minutes > 0) {
    parts.push(formatCountRu(minutes, ["минута", "минуты", "минут"]));
  }

  return parts.join(" ");
}

export function getReservationDeadlineMeta(reservation: UpcomingReservation, nowMs: number): DeadlineMeta | null {
  const expiresMs = new Date(reservation.expiresAt).getTime();
  if (Number.isNaN(expiresMs)) {
    return null;
  }

  const diffMs = expiresMs - nowMs;
  const duration = formatDurationLabel(diffMs);

  if (diffMs <= 0) {
    return {
      tone: "danger",
      title: `Бронь истекла ${duration} назад`,
      text: "Эта бронь уже недоступна для выдачи.",
      icon: "alert-triangle",
    };
  }

  if (reservation.status === "payment_authorized") {
    return {
      tone: "success",
      title: `До выдачи: ${duration}`,
      text: `Оплата подтверждена. Заберите до ${formatDateTime(reservation.expiresAt)}.`,
      icon: "check-circle",
    };
  }

  return {
    tone: "warn",
    title: `До отмены брони: ${duration}`,
    text: `Оплатите и заберите до ${formatDateTime(reservation.expiresAt)}.`,
    icon: "clock",
  };
}

export function getRentalDeadlineMeta(rental: RentalListItem, nowMs: number): DeadlineMeta | null {
  if (rental.status === "return_in_progress") {
    // Инструкцию с PIN и номером ячейки показывает сама карточка возврата —
    // здесь только срок, иначе один и тот же текст идёт дважды подряд.
    const expiresAt = rental.returnRequest?.expiresAt;
    return {
      tone: "success",
      title: "Возврат уже начат",
      text: expiresAt
        ? `Успейте закрыть дверцу до ${formatDateTime(expiresAt)}.`
        : "Осталось закрыть дверцу ячейки.",
      icon: "check-circle",
    };
  }

  // Завершённые аренды (терминальный статус ИЛИ проставлен actualEndAt) не
  // рисуют deadline-плашку вне зависимости от того, прошло ли плановое
  // окончание. Это закрывает в т.ч. случаи, когда статус ещё не успел
  // прийти к "completed" (отставание webhook'а, ручная админская правка),
  // но фактический возврат уже зафиксирован.
  if (isRentalFinished(rental)) {
    return null;
  }

  if (!rental.plannedEndAt) {
    return null;
  }

  const plannedEndMs = new Date(rental.plannedEndAt).getTime();
  if (Number.isNaN(plannedEndMs)) {
    return null;
  }

  const diffMs = plannedEndMs - nowMs;
  const duration = formatDurationLabel(diffMs);

  if (rental.status === "overdue" || diffMs <= 0) {
    return {
      tone: "danger",
      title: `Просрочено на ${duration}`,
      text: "Стоит оформить возврат как можно скорее.",
      icon: "alert-triangle",
    };
  }

  // Если до старта аренды ещё ждать — показываем дату выдачи, а не дедлайн.
  if (
    ["pickup_ready", "pickup_opened"].includes(rental.status) &&
    rental.startsAt
  ) {
    const startsMs = new Date(rental.startsAt).getTime();
    if (!Number.isNaN(startsMs) && startsMs - nowMs > 60 * 60 * 1000) {
      const wait = formatDurationLabel(startsMs - nowMs);
      return {
        tone: "warn",
        title: `Получение через ${wait}`,
        text: `Заберите товар после ${formatDateTime(rental.startsAt)}`,
        icon: "clock",
      };
    }
  }

  if (["pickup_ready", "pickup_opened", "active"].includes(rental.status)) {
    return {
      tone: "warn",
      title: `До возврата: ${duration}`,
      text: `Вернуть до ${formatDateTime(rental.plannedEndAt)}`,
      icon: "clock",
    };
  }

  return null;
}
