import { describe, it, expect } from "vitest";
import type { RentalListItem } from "@/shared/api/types";
import { computeOrderDeadlineMeta } from "../OrderDetailClient";

// Helper to build a minimal RentalListItem for the helper-level tests.
function makeRental(overrides: Partial<RentalListItem>): RentalListItem {
  return {
    id: "rental-test",
    status: "active",
    product: {
      id: "product-1",
      name: "Test product",
      coverUrl: null,
    },
    locker: {
      id: "locker-1",
      name: "Test locker",
    },
    ...overrides,
  };
}

// Validates: Requirements 1.1, 1.2 (bugfix.md) — bug condition exploration
// (mirror of getRentalDeadlineMeta.test.ts for the OrderDetailClient page).
//
// На UNFIXED коде этот тест ОЖИДАЕМО ПАДАЕТ — это успех exploration-этапа,
// потому что падение подтверждает наличие бага. После фикса (task 3.1)
// этот же тест будет переразапущен (task 3.2) и должен пройти.
describe("computeOrderDeadlineMeta — exploration (bug condition)", () => {
  it("reproduces user scenario: completed booking with past plannedEndAt is wrongly flagged as overdue", () => {
    const rental: RentalListItem = {
      id: "rental-completed-1",
      status: "completed",
      plannedEndAt: "2025-01-01T12:00:00Z",
      product: {
        id: "product-1",
        name: "Test product",
        coverUrl: null,
      },
      locker: {
        id: "locker-1",
        name: "Test locker",
      },
    };
    const nowMs = Date.parse("2025-01-01T12:01:00Z");

    const meta = computeOrderDeadlineMeta(rental, nowMs);

    // Encoded EXPECTED post-fix behaviour. On UNFIXED code these assertions
    // FAIL because the function returns
    //   { tone: "danger", title: "Просрочено на 1 минута", ... }
    expect(meta?.tone).not.toBe("danger");
    expect(meta?.title ?? "").not.toContain("Просрочено");
    expect(meta).toBeNull();
  });
});

// Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6 (bugfix.md) —
// preservation baseline. Каждый кейс отражает соответствующую строку
// Behaviour Matrix из design.md. ВАЖНО: `computeOrderDeadlineMeta` НЕ имеет
// под-ветки `pickup_ready >1h-before-start` (этой ветки нет в исходном IIFE),
// поэтому строки 6/7 матрицы из getRentalDeadlineMeta здесь не применимы —
// вместо них одна строка `pickup_ready` с будущим plannedEnd → ветка
// «До возврата». Все эти тесты ДОЛЖНЫ ПРОЙТИ на нефиксированном коде.
describe("computeOrderDeadlineMeta — preservation — Behaviour Matrix", () => {
  // Row 1: completed + now < plannedEndAt → null (req 3.6).
  it("returns null for completed booking when now < plannedEndAt", () => {
    const rental = makeRental({
      status: "completed",
      plannedEndAt: "2025-01-01T12:00:00Z",
    });
    const nowMs = Date.parse("2025-01-01T11:30:00Z");

    const meta = computeOrderDeadlineMeta(rental, nowMs);

    expect(meta).toBeNull();
  });

  // Row 2: completed + plannedEndAt = null → null (preservation).
  it("returns null for completed booking when plannedEndAt is null", () => {
    const rental = makeRental({
      status: "completed",
      plannedEndAt: null,
    });
    const nowMs = Date.parse("2025-01-01T12:30:00Z");

    const meta = computeOrderDeadlineMeta(rental, nowMs);

    expect(meta).toBeNull();
  });

  // Row 3: active + now > plannedEndAt → danger «Просрочено на …» (req 3.1).
  it("returns danger overdue meta for active booking past plannedEndAt", () => {
    const rental = makeRental({
      status: "active",
      plannedEndAt: "2025-01-01T12:00:00Z",
    });
    const nowMs = Date.parse("2025-01-01T12:01:00Z");

    const meta = computeOrderDeadlineMeta(rental, nowMs);

    expect(meta?.tone).toBe("danger");
    expect(meta?.title).toBe("Просрочено на 1 минута");
    expect(meta?.text).toBe("Стоит оформить возврат как можно скорее.");
  });

  // Row 4: active + now < plannedEndAt → warn «До возврата» (req 3.3).
  it("returns warn 'До возврата' meta for active booking with future plannedEndAt", () => {
    const rental = makeRental({
      status: "active",
      plannedEndAt: "2025-01-01T12:00:00Z",
    });
    const nowMs = Date.parse("2025-01-01T11:00:00Z");

    const meta = computeOrderDeadlineMeta(rental, nowMs);

    expect(meta?.tone).toBe("warn");
    expect(meta?.title).toBe("До возврата: 1 час");
  });

  // Row 5: overdue + now > plannedEndAt → danger «Просрочено …» (req 3.2).
  it("returns danger overdue meta for overdue booking past plannedEndAt", () => {
    const rental = makeRental({
      status: "overdue",
      plannedEndAt: "2025-01-01T12:00:00Z",
    });
    const nowMs = Date.parse("2025-01-01T13:00:00Z");

    const meta = computeOrderDeadlineMeta(rental, nowMs);

    expect(meta?.tone).toBe("danger");
    expect(meta?.title?.startsWith("Просрочено")).toBe(true);
  });

  // Replacement for rows 6/7: `pickup_ready` with future plannedEnd → warn
  // «До возврата». В отличие от getRentalDeadlineMeta здесь НЕТ под-ветки
  // «Получение через …» — функция всегда падает в "До возврата" для статусов
  // pickup_ready/pickup_opened/active при будущем plannedEnd.
  it("returns warn 'До возврата' meta for pickup_ready booking with future plannedEndAt", () => {
    const rental = makeRental({
      status: "pickup_ready",
      plannedEndAt: "2025-01-01T13:00:00Z",
      startsAt: "2025-01-01T15:00:00Z",
    });
    const nowMs = Date.parse("2025-01-01T11:00:00Z");

    const meta = computeOrderDeadlineMeta(rental, nowMs);

    expect(meta?.tone).toBe("warn");
    expect(meta?.title?.startsWith("До возврата")).toBe(true);
  });

  // Row 8: pickup_opened + now < plannedEndAt → warn «До возврата».
  it("returns warn 'До возврата' meta for pickup_opened booking near start", () => {
    const rental = makeRental({
      status: "pickup_opened",
      plannedEndAt: "2025-01-01T13:00:00Z",
      startsAt: "2025-01-01T11:30:00Z",
    });
    const nowMs = Date.parse("2025-01-01T11:00:00Z");

    const meta = computeOrderDeadlineMeta(rental, nowMs);

    expect(meta?.tone).toBe("warn");
    expect(meta?.title?.startsWith("До возврата")).toBe(true);
  });

  // Row 9: return_in_progress → success «Возврат уже начат» (req 3.4).
  it("returns success 'Возврат уже начат' meta for return_in_progress booking", () => {
    const rental = makeRental({
      status: "return_in_progress",
      plannedEndAt: "2025-01-01T12:00:00Z",
    });
    const nowMs = Date.parse("2025-01-01T13:00:00Z");

    const meta = computeOrderDeadlineMeta(rental, nowMs);

    expect(meta?.tone).toBe("success");
    expect(meta?.title).toBe("Возврат уже начат");
    expect(meta?.text).toBe("Завершите возврат через открытую ячейку постамата.");
  });

  // Row 10: cancelled + now > plannedEndAt — observation-first.
  // На UNFIXED коде cancelled не перехватывается: статус не "return_in_progress"
  // и не попадает в ранний выход, plannedEndAt валиден, diffMs <= 0 → срабатывает
  // ветка danger «Просрочено». Encoding actual unfixed return so preservation
  // baseline holds. После фикса (task 3.1) `isTerminalRentalStatus("cancelled")`
  // возвращает false, поэтому это поведение остаётся валидным и пост-фикс
  // (req 3.5 — окружающий JSX рисует cancellation card на UI-уровне).
  it("returns danger 'Просрочено' meta for cancelled booking past plannedEndAt (preservation, observation-first)", () => {
    const rental = makeRental({
      status: "cancelled",
      plannedEndAt: "2025-01-01T12:00:00Z",
    });
    const nowMs = Date.parse("2025-01-01T13:00:00Z");

    const meta = computeOrderDeadlineMeta(rental, nowMs);

    expect(meta?.tone).toBe("danger");
    expect(meta?.title).toBe("Просрочено на 1 час");
    expect(meta?.text).toBe("Стоит оформить возврат как можно скорее.");
  });
});
