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
