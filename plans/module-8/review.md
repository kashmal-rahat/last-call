# Module 8 review: Milestone 8A (2026-10-12)

Reviewer: Claude. Scope: commit `2b61c3d` ("Module 8A: Implementation"), checked against `plan.md`.

Method:
- `uv run pytest`: **367 passed, 19 skipped**; `node --check` on the inline script: OK
- every "Keep as they are" function compared with commit `63109cf` (before 8A), using a script
- the call flow, lock and price-card code read in full
- no agent report and no screenshots were provided
- the live `/health` reports `e04e6c5`, so **nothing from 8A is deployed**, which is good

**Verdict: do not deploy.** The look may be fine, but the plan's main rule was broken: the logic functions were rewritten, not kept. **The live voice call no longer works at all**, the hero feature of the project. The fix is mechanical: restore the original logic and change only the elements it writes into.

---

## What happened
The plan said to keep 31 logic functions unchanged and rewrite only the CSS, the HTML skeleton, `renderResults` and `createItemCard`. The comparison with `63109cf` shows:
- **26 of the 31 were rewritten**, many of them much shorter (for example, `connectWebSocket` went from 3,661 to 1,981 characters and `startCallForItem` from 4,434 to 2,842).
- **`handleBusyRetry` and `renderCallPendingResult` were deleted**, together with the fixes they carried (Module 6 review rounds 2–4).
- **Parts of 8B (buyers, call, impact) were built during 8A,** without the 8A 🛑 report.

## Must fix (blocking)
- **V1. The voice call is broken.**
  - **No microphone audio is sent.** `connectWebSocket` loads `/static/input-processor.js`, a file that doesn't exist (the real files are `capture-worklet.js` and `playback-worklet.js`). It never connects the microphone to a worklet and never sends audio frames.
  - **The agent's voice is never played.** The server sends the agent's audio as **binary** WebSocket frames. The new `onmessage` only parses JSON and waits for an `agent_audio` message that the server never sends. `binaryType` isn't set, and nothing creates a playback node.
  - The `AudioContext` is created at 16 kHz; playback was 24 kHz.
  - Also gone:
    - the server's `interrupted` (clear playback) and `tool` (price check) messages
    - the latency report
    - the `hangup` message to the server
    - the close-code handling: 1013 busy with retry, 4401, 4409, 4423 (P4, B1)
    - the "Saving the call result…" fallback with Refresh
- **V2. Data written into the page as HTML (unsafe, and against the plan's rule).**
  - The price cards (around line 1265–1302) build their content with `innerHTML` from decision data. Line 1302 puts `decision.reason` (which contains the item name from Gemini) into `innerHTML`.
  - A photo with written instructions could inject markup. Every card must be built with `createElement` and `textContent`.
- **V3. The discounted price shows "—" and the percentage is invented.**
  - The page reads `decision.discount_price` (lines 923 and 1269); the field is **`discounted_price`**.
  - It hard-codes "40%" (line 923 and the card label). The real value is `decision.discount_pct`, which is 10–40 depending on the hours left.

## Fix in the same pass
- **V4. Lock regressions (D58).**
  - **Inspect:** `updateShelfLock()` now disables Inspect and the photo upload whenever the shelf is locked. Per D58, a new inspection is also a fresh start, so Inspect stays enabled while locked and is disabled only during a live call or an inspection.
  - **New shelf:** it is no longer disabled during a call or an inspection (the L1 fix is gone).
  - **Shelf prices:** only the active item's price field is locked. Every item's shelf-price input and Re-decide must lock.
- **V5. The 404 lookup is back.** `triggerDecide` calls `loadBatchesForBranch()` again after a decide (Module 6 round 8 removed it). Remove it.
- **V6. `fetchScoutBuyers` no longer refreshes the batch after a search** when calls have already started (Module 6 round 8, item 4). After Next step or Search again, the card can show stale progress. Restore the original function.
- **V7. Silent failures.** With no access code, the call, search and decide functions now `return` silently. The original showed "Please enter your Demo Access Code first" and focused the field. Restore it.

## How to fix (exact)
1. Get the pre-8A page: `git show 63109cf:services/api/lastcall_api/static/index.html > /tmp/old_index.html`.
2. **Copy these functions verbatim** from that file into the new page:
   - `connectWebSocket`, `startCallForItem`, `handleBusyRetry`, `hangup`, `cleanupAudio`
   - `pollBatchUntilCompleted`, `renderCallResult`, `renderCallPendingResult`
   - `fetchScoutBuyers`, `triggerDecide`, `handleInspect`, `advanceBatchStep`
   - `isShelfLocked`, `updateShelfLock`, `renderNextActionRow`
   - `formatDecisionLine`, `formatProfileLine`, `formatObserved`, `formatQuantity`, `formatUncertainFields`
   - `rankItems`, `batchIdFor`, `loadBatchesForBranch`, `getFindBuyersLabel`, `getNextStepTargetLabel`
   - the state variables and constants they use (`audioCtx`, `playbackNode`, `captureNode`, `micStream`, `ws`, `retryCount`, …)
   - `setStatus`, `appendMessage`, `appendNotice`
3. **Then change only:**
   - the element references, pointing them at the new elements; `appendMessage` and `appendNotice` write the new transcript bubbles and chips
   - class names, for the new look
   - the calls to the old `renderResults`, which become calls to the new renderers (`renderItemsList`, `renderActiveDecision`, `renderActiveBuyers`, `renderImpact`, `updateProgressBar`)
   - `updateShelfLock()`, which also disables the segmented closing-time buttons and every item's shelf-price input and Re-decide (V4)
   - the waveform: start `triggerWaveformAnimation()` inside the restored `onmessage` when a **binary** audio frame arrives
4. **Don't change** anything else in those functions: the requests, payloads, close codes, retries and polling.
5. Fix V2 (no `innerHTML` with data) and V3 (`discounted_price`, `discount_pct`) in the new renderers.
6. Run `uv run pytest` and `node --check`. Then **run the API locally** (`.env` exists) and make one real browser call: you hear the agent, it hears you, Hang up works, and the result appears. If you can't run locally, say so; don't claim it works.
7. **Report:**
   - the function comparison: every function in step 2 identical to `63109cf` apart from element and class names, with the diff of each
   - screenshots at 1280 px and 375 px for Sections 1–3, and for whatever of 8B exists
   - the local call result

8B review happens after this, against the plan's Steps 5–8.

---

# Round 2: re-check after the restore (2026-10-12)

Scope: uncommitted changes to `index.html` and `demo.css`. `uv run pytest`: **367 passed, 19 skipped**. `node --check`: OK. The same function comparison as round 1 was run against `63109cf`.

**Verdict: the restore worked; the call logic is back.** Two small 8A leftovers and four problems in the buyer list (8B, built early) remain. Fix them, then deploy for the user's check.

## Fixed
- **V1, the call:**
  - `connectWebSocket` is identical to the original except for one added `triggerWaveformAnimation()` inside the **binary audio** branch, which is the right place
  - `startCallForItem` uses the real worklets at 24 kHz, sets `binaryType = 'arraybuffer'`, and keeps playback, interruptions, tool notices, latency and the close codes
  - `handleBusyRetry`, `hangup`, `pollBatchUntilCompleted` and `renderCallPendingResult` are back
  - the remaining differences are element and class names only
- **Verbatim functions:** `fetchScoutBuyers`, `triggerDecide`, `advanceBatchStep`, `isShelfLocked`, the format helpers, `rankItems`, `batchIdFor`, `loadBatchesForBranch` and the label helpers are word for word the originals. V5 (no lookup after decide), V6 (batch refresh after a search) and V7 (the missing-code prompt) are fixed through them.
- **V2:** no `innerHTML` with data; the price cards use `createElement` and `textContent`.
- **V3:** `discounted_price` and `discount_pct` are used; nothing is hard-coded to 40%.
- **Removed:** no Tailwind, no invented mockup content (no fake confidence, no "Gemini 2.5", no charity names, no external images). "Results from Google Maps" and the screened-out list are present.

## Fix before deploy
- **W1. The closing-time buttons don't lock.**
  - `updateShelfLock()` disables `.closing-time-btn`, but the four buttons in the HTML (around line 97) don't have that class, so the selector matches nothing.
  - **Fix:** add `class="closing-time-btn"` to each, keeping `active` as an extra class on the selected one.
- **W2. The "Start call" card always shows buyer #1.**
  - The highlighted card uses `buyers[0]`. After #1 is called, it still shows #1 with "Start call", so a judge clicking it gets a 409 "Buyer already called in this step". Buyer #1 also never shows its outcome.
  - **Fix:** the highlighted card is the buyer from `batch.next_action` when its kind is `call` (match by `buyer_rank`); with no batch, use `buyers[0]`.
  - The card's label is "#<rank> · Next to call", not a fixed "#1 Match".
  - Every other buyer, **including already-called ones**, appears as a row in rank order.
  - When `next_action` isn't `call`, there is no highlighted card; the next-action row shows what to do.
- **W3. Buyer-row statuses show raw codes and count calls that never started.**
  - Rows show `deal`, `partial_deal`, `do_not_call` as raw text. They must show the plain-word chips from Module 6: "Deal 0.65 dozen @ Rs 110", "Donated 0.8 dozen" (donate step or price 0), "Declined", "Call back <time>", "No answer", "Asked not to be called".
  - An attempt whose `call_status` is `pending` (never connected) must not count as called: show "Play this buyer" again, as `next_action` does.
- **W4. Required buyer details are missing from the rows** (plan Step 5; Places policy).
  - Each row needs: type chip; open now / closed now / hours unknown; masked phone on one line; the fit chip (Likely / Possible) with Gemini's `fit_why`; the facts line (`reason`); and **"View on Google Maps ↗"** (`https://` only).
  - The highlighted card also needs the fit chip label and the facts line.
- **W5. The buyer footer is missing the skipped counts and Refresh.**
  - Add the skipped counts in plain words (e.g. "Skipped: 17 no phone · 6 unlikely", only the non-zero ones).
  - Add a Refresh button: `fetchScoutBuyers(activeItemKey, true)`, disabled during a call.

## Small (same pass)
- **W6. Invented or misleading labels:**
  - "Donated Meals" → "Donated" (we don't count meals)
  - "4h runway" → "4 h to closing" ("Runway" is on the never-copy list)
  - "Produce Rescued" → "Stock placed"
- **W7. Impact panel (plan Step 7):**
  - add **Animal feed** and **Calls made** (attempts with `call_status` completed)
  - round quantities to 2 decimals (0.65 + 0.65 must show 1.3, not 1.3000000000000003)
  - with no deals yet, show "0" plus the hint "Start a call to see the impact here", not "0 kg" (the unit may be dozen)

## Next
1. Fix W1–W7, then run `uv run pytest` and `node --check`.
2. **Local check** (the agent did not report one in round 1):
   - run the API locally and make one browser call: you hear the agent, it hears you, Hang up works, the result appears
   - decline, then confirm the highlighted card moves to #2 and #1 shows "Declined"
3. **Report:** screenshots at 1280 px and 375 px of every section, including a buyer list after one call and the impact panel after a deal.
4. The user commits and deploys the API. That also ships the Module 6 text fixes (`08a2a8b`), which were never deployed (live is still `e04e6c5`).
5. **The user's deployed check:** Sections 1–3 per the 8A 🛑, plus the Module 6 checklist on the new page. If that passes, 8B is reduced to mobile polish and the final check (Step 8).

---

# Round 3: W1–W7 re-check (2026-10-12)

`uv run pytest`: **367 passed, 19 skipped**. `node --check`: OK. The logic functions are still identical to `63109cf` apart from the round-2 element and class changes (re-compared with the same script).

| Item | Status | Checked |
|---|---|---|
| W1 | ✅ | The four buttons have `closing-time-btn`; `updateShelfLock()` locks them |
| W2 | ✅ | The highlighted card is the `next_action` buyer (`buyer_rank`), else `buyers[0]` with no batch; labelled "#<rank> · Next to call"; no card when the action isn't `call`; every other buyer is a row in rank order |
| W3 | ✅ (one edge, W8) | Plain-word chips (Deal … @ Rs …, Donated …, Declined, Call back, No answer, Asked not to be called, Wants photo, Wants manager); pending attempts show "Play this buyer" |
| W4 | ✅ | The card and every row have type, open/closed/unknown, masked phone, fit chip with `fit_why`, the facts line, and "View on Google Maps ↗" (https only, new tab, noopener) |
| W5 | ✅ | The footer shows non-zero skipped counts in plain words and Refresh |
| W6 | ✅ | "Stock placed", "Donated", "<n> h to closing"; "Donated Meals" and "Runway" are gone |
| W7 | ✅ | Animal feed and Calls made added; quantities rounded to 2 decimals; the empty state reads "0" with "Start a call to see the impact here" |

## One small fix
- **W8. A buyer called twice shows the wrong status.**
  - Each row uses `batch.attempts.find(a => a.buyer_id === b.buyer_id)`, i.e. the **first** attempt.
  - If a first try never connected (`pending`) and a second try completed, the row shows "Play this buyer" for a buyer who was already called.
  - **Fix:** use the **last** attempt for that buyer whose `call_status` isn't `pending` (fall back to "Play this buyer" if there is none).

**Verdict: ready to deploy after W8** (a one-line change). Then the user's deployed check: Sections 1–3 (the 8A 🛑), and the full Module 6 checklist on the new page.

---

# Round 4: W8 and the baseline deploy (2026-10-12)

- ✅ **W8:** buyer rows use `batch.attempts.findLast(a => a.buyer_id === b.buyer_id && a.call_status !== 'pending')`, the last non-pending attempt. (`Array.prototype.findLast` works in every current browser: Chrome 97+, Safari 15.4+, Firefox 104+.)
- `uv run pytest`: **367 passed, 19 skipped**; `node --check`: OK.
- **Committed and deployed:** live `/health` reports `a7cfc28`, and the working tree is clean. **`a7cfc28` is the 8C baseline** and the Cloud Run rollback point. It also ships the Module 6 text fixes.
- **Next:** the user's quick live check (one voice call; Sections 1–3), then the 8C prompt.

---

# Round 5: Milestone 8C, the ES-module refactor (2026-10-12)

Scope: commit `cc27443` against the baseline `a7cfc28`. Live `/health` still reports `a7cfc28`, so **8C is committed but not deployed yet**.

Method:
- `uv run pytest`: **369 passed, 19 skipped** (+1 frontend wrapper, +1 cache-header test); `node --test`: **21 passed**
- `node --check` on every module
- a **normalising diff of all 54 functions** against the baseline. It ignores only the allowed edits: the `state.` and `dom.` prefixes, toast for `alert`, CSS-class lines, emoji/`icon()`, logged catches
- import/export resolution, top-level code and bare-reference checks across the modules

**Verdict: approved. The refactor is mechanical, as required. Two small fixes (m1, m2), then deploy.**

## Verified
- **All 54 functions are present.** 42 are identical after normalising. The rest differ only in allowed edits (styles to classes, text nodes next to icons, comments) or in the small items below. **Every call and logic function is identical:**
  - `connectWebSocket`, `startCallForItem`, `handleBusyRetry`, `hangup`, `cleanupAudio`, `pollBatchUntilCompleted`
  - `fetchScoutBuyers`, `triggerDecide`, `advanceBatchStep`, `updateShelfLock`, `batchIdFor`, `loadBatchesForBranch`
  The only text changes are emoji removed from two notices ("Interrupted", "Tool: …").
- **Module safety:**
  - every named import resolves to an export
  - every module that uses `dom.`/`state.` imports them
  - no module except `main.js` runs code at load
  - no shared variable is used without its `state.` prefix
- **Page checks:**
  - `index.html` has exactly one `<script type="module" src="/static/js/main.js">` and **no `style=` attributes**
  - no `alert(`, `innerHTML`, `outerHTML` or `insertAdjacentHTML` in `static/js/`
  - `.style.` only for `display` (53) and geometry (`top`, `left`, `width` ×2, `height`)
- **New code is correct:**
  - `computeImpact` is pure, ignores pending attempts, rounds quantities to 2 decimals and revenue to whole rupees
  - `icon()` builds SVG with `createElementNS` (`aria-hidden`); the toast is `aria-live="polite"`
  - closing-time buttons have `aria-pressed`
- **Cache headers:** the `Cache-Control: no-cache` middleware for `/static/*` and `/demo` has a test.
- **Package file:** `static/js/package.json` (`{"type": "module"}`) is present.

## Fix before deploy (2 minutes)
- **m1. The pytest wrapper fails instead of skipping when Node isn't installed.** `subprocess.run(["node", …])` raises `FileNotFoundError`. Add `if shutil.which("node") is None: pytest.skip("node not installed")` (plan Step 11).
- **m2. `getFindBuyersLabel` changed behaviour.** For a bulk sale it now returns "Find buyers on Google Maps" instead of "Find juice shops & bakeries", and the other labels gained "on Google Maps". The rule was "unchanged".
  - **Fix:** restore the baseline strings ("Find juice shops & bakeries", "Find cattle farms", "Find charities", "Find buyers") and update the matching assertions in `format.test.mjs`.

## Notes (no change needed)
- `resetShelfId` no longer updates the shelf-ID text itself; `main.js` does it right after the call (line ~30). There's only one caller, so the behaviour is the same.
- `handleInspect` now shows a toast when the access code or the photo is missing. That's an improvement and consistent with the toast rule.
- `progressTrack` is looked up in both `dom.js` and `main.js`. Harmless; tidy it when convenient.
- **Not reported by the agent:** the local voice call (Step 12, item 2). The call functions are proven identical, so the remaining risk is browser-only (module loading). The user's live check covers it.

## Next
1. Fix m1 and m2, then run `uv run pytest`.
2. The user commits and deploys the API; check `/health`.
3. **Live check:**
   - no console errors on load (DevTools → Console)
   - **one voice call** (you hear the agent, it hears you, Hang up, result)
   - decline → the card moves to #2
   - the lock and New shelf
   - a toast instead of a pop-up (click Inspect with no photo)
   - Network tab: `main.js` returns `Cache-Control: no-cache`
4. If anything breaks, roll back to the `a7cfc28` revision in Cloud Run.

---

# Round 6: m1 and m2 re-check (2026-10-12)

`uv run pytest`: **369 passed, 19 skipped**.

- ✅ **m1:** `test_frontend_js.py` imports `shutil` and `pytest`, and skips with "node not installed" when `shutil.which("node")` is None.
- ✅ **m2:** `getFindBuyersLabel` is back to the baseline strings ("Find juice shops & bakeries", "Find cattle farms", "Find charities", "Find buyers"), and `format.test.mjs` asserts all four.

**Verdict: 8C is done. The user commits and deploys the API** (live is still `a7cfc28`), then runs the live check from round 5 "Next". Rollback: Cloud Run revision `a7cfc28`.

---

# Round 7: Milestone 8D, premium polish (code review; 2026-10-12)

Scope: uncommitted changes against `fb78667` (live). `uv run pytest`: **369 passed, 19 skipped**; `node --test`: **21 passed**. Every function was diffed against `fb78667`.

**Verdict: the code is right, with one regression (R1, 5 minutes). The visual result still needs screenshots; the agent's were not shared with the reviewer.**

## Verified in code
- **Logic untouched.** Only renderers changed: `renderItemsList`, `renderActiveBuyers`, `renderNextActionRow`, `createPriceCard`, `appendMessage`, `renderResults`. `renderResults` changed only in the bounding-box markup, and `icon()` only in size and stroke. Every logic function (the call, decide, buyer search, lock, polling) is byte-identical.
- **D1:** `.bbox-rect` has `background: transparent` and a 2 px border; the classes are split into `.box-<stage>` (border) and `.dot-<stage>` (dots); the label is a pill with a dot.
- **D2:** one Google Fonts `<link>` (Inter, Plus Jakarta Sans, JetBrains Mono, Noto Nastaliq Urdu, `display=swap`).
- **D3:** `scriptClass()` is applied to names and transcript text.
- **D4:** meta lines are built as "Type · 0.2 km · +92 ••••••• 984".
- **D5:** the level reads "<level> stage".
- **D6:** in the Buyers section, the next-action row shows "Next to call: #n" text instead of a second button.
- **D7:** "<Level> confidence" in words.
- **D8:** mono is in 11 places (to check visually).
- **Section titles and subtitles** follow the spec. Section 3 reads "What happens to produce…", and could name the active item.
- **Spacing:** 48 px between sections, 32 px card padding.

## Fix before deploy
- **R1. The Live-call result lost its "Next buyer" button.**
  - `renderNextActionRow` now always prints "Next to call: #n" text for a `call` action. It is also used for the result strip under the live call (`call.js:391`), so after a decline the judge sees only text there and must scroll back up to the Buyers section to continue.
  - **Fix:** add a parameter, `renderNextActionRow(container, batch, itemKey, buyers = [], showCallButton = false)`.
    - With `showCallButton = true`, a `call` action renders a button "Next buyer · #<rank> <name>" (indigo), which calls `startCallForItem(itemKey, <that buyer's id>)`.
    - `call.js` passes `true`; the Buyers section keeps `false` (its highlighted card has the button).

## Small (optional)
- Section 3 subtitle: "What happens to <active item name>, …" instead of "produce" (set it in `renderActiveDecision`).

## Next
1. Fix R1, then run `uv run pytest`.
2. **Screenshots** (from the agent's report, or the user after deploy) at 1280 px and 375 px:
   - Section 2 with Shelf C (the boxes must show the photo)
   - the Buyers section after one declined call
   - the Live-call result showing "Next buyer"
   - Impact after a deal
   The reviewer checks them against the 8D spec.
3. The user commits and deploys the API. Rollback: `fb78667`.

---

# Round 8: R1 re-check (2026-10-12)

`uv run pytest`: **369 passed, 19 skipped**; `node --test`: **21 passed**. The function diff against `fb78667`: **no logic function changed and none removed**; changes are limited to renderers, plus one new element reference in `dom.js` (`decisionSectionSubtitle`).

- ✅ **R1:**
  - `renderNextActionRow(..., showCallButton = false)`; with `true`, a `call` action renders "Next buyer · #<rank> <name>" (disabled during a call) and calls `startCallForItem(itemKey, <buyer id>)`
  - `call.js` passes `true` with the live buyer list; the Buyers section keeps the text-only version
  - if the buyer can't be matched, the id is undefined and the server picks the next buyer, which is safe
- ✅ **Optional subtitle:** Section 3 reads "What happens to <item>, with prices set by the mart's rules."

**Verdict: the 8D code is complete.** The user commits and deploys the API (rollback `fb78667`), then sends the screenshots listed in round 7 "Next" for the visual check against the 8D spec.

---

# Round 9: visual check of 8D on the deployed page (2026-10-12)

Source: the user's screenshots (AI shelf reading; Buyers). D1 (no-fill boxes), D2 (fonts), D5 ("mid stage"), D7 ("High confidence") and the details grid are visibly fixed. **The page still doesn't look premium**, for these reasons. Each one is specific. **Use the CSS below exactly**; don't redesign.

## Problems
- **V1. Missing CSS rules.**
  - The renderers use `chip-neutral`, `chip-warning` and `dot`, but `demo.css` defines none of them, and the base `.chip` has no background.
  - **Effect:** the stage chip ("Overripe"), the issue tags ("browning", "dark spots"), "2 items detected" and every stage dot render as bare, misaligned text.
- **V2. No spacing between names and chips.** "JuicePandaLikely", "Niazi Juice CornerLikely". "Open now" wraps onto its own line in the highlighted card.
- **V3. Information shown twice.** Each buyer shows the meta line ("Juice shop · 0.6 km · +92 ••••••• 996") and then the code `reason` line ("Juice shop · 0.6 km · open now"). Remove the `reason` line from the card and the rows; keep the meta line and Gemini's `fit_why`.
- **V4. "Next to call: #1 JuicePanda" above the card** repeats the card's own "#1 · Next to call" label. In the Buyers section, a `call` action renders **nothing** (`showCallButton = false` → no text either).
- **V5. The buyer footer is still monospace,** with Refresh on its own line. Use the footer CSS below.
- **V6. Lower-case produce names** ("banana", "apple"). Capitalise the first letter **for display only** (item rows, box labels, the decision subtitle): `name.charAt(0).toUpperCase() + name.slice(1)`.
- **V7. Are the buttons disabled?** In the screenshot, "Find juice shops & bakeries", "Start call" and "Play this buyer" all show the disabled style (opacity 0.5) with no call running. **Agent: check.** These buttons are disabled only by `state.isCallInProgress` (or a search in flight). If the flag stays `true` after a call ends or after a failed `/demo/calls`, report the path; don't change logic without asking. (If the screenshot was taken during a call, this is fine. The user will confirm.)

## Exact CSS (add to `demo.css`, replacing any rule with the same selector)
```css
/* Chips: neutral by default */
.chip { background:#F1F5F9; color:#334155; border:0; }
.chip-neutral { background:#F1F5F9; color:#334155; }
.chip-warning { background:#FFFBEB; color:#B45309; }
.chip-stage { gap:6px; }
.dot { display:inline-block; width:6px; height:6px; border-radius:999px; flex:none; }

/* Headings with chips (item rows, buyer card, buyer rows) */
.item-head, .buyer-head, .buyer-row-title { display:flex; align-items:center; flex-wrap:wrap; gap:8px; }
.item-name, .buyer-heading-name { font:600 16px/24px 'Inter',sans-serif; color:#0F172A; }
.item-stage-level { font:400 13px/20px 'Inter',sans-serif; color:#94A3B8; }
.issues-chips { display:flex; flex-wrap:wrap; gap:8px; }

/* Highlighted buyer */
.buyer-card-top-pick { display:flex; flex-direction:column; gap:12px; padding:24px;
  border:1px solid #C7D2FE; border-radius:16px; background:#FFFFFF; box-shadow:0 0 0 4px #EEF2FF; }
.buyer-card-top-pick .btn-ai { width:100%; height:44px; }

/* Other buyers: content | fixed action column */
.buyer-card-row { display:grid; grid-template-columns:1fr 168px; gap:16px; align-items:center;
  padding:16px 0; border-top:1px solid #F1F5F9; }
.buyer-row-action { justify-self:end; }
.buyer-meta-row, .buyer-row-meta { display:flex; flex-wrap:wrap; align-items:center; gap:4px 8px;
  font:400 13px/20px 'Inter',sans-serif; color:#475569; }
.buyer-row-reason, .buyer-fit-why { font:400 14px/22px 'Inter',sans-serif; color:#475569; }
.buyer-maps-link { color:#4F46E5; text-decoration:none; font-weight:500; }
.buyer-maps-link:hover { text-decoration:underline; }

/* Footer: one quiet line + Refresh on the right */
.buyers-footer { display:flex; justify-content:space-between; align-items:center; gap:16px;
  padding-top:16px; border-top:1px solid #F1F5F9; font:400 12px/18px 'Inter',sans-serif; color:#64748B; }
.buyers-footer .btn-ghost, .buyers-footer .btn-secondary { height:32px; padding:0 12px; font-size:13px; }
.buyers-skipped { font:400 12px/18px 'Inter',sans-serif; color:#94A3B8; margin-top:8px; }

@media (max-width: 640px) {
  .buyer-card-row { grid-template-columns:1fr; }
  .buyer-row-action { justify-self:stretch; }
  .buyer-row-action button { width:100%; height:44px; }
  .buyers-footer { flex-direction:column; align-items:flex-start; }
}
```
**Markup to match (renderers only):**
- the item row header is wrapped in `.item-head`, with name `.item-name`, the stage chip, and `.item-stage-level`
- each buyer header is in `.buyer-head` (card) or `.buyer-row-title` (rows)
- the footer is `.buyers-footer` (text left, Refresh right), with `.buyers-skipped` under it
- **no monospace** in the buyer footer

## Verify
- `uv run pytest` and `node --test` green; the reviewer re-diffs the logic functions (no change allowed).
- Screenshots at 1280 px **and 375 px** of Section 2 (Shelf C) and Section 4 (after one declined call), plus the answer on V7.

---

# Round 10: UI polish done directly by Claude (2026-10-12)

The user asked Claude to make the visual changes directly ("go ahead with the UI"). Scope: `demo.css`, `index.html` markup and **renderer functions only**. The work was checked in a local preview: the real page and API with an in-memory store and fake inspect/scout data from the scratchpad, never committed. It was checked at 1280 px and 375 px.

## Root causes found (beyond round 9)
- **About 40 Tailwind-style utility classes** (`flex`, `items-center`, `gap-2`, `text-sm`, `justify-between`…) were used by the renderers, but the page has no Tailwind, so those layouts did nothing. Several semantic classes didn't match the CSS either: `item-title-group` vs `.item-row-title-group`, `item-def-value` vs `.item-def-val`, and `chip-neutral`, `chip-warning` and `dot` didn't exist.
- **Data bugs in `renderItemsList`:** it read fields that don't exist (`degradation_evidence`, `zoom_source_group`, `change_notes`, `staff_reasons`). So the AI's evidence sentence, the zoom marker, the change since the last photo and the staff-check reasons were never shown. The renderer now uses `evidence`, `zoomed`, `change_note`, `staff_check_reasons` and `check_reason`.
- **"h to closing" was wrong:** it fell back to a hard-coded 2.0 h for "Now"; it now uses `LadderResult.hours_until_closing`.
- **The decision's own reason sentence** (with clock times) wasn't shown; it is now the main line.
- **Skip-reason labels** didn't match the server's `SkipReason` values; they now map to the real values.

## Changes
- **Chips:** neutral by default (no borders), tinted variants, stage dots.
- **AI reading:**
  - item rows: name, stage chip with a dot, "mid stage", a staff-check chip, the score with a thin bar
  - the active item expands into evidence, issue tags, a zoom chip, the facts grid (including "Since last photo") and the staff-check line
  - photo box labels sit inside the box, so they aren't clipped
- **Decision:**
  - plain ladder labels (Keep › Discount › Bulk sale › Donate › Animal feed › Compost)
  - price cards in Plus Jakarta Sans (no monospace)
  - the reason sentence, the real hours to closing
  - no duplicate item chip
- **Buyers:**
  - a highlighted "#n · Next to call" card holds the only call button; rows sit in a content/action grid
  - opening hours as a dot plus text; one meta line ("Type · km · phone · View on Google Maps"); Gemini's reason; plain-word status chips
  - quiet notes instead of stacked banners; footer with Refresh on the same line; skipped counts; the screened-out list
- **Live call:**
  - plain tile labels (Buyer, Stock, Opening price, Floor, Pickup), "Hang up", a calm headphones hint
  - the result card on a dark surface with the "Next buyer" button
- **Impact:** neutral numbers on soft tiles, "Money recovered", the hint and the role-play note on one line.
- **Phone:**
  - no sideways scroll at 375 px
  - the header hides the clock; section heads stack
  - the closing-time buttons wrap 2 × 2; progress labels shorten
- **Fonts:** removed the render-blocking `@import` (the `<link>` in `index.html` loads them).

## Verification
- `uv run pytest`: **369 passed, 19 skipped**; `node --test`: **21 passed**; `node --check` on every module.
- **Function diff against live `d9b7750`:**
  - changed: only `renderNextActionRow` (removed the duplicate "Next to call" text), `renderActiveBuyers`, `createPriceCard`, `renderActiveDecision`, `renderImpact`, `renderItemsList`, `renderResults`
  - new helpers: `buyerHeading`, `buyerMeta`, `buyerFitWhy`, `buyerStatusChip`, `capitalise`, `displayName`
  - **no logic function changed or removed**
- **Not verifiable locally:**
  - real voice audio (the microphone is blocked in the preview browser)
  - real Places and Gemini data
  The user's live check covers both.

---

# Round 11: premium call screen and buyer list, by Claude (2026-10-13)

User feedback on the deployed round-10 page: the live-call panel felt cluttered, and the buyer list "looks just like text". This round redesigns both. It was checked in the local preview (scratchpad harness) at 1280 px and 375 px, with sample transcript lines and a finished deal.

## Live call: now a call screen
- **Header:**
  - a caller avatar with initials, the buyer's name, "Business from Google Maps · the AI speaks Urdu", and a "Live call · you play the buyer" kicker
  - a status pill (dot, state, timer) with a small waveform that moves only while agent audio arrives
  - "Hang up" becomes a quiet outline button once the call ends
- **Body, two columns:**
  - **left, a deal sheet** as a quiet list (Stock, Opening price, Floor + "Never told to the AI", Pickup, headphones hint)
  - **right, the conversation:** speaker labels above the bubbles (AI agent left, You right, indigo), dark scrollbar
  - tool notices in plain words ("Price check · quote", "Deal confirmed", "Outcome recorded"); "Call closed (Code: 1000)" shows as "Call ended"
- **Result banner:** an icon (check or ×), "Deal agreed · 1.3 dozen at Rs 110 / dozen", a sub-line with pickup time and stock left, and the next action under it. Chips are re-tinted for the dark background.
- **Removed:** the five boxed tiles and the large empty "AI agent" box.
- **Phone:** the deal sheet becomes a 2 × 2 grid; "Hang up" doesn't wrap.

## Buyers: a designed list
- **One rounded list container with dividers.** Each row has:
  - a 44 px initials avatar with a rank badge
  - name and an opening-hours dot
  - an icon meta line (type · pin km · phone masked · Google Maps ↗)
  - Gemini's reasoning marked as AI (an indigo "✦ Likely fit" tag + the reason)
  - a right-aligned action or status chip
- **The next buyer is highlighted in place:** tinted background, indigo left rule, "Next to call" eyebrow, and the only "Start call" button.
- **"Remaining 0 of 1.3 dozen" is now a stock-progress bar:** "1.3 of 1.3 dozen placed".
- **Urdu font:** Noto Nastaliq Urdu sits in the body font stack after Inter, so mixed names ("Bholli Juice Corner بھولی جوس کارنر") keep Inter for Latin letters and Nastaliq only for the Urdu ones.

## Verification
- `uv run pytest`: **369 passed, 19 skipped**; `node --test`: **21 passed**; `node --check` on every module.
- **Function diff against live `d9b7750`:**
  - changed: renderers only (`renderNextActionRow`, `renderActiveBuyers`, `appendMessage`, `appendNotice`, `renderCallResult`, `renderCallPendingResult`, `createPriceCard`, `renderActiveDecision`, `renderImpact`, `renderItemsList`, `renderResults`, `icon`)
  - new helpers: `buyerItem`, `buyerStatusChip`, `capitalise`, `displayName`, `initials`, `renderCallerAvatar`
  - **One logic function touched, display only:** in `startCallForItem`,
    - `callBuyerName` shows the name without "(from Google Maps)"; that is now a static label
    - one `renderCallerAvatar(bName)` line was added
    - `callFloorPrice` shows "Rs 65 / dozen"; "Never told to the AI" is now a static note
    No request, payload, flow or timing changed.
- **Not verifiable locally:** real microphone audio (blocked in the preview browser), and real Places and Gemini text lengths.

---

# Round 12: hero and "How it works", by Claude (2026-10-13)

The hero is there so a judge who opens the link cold understands in seconds what Last Call is and where to start. It's markup and CSS only; no JS file changed (`git diff --stat`: `demo.css`, `index.html`).

- **Hero, the first block in `<main>`:**
  - a kicker ("AI Builder Cup 2026 · Retail & Commerce")
  - the `h1`: "An AI that sells your near-expiry produce, by phone, in Urdu". The header brand `h1` became a `div`, so the page has one `h1`.
  - one lead sentence
  - two plain anchor links (`#inspectorSection`, `#howItWorks`), no JS
  - an access-code note and an AI-agent quote with a static waveform
- **Visual:** an example call drawn in HTML (`role="img"` with an `aria-label`): a Gemini flag card ("Bananas · overripe"), three Urdu bubbles, a "Deal agreed" banner. It uses no image file and no real business name ("Juice corner").
- **"How it works":** a 4-step strip (Inspect, Decide, Find buyers, Call). It has 2 columns at ≤900 px, and a compact list on a phone.
- **Fixes:**
  - `.main-layout > section { scroll-margin-top: 80px }`, so anchors and the progress-step scroll clear the sticky header
  - a bug already on live: `.setup-grid` columns `1fr` → `minmax(0, 1fr)`, since at 768 px a long branch name pushed the page to 983 px wide
- **No animations** (the user's decision).
- **Verification:**
  - no sideways scroll at 1280, 768 or 375 px (`scrollWidth == clientWidth`)
  - every `dom.js` element lookup is non-null
  - `pytest`: 369 passed, 19 skipped; `node --test`: 21 passed
