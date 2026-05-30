# Design Document

## Overview

This feature is a focused set of presentation and copy edits to the public marketing
site. There is no backend, data-model, or API impact. The work touches one React
component for the franchise page, one for the site header, and five CSS partials that
make up the global stylesheet.

The design maps each requirement to concrete, minimal edits in specific files. Code
examples use TypeScript/TSX and CSS to match the existing Next.js (App Router) project.

Affected files:

| File | Purpose of change | Requirements |
| --- | --- | --- |
| `web/src/app/franchise/FranchiseClient.tsx` | Metrics figures, entry-threshold copy, 6th placement card, icon import | 2, 3, 4 |
| `web/src/components/AppHeader.tsx` | Add "Франшиза" nav entry (nav array + icon import) | 5 |
| `web/src/app/styles/globals-07.css` | Hero frame base `border-radius` → 0 | 1 |
| `web/src/app/styles/globals-18.css` | Hero frame ≤720px `border-radius` → 0 | 1 |
| `web/src/app/styles/globals-23.css` | Franchise step number+icon on one row; franchise card mobile sizing | 6, 7 |
| `web/src/app/styles/globals-12.css` | Franchise card equal-height mobile sizing | 6 |
| `web/src/app/styles/globals-13.css` | Franchise card equal-height mobile sizing | 6 |

All edits are committed as a single commit and pushed to the current working branch
(never `main`/`master`), per Requirement 8 and the project steering rule.

## Architecture

No architectural change. The franchise page is a client component (`FranchiseClient`)
rendered inside `PageChrome`; data for the page lives in module-level `const` arrays
(`metrics`, `placements`, economics cards as inline JSX). The header is a client
component (`AppHeader`) that derives its desktop and mobile navigation from a single
`nav` array. Styling is a stack of numbered `globals-NN.css` partials cascaded in order,
with later/breakpoint files overriding base rules.

The changes therefore fall into three buckets:

1. **Content/data edits** — string and array literals in `FranchiseClient.tsx` and `AppHeader.tsx`.
2. **Static base CSS edits** — single declarations in `globals-07.css`.
3. **Responsive CSS edits** — declarations inside existing `@media` blocks in `globals-18.css`, `globals-23.css`, `globals-12.css`, `globals-13.css`.

## Components and Interfaces

### 1. HOME hero photo frame — square corners (Req 1)

`.hero-service-media-frame` is defined once in `globals-07.css` (base) and overridden at
`max-width: 400px` in `globals-18.css` (the override the requirement calls the ≤720px
rule; it lives in the narrow-viewport media block).

- **`globals-07.css`** (base rule, currently `border-radius: 24px`):

```css
.hero-service-media-frame {
  width: min(100%, 340px);
  aspect-ratio: 1054 / 1492;
  overflow: hidden;
  border: 1px solid rgba(234, 223, 206, 0.95);
  border-radius: 0;            /* was 24px */
  background: linear-gradient(180deg, rgba(255, 252, 248, 0.98), rgba(255, 247, 240, 0.96));
  box-shadow: 0 22px 44px rgba(63, 42, 24, 0.16);
}
```

- **`globals-18.css`** (inside the existing narrow-viewport `@media` block, currently `border-radius: 14px`):

```css
.hero-service-media-frame {
  border-radius: 0;            /* was 14px */
}
```

Only the two `border-radius` declarations change. `width`, `aspect-ratio`, `overflow`,
`border`, `background`, and `box-shadow` are left untouched (Req 1.3).

### 2. Entry threshold → 550 000 ₽ (Req 2)

Two locations in `FranchiseClient.tsx` plus a no-stale-value check.

- **Metrics_Strip** — first `metrics` array entry value `"от 350 000 ₽"` → `"от 550 000 ₽"`
  (label "стартовые вложения" unchanged):

```tsx
{ value: "от 550 000 ₽", label: "стартовые вложения", note: "* возможен лизинг от партнёра" },
```

- **Economics_Card "Низкий порог входа"** — body text:

```tsx
<strong>Низкий порог входа</strong>
<p>Старт от 550 000 ₽, возможен лизинг оборудования от партнёра.</p>
```

After both edits there must be no remaining `350 000 ₽` substring anywhere in
`FranchiseClient.tsx` (Req 2.3) — verified by a string search over the file.

### 3. Sixth placement card (Req 3)

Append one entry to the `placements` array, after the five existing entries (order
preserved, Req 3.4). The icon must be chosen from the shopping/building family and added
to the lucide import. `Building2` and `Store` are already imported; the existing card
"Прикассовые и розничные зоны" already uses `Store` and mentions "торговые центры", so to
keep icons distinct we add `ShoppingCart` to the import and use it for the new card.

- **Import** in `FranchiseClient.tsx` lucide-react block — add `ShoppingCart`
  (alphabetically near `ShieldCheck`/`Store`):

```tsx
import {
  ArrowRight, Boxes, Building2, CreditCard, Factory, GraduationCap, Hotel,
  MapPinned, PackageCheck, RefreshCw, ShieldCheck, ShoppingCart, Store,
  Timer, TrendingUp, Truck, Users, Wallet,
} from "lucide-react";
```

- **`placements` array** — append sixth entry:

```tsx
const placements = [
  { icon: Building2, title: "Подъезды и холлы ЖК", text: "Большие жилые комплексы с постоянным трафиком жильцов." },
  { icon: Store, title: "Прикассовые и розничные зоны", text: "Магазины у дома, супермаркеты, торговые центры." },
  { icon: GraduationCap, title: "Студенческие общежития", text: "Высокий спрос на технику и вещи на короткий срок." },
  { icon: Hotel, title: "Гостиницы и апарт-отели", text: "Дополнительный сервис для гостей без расходов на штат." },
  { icon: Truck, title: "ПВЗ и коворкинги", text: "Точки выдачи маркетплейсов и рабочие пространства." },
  { icon: ShoppingCart, title: "Торговые центры и гипермаркеты", text: "Высокий пеший трафик и готовая аудитория покупателей рядом с точкой." },
];
```

The placement cards render via `placements.map(...)`, so no JSX change is needed beyond
the array; the sixth card flows into the existing `.benefit-grid` automatically.

### 4. Economics figures in the metrics strip (Req 4)

Update three `metrics` entries and confirm the three old values are gone (Req 4.4). The
profit entry also gets a longer label.

```tsx
const metrics = [
  { value: "от 550 000 ₽", label: "стартовые вложения", note: "* возможен лизинг от партнёра" },
  { value: "до 2,7 млн ₽", label: "выручка в год" },
  { value: "0 ₽", label: "затраты на персонал" },
  { value: "от 55 000 ₽", label: "прибыль в месяц с одного постамата" },
  { value: "7–12 месяцев", label: "окупаемость" },
  { value: "1490 ₽", label: "средний чек" },
];
```

Removed values: `от 85 000 ₽`, `~18 месяцев`, `≈ 3 700 ₽`. The metric tiles render in a
grid via `metrics.map(...)`; the longer profit label wraps within its tile and needs no
layout change. (Note: the "стартовые вложения" value here also satisfies Req 2.2 — the
two requirements edit the same array entry consistently.)

### 5. "Франшиза" navigation link (Req 5)

`AppHeader.tsx` builds both navigations from one `nav` array:

- `desktopNav = nav.filter((item) => item.href !== "/ideas")` — the mobile burger renders
  the full `nav`; the desktop bar renders `desktopNav`.

**Decision (Req 5.4):** Add `Франшиза` to the shared `nav` array. Because `desktopNav`
only filters out `/ideas`, the new entry automatically appears in **both** the desktop bar
and the mobile burger. The desktop bar currently shows four items (Главная, Каталог,
Постаматы, Вопрос-ответ); one additional short label ("Франшиза") fits without removing
any existing item, satisfying 5.4. If horizontal overflow were observed in review, the
fallback would be to filter `/franchise` out of `desktopNav` (same pattern as `/ideas`)
so it stays in the burger only — but the default is to include it on desktop.

Icon: use `Store` from lucide-react (building/shop family, fits the franchise theme). It
is not currently imported in `AppHeader.tsx`, so add it to the import.

- **Import** — add `Store`:

```tsx
import {
  ChevronDown, ChevronRight, CircleUserRound, HelpCircle, Home, Lightbulb,
  LogOut, MapPin, MapPinned, Menu, PackageCheck, ShoppingBag, Store, X,
} from "lucide-react";
```

- **`nav` array** — append the franchise entry (placed after `/faq`, before `/ideas` so
  desktop order reads naturally and `/ideas` remains last/burger-only):

```tsx
const nav = [
  { href: "/", label: "Главная", icon: Home },
  { href: "/catalog", label: "Каталог", icon: ShoppingBag },
  { href: "/lockers", label: "Постаматы", icon: MapPinned },
  { href: "/faq", label: "Вопрос-ответ", icon: HelpCircle },
  { href: "/franchise", label: "Франшиза", icon: Store },
  { href: "/ideas", label: "Идея для аренды", icon: Lightbulb },
] as const;
```

No render-logic change is required: the desktop `desktopLinks.map(...)` and the mobile
`nav.map(...)` both pick up the new entry. Navigation to `/franchise` (Req 5.5) is handled
by the existing `next/link` `Link` wrapper and `isActive` highlighting already in place.

### 6. Uniform franchise card sizing on mobile (Req 6)

Franchise cards are `.benefit-card` inside `.benefit-grid`. Base layout
(`globals-08.css`) already sets each card to `display: grid; align-content: start;
min-height: 156px`. The grid itself (`globals-07.css`) is `display: grid` with equal
columns — CSS Grid items already stretch to the row's height by default (`align-items:
stretch`), so the main risk to equal height on mobile is the `min-height: 0` reset applied
at the narrow breakpoint in `globals-12.css`, which lets cards collapse to differing
content heights.

Approach: keep the grid stretch behavior and restore a consistent minimum height for
`.benefit-card` at the mobile breakpoints, without disturbing padding, border-radius, or
typography (Req 6.3). Two-column rows are the mobile layout (set in `globals-12.css` at
≤680px and `globals-13.css` at ≤440px).

- **`globals-12.css`** (≤680px block) — ensure the grid stretches rows and give cards a
  shared minimum height instead of `min-height: 0`:

```css
.benefit-grid {
  align-items: stretch;
  grid-auto-rows: 1fr;          /* equal-height rows */
}

.benefit-card,
.workflow-card {
  min-height: 132px;            /* was 0 — restore uniform floor */
  gap: 8px;
  padding: 12px;                /* unchanged */
  border-radius: 16px;          /* unchanged */
}
```

- **`globals-13.css`** (≤440px block) — keep the two-column grid stretching and the
  shared floor at the tighter width (cards are smaller here):

```css
.benefit-grid {
  align-items: stretch;
  grid-auto-rows: 1fr;
}

.benefit-card,
.workflow-card {
  min-height: 120px;
  padding: 12px;                /* unchanged */
}
```

- **`globals-23.css`** — franchise-specific cards live in standard `.benefit-grid`
  sections, so they inherit the above. No franchise-only override is required for card
  height; if a franchise section needs a distinct floor it can scope
  `.franchise-economics .benefit-card` / `.franchise-downloads .benefit-card`, but the
  default is to rely on the shared `.benefit-card` rules so all rows match.

`grid-auto-rows: 1fr` combined with the default `align-items: stretch` guarantees cards in
the same row share the tallest card's height; `min-height` provides a consistent floor for
single or short cards. Existing `padding`, `border-radius`, `strong`/`p` font sizes in the
same breakpoint blocks are left as-is (Req 6.3).

### 7. Step number and icon on the same row (Req 7)

The JSX for each step is, in order: `.franchise-step-index` span, `.franchise-step-icon`
span, then a span wrapping `<strong>` (title) + `<small>` (description):

```tsx
<li className="franchise-step">
  <span className="franchise-step-index">01</span>
  <span className="franchise-step-icon"><Icon /></span>
  <span><strong>{title}</strong><small>{text}</small></span>
</li>
```

Currently `.franchise-step` is `display: grid; gap: 8px`, which stacks the three children
vertically (index, then icon, then text block). The goal is index + icon on one horizontal
row, with the title/description block below — **without a JSX restructure**.

Approach: use `grid-template-areas` so the first two children share a top row and the
third child spans a full-width row beneath. This keeps the existing child order and
classes intact.

- **`globals-23.css`** — restructure `.franchise-step` only:

```css
.franchise-step {
  position: relative;
  display: grid;
  grid-template-columns: auto auto;          /* index | icon */
  grid-template-areas:
    "index icon"
    "body  body";
  justify-content: start;                    /* keep index+icon left-aligned, snug */
  align-items: center;                       /* vertically center index with icon */
  column-gap: 10px;
  row-gap: 10px;
  padding: 18px;                             /* unchanged */
  border: 1px solid var(--line);             /* unchanged */
  border-radius: 18px;                       /* unchanged */
  background: var(--surface);                /* unchanged */
}

.franchise-step-index { grid-area: index; }
.franchise-step-icon  { grid-area: icon; }
.franchise-step > span:last-child { grid-area: body; }  /* title + description block */
```

`.franchise-step-index`, `.franchise-step-icon`, and the `strong`/`small` rules keep their
existing typography and sizing. The third child (the text wrapper span) is targeted via
`:last-child` so no JSX class needs to be added. If `:last-child` targeting proves fragile
during implementation, the single minimal JSX change would be adding
`className="franchise-step-body"` to the wrapper span and mapping that to
`grid-area: body` — but the default is the no-JSX-change CSS approach above.

Padding, border, border-radius, and background of `.franchise-step` are unchanged (Req 7.3).

## Data Models

No data models change. The only structured data touched are two in-memory literal arrays
in client components:

- `metrics: { value: string; label: string; note?: string }[]` — three values and one
  label updated; length unchanged (6 entries).
- `placements: { icon: LucideIcon; title: string; text: string }[]` — grows from 5 to 6
  entries.
- `nav: readonly { href: string; label: string; icon: LucideIcon }[]` — grows by one entry.

## Error Handling

Not applicable. These are static content and stylesheet edits with no runtime branching,
I/O, or user input beyond the existing (unchanged) consultation form. The only failure
modes are build-time: a missing icon import (mitigated by adding `ShoppingCart` to
`FranchiseClient.tsx` and `Store` to `AppHeader.tsx` imports) or a TypeScript/JSX syntax
error, both caught by `next build` / type-check during verification.

## Testing Strategy

Verification is example/visual based, consistent with the prework analysis:

- **Type-check / build**: run the project build (`next build` or the repo's lint/type
  script) to confirm no broken imports or JSX after the array and import edits.
- **Content assertions (manual or grep)**:
  - `FranchiseClient.tsx` contains `от 550 000 ₽`, `от 55 000 ₽`,
    `прибыль в месяц с одного постамата`, `7–12 месяцев`, `1490 ₽`, and the
    "Торговые центры и гипермаркеты" card; and contains none of `350 000 ₽`,
    `от 85 000 ₽`, `~18 месяцев`, `≈ 3 700 ₽`.
  - `placements` has 6 entries with the original five first, in order.
  - `AppHeader.tsx` `nav` contains `{ label: "Франшиза", href: "/franchise" }` with
    `Store` imported; the item appears in both the desktop bar and the mobile burger.
- **Visual checks**:
  - HOME hero photo has square corners at desktop and ≤720px widths.
  - Franchise cards in a mobile row render at equal height with unchanged padding/radius/typography.
  - Each franchise step shows the number and icon side by side, with title/description below.
  - Desktop nav shows the new "Франшиза" link without overflowing or dropping items.
- **Process check (Req 8)**: a single commit referencing the `franchise-page-edits` spec
  is pushed to the current working branch, not to `main`/`master`.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid
executions of a system — a formal statement about what the system should do.*

Per the prework analysis, every acceptance criterion in this feature is one of: a static
CSS value/layout change, a fixed copy/data edit, a fixed-size array structural change, a
framework (Next.js routing) behavior, or a git process step. None of these expose a
meaningful "for all inputs X, property P(X) holds" relationship over a non-trivial input
space, and the workflow guidance explicitly excludes UI rendering/layout, simple content
edits, and routing from property-based testing.

**No correctness properties are defined for this feature.** Validation is handled entirely
by the example assertions and visual/manual checks in the Testing Strategy section above,
each tracing back to its requirement.
