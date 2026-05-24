import { describe, it, expect } from "vitest";
import {
  calculateRentalTotalMinor,
  daysBetweenInclusive,
  progressiveDiscountFraction,
  progressiveDiscountPercent,
} from "../rentalPricing";

// Проверяет соответствие формуле, описанной в
// `backend/scripts/add_extra_price_plans.py`.
describe("progressiveDiscountPercent", () => {
  it.each([
    [1, 5],
    [2, 10],
    [3, 15],
    [4, 18],
    [5, 21],
    [6, 24],
    [7, 27],
    [14, 48],
    [18, 60],
    [25, 60],
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

  it("caps the discount at 60 percent for very long rentals", () => {
    // Без cap'a 30 дней давало бы 15 + 27*3 = 96; со старой формулой — тот же
    // потолок, но теперь установлен на 60%.
    expect(progressiveDiscountPercent(20)).toBe(60);
    expect(progressiveDiscountPercent(30)).toBe(60);
    expect(progressiveDiscountPercent(365)).toBe(60);
  });

  it("floors fractional days", () => {
    expect(progressiveDiscountPercent(2.9)).toBe(10);
    expect(progressiveDiscountPercent(3.1)).toBe(15);
  });
});

describe("progressiveDiscountFraction", () => {
  it("returns the fraction form of the percent discount", () => {
    expect(progressiveDiscountFraction(1)).toBeCloseTo(0.05, 10);
    expect(progressiveDiscountFraction(3)).toBeCloseTo(0.15, 10);
    expect(progressiveDiscountFraction(7)).toBeCloseTo(0.27, 10);
  });
});

describe("calculateRentalTotalMinor", () => {
  // Базовая цена 100 руб/день = 10_000 минорных единиц.
  const BASE = 10_000;

  it("applies 5% discount for 1 day", () => {
    // 100 * 1 * 0.95 = 95 ₽ → округление до 10 ₽ = 100 ₽ → 10 000 минорных.
    expect(calculateRentalTotalMinor(BASE, 1)).toBe(10_000);
  });

  it("applies 10% discount for 2 days", () => {
    // 100 * 2 * 0.9 = 180 ₽ → 18 000.
    expect(calculateRentalTotalMinor(BASE, 2)).toBe(18_000);
  });

  it("applies 15% discount for 3 days", () => {
    // 100 * 3 * 0.85 = 255 ₽ → 260 ₽ → 26 000.
    expect(calculateRentalTotalMinor(BASE, 3)).toBe(26_000);
  });

  it("applies 18% discount for 4 days", () => {
    // 100 * 4 * 0.82 = 328 ₽ → 330 ₽ → 33 000.
    expect(calculateRentalTotalMinor(BASE, 4)).toBe(33_000);
  });

  it("applies 48% discount for 14 days", () => {
    // 100 * 14 * 0.52 = 728 ₽ → 730 ₽ → 73 000.
    expect(calculateRentalTotalMinor(BASE, 14)).toBe(73_000);
  });

  it("returns 0 for invalid inputs", () => {
    expect(calculateRentalTotalMinor(0, 5)).toBe(0);
    expect(calculateRentalTotalMinor(BASE, 0)).toBe(0);
    expect(calculateRentalTotalMinor(BASE, -3)).toBe(0);
    expect(calculateRentalTotalMinor(Number.NaN, 5)).toBe(0);
    expect(calculateRentalTotalMinor(BASE, Number.NaN)).toBe(0);
  });

  it("rounds totals to the nearest 10 ₽", () => {
    // 333 ₽/день * 5 * 0.79 = 1315.35 ₽ → 1320 ₽.
    expect(calculateRentalTotalMinor(33_300, 5)).toBe(132_000);
  });
});

describe("daysBetweenInclusive", () => {
  it("returns 1 when start and end are the same day", () => {
    expect(daysBetweenInclusive("2026-05-25", "2026-05-25")).toBe(1);
  });

  it("returns 2 for one-night rental", () => {
    expect(daysBetweenInclusive("2026-05-25", "2026-05-26")).toBe(2);
  });

  it("returns the inclusive day count for a multi-day range", () => {
    expect(daysBetweenInclusive("2026-05-01", "2026-05-15")).toBe(15);
  });

  it("handles month boundaries correctly", () => {
    // 25 апреля → 5 мая = 11 календарных дней включительно.
    expect(daysBetweenInclusive("2026-04-25", "2026-05-05")).toBe(11);
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
