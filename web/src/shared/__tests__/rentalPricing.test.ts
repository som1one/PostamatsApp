import { describe, it, expect } from "vitest";
import {
  calculateRentalTotalMinor,
  daysBetweenInclusive,
  progressiveDiscountFraction,
  progressiveDiscountPercent,
} from "../rentalPricing";

// Проверяет соответствие формуле из `backend/utils/rental_pricing.py`.
describe("progressiveDiscountPercent", () => {
  it.each([
    [1, 0],
    [2, 5],
    [3, 10],
    [4, 11],
    [5, 12],
    [6, 13],
    [7, 14],
    [14, 21],
    [17, 24],
    [18, 25],
    [25, 25],
  ] as const)("returns %s%% discount for %s day(s)", (days, expected) => {
    expect(progressiveDiscountPercent(days)).toBe(expected);
  });

  it("returns 0 for non-positive days", () => {
    expect(progressiveDiscountPercent(0)).toBe(0);
    expect(progressiveDiscountPercent(-5)).toBe(0);
  });

  it("returns 0 for non-finite or NaN", () => {
    expect(progressiveDiscountPercent(Number.NaN)).toBe(0);
    expect(progressiveDiscountPercent(Number.POSITIVE_INFINITY)).toBe(0);
  });

  it("caps the discount at 25 percent for very long rentals", () => {
    // Без потолка 30 дней давали бы 10 + 27 = 37%.
    expect(progressiveDiscountPercent(20)).toBe(25);
    expect(progressiveDiscountPercent(30)).toBe(25);
    expect(progressiveDiscountPercent(365)).toBe(25);
  });

  it("floors fractional days", () => {
    expect(progressiveDiscountPercent(2.9)).toBe(5);
    expect(progressiveDiscountPercent(3.1)).toBe(10);
  });
});

describe("progressiveDiscountFraction", () => {
  it("returns the fraction form of the percent discount", () => {
    expect(progressiveDiscountFraction(1)).toBeCloseTo(0, 10);
    expect(progressiveDiscountFraction(2)).toBeCloseTo(0.05, 10);
    expect(progressiveDiscountFraction(3)).toBeCloseTo(0.1, 10);
    expect(progressiveDiscountFraction(7)).toBeCloseTo(0.14, 10);
  });
});

describe("calculateRentalTotalMinor", () => {
  // Базовая цена 100 руб/день = 10_000 минорных единиц.
  const BASE = 10_000;

  it("applies no discount for 1 day", () => {
    // 100 * 1 = 100 ₽ → 10 000 минорных. 1-дневный тариф — это базовый
    // прайс-лист, скидка начинает работать со 2-го дня.
    expect(calculateRentalTotalMinor(BASE, 1)).toBe(10_000);
  });

  it("applies 5% discount for 2 days", () => {
    // 100 * 2 * 0.95 = 190 ₽ → 19 000.
    expect(calculateRentalTotalMinor(BASE, 2)).toBe(19_000);
  });

  it("applies 10% discount for 3 days", () => {
    // 100 * 3 * 0.9 = 270 ₽ → 27 000.
    expect(calculateRentalTotalMinor(BASE, 3)).toBe(27_000);
  });

  it("applies 11% discount for 4 days", () => {
    // 100 * 4 * 0.89 = 356 ₽ → 360 ₽ → 36 000.
    expect(calculateRentalTotalMinor(BASE, 4)).toBe(36_000);
  });

  it("applies 21% discount for 14 days", () => {
    // 100 * 14 * 0.79 = 1106 ₽ → 1110 ₽ → 111 000.
    expect(calculateRentalTotalMinor(BASE, 14)).toBe(111_000);
  });

  it("returns 0 for invalid inputs", () => {
    expect(calculateRentalTotalMinor(0, 5)).toBe(0);
    expect(calculateRentalTotalMinor(BASE, 0)).toBe(0);
    expect(calculateRentalTotalMinor(BASE, -3)).toBe(0);
    expect(calculateRentalTotalMinor(Number.NaN, 5)).toBe(0);
    expect(calculateRentalTotalMinor(BASE, Number.NaN)).toBe(0);
  });

  it("rounds totals to the nearest 10 ₽", () => {
    // 333 ₽/день * 5 * 0.88 = 1465.2 ₽ → 1470 ₽.
    expect(calculateRentalTotalMinor(33_300, 5)).toBe(147_000);
  });

  it("matches the backend to the kopeck", () => {
    // Те же суммы зашиты в backend/tests/test_rental_pricing.py: оценка на
    // странице и сумма предавторизации не должны расходиться.
    expect(calculateRentalTotalMinor(89_900, 9)).toBe(680_000);
    expect(calculateRentalTotalMinor(59_000, 7)).toBe(355_000);
    // 590 * 18 * 0.75 = 7965 ₽ и 1250 * 3 * 0.9 = 3375 ₽ — ровно половина
    // шага, округляется вверх.
    expect(calculateRentalTotalMinor(59_000, 18)).toBe(797_000);
    expect(calculateRentalTotalMinor(125_000, 3)).toBe(338_000);
  });
});

describe("daysBetweenInclusive", () => {
  it("returns 1 when start and end are the same day (single-day rental)", () => {
    expect(daysBetweenInclusive("2026-05-25", "2026-05-25")).toBe(1);
  });

  it("returns 1 for one-night rental (start to next day = one rental day)", () => {
    expect(daysBetweenInclusive("2026-05-25", "2026-05-26")).toBe(1);
  });

  it("returns 2 for two-night rental", () => {
    expect(daysBetweenInclusive("2026-05-25", "2026-05-27")).toBe(2);
  });

  it("returns the night count for a multi-day range", () => {
    // 1 мая → 15 мая = 14 ночей = 14 суток аренды.
    expect(daysBetweenInclusive("2026-05-01", "2026-05-15")).toBe(14);
  });

  it("handles month boundaries correctly", () => {
    // 25 апреля → 5 мая = 10 ночей = 10 суток аренды.
    expect(daysBetweenInclusive("2026-04-25", "2026-05-05")).toBe(10);
  });

  it("returns 0 for inverted ranges", () => {
    expect(daysBetweenInclusive("2026-05-26", "2026-05-25")).toBe(0);
  });

  it("returns 0 for malformed inputs", () => {
    expect(daysBetweenInclusive("", "2026-05-25")).toBe(0);
    expect(daysBetweenInclusive("2026-05-25", "")).toBe(0);
    expect(daysBetweenInclusive("not-a-date", "2026-05-25")).toBe(0);
  });
});
