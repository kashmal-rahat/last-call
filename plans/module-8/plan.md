# Module 8: Judge demo experience (UI redesign), plan (v1)

> Approved 2026-10-12. Claude plans and reviews; Gemini Flash in Antigravity implements. Follow the steps in order and stop at every 🛑.
>
> **Rules for the coding agent:**
> - **Page only.** Change `services/api/lastcall_api/static/index.html` and add `services/api/lastcall_api/static/demo.css`. **No server, endpoint, model or Terraform change.** Every Module 1–6 test must pass unchanged.
> - **Keep the logic.** The functions in "Keep as they are" below keep their behaviour; you may only change the elements they write into and the class names they use. The flow tested in Module 6 must work exactly as before.
> - **Real data only.** Never show a number, name, model, percentage or claim that doesn't come from an API response. The design mockups contain invented content (see "Never copy from the mockups").
> - All API, Places and Gemini text goes through `textContent`, never `innerHTML`. Full phone numbers never appear (D51, D55).
> - No Tailwind, no CSS framework, no JS framework, no build step. Plain CSS in `demo.css`, plain JS in the page.
> - No commits, pushes or deploys. The user commits and deploys.
> - After each 🛑, report what works, what doesn't and what couldn't be verified, with `uv run pytest`, `node --check` on the extracted inline script, and screenshots at 1280 px and 375 px wide.
>
> **Read first:** `plans/README.md` (D1–D59), this plan, `design/stitch/desktop/` and `design/stitch/mobile/` (`DESIGN.md`, `screen.png`, `code.html`), `plans/module-6/plan.md` Step 7 and `plans/module-6/review.md` (the page behaviour that must keep working).

## Context
The demo works end to end (Modules 1–6, deployed and checked on 2026-10-12), but the page looks like a dark internal dashboard. Judges use it from 18 Oct to 4 Nov, and the submission video and deck show it on almost every frame. The user picked a light, premium design from Stitch (desktop and mobile exports in `design/stitch/`, sharing one `DESIGN.md`).

Module 8 rebuilds the page's look and layout around the existing, tested logic. It adds the pieces the mockups left out: Google Maps attribution, the screened-out list, several items per photo, every state other than the happy path, and an honest impact panel.

## Decision (add as D59 in `plans/README.md`)
| # | Decision | Why |
|---|---|---|
| D59 | **The judge page is rebuilt in the Stitch light design** (`design/stitch/`) as **one responsive page** (one column; the same page on phone and desktop), styled by its own `static/demo.css` built from `DESIGN.md` (no Tailwind CDN). **Sections 3–5 follow one "active item"** picked from the AI reading (default: the top-ranked item; switching is disabled during a live call). The **impact panel counts only this shelf's real call outcomes** (from the batches the page already loads), labelled as demo role-play. **No server change.** Real data only; nothing invented from the mockups | The user's choice of design. One page with an active item tells one clear story per item instead of a long stack of cards. Computing impact from data already on the page needs no endpoint and can't overstate results. Tailwind's CDN script is for development only |

## Never copy from the mockups
These are invented and must not appear: "96.8% Conf", "Brown sugar spots 42%", "Pulp intact · No mould", "Ideal for Milkshakes & Bakeries", "Verified", "Gemini 2.5 Flash · 420ms", "Cavendish", any Urdu translation of a produce name, "Hybrid Salad Tomatoes", the banana emoji in place of the photo, "LIVE CAM", "#LHR-JT-408", "G1 Market", "Sector C", "Main Blvd", "Johar Town Hub", "Judge Session", the avatar, the logo image hosted on Google's servers, "High demand match", "5 Leads Verified", "Runway", "Simulate Call", all impact numbers ("Rs 14,850", "68.5 kg", "91.4% Waste Diverted", "+18% vs manual"), and **"Edhi & Al-Khidmat"** (real charities; naming them would be a false claim). Labels the mockups renamed keep our wording: "Bin capacity (kg, optional)" (not "clearance cap"), "Last hour" (not "1h Flash"), four closing times (not three).

## Keep as they are (behaviour unchanged; only target elements and class names may change)
`getStoredItem`, `setStoredItem`, `generateShelfId`, `getOrCreateShelfId`, `resetShelfId`, `loadSamples`, `loadBranches`, `batchIdFor`, `loadBatchesForBranch`, `isShelfLocked`, `updateShelfLock`, `fetchScoutBuyers`, `rankItems`, `formatObserved`, `formatQuantity`, `formatUncertainFields`, `formatDecisionLine`, `formatProfileLine`, `getFindBuyersLabel`, `getNextStepTargetLabel`, `renderNextActionRow` (restyle only), `triggerDecide`, `handleInspect`, `advanceBatchStep`, `startCallForItem`, `connectWebSocket`, `pollBatchUntilCompleted`, `renderCallResult`, `renderCallPendingResult`, `handleBusyRetry`, `hangup`, `cleanupAudio`, the audio worklets, and every request (`/demo/samples`, `/demo/branches`, `/demo/inspect`, `/demo/decide`, `/demo/scout`, `/demo/calls`, `/demo/batches/...`).
**Rewritten:** the CSS, the HTML skeleton, `renderResults` and `createItemCard` (split into the section renderers below).

## Milestones
- **8A (Steps 1–4):** design system, header and progress, setup, AI reading with the active item, decision. 🛑 The user deploys the API and checks.
- **8B (Steps 5–8):** buyers, live call, impact, mobile polish, final check. 🛑 The user deploys and reruns the Module 6 checklist.
- **8C (Steps 9–12, added 2026-10-12, D60):** the page's script is split into ES modules with tests and polish, after W8 is deployed as the baseline. Its single server change, `Cache-Control: no-cache` on `/static/*` and `/demo`, is the one exception to "page only". Step 8 of 8B (mobile polish and final check) runs after 8C.

**Stop rules:** if the same test fails twice for the same reason, stop and report. Don't change logic to fix a layout problem; ask.

---

# Milestone 8A

### Step 1: Design system (`static/demo.css`)
- Move all styling out of the inline `<style>` into `static/demo.css`, linked as `<link rel="stylesheet" href="/static/demo.css">`. Delete the old dark styles; nothing dark remains except the live-call panel (Step 6).
- Define the tokens from `DESIGN.md` as CSS variables on `:root`:
  - canvas `#F8FAFC`, surface `#FFFFFF`, border `#E2E8F0`, muted border `#F1F5F9`
  - text `#0F172A` / `#334155` / `#64748B`
  - emerald `#059669` / `#10B981`, indigo `#4F46E5`, amber `#F59E0B` / `#D97706`, rose `#E11D48`
  - radii 8 / 12 / 16 / 24 px and pill; the level-1 and level-2 shadows
  - a 4 px spacing scale
- Fonts (Google Fonts, one `<link>`, `display=swap`): Plus Jakarta Sans (headings), Inter (body), JetBrains Mono (prices, quantities, timers, IDs; `font-variant-numeric: tabular-nums`), Noto Nastaliq Urdu (the Urdu transcript and Urdu parts of business names, with `dir="auto"` on those elements).
- Base components to reuse everywhere:
  - `.card` (white, 1 px border, 16–24 px radius, level-1 shadow)
  - `.section-head` (numbered circle + title + right-side chip)
  - `.chip` variants: emerald, indigo, amber, rose, slate
  - buttons: `.btn-primary` (emerald), `.btn-ai` (indigo, for call actions), `.btn-ghost`, `.btn-danger`, each with disabled and focus-visible states
  - `.field` (label + input/select, 8 px radius, emerald focus ring)
  - `.banner` (info, warn, error)
- Light theme only. Keep a visible focus ring on every interactive element.

### Step 2: Header, progress and setup (Section 1)
- **Header** (sticky, white):
  - a text logo "Last Call" with a small inline SVG leaf icon (no external image)
  - a chip with the selected branch name
  - the current Pakistan time (`Asia/Karachi`, updated every minute)
- **Progress bar** under the header (from the mobile design), six segments: 1 Setup, 2 AI reading, 3 Decision, 4 Buyers, 5 Live call, 6 Impact. A segment fills when its step has data:
  - 2: an inspection exists
  - 3: decisions exist
  - 4: the active item has a buyer list
  - 5: any call has started
  - 6: any deal exists
  Clicking a segment scrolls to its section. It is plain text and divs; no animation library.
- **Section 1 "Shelf setup":**
  - access code
  - branch `<select>`
  - **closing time as 4 segmented buttons** (Now (closes 23:00) · Morning, 12 h · Evening, 4 h · Last hour). The existing `closingTimeSelect` stays as the hidden source of truth: a button sets its value and dispatches `change`, and the selected button follows the select, so the existing decide and lock logic is unchanged. On mobile the buttons wrap 2 × 2.
  - bin capacity (kg, optional)
  - the 3 sample photos as thumbnails, and upload
  - the primary "Inspect shelf photo" button
  - the shelf ID with "New shelf"
  - the lock note (D58) under the controls
- **Lock:** `updateShelfLock()` must also disable the segmented buttons. Check it.

### Step 3: AI reading with the active item (Section 2)
- **Left: the real photo** in a dark rounded frame, with the existing bounding boxes restyled (stage colours from the tokens). **Clicking a box selects that item.**
- **Right: one row per item**, in `rankItems` order. Each row shows:
  - name, stage chip and level, a score bar 0–100
  - a "Zoomed in" chip when `zoomed`
  - the selected row is expanded and marked "Active"
- **The expanded active item shows:**
  - evidence
  - issue tags
  - observed count (`formatObserved`)
  - estimated stock (`formatQuantity` + confidence level)
  - `change_note` when present
  - the staff-check flag with `check_reason`
- **The active item:** `activeItemKey`, defaulting to the first item of `rankItems`. It is reset on a new inspection and on New shelf. It can't change while `isCallInProgress`.
- **Banners kept from today:** photo status (no produce / unreadable), photo issues, and the instruction-text warning.
- **Section footer** (small mono text): model, latency, "stored reading reused" when `from_cache`, zoomed groups, hedges.
- **Loading state:** "Reading the shelf with Gemini…" with a skeleton for the item list.

### Step 4: Decision for the active item (Section 3)
- **Ladder stepper:** Keep → Discount → Bulk sale → Donate → Animal feed → Compost.
  - the chosen step is highlighted (emerald, "Active")
  - steps in `next_steps` are marked "Next"
  - steps not in `allowed_steps` are greyed out
  - on mobile it scrolls sideways
- **Price cards** (mono numbers), by step:
  - **discount:** shelf price → discounted price, with "−40%"
  - **bulk sale or animal feed:** three cards: shelf price · AI opening offer · floor, labelled "Floor · never told to the AI"
  - **donate:** "Free to charities"
  - **keep:** shelf price, "Stays at full price"
  - **needs price:** a shelf-price input and "Re-decide" (existing behaviour)
- **Reason line** (`formatDecisionLine` / `reason`), the produce profile line (`formatProfileLine`), and badges: on hold for staff check, needs manager approval, staff actions.
- **A right-side chip** in the section head: hours until closing from the `LadderResult` (e.g. "4 h to closing").
- **Shelf price input and Re-decide** for every item, as today, covered by the lock.
- **Deciding state:** "Deciding…" skeleton.

🛑 **8A report:**
- `uv run pytest`, `node --check`
- screenshots at 1280 px and 375 px: empty page, after inspect, a discount decision, a bulk-sale decision, a locked state
- confirm the closing-time buttons re-decide and lock exactly as the old select did

The user deploys the API (`./scripts/deploy.sh api`) and checks Sections 1–3 on the deployed page.

---

# Milestone 8B

### Step 5: Buyers for the active item (Section 4)
- Shown when the active decision's step is bulk sale, donate or animal feed (as today, using the batch's current step when a batch exists).
- **Section head chip:** "<n> buyers · <branch name>".
- **Controls:**
  - the Find buyers button (label from `getFindBuyersLabel`), with the searching state "Searching Google Maps…"
  - the quantity field, or "Remaining X of Y" once a batch exists
  - the staff-checked checkbox when on hold
  - the copy line "In a real mart, the AI calls these in order on its own; here you play the buyer."
  - the calling-hours note when it applies
- **The next buyer to call** (`next_action` buyer, else rank 1) is an emphasised card ("#1 match" style). It shows:
  - name (`dir="auto"`), type chip, distance, open now / closed now / hours unknown
  - the masked phone **on one line** (`white-space: nowrap`)
  - the fit chip with Gemini's reason, and the facts line
  - "View on Google Maps ↗" (`https://` only, `target="_blank" rel="noopener"`)
  - the call button **"Start call · you play the buyer"**
- **The other buyers** are compact rows with the same facts, plus "Play this buyer" or their status chip (Declined · Deal … @ Rs … · Donated … · Call back … · No answer · Asked not to be called).
- **The next-action row** (`renderNextActionRow`, restyled): Next buyer, Next step, All stock placed, compost approval, no buyers, Search again, Call in progress.
- **Footer** (required by Places policy and D50): **"Results from Google Maps"**, skipped counts in plain words, "Near <branch> · within 10 km", "Searched N min ago" (+ "· reused"), Refresh.
- **"Screened out by Gemini (n)"** collapsible list: name · type · distance — reason.
- Error banner and empty state ("No suitable buyers found nearby") as today.

### Step 6: Live call (Section 5, the only dark panel)
- **A dark card** (`#0F172A`), shown when a call starts and kept with its result after the call. It shows:
  - a status pill (Connecting · Live · Ended) with a call timer counting up (client side)
  - Hang up (`.btn-danger`)
  - the headphones hint
- **Four info tiles:**
  - Buyer: name "(from Google Maps)"
  - Batch: item and quantity
  - Price: opening → floor ("floor never told to the AI"; for a donation: "Free")
  - Pickup: the pickup window
- **Agent audio tile:** a simple CSS bar waveform that animates only while agent audio is arriving (add a class when audio frames arrive; remove it after 400 ms without audio). No audio analysis.
- **Transcript:**
  - agent bubbles on the left, buyer ("You") on the right
  - `dir="auto"`, Noto Nastaliq Urdu for Urdu script, auto-scroll
  - tool events as small chips ("Price check · counter Rs 95")
- **Result strip** at the bottom (from `renderCallResult`): the outcome, "Donated …" or "Deal … @ Rs …", remaining stock, and the next action button.

### Step 7: Impact (Section 6)
- **Totals for this shelf only,** computed in the page from `currentBatchesMap` (every item's batch on the current branch, already loaded by the existing code). For each attempt with outcome deal or partial_deal:
  - **money recovered:** Σ agreed_price × agreed_quantity for steps other than donate (Rs, mono)
  - **stock placed:** Σ agreed_quantity per unit ("1.3 dozen", "12 kg"; never add kg and dozen together)
  - **donated:** Σ quantity for donate
  - **animal feed:** Σ quantity for animal_feed
  - **calls made:** attempts with call status completed
  - **deals closed:** the number of deal attempts
- **Label under the panel:** "From your calls on this shelf · demo role-play, not real sales".
- **When there are no calls yet,** show zeros with the hint "Start a call to see the impact here". No other numbers, no percentages, no charity names.

### Step 8: 🛑 Mobile polish and final check
1. **At 375 px:**
   - no sideways page scroll (only the ladder stepper scrolls inside itself)
   - buttons at least 44 px tall
   - masked phones on one line
   - the transcript readable
   - the progress bar visible under the header
2. **At 1280 px:** the single centred column (max width about 1040 px), as in the desktop mockup.
3. `uv run pytest` green; `node --check` on the inline script.
4. **Report:** screenshots at 1280 and 375 px for each section, including a live call and the impact panel after a deal (or the empty impact state), the list of changed files, and confirmation that no file outside `static/` changed.
5. **The user deploys the API and reruns the Module 6 checklist on the deployed `/demo`:**
   - Find buyers, then Start call
   - decline → Next buyer
   - partial deal → next buyer offered at once
   - "don't call again"
   - Next step → charities → donation
   - Last hour → discount
   - the lock and New shelf
   - `quantity: null`
   - no full phones in the network tab
   Plus: the impact panel matches the deals made, and clicking a photo box changes the active item.

---

## Verification checklist
- **8A:** pytest green; screenshots; the closing-time buttons behave like the old select (re-decide, lock); Sections 1–3 correct on the deployed page.
- **8B:** pytest green; screenshots; the Module 6 checklist passes on the deployed page; Google Maps attribution and the screened-out list visible; impact correct; nothing invented on screen.

## Prompt for the coding agent (paste into a fresh chat)
````text
You are implementing Module 8 (judge demo experience: UI redesign) of "Last Call" in /Users/kashmalrahat/AI-Builder-Cup/last-call. A planner (Claude) wrote the plan; implement it exactly, step by step.

Read first, in this order:
1. plans/README.md: rules and decisions D1–D59 (D59 is this module; D51, D55 and D58 constrain the page).
2. plans/module-8/plan.md: the plan. Follow its steps in order and stop at every 🛑.
3. design/stitch/desktop/ and design/stitch/mobile/: DESIGN.md (tokens), screen.png (look) and code.html (structure reference only; don't copy its Tailwind classes or invented content).
4. plans/module-6/plan.md Step 7 and plans/module-6/review.md: the page behaviour that must keep working.
5. services/api/lastcall_api/static/index.html: the page you rebuild.

Rules:
- Page only: change static/index.html and add static/demo.css. No server, endpoint, model or Terraform change. All tests must pass unchanged.
- Keep the listed logic functions and every request exactly as they behave today; rewrite only the CSS, the HTML skeleton, renderResults and createItemCard.
- Real data only. Never copy the invented mockup content listed in "Never copy from the mockups" (no fake confidence %, no "Gemini 2.5", no impact numbers, no charity names, no avatar or external logo).
- textContent for all API, Places and Gemini text; never innerHTML with data. No full phone numbers anywhere.
- No Tailwind, CSS framework, JS framework or build step.
- No commits, pushes or deploys.
- Start with Milestone 8A (Steps 1–4) and stop at its 🛑 with pytest, node --check and screenshots at 1280 px and 375 px.
- If the same test fails twice for the same reason, stop and report. Don't change logic to fix layout; ask.

Start now with Step 1 (demo.css design system).
````

---

# Milestone 8C: page refactor to ES modules, tests and polish (added 2026-10-12, D60)

> **Why:** after 8A the page works, but it is one 3,070-line file:
> - the buyer renderer alone is 579 lines; 29 global variables
> - 166 inline style assignments in the JavaScript and 43 in the HTML
> - 13 `alert()` pop-ups, 5 silent `catch {}`, no ARIA attributes, emoji used as icons
> - no frontend tests
>
> 8C makes the page as well built as the backend **without changing behaviour**. It is a **mechanical** refactor that the reviewer can verify with a script. It is not a rewrite.
>
> **Order:**
> 1. W8 (review round 3) is fixed, committed and **deployed**. That commit is the baseline and the Cloud Run rollback point; write its hash in the 8C report.
> 2. 8C.
> 3. 8B's remaining polish (Step 8) runs on the new structure.

## Rules for 8C (in addition to the module rules at the top)
- **No framework, no bundler, no build step, no new dependencies.** Native ES modules (`<script type="module">`), which every current browser supports.
- **Function bodies move unchanged.** Only these edits are allowed inside a moved function:
  1. a reference to a former top-level `let` becomes `state.<name>` (e.g. `currentBatchesMap` → `state.currentBatchesMap`)
  2. `alert(msg)` becomes `showToast(msg, 'error')`
  3. in any function, an inline `.style.<prop> = …` line for **looks** (colour, font, spacing, flex, border, outline, opacity…) is replaced by a CSS class. **Only `display` (show/hide, used 66 times, including in logic functions) and geometry (`top`, `left`, `width`, `height`: bounding boxes, score bar) stay inline.** Stage colours on boxes and bars become classes (`.stage-fresh`, `.stage-ripening`, `.stage-overripe`, `.stage-spoiled`, `.stage-unsafe`, plus `.bbox-worst` for the worst-piece outline) instead of `getStageColor()` values
  4. in renderers only: an emoji icon is replaced by `icon('<name>')`
  5. an empty `catch {}` becomes `catch (e) { console.warn('<function name>', e); }`

  Anything else (requests, payloads, conditions, order of calls, close codes, retries, polling, lock logic) must stay identical. The reviewer checks this with a normalising diff against the baseline.
- **Checked by the planner (2026-10-12):**
  - the inline script has no `onclick=` handlers in the HTML
  - it parses in strict mode (modules are always strict) and assigns no undeclared variables
  - the nine helpers planned for `format.js` touch neither the DOM nor shared state
  If you find otherwise, stop and report.
- **No top-level code in any module except `main.js`.** Other modules only declare and export functions and constants. This keeps the circular imports between `call.js`, `buyers.js` and `impact.js` safe: function declarations are hoisted.
- Keep every element ID and every name (functions, state fields) exactly as they are today.

### Step 9: Module layout (`services/api/lastcall_api/static/js/`)
| File | Contents |
|---|---|
| `dom.js` | The 64 element references, `export const <same name> = document.getElementById('<same id>')`. No imports |
| `state.js` | `export const state = { … }`: the 29 former top-level `let`s with their exact initial values. No imports |
| `storage.js` | `getStoredItem`, `setStoredItem`, `generateShelfId`, `getOrCreateShelfId`, `resetShelfId` |
| `format.js` (**pure**: no DOM, no `state`) | `rankItems`, `getStageColor`, `formatObserved`, `formatQuantity`, `formatUncertainFields`, `formatDecisionLine`, `formatProfileLine`, `getFindBuyersLabel`, `getNextStepTargetLabel`, `STAFF_REASON_LABELS`, `STAFF_ACTION_LABELS`, plus the new `computeImpact(batchesMap)` (below) |
| `ui.js` | `icon(name)` (inline SVG built with `document.createElementNS`; names `pin`, `phone`, `lock`, `warning`, `check`, `leaf`, `clock`, `external`); `showToast(message, kind)`, a `role="status"` `aria-live="polite"` toast that hides after 5 s and replaces `alert()` |
| `setup.js` | `updateClock`, `syncClosingTimeButtons`, `loadSamples`, `loadBranches`, `updateHeaderBranch`, `updateProgressBar` |
| `lock.js` | `batchIdFor`, `loadBatchesForBranch`, `isShelfLocked`, `updateShelfLock` |
| `reading.js` | `handleInspect`, `setActiveItem`, `highlightActiveBox`, `renderItemsList`, `renderResults` |
| `decision.js` | `triggerDecide`, `renderActiveDecision` |
| `buyers.js` | `fetchScoutBuyers`, `renderNextActionRow`, `advanceBatchStep`, `renderActiveBuyers` |
| `call.js` | `setStatus`, `appendMessage`, `appendNotice`, `startCallTimer`, `stopCallTimer`, `triggerWaveformAnimation`, `startCallForItem`, `connectWebSocket`, `pollBatchUntilCompleted`, `renderCallResult`, `renderCallPendingResult`, `handleBusyRetry`, `hangup`, `cleanupAudio` |
| `impact.js` | `renderImpact`, now a thin renderer over `computeImpact(state.currentBatchesMap)` |
| `main.js` | Everything that runs at load today: every top-level `addEventListener` (New shelf, closing buttons, closing select, branch, photo input, Inspect, Hang up, Re-decide, Find buyers, access-code input), the saved-code restore, `updateClock()` plus its `setInterval`, `loadSamples()`, `loadBranches()`, `updateProgressBar()`, `renderImpact()`, in today's order |

- **`computeImpact(batchesMap)`** returns `{ revenue, placedByUnit, donatedByUnit, feedByUnit, callsMade, dealsClosed }`. It is the logic inside today's `renderImpact`, moved unchanged, with the same rounding.
- **`index.html`** becomes HTML only: the skeleton, `<link rel="stylesheet" href="/static/demo.css">`, and **one** `<script type="module" src="/static/js/main.js"></script>`. No inline `<script>` and no `style="…"` attributes (move them to classes).
- **Accessibility:**
  - `aria-live="polite"` on the call status and the transcript container
  - `aria-pressed` on the closing-time buttons, updated by `syncClosingTimeButtons`
  - `aria-label` on any button whose text is only an icon
  - every input has a `<label>`

### Step 10: Cache headers (the one server change, `main.py`)
**Why:** browsers can cache the module files and mix an old `call.js` with a new `main.js` after a deploy.
- Add a small HTTP middleware that sets `Cache-Control: no-cache` on responses for paths starting with `/static/` and for `/demo`. `no-cache` still lets the browser revalidate with the ETag, so an unchanged file costs a 304, not a download.
- **Test** (`services/api/tests/test_demo_routes.py`): `GET /static/js/main.js` and `GET /demo` carry `Cache-Control: no-cache`; `GET /health` doesn't need it.

### Step 11: Frontend tests (Node's built-in runner, no packages)
`services/api/tests/js/` (not under `static/`, so the tests aren't served publicly):
- **`format.test.mjs`**, importing `../../lastcall_api/static/js/format.js`:
  - `rankItems` orders a compost item, an off-shelf item, a discount and a keep item as today
  - `formatDecisionLine`: a discount ("Rs 180 → Rs 110 / dozen (−40%)" from `discounted_price` and `discount_pct`), a bulk sale, needs-price
  - `getFindBuyersLabel` and `getNextStepTargetLabel` for each step
  - `computeImpact`:
    - two sales of 0.65 dozen at Rs 110 give revenue 143 and placed 1.3 dozen (not 1.3000000000000003)
    - a donation adds to donated and not to revenue; animal feed adds to feed
    - `pending` attempts are ignored; calls made counts only `completed`
- **`static.test.mjs`**, reading every file in `static/js/` and `static/index.html`:
  - no `innerHTML`, `outerHTML`, `insertAdjacentHTML` or `document.write`
  - no `alert(`
  - no `+92` followed by 9 or more digits (a full phone number)
  - no inline `<script>` without `src` in `index.html`, and no `style="` in `index.html`
  - in `static/js/`, `.style.` is used only for `display`, `top`, `left`, `width`, `height`
- **`services/api/lastcall_api/static/js/package.json`** containing only `{"type": "module"}`, so Node always loads these `.js` files as ES modules in the tests (browsers ignore it).
- **`services/api/tests/test_frontend_js.py`** runs `node --test "services/api/tests/js/*.test.mjs"` (Node expands the glob itself) with `subprocess` and asserts exit code 0. It skips (with a reason) if `node` isn't installed, so `uv run pytest` covers the page too. The Docker image doesn't need Node.

### Step 12: 🛑 Verify and report
1. `uv run pytest` green, including the new JS tests and the cache-header test.
2. **Run the API locally** (`.env` exists) and check in the browser:
   - no console errors on load
   - inspect, decide, Find buyers and the lock work
   - **one real voice call**: you hear the agent, it hears you, Hang up works, the result appears
   - decline, then the highlighted card moves to #2
   - a toast appears where an `alert()` used to be (e.g. clicking Inspect with no photo)
   If you can't run locally, say so; don't claim it works.
3. **Report:**
   - the baseline commit hash
   - the file list with line counts (no file over about 600 lines, except `buyers.js` if it can't be split without changing logic; say so)
   - the pytest summary
   - screenshots at 1280 px and 375 px of every section
   - a list of every function moved, with its new file
4. **Reviewer (Claude):** runs the normalising function diff against the baseline. Then the user commits, deploys the API (`./scripts/deploy.sh api`) and reruns the Module 6 checklist on the live page.

### 8C prompt for the coding agent (paste into the same or a fresh chat)
````text
Implement Milestone 8C in plans/module-8/plan.md (Steps 9–12) for "Last Call" in /Users/kashmalrahat/AI-Builder-Cup/last-call. Read plans/README.md (D60), plans/module-8/plan.md (the 8C section and the module rules at the top) and plans/module-8/review.md first.

This is a MECHANICAL refactor, not a rewrite:
- Split the inline script of services/api/lastcall_api/static/index.html into native ES modules under static/js/ exactly as the Step 9 table says. No framework, bundler, build step or new dependency.
- Move function bodies UNCHANGED. The only allowed edits inside a moved function are the five listed in "Rules for 8C" (state.<name> for former top-level lets; alert → showToast; inline looks-styles → CSS classes, keeping only display and top/left/width/height inline, with stage colours as .stage-* classes; emoji → icon(); empty catch → console.warn). Requests, payloads, conditions, call order, close codes, retries, polling and lock logic must stay identical; the reviewer will diff every function.
- No top-level code outside main.js. Keep every element ID and every function and state name.
- index.html: HTML only, one <script type="module" src="/static/js/main.js">, no style="" attributes.
- Step 10: the Cache-Control: no-cache middleware for /static/* and /demo, with its test.
- Step 11: the node:test tests in services/api/tests/js/, static/js/package.json with {"type": "module"}, and the pytest wrapper (node --test "services/api/tests/js/*.test.mjs").
- Step 12: uv run pytest; run the API locally and make one real voice call; report the baseline commit, files and line counts, screenshots at 1280 and 375 px, and the function-to-file list. If you can't run it locally, say so.
No commits, no deploy. If the same test fails twice for the same reason, stop and report. Don't change logic to fix anything; ask.
````
