import { describe, it, expect } from "vitest";
import { isTerminalRentalStatus } from "../rentalStatus";

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
