# Requirements Document

## Introduction

This feature covers a focused set of UI and content edits across the public marketing site. The changes touch the HOME hero image styling, the franchise landing page content (economics figures, entry threshold, placement cards), site-wide navigation, and mobile layout consistency for franchise cards and numbered steps. All changes are presentation and copy edits with no backend or data-model impact. Per the project workflow rule, the completed edits are committed and pushed to a working branch (not `main`).

## Glossary

- **Hero_Frame**: The styled container `.hero-service-media-frame` that frames the red-locker photo in the HOME hero section, defined in `web/src/app/styles/globals-07.css` and overridden responsively in `web/src/app/styles/globals-18.css`.
- **Franchise_Page**: The franchise landing page rendered by the component in `web/src/app/franchise/FranchiseClient.tsx`.
- **Metrics_Strip**: The top key-figures block on the Franchise_Page driven by the `metrics` array in `FranchiseClient.tsx`.
- **Economics_Card**: A `.benefit-card` element inside the `franchise-economics` section of the Franchise_Page.
- **Placements_List**: The `placements` array in `FranchiseClient.tsx` whose entries render the "Где ставить постамат" placement cards.
- **App_Header**: The site navigation component in `web/src/components/AppHeader.tsx`, including its `nav` array, derived `desktopNav`, and the mobile burger menu.
- **Franchise_Card**: A `.benefit-card` element on the Franchise_Page that renders inside a `.benefit-grid`.
- **Franchise_Step**: A `.franchise-step` list item in the franchise steps section, styled in `web/src/app/styles/globals-23.css`, containing a numeric index (`.franchise-step-index`) and an icon (`.franchise-step-icon`).
- **Mobile_Breakpoint**: A CSS media query for narrow viewports defined in the project breakpoint files (`globals-12.css`, `globals-13.css`, `globals-18.css`, `globals-23.css`).

## Requirements

### Requirement 1: Remove rounding from the HOME hero photo frame

**User Story:** As a visitor on the home page, I want the red-locker hero photo to have square corners, so that the hero image matches the intended sharp visual style on every screen size.

#### Acceptance Criteria

1. THE Hero_Frame SHALL apply `border-radius: 0` in the base rule in `web/src/app/styles/globals-07.css`, replacing the existing `border-radius: 24px`.
2. WHERE the viewport width is at most 720px, THE Hero_Frame SHALL apply `border-radius: 0` in the override in `web/src/app/styles/globals-18.css`, replacing the existing `border-radius: 14px`.
3. THE Hero_Frame SHALL retain its existing dimensions, border, background, and box-shadow declarations unchanged.

### Requirement 2: Update the franchise entry threshold to 550 000 ₽

**User Story:** As a prospective franchise partner, I want the entry threshold figure to read 550 000 ₽ consistently, so that the displayed starting investment matches the current offer.

#### Acceptance Criteria

1. THE Economics_Card titled "Низкий порог входа" SHALL display the text "Старт от 550 000 ₽, возможен лизинг оборудования от партнёра."
2. THE Metrics_Strip entry labeled "стартовые вложения" SHALL display the value "от 550 000 ₽".
3. THE Franchise_Page SHALL contain no remaining occurrence of "350 000 ₽".

### Requirement 3: Add a sixth placement card for shopping centers

**User Story:** As a prospective franchise partner, I want a placement option for shopping centers and hypermarkets, so that I can see that high-traffic retail venues are supported.

#### Acceptance Criteria

1. THE Placements_List SHALL contain a sixth entry with the title "Торговые центры и гипермаркеты".
2. THE sixth Placements_List entry SHALL include descriptive text appropriate to shopping centers and hypermarkets.
3. THE sixth Placements_List entry SHALL use a lucide icon from the shopping or building family (for example `ShoppingCart` or `Building2`).
4. THE Placements_List SHALL retain all five existing entries in their current order.
5. THE imported icon used by the sixth Placements_List entry SHALL be present in the lucide-react import statement in `FranchiseClient.tsx`.

### Requirement 4: Update franchise economics figures in the metrics strip

**User Story:** As a prospective franchise partner, I want the headline economics figures to reflect the current model, so that profit, payback, and average-check values shown match the offer.

#### Acceptance Criteria

1. THE Metrics_Strip entry for monthly profit SHALL display the value "от 55 000 ₽" with the label "прибыль в месяц с одного постамата".
2. THE Metrics_Strip entry labeled "окупаемость" SHALL display the value "7–12 месяцев".
3. THE Metrics_Strip entry labeled "средний чек" SHALL display the value "1490 ₽".
4. THE Metrics_Strip SHALL contain no remaining occurrence of "от 85 000 ₽", "~18 месяцев", or "≈ 3 700 ₽".

### Requirement 5: Add a Франшиза link to site navigation

**User Story:** As a visitor, I want a "Франшиза" entry in the site navigation, so that I can reach the franchise page without using the footer.

#### Acceptance Criteria

1. THE App_Header `nav` array SHALL include an entry with label "Франшиза" and href "/franchise".
2. THE App_Header mobile burger menu SHALL render the "Франшиза" navigation item.
3. THE "Франшиза" navigation entry SHALL use a defined lucide icon present in the `AppHeader.tsx` import statement.
4. WHERE the "Франшиза" item is added to the desktop navigation, THE App_Header desktop navigation SHALL render the existing items plus "Франшиза" without removing any current desktop item.
5. THE App_Header SHALL navigate to the `/franchise` route when the "Франшиза" navigation item is activated.

### Requirement 6: Enforce uniform franchise card sizing on mobile

**User Story:** As a visitor browsing the franchise page on a phone, I want the cards in a row to be the same size, so that the layout looks consistent and aligned.

#### Acceptance Criteria

1. WHERE the viewport is at a Mobile_Breakpoint, THE Franchise_Card elements within the same `.benefit-grid` row SHALL render with equal height.
2. WHERE the viewport is at a Mobile_Breakpoint, THE Franchise_Card elements SHALL share a consistent minimum height and grid alignment defined in the relevant breakpoint files (`globals-12.css`, `globals-13.css`, `globals-23.css`).
3. THE Franchise_Card sizing rules SHALL preserve the existing card padding, border-radius, and typography for the Mobile_Breakpoint.

### Requirement 7: Place the step number and icon on the same row

**User Story:** As a visitor reading the franchise "how it works" steps, I want the step icon to sit beside the step number, so that the number and icon read together on one line instead of stacking.

#### Acceptance Criteria

1. THE Franchise_Step layout in `web/src/app/styles/globals-23.css` SHALL position `.franchise-step-index` and `.franchise-step-icon` on the same horizontal row.
2. THE Franchise_Step SHALL render the step title and description text below the number-and-icon row.
3. THE Franchise_Step SHALL retain its existing padding, border, border-radius, and background.

### Requirement 8: Commit and push the edits to a working branch

**User Story:** As the project maintainer, I want every change committed and pushed to a working branch, so that the edits are tracked in version control without touching `main`.

#### Acceptance Criteria

1. WHEN all edits in this feature are complete, THE developer SHALL commit the changed files with a descriptive message referencing the `franchise-page-edits` spec.
2. THE developer SHALL push the commit to the current working branch on the remote.
3. THE developer SHALL NOT push the commit directly to `main` or `master`.
