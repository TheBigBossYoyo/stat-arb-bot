# Dashboard Redesign Report

Polish sprint on `paper-long-only-t212`: turn a functional-but-plain developer UI
into a polished, clearly-organised trading control panel — while keeping every
safety invariant. **NOT LIVE ELIGIBLE** throughout.

## 1. What was ugly or badly organized before?

* Flat, undifferentiated cards; inconsistent spacing and card sizes; no visual
  hierarchy between "the one thing to do today" and background detail.
* Plain-text status everywhere instead of consistent badges.
* The Command Center was a list of similar cards with a one-line "next action"
  and a generic "Go →" button — it did not tell the operator *exactly* what to do.
* Diagnostic pages were read-only markdown dumps with no way to rerun from the UI.
* The Order Preview page had a **standalone "Execute on DEMO…" button** and a
  disabled "GO LIVE" button — confusing and against the gated-only design.
* Sidebar was a single non-collapsible column; the top bar was functional but
  cramped.

## 2. What layout changed?

* **Collapsible, icon-led sidebar** (`Layout.tsx`) with seven labelled groups
  (Command Center, Long-only T212, Supervised Paper, Broker, Risk & Safety,
  Research, System), an active-item accent bar, and a persisted collapsed mode
  (icon rail) for laptops.
* **Compact always-on top status bar**: NOT LIVE ELIGIBLE, mode, product decision,
  kill switch, T212 demo, controls/read-only, backend connection, and the UTC
  clock — all readable at a glance.
* Roomier main content padding; a subtle radial background so the dark canvas has
  depth instead of reading as flat black.

## 3. What design system was added?

A shared, intentional system rather than per-page ad-hoc styling:

* **Tokens** in `index.css`: surface/border colours, card & pop shadows, a shimmer
  skeleton, and a fade-in animation (all respecting `prefers-reduced-motion`).
  Status colour usage is centralised in TypeScript (Badge tones, Button variants)
  so the same concept always renders the same way.
* **`components/ui.tsx`**: `Card` (now with subtitle/icon), `PageHeader`,
  `SectionHeader`, `Badge`, **`StatusBadge`** (semantic status→tone mapping),
  `Button` (8 variants: default/primary/secondary/ghost/success/warning/danger/
  demo + sizes + icons), `Skeleton`, `LoadingSkeleton`, `EmptyState`, `ErrorState`
  (with retry), `Field`, `Tabs`.
* **`components/icons.tsx`**: a dependency-free stroke icon set.
* **`components/ActionCard.tsx`**: the prominent "what to do now" hero card.
* **`components/MetricCard.tsx`**: accent stripes + optional icon.

## 4. What pages were redesigned?

* **Command Center** — rebuilt as a cockpit: a hero **Today's Action** card driven
  by a tested state machine (`lib/todaysAction.ts`), a 6-tile product-status grid,
  a paper-equity chart, and recent reports/actions.
* **Order Preview** — standalone demo/live buttons **removed**; rebuilt around
  *Generate shadow / demo preview* (offline, sends nothing) with target weights,
  planned buys/sells, skipped orders + reasons, cash/slippage/market-hours, and a
  validation-checks tab. Banner: *"Demo execution is only available inside the
  gated supervised paper daily run."*
* **Concentration / Crisis / Survivorship** — rerun buttons (gated on controls),
  metric grids, tabs (result / details / report), CSV, and a crisis scenario chart.
* **Readiness** — new dedicated page: gate scorecard (e.g. 18/18), paper-candidate
  verdict, outstanding gates/notes, and a rerun of the readiness battery.
* **Product Decision** — rerun button + a clear "dashboard actions allowed?"
  indicator.
* **Supervised Paper** — modern page header; existing gated controls preserved.

## 5. What components were added?

`PageHeader`, `SectionHeader`, `StatusBadge`, `ActionCard`, `Tabs`,
`LoadingSkeleton`, an enhanced `ErrorState`/`EmptyState`/`Button`/`MetricCard`,
`charts.ChartCard`, `charts.MiniArea`, `charts.ContributionChart`,
`charts.ScenarioDrawdownChart`, the `icons` set, and the `useControls` /
`computeTodaysAction` helpers.

## 6. What charts/tables were improved?

* A shared chart palette + `ChartCard` container with a built-in empty state.
* New `ScenarioDrawdownChart` (crisis), `ContributionChart`, and `MiniArea`; the
  Command Center renders the paper equity curve.
* Tables continue to use the shared `DataTable` (search, sort, pagination, CSV,
  empty state); the heavier tables now sit behind **tabs** so the first screen is
  a summary, not a wall of rows.

## 7. What empty/loading/error states were added?

* `EmptyState` now carries an icon, hint, and an optional inline action (e.g.
  "Start session"). Used on every page that can be data-empty (no preview yet, no
  reports, no scenarios, nothing skipped, no session).
* `LoadingSkeleton` / shimmer skeletons for loading.
* `ErrorState` summarises the failure with a retry affordance instead of dumping a
  raw stack trace.

## 8. What safety UI remains always visible?

* The top bar shows **NOT LIVE ELIGIBLE** on every page, plus kill-switch and
  controls/read-only state.
* Every operator page carries a NOT LIVE ELIGIBLE badge and/or banner.
* The mode banner asserts "PAPER MODE — no real orders can be placed".
* Order Preview shows the gated-only banner; demo execution is locked to the
  supervised daily run with the exact-phrase modal.

## 9. What actions are easier to find now?

* **Today's required action** is the first, largest element on the Command Center,
  with one primary button to the right page.
* Every diagnostic page has its rerun/compare/download actions in the page header.
* Related actions live together (daily run in Supervised Paper; broker in Trading
  212 Setup; diagnostics under Long-only T212; safety under Risk & Safety; reports
  in Reports Library).
* Button copy is specific ("Rerun long-only readiness", "Generate shadow preview",
  "Run demo execute day…") rather than "Run"/"Submit".

## 10. What still needs visual polish later?

* Secondary/legacy System pages (Strategies, Portfolio, Risk Cockpit, Execution,
  Pairs, Logs, Settings) still use the older `PageTitle` header — they work but
  have not been brought fully onto the new `PageHeader`/`Tabs` system.
* The JS bundle is a single chunk (~790 kB) — code-splitting by route would speed
  first load.
* Mobile/tablet is usable but not optimised; the focus was 1440px desktop and
  laptop screens.
* A couple of charts (benchmark overlay, monthly PnL contribution) are wired in the
  component library but not yet surfaced on every page that could use them.

## Verification

* `npm run typecheck` ✅ · `npm run test:run` ✅ (28) · `npm run build` ✅
* `pytest` ✅ (full suite) · `ruff check .` ✅
