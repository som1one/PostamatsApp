# Implementation Plan: Franchise Page Edits

## Overview

A focused set of presentation and copy edits to the public marketing site: square the
HOME hero photo frame, refresh the franchise economics figures and entry threshold, add a
sixth placement card and a "Франшиза" navigation link, make franchise cards equal height
on mobile, and put the step number and icon on one row. There is no backend, data-model,
or API impact.

Most edits touch independent files and can be done in parallel; the only file edited by
more than one task is `web/src/app/franchise/FranchiseClient.tsx` (metrics/economics in
one task, placements in another), which are sequenced to avoid write conflicts. A final
build/type-check verification gates the single commit + push to the working branch.

The design defines no correctness properties (static CSS, fixed copy/array edits, Next.js
routing, git process), so testing is example/grep/build based. Optional verification
sub-tasks are marked with `*`.

## Tasks

- [x] 1. Square the HOME hero photo frame corners
  - [x] 1.1 Set Hero_Frame base `border-radius` to 0 in `web/src/app/styles/globals-07.css`
    - Change `.hero-service-media-frame` `border-radius: 24px` → `border-radius: 0`
    - Leave `width`, `aspect-ratio`, `overflow`, `border`, `background`, `box-shadow` unchanged
    - _Requirements: 1.1, 1.3_

  - [x] 1.2 Set Hero_Frame narrow-viewport override `border-radius` to 0 in `web/src/app/styles/globals-18.css`
    - In the existing ≤720px (`max-width: 400px`) `@media` block, change `.hero-service-media-frame` `border-radius: 14px` → `border-radius: 0`
    - Do not alter any other declaration in the block
    - _Requirements: 1.2, 1.3_

- [x] 2. Update franchise economics figures and entry-threshold copy in `web/src/app/franchise/FranchiseClient.tsx`
  - [x] 2.1 Update the `metrics` array and the "Низкий порог входа" economics card
    - In `metrics`: set "стартовые вложения" value to `"от 550 000 ₽"`; set the monthly-profit entry to value `"от 55 000 ₽"` with label `"прибыль в месяц с одного постамата"`; set "окупаемость" value to `"7–12 месяцев"`; set "средний чек" value to `"1490 ₽"`
    - In the Economics_Card "Низкий порог входа" body, set the text to `Старт от 550 000 ₽, возможен лизинг оборудования от партнёра.`
    - Ensure the file contains no remaining occurrence of `350 000 ₽`, `от 85 000 ₽`, `~18 месяцев`, or `≈ 3 700 ₽`
    - _Requirements: 2.1, 2.2, 2.3, 4.1, 4.2, 4.3, 4.4_

  - [x]* 2.2 Assert economics content (grep over `FranchiseClient.tsx`)
    - Confirm presence of `от 550 000 ₽`, `от 55 000 ₽`, `прибыль в месяц с одного постамата`, `7–12 месяцев`, `1490 ₽`
    - Confirm absence of `350 000 ₽`, `от 85 000 ₽`, `~18 месяцев`, `≈ 3 700 ₽`
    - _Requirements: 2.3, 4.4_

- [x] 3. Add a sixth placement card in `web/src/app/franchise/FranchiseClient.tsx`
  - [x] 3.1 Add the `ShoppingCart` import and append the sixth `placements` entry
    - Add `ShoppingCart` to the `lucide-react` import statement
    - Append a sixth entry after the five existing ones (order preserved): `{ icon: ShoppingCart, title: "Торговые центры и гипермаркеты", text: "Высокий пеший трафик и готовая аудитория покупателей рядом с точкой." }`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x]* 3.2 Assert placements content (grep over `FranchiseClient.tsx`)
    - Confirm `ShoppingCart` is imported and `Торговые центры и гипермаркеты` is present
    - Confirm the five original placement titles still appear in their original order ahead of the new entry
    - _Requirements: 3.1, 3.4, 3.5_

- [x] 4. Add the "Франшиза" navigation link in `web/src/components/AppHeader.tsx`
  - [x] 4.1 Add the `Store` import and the franchise `nav` entry
    - Add `Store` to the `lucide-react` import statement
    - Insert `{ href: "/franchise", label: "Франшиза", icon: Store }` into the `nav` array after the `/faq` entry and before `/ideas`
    - Rely on the existing `desktopNav` filter (only `/ideas` removed) so the item renders in both the desktop bar and the mobile burger; no render-logic change needed
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x]* 4.2 Assert navigation entry (grep over `AppHeader.tsx`)
    - Confirm `Store` is imported and a `nav` entry with `label: "Франшиза"` and `href: "/franchise"` exists
    - Confirm no existing `nav` entry was removed
    - _Requirements: 5.1, 5.3, 5.4_

- [x] 5. Enforce uniform franchise card sizing on mobile
  - [x] 5.1 Add equal-height card rules at ≤680px in `web/src/app/styles/globals-12.css`
    - In the ≤680px block, set `.benefit-grid` to `align-items: stretch; grid-auto-rows: 1fr;`
    - Replace the `.benefit-card` (and `.workflow-card`) `min-height: 0` with a shared floor `min-height: 132px`
    - Keep existing `padding`, `border-radius`, and typography in the block unchanged
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 5.2 Add equal-height card rules at ≤440px in `web/src/app/styles/globals-13.css`
    - In the ≤440px block, set `.benefit-grid` to `align-items: stretch; grid-auto-rows: 1fr;`
    - Set `.benefit-card` (and `.workflow-card`) `min-height: 120px`
    - Keep existing `padding`, `border-radius`, and typography in the block unchanged
    - _Requirements: 6.1, 6.2, 6.3_

- [x] 6. Place the franchise step number and icon on the same row
  - [x] 6.1 Restructure `.franchise-step` with `grid-template-areas` in `web/src/app/styles/globals-23.css`
    - Set `.franchise-step` to a two-column grid with areas `"index icon"` / `"body body"`, `justify-content: start`, `align-items: center`, and column/row gaps
    - Map `.franchise-step-index` → `grid-area: index`, `.franchise-step-icon` → `grid-area: icon`, and `.franchise-step > span:last-child` → `grid-area: body`
    - Keep `.franchise-step` `padding`, `border`, `border-radius`, and `background` unchanged; no JSX change
    - _Requirements: 7.1, 7.2, 7.3_

- [x] 7. Verify, commit, and push
  - [x] 7.1 Run build / type-check and visual-content verification
    - Run the project build or type-check (`next build` or the repo's lint/typecheck script) and fix any broken import or JSX error
    - Confirm the hero frame has square corners, franchise mobile cards are equal height, step number+icon sit on one row, and the desktop nav shows "Франшиза" without dropping items
    - _Requirements: 1.1, 1.2, 3.5, 5.4, 6.1, 7.1_

  - [x] 7.2 Commit and push to the current working branch
    - Stage only the changed files (`globals-07.css`, `globals-18.css`, `globals-12.css`, `globals-13.css`, `globals-23.css`, `FranchiseClient.tsx`, `AppHeader.tsx`) — do not use `git add .`
    - Create a single commit with a descriptive message referencing the `franchise-page-edits` spec
    - Push to the current working branch on the remote; do NOT push to `main`/`master`
    - _Requirements: 8.1, 8.2, 8.3_

## Notes

- Tasks marked with `*` are optional verification sub-tasks and can be skipped for a faster path.
- The design defines no correctness properties, so there are no property-based tests; verification is build/type-check plus content (grep) and visual checks.
- `FranchiseClient.tsx` is written by tasks 2.1 and 3.1; they are scheduled in different waves to avoid write conflicts.
- All edits land in a single commit pushed to the working branch (Requirement 8), per the project steering rule.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "2.1", "4.1", "5.1", "5.2", "6.1"] },
    { "id": 1, "tasks": ["3.1", "4.2"] },
    { "id": 2, "tasks": ["2.2", "3.2"] },
    { "id": 3, "tasks": ["7.1"] },
    { "id": 4, "tasks": ["7.2"] }
  ]
}
```
