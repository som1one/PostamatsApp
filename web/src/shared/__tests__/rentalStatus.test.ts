import { describe, it, expect } from "vitest";
import { isRentalFinished, isTerminalRentalStatus } from "../rentalStatus";

// Validates: design.md "Unit Tests → isTerminalRentalStatus" 9-row table.
describe("isTerminalRentalStatus", () => {
  it.each([
    ["completed", true],
    ["cancelled", false],
    ["active", false],
    ["overdue", false],
    ["pickup_ready", false],
    ["pickup_opened", false],
    ["return_in_progress", false],
  ] as const)("returns %s for status %s", (status, expected) => {
    expect(isTerminalRentalStatus(status)).toBe(expected);
  });

  it("returns false for null", () => {
    expect(isTerminalRentalStatus(null)).toBe(false);
  });

  it("returns false for undefined", () => {
    expect(isTerminalRentalStatus(undefined)).toBe(false);
  });
});

// Validates: бэкендовский invariant — `actual_end_at` проставляется при любом
// фактическом окончании аренды (успешный возврат, отмена в админке,
// просроченный pickup). На UI это считается «аренда уже завершена», даже если
// статус ещё не успел синхронизироваться (отставание webhook'а).
describe("isRentalFinished", () => {
  it("returns true when status is 'completed' regardless of actualEndAt", () => {
    expect(isRentalFinished({ status: "completed", actualEndAt: null })).toBe(
      true,
    );
    expect(
      isRentalFinished({
        status: "completed",
        actualEndAt: "2025-01-01T12:00:00Z",
      }),
    ).toBe(true);
  });

  it("returns true when actualEndAt is set, even if status lags behind", () => {
    // Например, возврат фактически завершён, но статус ещё `active` /
    // `overdue` / `incident` — overlay «Просрочено» показывать не должны.
    expect(
      isRentalFinished({
        status: "active",
        actualEndAt: "2025-01-01T12:00:00Z",
      }),
    ).toBe(true);
    expect(
      isRentalFinished({
        status: "overdue",
        actualEndAt: "2025-01-01T12:00:00Z",
      }),
    ).toBe(true);
    expect(
      isRentalFinished({
        status: "incident",
        actualEndAt: "2025-01-01T12:00:00Z",
      }),
    ).toBe(true);
  });

  it("returns false for active rentals without actualEndAt", () => {
    expect(isRentalFinished({ status: "active", actualEndAt: null })).toBe(
      false,
    );
    expect(isRentalFinished({ status: "active", actualEndAt: undefined })).toBe(
      false,
    );
    expect(isRentalFinished({ status: "overdue", actualEndAt: null })).toBe(
      false,
    );
    expect(
      isRentalFinished({ status: "pickup_ready", actualEndAt: null }),
    ).toBe(false);
    expect(
      isRentalFinished({ status: "return_in_progress", actualEndAt: null }),
    ).toBe(false);
  });

  it("returns false for cancelled rentals without actualEndAt (preservation)", () => {
    // req 3.5 — отменённое бронирование без actualEndAt не считаем завершённой
    // арендой, чтобы окружающий JSX мог отрисовать свою cancellation card.
    expect(isRentalFinished({ status: "cancelled", actualEndAt: null })).toBe(
      false,
    );
  });

  it("returns true for cancelled rentals when actualEndAt is set", () => {
    // На бэке `actual_end_at` проставляется в т.ч. при `pickup_expired` и
    // админской отмене активной аренды. Если этот сигнал есть — overlay
    // «Просрочено» в любом случае не показываем.
    expect(
      isRentalFinished({
        status: "cancelled",
        actualEndAt: "2025-01-01T12:00:00Z",
      }),
    ).toBe(true);
  });
});
