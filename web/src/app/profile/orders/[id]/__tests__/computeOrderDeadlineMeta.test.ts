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

  // Replacement for rows 6/7: `pickup_ready` → warn «Аренда начнётся после
  // получения PIN». В отличие от getRentalDeadlineMeta здесь НЕТ под-ветки
  // «Получение через …»: дату выдачи страница и так печатает строкой
  // «Начало аренды», дублировать её в плашке незачем.
  it("returns warn 'Аренда начнётся…' meta for pickup_ready booking", () => {
    const rental = makeRental({
      status: "pickup_ready",
      plannedEndAt: "2025-01-01T13:00:00Z",
      startsAt: "2025-01-01T15:00:00Z",
    });
    const nowMs = Date.parse("2025-01-01T11:00:00Z");

    const meta = computeOrderDeadlineMeta(rental, nowMs);

    expect(meta?.tone).toBe("warn");
    expect(meta?.title).toBe("Аренда начнётся после получения PIN");
  });

  // Row 8: pickup_opened → та же ветка, что и pickup_ready.
  it("returns warn 'Аренда начнётся…' meta for pickup_opened booking near start", () => {
    const rental = makeRental({
      status: "pickup_opened",
      plannedEndAt: "2025-01-01T13:00:00Z",
      startsAt: "2025-01-01T11:30:00Z",
    });
    const nowMs = Date.parse("2025-01-01T11:00:00Z");

    const meta = computeOrderDeadlineMeta(rental, nowMs);

    expect(meta?.tone).toBe("warn");
    expect(meta?.title).toBe("Аренда начнётся после получения PIN");
    // Срок = plannedEndAt - startsAt = 1 ч 30 мин.
    expect(meta?.text).toBe("Срок (1 час 30 минут) отсчитывается с момента, когда вы заберёте товар.");
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

// Регрессия: жалоба клиента «сутки посчитались с 00 часов» — зеркало кейса из
// getRentalDeadlineMeta.test.ts. До получения PIN `plannedEndAt` посчитан от
// выбранной ДАТЫ (00:00) и будет перезаписан на confirm-pickup, поэтому ни
// обратного отсчёта, ни просрочки на странице заказа быть не должно.
describe("computeOrderDeadlineMeta — regression: preliminary plannedEndAt before pickup", () => {
  it("does not count down to return for pickup_ready booking whose date-only start is already past", () => {
    const rental = makeRental({
      status: "pickup_ready",
      // 21.08.2026 00:00 и 22.08.2026 00:00 по МСК (UTC+3).
      startsAt: "2026-08-20T21:00:00Z",
      plannedEndAt: "2026-08-21T21:00:00Z",
    });
    // 21.08.2026 10:27 МСК — клиент открыл заказ, PIN ещё не получал.
    const nowMs = Date.parse("2026-08-21T07:27:00Z");

    const meta = computeOrderDeadlineMeta(rental, nowMs);

    expect(meta?.tone).toBe("warn");
    expect(meta?.title).toBe("Аренда начнётся после получения PIN");
    expect(meta?.text).toBe("Срок (1 день) отсчитывается с момента, когда вы заберёте товар.");
    expect(meta?.text ?? "").not.toContain("Вернуть до");
  });

  it("does not flag pickup_ready booking as overdue when preliminary plannedEndAt is past", () => {
    const rental = makeRental({
      status: "pickup_ready",
      startsAt: "2026-08-20T21:00:00Z",
      plannedEndAt: "2026-08-21T21:00:00Z",
    });
    // 22.08.2026 01:00 МСК — предварительный дедлайн позади, аренда не начата.
    const nowMs = Date.parse("2026-08-21T22:00:00Z");

    const meta = computeOrderDeadlineMeta(rental, nowMs);

    expect(meta?.tone).not.toBe("danger");
    expect(meta?.title ?? "").not.toContain("Просрочено");
  });

  it("warns about the pickup deadline so the booking does not vanish silently", () => {
    const rental = makeRental({
      status: "pickup_ready",
      startsAt: "2026-08-20T21:00:00Z",
      plannedEndAt: "2026-08-21T21:00:00Z",
      // Дедлайн забора = starts_at + 24 ч, то есть 22.08.2026 00:00 МСК.
      pickupExpiresAt: "2026-08-21T21:00:00Z",
    });
    const nowMs = Date.parse("2026-08-21T07:27:00Z");

    const meta = computeOrderDeadlineMeta(rental, nowMs);

    expect(meta?.tone).toBe("warn");
    expect(meta?.title).toBe("Аренда начнётся после получения PIN");
    expect(meta?.text).toContain("Забрать нужно до");
    expect(meta?.text).toContain("деньги вернутся");
  });

  it("flags an already-missed pickup deadline instead of a silent cancellation", () => {
    const rental = makeRental({
      status: "pickup_ready",
      startsAt: "2026-08-20T21:00:00Z",
      plannedEndAt: "2026-08-21T21:00:00Z",
      pickupExpiresAt: "2026-08-21T21:00:00Z",
    });
    // Шедулер экспирации ещё не добежал (тик раз в 60 с).
    const nowMs = Date.parse("2026-08-21T21:00:30Z");

    const meta = computeOrderDeadlineMeta(rental, nowMs);

    expect(meta?.tone).toBe("danger");
    expect(meta?.title).toBe("Время на получение истекло");
    expect(meta?.text).toContain("деньги вернутся");
  });
});

// Регрессия: реальный пользовательский кейс — пользователь уже сдал товар
// (`actualEndAt` проставлен бэком), но `status` ещё не успел переключиться
// на "completed". Без фикса страница `/profile/orders/[id]` рисовала бы
// «Просрочено на N дней» поверх блока «Фактическое окончание: …», что
// очевидно противоречит данным, отображаемым в той же карточке.
describe("computeOrderDeadlineMeta — regression: actualEndAt suppresses 'Просрочено' overlay", () => {
  it("returns null when actualEndAt is set and status is still 'active'", () => {
    const rental = makeRental({
      status: "active",
      plannedEndAt: "2025-01-02T21:38:00Z",
      actualEndAt: "2025-01-01T21:38:00Z",
    });
    const nowMs = Date.parse("2025-01-03T23:38:00Z");

    const meta = computeOrderDeadlineMeta(rental, nowMs);

    expect(meta).toBeNull();
  });

  it("returns null when actualEndAt is set and status is 'overdue'", () => {
    const rental = makeRental({
      status: "overdue",
      plannedEndAt: "2025-01-02T21:38:00Z",
      actualEndAt: "2025-01-01T21:38:00Z",
    });
    const nowMs = Date.parse("2025-01-03T23:38:00Z");

    const meta = computeOrderDeadlineMeta(rental, nowMs);

    expect(meta).toBeNull();
  });

  it("returns null when actualEndAt is set and status is 'incident'", () => {
    const rental = makeRental({
      status: "incident",
      plannedEndAt: "2025-01-02T21:38:00Z",
      actualEndAt: "2025-01-01T21:38:00Z",
    });
    const nowMs = Date.parse("2025-01-03T23:38:00Z");

    const meta = computeOrderDeadlineMeta(rental, nowMs);

    expect(meta).toBeNull();
  });
});
