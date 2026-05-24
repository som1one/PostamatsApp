import type { RentalListItem } from "@/shared/api/types";

// Терминальные статусы аренды, для которых не нужно показывать
// deadline-overlay, даже если plannedEndAt уже в прошлом.
//
// ВНИМАНИЕ: "cancelled" сюда НЕ включаем — req 3.5 требует сохранить текущее
// представление отменённого бронирования (cancellation card в окружающем JSX).
// Если потребуется расширить набор (например, при появлении нового
// терминального статуса), это делается в одном месте.
export function isTerminalRentalStatus(
  status: string | null | undefined,
): boolean {
  return status === "completed";
}

// Аренда уже завершена с точки зрения данных, если:
//   1) её статус терминальный (например, "completed"), ИЛИ
//   2) у неё проставлен `actualEndAt` — фактический момент окончания.
//
// Бэкенд проставляет `actual_end_at` каждый раз, когда аренда фактически
// прекращается: успешный возврат (`COMPLETED`), отмена в админке
// (`CANCELLED`), просроченный pickup (`CANCELLED`). При этом статус и
// `actualEndAt` обновляются разными путями (return-webhook, админка,
// scheduler), и в редких случаях видим отставание статуса от фактического
// состояния (например, аренда уже возвращена, но `status` остался
// `overdue`/`active`/`incident`). В такой ситуации мы НЕ должны рисовать
// overlay «Просрочено» — товар уже сдан.
//
// Поэтому при расчёте deadline-плашки опираемся на оба сигнала.
export function isRentalFinished(
  rental: Pick<RentalListItem, "status" | "actualEndAt">,
): boolean {
  if (isTerminalRentalStatus(rental.status)) {
    return true;
  }
  if (rental.actualEndAt) {
    return true;
  }
  return false;
}
