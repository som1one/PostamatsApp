# Implementation Plan

## Overview

Bugfix workflow для дефекта «Завершённые бронирования отображаются как
Просрочено в клиентском веб-интерфейсе».

Порядок: **Exploration → Preservation → Implement → Validate**.

Тестирование — **только vitest unit-тесты, без property-based / fast-check**
(решение пользователя). Каждый тест — детерминированный кейс из таблицы
Behaviour Matrix в design.md.

Файлы, упомянутые из design.md:
- `web/src/app/rentals/RentalsClient.tsx` — `getRentalDeadlineMeta` (~L111).
- `web/src/app/profile/orders/[id]/OrderDetailClient.tsx` — inline IIFE
  (~L581–619), будет вынесено в `computeOrderDeadlineMeta(rental, nowMs)`.
- `web/src/shared/rentalStatus.ts` — НОВЫЙ файл, экспорт `isTerminalRentalStatus`.

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 1, "tasks": ["1"] },
    { "wave": 2, "tasks": ["2"] },
    { "wave": 3, "tasks": ["3.1"] },
    { "wave": 4, "tasks": ["3.2", "3.3"] },
    { "wave": 5, "tasks": ["4"] },
    { "wave": 6, "tasks": ["5"] }
  ]
}
```

Visual:

```
1 (Exploration: tooling + extract IIFE + reproduction tests — must FAIL)
  └── 2 (Preservation: Behaviour-Matrix tests on unfixed code — must PASS)
        └── 3.1 (Implement guard via shared helper)
              ├── 3.2 (re-run reproduction tests — now PASS)
              └── 3.3 (re-run preservation tests — still PASS)
                    └── 4 (Verification: lint + typecheck + vitest + build)
                          └── 5 (Optional manual smoke check)
```

## Tasks

- [x] 1. Bug condition exploration test — wire vitest, extract IIFE, reproduce the user scenario
  - **Property 1: Bug Condition** — Завершённое бронирование с прошедшим plannedEndAt помечается как «Просрочено»
  - **CRITICAL**: This task's user-reproduction test MUST FAIL on UNFIXED code — that failure confirms the bug exists. **DO NOT attempt to fix the test or the production code when it fails in this task.** The same test will be re-run in task 3.2 and is expected to pass after the fix.
  - **GOAL**: Surface a concrete deterministic counterexample that demonstrates the bug exists in BOTH `getRentalDeadlineMeta` (RentalsClient) and `computeOrderDeadlineMeta` (extracted from OrderDetailClient IIFE).
  - **Scoped Approach**: Bug is fully deterministic, so the test scopes the property to ONE concrete failing case (the exact user scenario), not a generated input space.
  - **Sub-step 1.a — Tooling setup** (no behaviour change):
    - Add `vitest` to `web/package.json` `devDependencies` (latest stable, no `fast-check`).
    - Add `"test": "vitest run"` to `web/package.json` `scripts`.
    - If needed for Next.js / TS path resolution, add a minimal `web/vitest.config.ts` that matches the existing `tsconfig.json` `paths` (in particular the `@/` alias used across the codebase). Do not add jsdom unless required — these are pure-function tests and `node` env is sufficient.
    - Run `cd web && npm install` to materialise the new devDep in `package-lock.json`.
  - **Sub-step 1.b — Pure refactor: extract IIFE** (no behaviour change):
    - In `web/src/app/profile/orders/[id]/OrderDetailClient.tsx`, extract the inline deadline-meta IIFE (~L581–619) into a named pure function `computeOrderDeadlineMeta(rental, nowMs)` co-located in the same file (above the component) and `export` it for testing.
    - Replace the JSX block `{(() => { ... })()}` with `{computeOrderDeadlineMeta(order.data, nowMs) ? (... existing JSX using the result ...) : null}` — semantics MUST mirror the original IIFE exactly (same branches, same returned shapes, same icon imports).
    - Verify by inspection that the function body is byte-equivalent to the IIFE body, with `rental` and `nowMs` substituted for what the IIFE was closing over.
  - **Sub-step 1.c — User-reproduction test (the FAILING test)**:
    - Create `web/src/app/rentals/__tests__/getRentalDeadlineMeta.test.ts` with ONE `it()` named `"reproduces user scenario: completed booking with past plannedEndAt is wrongly flagged as overdue"`. Inputs: `status="completed"`, `plannedEndAt="2025-01-01T12:00:00Z"`, `nowMs=Date.parse("2025-01-01T12:01:00Z")`. To make the test runnable, `getRentalDeadlineMeta` may need to be `export`ed from `RentalsClient.tsx` (export the function only — no runtime change).
    - Create `web/src/app/profile/orders/[id]/__tests__/computeOrderDeadlineMeta.test.ts` with the mirror `it()` for `computeOrderDeadlineMeta` using the same inputs.
    - **Assertions in BOTH tests** (encoding the expected post-fix behaviour):
      - `expect(meta?.tone).not.toBe("danger")`.
      - `expect(meta?.title ?? "").not.toContain("Просрочено")`.
      - Equivalent stricter form, also asserted: `expect(meta).toBeNull()`.
  - **Run**: `cd web && npx vitest run` against UNFIXED code.
  - **EXPECTED OUTCOME**: Both `it()` cases FAIL — the unfixed code returns `{ tone: "danger", title: "Просрочено на 1 минуту", ... }`. Document the exact returned object as the counterexample in the task notes / commit message.
  - **Acceptance criteria**:
    - `npm test` (or `npx vitest run`) runs and finds both test files.
    - Both reproduction tests fail with the documented counterexample.
    - No production-code branch logic was changed (only `export`s added and IIFE extracted).
    - `npm run lint` and `npm run typecheck` still pass on the refactor.
  - **Files touched**: `web/package.json`, `web/package-lock.json`, optionally `web/vitest.config.ts`, `web/src/app/rentals/RentalsClient.tsx` (export only), `web/src/app/profile/orders/[id]/OrderDetailClient.tsx` (IIFE → named exported function), `web/src/app/rentals/__tests__/getRentalDeadlineMeta.test.ts` (NEW), `web/src/app/profile/orders/[id]/__tests__/computeOrderDeadlineMeta.test.ts` (NEW).
  - _Bug_Condition: `rental.status = "completed" AND rental.plannedEndAt ≠ NULL AND nowMs > parseDate(rental.plannedEndAt)`_
  - _Requirements: 1.1, 1.2_

- [x] 2. Preservation baseline tests — observation-first, MUST PASS on unfixed code
  - **Property 2: Preservation** — Все небаговые входы из Behaviour Matrix дают ровно то же значение, что и до фикса
  - **IMPORTANT**: Follow observation-first methodology. For each non-bug-condition row of the Behaviour Matrix in design.md, run the UNFIXED code (after the pure refactor in task 1.b — same behaviour), observe what it returns, and encode that observation as a deterministic `expect(...)` in vitest. **DO NOT change production logic in this task.**
  - **EXPECTED OUTCOME on UNFIXED code (post task 1.b)**: All preservation tests PASS — this confirms the baseline behaviour we must preserve after the fix.
  - **Sub-step 2.a — `getRentalDeadlineMeta` Behaviour-Matrix tests**:
    - Extend `web/src/app/rentals/__tests__/getRentalDeadlineMeta.test.ts` with `describe("preservation — Behaviour Matrix", () => { ... })` and one `it()` per non-bug-condition row:
      - `completed` + `now < plannedEndAt` → `null` (req 3.6).
      - `completed` + `plannedEndAt = null` → `null` (preservation).
      - `active` + `now > plannedEndAt` → `tone === "danger"`, `title.startsWith("Просрочено")` (req 3.1).
      - `active` + `now < plannedEndAt` → `tone === "warn"`, `title.startsWith("До возврата")` (req 3.3).
      - `overdue` + `now > plannedEndAt` → `tone === "danger"` (req 3.2).
      - `pickup_ready` + `startsAt > now + 1h` → `tone === "warn"`, `title.startsWith("Получение через")`.
      - `pickup_ready` + `startsAt ≤ now + 1h` (or in past) + `now < plannedEndAt` → `tone === "warn"`, `title.startsWith("До возврата")` (req 3.3).
      - `pickup_opened` + `now < plannedEndAt` → same shape as `pickup_ready` near-start branch (preservation).
      - `return_in_progress` → `tone === "success"`, `title === "Возврат уже начат"` (req 3.4).
      - `cancelled` + any → `null` (helper-level; req 3.5 is enforced by surrounding JSX, unchanged).
    - For each case, observe the actual return value on unfixed code first, then encode it as the expected value.
  - **Sub-step 2.b — `computeOrderDeadlineMeta` Behaviour-Matrix tests**:
    - Extend `web/src/app/profile/orders/[id]/__tests__/computeOrderDeadlineMeta.test.ts` with the mirror `describe("preservation — Behaviour Matrix", () => { ... })` covering the same rows, observing and encoding the actual outputs of the (just-extracted, behaviour-equivalent) function.
  - **Sub-step 2.c — `isTerminalRentalStatus` placeholder note**:
    - At this task's stage `web/src/shared/rentalStatus.ts` does NOT yet exist (created in task 3.1). Therefore do NOT create `rentalStatus.test.ts` here. The 9-row helper table is added as part of task 3.1.
  - **Run**: `cd web && npx vitest run` against UNFIXED code (with task 1.b refactor applied).
  - **EXPECTED OUTCOME**: All preservation `it()` cases PASS. The user-reproduction tests from task 1.c continue to FAIL (still expected at this stage).
  - **Acceptance criteria**:
    - Every non-bug-condition row of the Behaviour Matrix has at least one `it()` for `getRentalDeadlineMeta` AND one for `computeOrderDeadlineMeta`.
    - All preservation `it()` cases PASS on unfixed code.
    - `npm run lint` and `npm run typecheck` still pass.
  - **Files touched**: `web/src/app/rentals/__tests__/getRentalDeadlineMeta.test.ts` (extend), `web/src/app/profile/orders/[id]/__tests__/computeOrderDeadlineMeta.test.ts` (extend).
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 3. Fix for «Завершённые бронирования отображаются как Просрочено»

  - [x] 3.1 Implement the fix
    - Create `web/src/shared/rentalStatus.ts` with:
      ```ts
      export function isTerminalRentalStatus(
        status: string | null | undefined,
      ): boolean {
        return status === "completed";
      }
      ```
      Comment must explicitly note that `cancelled` is NOT included (req 3.5 — see design.md «Out-of-scope»).
    - In `web/src/app/rentals/RentalsClient.tsx`:
      - Import `isTerminalRentalStatus` from `@/shared/rentalStatus`.
      - In `getRentalDeadlineMeta`, immediately AFTER the `return_in_progress` branch and BEFORE the `if (!rental.plannedEndAt) return null;` line, add:
        ```ts
        if (isTerminalRentalStatus(rental.status)) {
          return null;
        }
        ```
    - In `web/src/app/profile/orders/[id]/OrderDetailClient.tsx`:
      - Import `isTerminalRentalStatus` from `@/shared/rentalStatus`.
      - In `computeOrderDeadlineMeta` (the function extracted in task 1.b), apply the SAME guard at the SAME structural position: immediately after the `return_in_progress` branch and before the `plannedEndAt` validity check.
    - Add helper unit tests in NEW file `web/src/shared/__tests__/rentalStatus.test.ts` covering the 9-row table from design.md «Unit Tests → `isTerminalRentalStatus`»: `"completed" → true`; `"cancelled"`, `"active"`, `"overdue"`, `"pickup_ready"`, `"pickup_opened"`, `"return_in_progress"`, `null`, `undefined` → `false`.
    - **Acceptance criteria**:
      - `web/src/shared/rentalStatus.ts` exists, exports `isTerminalRentalStatus`, has the cancelled-exclusion comment.
      - Both production files contain the early-return guard at the documented position; no other branch was modified.
      - `web/src/shared/__tests__/rentalStatus.test.ts` covers all 9 rows and all assertions pass.
      - `npm run lint` (`--max-warnings=0`) and `npm run typecheck` pass.
    - **Files touched**: `web/src/shared/rentalStatus.ts` (NEW), `web/src/shared/__tests__/rentalStatus.test.ts` (NEW), `web/src/app/rentals/RentalsClient.tsx`, `web/src/app/profile/orders/[id]/OrderDetailClient.tsx`.
    - _Bug_Condition: `isBugCondition(rental, nowMs)` from design.md — `rental.status = "completed" AND rental.plannedEndAt ≠ NULL AND nowMs > parseDate(rental.plannedEndAt)`_
    - _Expected_Behavior: For inputs satisfying `isBugCondition`, both `getRentalDeadlineMeta'` and `computeOrderDeadlineMeta'` return `null` (i.e. `tone ≠ "danger"` AND `title` does NOT contain "Просрочено")._
    - _Preservation: For inputs NOT satisfying `isBugCondition`, both functions return values structurally equal to the originals (every row of Behaviour Matrix in design.md)._
    - _Requirements: 2.1, 2.2, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 3.2 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** — Завершённое бронирование с прошедшим plannedEndAt не рисует deadline-плашку
    - **IMPORTANT**: Re-run the SAME tests from task 1.c — do NOT write new tests. The user-reproduction `it()` in `getRentalDeadlineMeta.test.ts` and its mirror in `computeOrderDeadlineMeta.test.ts` already encode the expected post-fix behaviour.
    - Run: `cd web && npx vitest run`.
    - **EXPECTED OUTCOME**: Both user-reproduction tests now PASS — `getRentalDeadlineMeta` and `computeOrderDeadlineMeta` return `null` for `status="completed"`, `plannedEndAt="2025-01-01T12:00:00Z"`, `nowMs=Date.parse("2025-01-01T12:01:00Z")`.
    - **Acceptance criteria**: Both reproduction tests pass; no other test status changed unexpectedly.
    - _Requirements: 2.1, 2.2 (Expected Behavior Properties from design — Property 1)_

  - [x] 3.3 Verify preservation tests still pass
    - **Property 2: Preservation** — Все небаговые входы из Behaviour Matrix дают тот же результат, что и до фикса
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests.
    - Run: `cd web && npx vitest run`.
    - **EXPECTED OUTCOME**: Every preservation `it()` for `getRentalDeadlineMeta` and `computeOrderDeadlineMeta` (and the 9-row `isTerminalRentalStatus` table from task 3.1) PASSES. No regressions.
    - **Acceptance criteria**: All preservation tests green; total vitest output shows zero failures across both test files plus the helper test file.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 4. Verification — full quality gate
  - Run, in order, from `web/`:
    1. `npm run lint` — must pass with `--max-warnings=0`.
    2. `npm run typecheck` — `tsc --noEmit` must succeed.
    3. `npx vitest run` — all tests green, including the user-reproduction case from task 1.c (now passing) and the full Behaviour-Matrix coverage from tasks 2 and 3.1.
    4. `npm run build` — `next build` must complete cleanly.
  - **Acceptance criteria**: All four commands exit with code 0. If any fails, return to the relevant prior task — do NOT mass-edit unrelated code.
  - **Files touched**: none (verification only).
  - _Requirements: validates 1.1, 1.2, 2.1, 2.2, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [ ] 5. (Optional) Manual smoke check on dev server
  - Out of scope for automated CI; perform manually before considering the spec done.
  - User runs `cd web && npm run dev` (port 3001) — agent does NOT start the dev server (long-running command).
  - Navigate to `/rentals` for a user that has a completed booking with `plannedEndAt` in the past:
    - StatusPill shows «Завершено».
    - There is NO `rental-deadline rental-deadline-danger` block / no «Просрочено на …» overlay.
    - There is NO «Оформить возврат как можно скорее» CTA on the card.
  - Navigate to `/profile/orders/[id]` for the same booking — same expectations (no danger overlay, no return-now CTA).
  - As a control: a booking with `status="active"` and `plannedEndAt` in the past STILL shows «Просрочено» (req 3.1).
  - Document the result (✅ / ❌ + screenshot or note) in the spec or commit message.
  - **Acceptance criteria**: Both pages render the completed booking without «Просрочено»; the active-overdue control still renders «Просрочено».
  - **Files touched**: none.
  - _Requirements: end-to-end manual validation of 2.1, 2.2 and regression control for 3.1_

## Notes

### Out of scope (for these tasks)

- Changes to `backend/` (rental_overdue, mark_overdue_rentals, RentalStatus enum).
- Changes to `admin/`.
- Deployment to `root@31.129.97.114` or any server — performed by the user as a separate manual step after this spec is implemented.
- Changing `StatusPill` labels or status mapping in `web/src/shared/format.ts`.
- Refactoring of unrelated duplicated helpers between `RentalsClient.tsx` and `OrderDetailClient.tsx` (e.g. `formatDurationLabel`).
- Treating `cancelled` as a terminal status (blocked by req 3.5).
- Property-based testing / `fast-check` (explicitly excluded by user decision).

### Bugfix workflow conventions used here

- Task 1 is the **exploration** task. Its primary user-reproduction test is
  expected to FAIL on unfixed code — that failure is the success criterion
  for the task, not a bug in the test.
- Task 2 is the **preservation baseline** task. Its tests are expected to
  PASS on unfixed code (observation-first methodology).
- Tasks 3.2 and 3.3 re-run those same tests post-fix; assertions are unchanged.
