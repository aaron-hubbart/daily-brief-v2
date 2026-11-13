# Daily Brief Viewer — Navigation & Layout Redesign

## Intent and why

The viewer has grown five areas (Brief, Environments, Tasks, Day Plan, Account
Health) plus a Settings modal, but the information architecture didn't grow
with it. Today:

- The Brief view (`daily-brief-viewer.html`) is a rich single-page app with a
  topbar, a brief-history timeline, four nav links, and a Settings gear.
- Environments, Tasks, Day Plan, and Account Health are each a **separate,
  full Flask-rendered page** reached via `<a href>` — a real browser
  navigation away from the SPA shell. Each re-declares its own copy of the
  theme CSS and has only a bare "← Back to briefs" link, no way to jump
  directly to a sibling area.
- Settings is a five-tab modal (Setup, Account, Customers, Day Planning,
  Admin) that mixes one-time setup, account-level preferences, and two
  content lists (the Customers/account roster, Day Planning categories) that
  conceptually belong to the Account Health and Day Plan pages, not to
  "Settings."
- The Brief itself is a single long page of stacked, collapsible sections —
  you scroll past everything to get to what you want.

The product is used by a broad group of users (not just power users), so the
navigation needs to be self-explanatory without a learning curve, and the fix
needs to hold up for people who've never seen the old layout.

## Goals

- All five areas (Brief, Environments, Tasks, Day Plan, Account Health) are
  equal, always-visible siblings in the nav — no area is privileged in the
  sidebar, and you can jump directly from any one to any other. (A fresh,
  non-deep-linked visit still has to land somewhere — see Decision 8 below;
  that's a default-route choice, not a nav-privilege one.)
- Moving between areas never triggers a full page reload: in-memory state
  (brief selection, scroll position, light/dark mode, open sections) survives
  switching tabs.
- Settings shrinks to account-level concerns only (Setup, Account, Admin).
  Content configuration (Customers roster, Day Planning categories) lives on
  the page it configures.
- The Brief's sections are navigable without endless scrolling, and a user
  can tell at a glance how much of each section they've worked through.

## Non-goals

- No visual redesign of the content *within* each section/page beyond what's
  needed to support tabs and the sidebar shell (e.g., account-health cards,
  task rows, environment panels keep their current look).
- No change to the underlying data model, brief-generation skill, or any
  `/api/*` response shape beyond what's needed to serve fragments instead of
  full pages.
- No new auth/permissions model — Admin stays gated exactly as it is today.

## Anti-goals

- This should not ship as a bigger rebuild than it needs to be: no
  introducing a frontend framework (React/Vue/etc.) or a build step. The
  existing vanilla-JS + fetch + server-rendered-fragment pattern stays.

## Constraints

- Flask + Jinja + server-rendered fragments is the existing stack; stay in it.
- The app already uses a fetch-and-inject-fragment pattern for dynamic
  content (`tasks_fragment.html`, `morning_plan_fragment.html`,
  `evening_wrapup_fragment.html`, `section_fragment.html`,
  `action_items_fragment.html`) — reuse this pattern rather than inventing a
  new one.
- Broad, non-technical user base: navigation must be discoverable without
  explanation; no behavior that only makes sense if you know the old layout.
- Existing responsive breakpoint at 640px (topbar reflow) is the baseline to
  carry forward for the sidebar's mobile behavior.

## Approaches considered

**A — Shared chrome, keep real page navigations.** Extract one Jinja base
template carrying the sidebar/header/CSS tokens; every page extends it.
Clicking a sidebar item is still a normal full-page browser navigation, but
every page now shares the same chrome and links directly to every sibling.
Lowest engineering risk — mostly template/CSS consolidation, no JS
rework — but doesn't actually stop the "losing my place" feeling: state still
resets on every click, it just resets inside a prettier shell.

**B — One true single-page shell; sidebar clicks swap content via fetch.**
(Chosen.) Keep one shell page (today's `daily-brief-viewer.html`, generalized
beyond "brief viewer"). Environments, Tasks, Day Plan, and Account Health
stop being full pages and become fragments the shell fetches and swaps into
a content area — the same mechanism the brief content and Settings tabs
already use internally. Clicking a sidebar item never reloads the page: open
accordions, scroll position, and light/dark mode persist. Bigger lift —
four routes change from full-page to fragment responses, and client-side
routing (so the back button and deep links still resolve to the right area)
needs real implementation — but it's not new territory for this codebase,
just extending an existing pattern to the top level.

**Why B:** the user's top-ranked pain point was explicitly "losing my place
navigating." A only makes the detour *look* consistent; it doesn't remove
the detour. B removes it.

(A third axis — top tab bar vs. left sidebar for the nav shape itself — was
evaluated visually; left sidebar was chosen. See "Decisions" below.)

## Decisions made in the conversation

1. **Nav shape: left sidebar**, listing Brief, Environments, Tasks, Day Plan,
   Account Health, with a gear icon (Settings) pinned at the bottom. Chosen
   over a top tab bar for a clearer "you are here" affordance and room to
   grow if more areas get added later.
2. **Nav mechanics: Approach B** (true SPA shell, fragment-fetch swapping,
   no full reloads).
3. **Settings reorganized:**
   - Gear icon opens a small panel/modal with only **Setup, Account, Admin**
     (Admin still hidden unless the user is an admin, as today).
   - The **Customers roster** (today's `tab-customers` in Settings) moves
     onto the **Account Health** page as its own panel.
   - **Day Planning categories** (today's `tab-day-planning` in Settings)
     moves onto the **Day Plan** page as its own panel.
4. **Brief content: sections become tabs.** Instead of a vertical stack of
   `<details>` accordions, each section (Action Items, FYI, Customer
   Updates, Key Meetings, Risks, etc. — the section list is server-driven
   and varies per brief) gets its own tab. Only the active tab's content is
   shown — no more scrolling past every section to reach the one you want.
5. **Progress indicator style:** each tab shows a thin progress bar under
   its label, **color-coded by completion** (red → amber → green) plus an
   `x of y` item count, e.g. `FYI 2 of 5` — not a percentage. Chosen after
   two rounds of visual iteration —
   first pass (subtle blue-on-blue shading) was rejected as too low-contrast;
   second pass offered a thicker single-color bar vs. this color-coded
   version, and color-coded + count was picked.
   - **Known risk, accepted:** red at the low end can read as "something's
     wrong" rather than "just not started yet." Mitigation left to the
     builder: consider a neutral gray for the true 0% state and reserve red
     for some-but-little progress, or ship as literally red/amber/green and
     revisit if user feedback says otherwise. This is a small, cheap-to-tweak
     CSS decision, not worth blocking the rest of the design on.
6. **All sections are checkable — superseded from an earlier draft.** Every
   section tab shows an `x of y` count; nothing falls back to a bar-less
   plain tab. This reaches sections that have no checkbox today:
   - `customer-updates` ("Account Updates"): each account card's FYI /
     Action / Risk preview becomes three **independently checkable** lists
     — checking an item strikes it through in the preview, same visual
     language as every other checkbox in the app, but does **not** edit the
     raw draft text underneath (the textarea stays freely editable as its
     own thing). An account card's own mini-progress (e.g. "Acme Corp: 1 of
     4") rolls up across its three buckets; the Account Updates tab's `x of
     y` rolls up across every account card the same way. Confirmed via
     mockup.
   - `account-recap` / `today` "card"-type items (html-content blocks with
     a plain `<li>` Action Items list, or a Team-Standup-style textarea):
     same bucket-checkbox treatment as above where there's a list to attach
     checkboxes to.
   - `manager-update`: a single "drafted" checkbox for the whole update
     (done = you've reviewed/sent it) rather than forcing it through FYI/
     Action/Risk buckets. Its tab shows `0 of 1` / `1 of 1`, not a percentage
     scale — it's a binary, not a count of sub-items.
7. **"Expand all / Collapse all" toolbar scope (my call).** Today it toggles
   every `<details>` on the whole page. Once sections are tabs, it scopes to
   the active tab's content only — there's nothing else on screen to expand.
8. **Default landing area: always Brief.** Loading `/` fresh, or any
   non-deep-linked visit, lands on Brief — same as today. No last-viewed-area
   persistence; that would be new state-storage plumbing not otherwise
   needed, for a marginal gain over a predictable default.

## What's left to the builder

- **Client-side routing.** Pick a concrete mechanism (e.g. `history.pushState`)
  so that clicking a sidebar item updates the URL without a full reload, and
  browser back/forward moves between areas correctly. Old URLs
  (`/tasks`, `/environments`, `/day-plan`, `/account-health`) are not
  required to keep resolving exactly as they do today — breaking them is an
  acceptable cost of this redesign, not a blocker.
- **Converting the four standalone pages into fragments.** For each of
  Environments, Tasks, Day Plan, Account Health: split the existing full
  template into (a) a thin top-level route that returns the full shell with
  that area pre-selected (for direct loads), and (b) a fragment endpoint the
  shell's JS fetches when switching tabs client-side — mirroring how
  `tasks_fragment.html` etc. already work. Each page's page-specific CSS
  needs consolidating into the shell's shared stylesheet/tokens so there's
  one source of truth instead of four duplicated copies of the color
  variables.
- **Sidebar responsive behavior** below the existing 640px breakpoint —
  collapse to an icon rail or a hamburger/drawer; follow whatever the current
  topbar reflow at that breakpoint implies for consistency.
- **Settings panel chrome** once it's down to three tabs — decide whether it
  stays a modal or becomes a lighter popover, and where the "Replay setup
  guide" and Admin-only tab visibility logic land.
- **Account Health page layout** to accommodate the newly-added Customers
  roster panel, and **Day Plan page layout** to accommodate the newly-added
  Day Planning categories panel — both should feel like a natural part of
  the page, not a bolted-on settings leftover.
- **Brief tab bar overflow** — behavior when there are more sections than
  fit in the available width (scroll the tab row, wrap, or collapse into a
  dropdown) is not yet decided; pick whichever matches the sidebar's own
  responsive pattern.
- Exact wording/iconography for the sidebar items and the gear icon.
