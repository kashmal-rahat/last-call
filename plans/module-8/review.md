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

---

# Round 13: calmer hero, step cards, progress bar removed, by Claude (2026-10-13)

User feedback: the hero felt cluttered.
- **Hero:**
  - The lead sentence is now "reads your shelf from a photo … then calls and negotiates with them in the local language (Urdu)", with no bold text.
  - Removed: the "See how it works" button, the access-code note, and the quoted AI line with its waveform (and their CSS).
- **"How it works":** four separate cards, with the numbered circles joined by a line (desktop: horizontal, first to last circle; phone: a short vertical connector between steps). Step 4 is now "Call and negotiate". Markup is an `<ol>`.
- **Progress bar removed** (the user judged it useless). That removed the markup, its CSS, the 7 `dom.js` lookups, `updateProgressBar` (`setup.js`) and its 4 calls (`main.js`, `reading.js`), the click-to-scroll handler (`main.js`), and the `progressTrack` assertion and export-list entry in `static.test.mjs`.
  - **The JS diff is deletions only;** no other logic changed.
- **Verification:**
  - preview flow: sample → Inspect (3 items, decision shown) → Find buyers (5 buyers, next highlighted), with no JS errors (only the expected 404s for "no batch yet")
  - no sideways scroll at 1280, 768 or 375 px
  - `pytest`: 369 passed, 19 skipped; `node --test`: 21 passed; `node --check` on every module
- **Follow-up (same round, after the user's local check):** the connector line looked busy, so it's gone. Each step is now one card with its number badge inside (`.how-step` is the card; `.how-card` was removed). 4 columns, 2 at ≤900 px, 1 at ≤560 px. No JS change; `node --test` passes 21.
- **Second follow-up:** the number is now a 24 px outlined circle (1.5 px emerald border, 12 px digit) instead of a 32 px filled square. The cards are tighter: padding 18×20 (16×18 on a phone), radius 14, 12 px above the title.

---

# Round 14: "closing time" hero, by Claude (2026-10-14)

User feedback: the hero's dark chat card, and two replacements tried in this round (a shelf photo with floating cards, a line-art sketch), all looked "like a uni project". All three tried to explain the pipeline inside the picture. We looked at the live heroes of Sierra, ElevenLabs Agents, Decagon and Bland. They share: one atmosphere instead of a diagram, at most one piece of product UI, light-weight headlines, one call to action.

- **Hero:** a **full-width** dusk band directly under the header, "the last hour before closing", built from the page's own colours:
  - slate navy `#0F172A` (the call panel) into deep indigo (the AI and call colour)
  - one muted apricot horizon (the only new tone)
  - fine SVG grain so it reads as sky
  Its content sits on the same 1040 px column as the sections below:
  - the `h1` in Plus Jakarta Sans **500** (weight added to the existing Google Fonts link), white, no accent phrase, three lines ("near-expiry" never breaks)
  - the lead sentence from round 13
  - one emerald pill, "Try the live demo"
  The right side is left empty on purpose (the user's choice, after trying one frosted-glass call bubble there).
- **Markup:** `<main>` now holds the first-screen wrapper (hero band and steps), then `<div class="main-layout">` with the sections (it was `<main class="main-layout">`), so the band can span the full width. No JS or test referred to the old element.
- **"How it works" rests on the horizon:** the four separate cards became **one white panel** whose top overlaps the bottom of the band (`--how-overlap`: 96 px, 40 px on a phone; a more compact version was tried and reverted at the user's request; the hero's bottom padding leaves that room). Hairlines between the steps come from a 1 px grid gap over the border colour, so they are right in 4, 2 or 1 columns. On a phone each step puts its number beside the text. The markup is unchanged.
- **Follow-up (after the first commit):** the kicker line is gone; "by phone, in Urdu" is mint `#6EE7B7`, the button's green family, so no new colour (apricot was tried and dropped: too many colours; a paler mint was tried and the user preferred this one); the lead is now one short sentence ("reads your shelf from a photo, finds nearby buyers, then calls and negotiates with them to close the deal"). It leaves out the language, which the headline already states, and claims nothing beyond what was built.
- **The first screen is only the hero:** the band and the steps panel sit in one `.intro` wrapper with `min-height: calc(100svh - 65px)` (below the header), so Shelf setup always starts just past the fold at any screen size; extra height goes above the title, and the panel ends 32 px above the fold. `How it works` moved out of `.main-layout` into that wrapper (it carries its own 1040 px column). On a phone the content is taller than the screen anyway.
- **Known and accepted:** the hero button's white label on `#059669` is about 3.8:1, under WCAG AA's 4.5:1 for 15 px text. The user kept it for its look on the dark band; the page's other buttons stay `#047857` (about 5.5:1).
- **Removed:** the dark chat card with three bubbles and its deal banner, the "Bananas · overripe" flag (which covered the avatar), the radial glow behind the hero, the kicker pill, and the call bubble tried in this round. The photo and sketch candidates were reverted and never kept.
- **Spec change:** the live-call panel is no longer the page's only dark surface. The hero is a second dark block, at the top, outside the working sections; it echoes the call screen further down.
- **One button shape:** every button (`btn-primary`, `btn-ai`, `btn-ghost`/`btn-secondary`, `btn-danger`) is now a pill like the hero's and the call screen's "Hang up", with 2 px more side padding. Inputs, the closing-time segmented control and chips keep their shapes.
- **Bug fixed (it shipped in `144bbd0`):** a stray `</div>` after the ladder stepper (there since Module 8A) closed `#decisionContent` early. The browser used to ignore the extra one, but once the sections sat inside `<div class="main-layout">` it closed that column after Decision, so Buyers, the call panel and Impact ran full width. Removed. JS only looks up `#decisionContent` and no CSS targets it, so nothing else changes. New test in `static.test.mjs`: every `main`, `section`, `div`, `ol`, `ul`, `li`, `label` and `button` opened in `index.html` is closed (it fails on `144bbd0`: 117 `div`s opened, 118 closed).
- **No JS change**; markup, CSS and one page test.
- **Verification:**
  - preview at 1280, 768 and 375 px; no sideways scroll
  - `ruff` clean; `pytest`: 418 passed, 20 skipped; `node --test`: 21 passed

---

# Round 15: New shelf bug and "Since last photo" wording, by Claude (2026-10-14)

- **Bug (on live):** after **New shelf**, an inspection showed "N items detected" and the decision, but no photo and no items.
  - Cause: the New shelf handler set `#inspectResultContainer` to `display: none`, and nothing showed it again. `renderResults` restores the section, banners and footer, but never that container.
  - Fix: the line is removed (`main.js`). Hiding `#sectionAiReading` already hides the container.
  - Checked in the preview: inspect, New shelf, inspect again; the photo and 3 items show.
- **Wording (D26 matching unchanged):**
  - An unmatched item shows "New on this shelf" when the inspection had a previous photo, and "First photo of this shelf" only when it had none (`reading.js`).
  - The change note now reads "dropped 42 points since the last photo (today 10:14)" (`matching.py`). The time is when the last photo reached the app, which is when a shelf camera shot it. An uploaded old photo has no capture time (EXIF is stripped, D62), so the note no longer suggests one.
  - A test pins the new wording.
- **Checks:** `pytest` 421 passed, 20 skipped; `node --test` 22 passed.

---

# Round 16: Shelf setup photo picker and the user's sample photos, by Claude (2026-10-14)

- **New samples** (the user's photos, replacing Shelf B, Shelf C and the simulated banana tray):
  - Day 2 · Mixed
  - Day 4 · Banana Tomato
  - Day 7 · Banana Tomato
  - Day 7 · Lemon
  - Day 10 · Banana Tomato · AI

  Day 4, 7 and 10 are the same two trays over time, so inspecting them in order on one shelf shows the change notes and the decision moving down the ladder.
- **How the files were made:**
  - EXIF orientation applied, **all metadata dropped** (camera model and dates; there was no GPS), long side ≤ 3072 px, JPEG q90 (0.8–2.2 MB)
  - a 720 px preview in `samples/thumbs/` for the large preview and the list thumbnails
  - file names kept as the user's, with `-AI` added for the AI-generated Day 10
  - `samples.json` gains `thumb` and `ai_generated` and drops the unused `series`
- **Honesty about Day 10:** the Module 3 review said not to pair an AI-generated photo with real ones as a time-lapse. The user chose to include it, so it is labelled "· AI" in the list with a visible "AI-generated image" line under it, and the test checks that `ai_generated` matches the label.
- **Photo picker** (replaces the 3-card grid and the raw "Choose file" input):
  - **left:** one large preview of the selected photo (280 × 372 px, a whole-pixel height so the five 68 px rows and their gaps end exactly with it; the hairline edge is drawn inside so it doesn't stick out), with its name on a soft gradient and a 200 ms crossfade (none with reduced motion)
  - **right:** the five samples as a list whose rows share the preview's height exactly (top and bottom edges aligned), each with a 3:4 thumbnail (40 × 54 px, the photos' own shape, so both trays show) (`role="radiogroup"`, each option `role="radio"` with `aria-checked`), the selected one tinted with a check
  - **upload:** an outlined "Upload your own photo" pill beside **Inspect Shelf Photo**, a styled label for the visually hidden file input; once a file is chosen it reads "<file name> · Change", the preview shows "Your photo" and the sample rows lose their check
  - **on a phone,** the large preview is hidden (the thumbnail rows are enough), and Upload sits above Inspect, both full width
  - a first version showed a fanned stack of photo cards; the user found it old-fashioned, so it was replaced
- **Logic touched (deliberate):**
  - `setup.js`: `loadSamples` rewritten with `selectSample`, `showUploadedPhoto` and `renderPhotoPreview`. The sample blob is now kept only if that sample is still selected, which fixes a race when clicking quickly.
  - `main.js`: the file-input handler calls `showUploadedPhoto`.
- **Bin capacity removed from the page:** the field, its `dom.js` lookup and the 4 lines in `reading.js` that sent it. The API still accepts `bin_capacity_kg`.
- **Closing window** now has its own full-width row, which fixes the overflow at 1280 px (contents were 26 px wider than the control).
- **Checks:**
  - preview: select a sample, upload a file, inspect a sample (photo and items show), at 1280 and 375 px with no sideways scroll
  - `pytest` 421 passed, 20 skipped; `node --test` 22 passed; `node --check` on every module

---

# Round 17: field help (toggletips) and clearer time pills, by Claude (2026-10-14)

The user wanted the three setup fields explained without adding visible text. The pattern was checked against design-system practice (Primer, Atlassian, Polaris "info icon"; the "toggletip" in Inclusive Components) and WCAG 2.2 AA.

- **Labels:** sentence case ("Access code", "Branch", "Time until closing"), each followed by a small ⓘ.
- **The ⓘ button:** a 14 px glyph in a 24 × 24 px target (WCAG 2.5.8), named "About …", with `aria-describedby` pointing at the text and `aria-expanded` when pinned.
- **How the text shows:**
  - **hover or keyboard focus** shows it (CSS)
  - **a tap or click** pins it open (`ui.js` `initInfoTips`, about 30 lines)
  - **Esc** dismisses it, and a **click elsewhere** closes it; only one is open at a time
  - the icon and the text share one hover area, with a bridge across the gap, so the pointer can move onto the text (WCAG 1.4.13: dismissible, hoverable, persistent)
  - the browser's Popover API was not used: it only became Baseline in 2025, and hover-to-open (`interestfor`) is still experimental (MDN)
- **Placement:** above the label, anchored to the label row and capped at the field's width. A first version anchored it to the icon; on a phone the hidden "Time until closing" text then reached past the screen (scrollWidth 417 on 375), so it was moved.
- **Wording:**
  - Access code: "The code is in our submission deck."
  - Branch: "Which branch's neighbourhood the AI searches for buyers. Prices and decisions don't change."
  - Time until closing: "The mart closes at 23:00. Pick an earlier time to see how the AI's decision changes as closing nears. Pickup times stay real." (D56: the selector only simulates the decision)
- **Essential information is not only in a tooltip:**
  - the access-code placeholder reads "From our submission deck"
  - a wrong code says "Invalid access code. You'll find it in our submission deck." (`reading.js`, `call.js`)
- **Time pills:** two lines each, "Now / real time", "12 h left / morning", "4 h left / evening", "1 h left / last hour" (was "Morning (12 h)" etc.). Values and logic are unchanged.
- **Branch dropdown:** the branch name only ("Demo Mart Johar Town"). The two places that read the option text split on "(", which still works.
- **Checks:**
  - preview at 1280 and 375 px: hover, tap, Esc and click-outside all work; no sideways scroll
  - `pytest` 421 passed, 20 skipped; `node --test` 22 passed; `node --check` on every module
- **Defaults (D65, same round):** the page opens with **4 h left** selected (the hidden select's `selected` option and the active pill moved from "Now") and on **Day 4 · Banana Tomato** (`"default": true` in `samples.json`; `loadSamples` selects it, else the first). Checked in the preview: the first `/demo/decide` request sends `hours_until_closing: 4`, and the chip reads "4 h to closing". A test pins the single default sample.
- **Select chevron (same round):** the browser's own arrow sat against the right edge (about 10 px) while the text is inset 14 px, so it looked off. `.field select` now uses `appearance: none` with an inline SVG chevron at `right 0.875rem center` (the same 14 px) and 40 px right padding. The dropdown list stays native, so keyboard and screen readers behave as before.
- **Senior review fixes (same round):**
  - **Keyboard:** the photo list used `<button role="radio">`, so every row was a Tab stop and the arrow keys did nothing, short of the WAI-ARIA APG radio-group pattern. Each row is now a `<label>` with a native, visually hidden `<input type="radio" name="shelfSample">`, so there is one Tab stop and the arrow keys move between photos, with native screen-reader semantics. Focus ring: `.photo-option:has(input:focus-visible)`. If a call or inspection is running, a change is reverted to the current photo.
  - **Contrast (WCAG 1.4.3 / 1.4.11):**
    - the pills' small "morning / evening" text was #94A3B8 (2.3:1); it is now #475569 (6.9:1)
    - the ⓘ icon was #94A3B8 (2.6:1 against the 3:1 that icons need); it is now #64748B (4.8:1)
  - **Checked:** arrow keys, mouse, upload (unchecks all radios) and inspect; no sideways scroll at 375 px.
- **Known and left as it was:** the existing 12 px uppercase labels elsewhere on the page use #94A3B8 (from the Module 8 spec). That is below 4.5:1 and worth a separate pass.

---

# Round 18: page-wide text contrast (WCAG 2.2 AA), by Claude (2026-10-14)

Round 17 noted that the muted grey #94A3B8 (from the Module 8 spec) was used for small text across the page at about 2.5:1, below AA's 4.5:1.

- **Method:** a browser audit of every visible text node. It compares the computed colour with the first opaque background behind it, using WCAG relative luminance and 4.5:1 (3:1 for large text). It covered the full flow (reading, decision, buyers, impact) and the call panel, which was shown for the check. The hero (dark band) was checked separately.
- **Before:** 11 failing styles, all #94A3B8 on white or #F8FAFC (2.45–2.56:1): the header clock, the reading footer, the stage level, item facts and impact labels, price-card labels and units, profile line, buyer hours, skipped counts, the impact note.
- **Fixes:**
  - **`--text-muted` is now #5B6B80:** 4.9–5.4:1 on every light background used (white, #F8FAFC, #F1F5F9, the emerald and indigo tints) and still lighter than secondary text (#475569). #64748B was rejected because it fails on #F1F5F9 (4.34) and the indigo tint (4.26).
  - **Hard-coded #94A3B8 text on light backgrounds** now uses the token: evidence title, item and metric labels, the three price-card label variants, skipped counts, impact labels and note, and the buyer meta icons. The buyers footer and the ⓘ icon (#64748B) use it too.
  - **"Not allowed" ladder steps:** legible muted text with a hollow dot, instead of #94A3B8 at 60% opacity (about 1.6:1). These are text, not disabled controls, so they need contrast.
  - **Call panel:** five labels used #64748B, which fails on the dark panel (3.1–3.9:1): deal-sheet labels, "Never told to the AI", the headphones hint, speaker labels and transcript notices. They now use `--call-muted` (#94A3B8, 5.7–7.3:1 on dark). The status pill's "·" separator is marked `aria-hidden` as decoration.
  - **Left as they are, and allowed:** decorative dots, the disabled Hang up and disabled inputs (WCAG exempts inactive controls), and #94A3B8 texts on the dark panel that already pass.
- **After:** 204 visible text nodes, 0 failing.
- **Checks:** `pytest` 421 passed, 20 skipped; `node --test` 22 passed; no sideways scroll at 1280 or 375 px.

---

# Round 19: AI shelf reading, box alignment and a calmer item card, by Claude (2026-10-14)

- **Bug fixed: boxes off the produce on tall photos.**
  - The picture sat letterboxed inside the dark viewfinder (`object-fit: contain`, `max-height: 480px`), but the box overlay covered the whole frame, so on portrait photos the boxes shifted and stretched by the bars.
  - The image and overlay now sit in `.photo-stage`, an inline-block exactly the picture's size, centred in the unchanged dark frame.
  - Measured in the preview: portrait 360 × 480 and phone 301 × 401, each with the overlay identical to the image.
- **Keyboard access:** each item header is a `<button>` with `aria-expanded` (and `aria-controls` on the open item). It is reset to look exactly as before, with a focus ring for keyboard use only. Enter or Space opens an item and keeps focus on it after the list is rebuilt. The box overlay is `aria-hidden` (a pointer shortcut for the same choice).
- **The item card (several rounds with the user; the dark frame, mint outline and facts box stay):**
  - **Freshness scale under the AI sentence:** Fresh · Ripening · Overripe · Spoiled · Unsafe in the stage colours, the item's stage solid, a marker at early, mid or late, and the current label bold. It has `role="img"` with a sentence label. It replaces the small score bar on the open card.
  - **Header:** every item states its verdict, "● Overripe · mid stage", with the score as "46/100" (headline plus chart: the header says it, the scale shows where). "Zoomed in for a closer look" is a small indigo line with a sparkle under the AI sentence. For a while the zoom note took the header and the stage chip appeared only on collapsed rows; that made the verdict hard to see at a glance, so it was reverted.
  - **Scale emphasis:** a 6 px track, the other stages at 22%, a 14 px marker. The current stage's name is 12 px bold, in a text-safe version of its colour (fresh #047857, ripening #4D7C0F, overripe #B45309, spoiled #C2410C, unsafe #B91C1C; 5.0–6.5:1 on white). The level is not repeated under it, since the header says "mid stage". Tried and reverted: 35% opacity with thicker and thinner bars and a 16 px marker.
  - **Duplicates removed:** the issue tags (dark spots, browning) repeated the AI sentence, and the stage chip repeated the scale.
  - **Facts:** three equal, top-aligned columns in the box: **Stock** "2.1–2.9 dozen" with "25–34 pieces" (or "container 60–80% full") beneath, replacing Observed and Estimated stock; **Confidence** "High"; **Since last photo** "−9 points" in amber (green when up) with "since 21:36" beneath.
  - **Type:** labels 12 px muted, values 15 px semibold, details 13 px secondary, so each step down is quieter.
  - **Open card:** keeps the mint outline on white. Matching the photo list's emerald tint was tried and reverted at the user's request.
  - **Spacing:** 24 px between the AI sentence and the scale; the facts box has 20 px padding top and bottom, with 4 px between label, value and detail. Stacked on a phone, the three facts are 16 px apart, so each group reads as its own.
  - **Alignment:** each fact is centred in its third ("Confidence" sits on the box's centre line, measured), so the three read as one balanced strip under the centred scale labels. Left-aligned when stacked on a phone.
  - **Tried and dropped at the user's request:** a lighter restyle without the dark frame; icons, meters and trend badges per fact (judged too busy); the facts without a box; "counted" and "55 → 46" in the details.
- **Footer:** "✦ Read by Gemini 3.8 Flash · 4.2 s · 2 calls · 1 zoomed in" (or "same photo as before, stored reading reused") in the body font. It replaces the monospace `Model: … Latency: 60004 ms calls: 4 Hedges: 1 Zoomed: 0`. `readingSummary` is in `format.js` with unit tests; the raw numbers stay in the API response. On a phone, where it wraps, the sparkle stays on the first line.
- **Code:** `formatChange`, `formatStockBasis` and `freshnessPosition` are pure functions in `format.js`, with 13 unit-test cases. The renderer changes are in `renderItemsList` and the new `renderFreshnessScale`. Unused styles (`issues-chips`, `issue-tag`, `item-stage-level`) are removed.
- **Checks:** `pytest` 421 passed, 20 skipped; `node --test` 26 passed; `node --check` on every module; no sideways scroll at 1280 and 375 px.

# Round 20: take the judge to the reading after Inspect, by Claude (2026-10-14)

The reading appeared below the fold on a laptop, so pressing Inspect could look as if nothing happened.

- **How:** when a reading has rendered, the page focuses the "AI shelf reading" heading (`tabindex="-1"`, no focus ring since it is not a control). This is the usual pattern after new content, so keyboard and screen-reader users land on the result too. The section scrolls to just under the sticky header (the existing `scroll-margin-top`). The scroll is smooth, or instant when the visitor has reduced motion turned on. Only this one scroll changes; there is no page-wide `scroll-behavior`.
- **When it does nothing:**
  - the judge scrolled more than 40 px while waiting (they are reading something else, so they stay there);
  - the section is already just under the header;
  - the inspection failed (the error stays by the button).
- **Order:** it runs after the loading box is hidden, so the layout above the reading doesn't shift after the scroll.
- **Not touched:** the inspection, the API and the cache. If this step fails, the page is simply as it was before.
- **Checks:** in the preview, a normal reading (smooth scroll, focus on the heading), scrolling away while waiting (no scroll, focus unchanged), reduced motion (instant) and an error (no scroll, error shown). The browser pane was hidden, so these were checked by recording the scroll and focus calls, not by watching the page move.

# Round 21: Decision prices, by Claude (2026-10-15)

Radish showed "Rs —" on the Decision card. The demo price list had 20 produce and missed radish, turnip and green bean (the Day 2 sample) and lime.

- **Price list** (`shared/lastcall_shared/marts/demo_mart.json`): 56 common Lahore produce, still marked "Demo prices, not live market rates". It covers every item in the 5 sample photos (a test checks this) plus common produce: peas, garlic, ginger, aubergine, capsicum, mango, melons and others. The new prices are rough everyday retail levels, in line with the existing ones.
- **Names:** English only. The Inspector names produce in everyday English (`system_prompt.md`), and only that name reaches `find_price`. The Urdu names (tamatar, bhindi…) could never match, so they were removed. English alternatives Gemini may use are kept: aubergine, brinjal, eggplant; capsicum, bell pepper; lemon, lime. Local names that are the everyday word in Pakistan stay (kinnow, malta, chikoo, mosambi). In the 36 item readings checked (15 consistency runs), every name came back in English. If one ever doesn't match, the item takes the "Price not set" path below.
- **Descriptive-word fallback (D66):** in a live check Gemini said "white radish" (15 earlier runs said "radish"), so the item showed "Price not set". `find_price` now tries the full name against the whole list first, then the name without a fixed set of descriptive words (colours, baby, small, large, desi, local, hybrid, organic, fresh, raw). Any other extra word leaves it unpriced, so it fails safe ("black plum", "custard apple", "winter melon" stay unpriced; "black" and "sweet" are deliberately not descriptive). "bitter melon" is listed under bitter gourd (karela). The engine stays pure: no log line, since logs never carry produce names. Tests cover each case, and that no descriptive word is itself a produce name on the list.
- **One entry per name:** `MartRules` now rejects a name listed under two entries (ignoring case, spaces and plurals, the way the lookup matches), so a price can't depend on the file's order. This is tested.
- **Rejected:** a random price (Rs 150–350) for unknown produce. It would differ per instance and per restart (Cloud Run can't write back to the file), show implausible prices, and break D41 (money never depends on a guess).
- **"Price not set" card:** when there's no price in the item's unit, the card no longer shows "Rs —". It shows SHELF PRICE · "Price not set", then "No price per kg on the mart's list yet. Enter it below to set this item's prices." (or "per dozen"), with a dashed border. It covers both an unknown item and an item listed only in the other unit. Prices are never converted between kg and dozen (D4).
- **Unchanged:** the Ladder logic. Without a price the step is still chosen, but there are no prices and no buyer search or calls until staff enter one (`handoff.py`), including for Donate, since the market value goes into Impact.
- **Production note:** the sale unit comes from the Inspector's prompt rule (dozen for bananas, and for kinnows and oranges displayed loose). In production it would come from the POS with the price.
- **Checks:** pytest 425 passed, 20 skipped (added: sample produce priced, unique names, English alternative and lime lookups, the descriptive-word fallback and its word list); `node --test` 26 passed; ruff clean. In the preview, Day 2 Mixed showed a price on all 5 items, and the "Price not set" card was checked for kg and dozen.

# Round 22: Decision section, in the AI reading card's style, by Claude (2026-10-15)

The Decision section still used the older style: three heavy white cards with uppercase labels, a log-like profile line, and the same facts said twice.

- **Order:** steps → one reason sentence → price strip → status and staff chips → shelf price row → a quiet footer. This is the reading card's rhythm (sentence, soft facts box, footer).
- **Reason sentence** (`ladder/engine.py`, text only, no logic): it starts with the stage and no longer repeats the item's name (in the header) or the step (in the stepper). For example "Banana, overripe: juice shops and bakeries can use it → bulk sale" becomes "Overripe: juice shops and bakeries can use it." The discount percentage moved out of the sentence, since the strip shows it. Only the page shows this text. The scenario tests keep their phrase checks, and all 24 scenarios now also check that a reason starts with the stage and contains neither the name nor "→".
- **Price strip:** one soft box like the reading's facts (#F8FAFC, radius 10, 20 px padding), one centred column per price (CSS `grid-auto-flow: column`, so 1–3 columns need no JS), labels in 12 px sentence case, prices in 22 px heading font (still the section's headline). The floor keeps its lock and "never told to the AI". Labels are "Stays at full price", "Shelf price · Discounted · 25% off", "Shelf price · AI opening offer · Floor", "Donation · Free to charities". Compost has no prices, so the strip is hidden (the sentence says why). "Price not set" is now a strip cell with the ask beneath it. On a phone the prices stack on the left edge, like the facts.
- **No repeats:**
  - the shelf price row says "Change shelf price (Rs)" with the placeholder "New price" (the strip already shows the price), or "Shelf price (Rs)" and "Enter price" when the item has no price yet (this depends on the price, not the step, so a donate item without one is asked correctly);
  - action chips that repeat a status are skipped ("check before off-shelf" under "On hold until staff check", "approve compost" under "Needs manager approval", "enter shelf price" under "Price not set");
  - the price row is hidden for compost, which has no price. Donate keeps it, since a donation's market value goes into Impact.
- **Footer:** "✦ Banana profile by Gemini · 5 votes, agreed except on spoiled as cattle feed" (or "all agreed", "set by the store manager", "general profile, as Gemini's wasn't available"), in the same style as the reading's footer. It replaces "Produce profile: banana · Gemini, 5 votes · uncertain: cattle spoiled". `formatUncertainFields` and `formatProfileLine` have updated tests.
- **Phone:** the longer label made the price input one letter wide, so at ≤640 px the label now takes its own line.
- **Photo picker, the same selected style:** the selected sample was a mint-filled row with a strong emerald border, now the heaviest element on the page. It now uses the open item card's style: white, a soft mint border (#A7F3D0) and a 3 px #ECFDF5 ring, so the page has one "selected" look. The check circle stays as the sign of the choice (not colour alone, WCAG 1.4.1). The keyboard focus outline moved to a 4 px offset to clear the ring, as on the item card. CSS only.
- **Steps on a phone:** at 375 px only about 3½ of the 6 steps fit, so on Animal feed or Compost the chosen step was off-screen, and the browser's grey scrollbar showed under the row. Now:
  - when a decision renders, the row scrolls sideways so the chosen step is centred (`scrollLeft` on the row only; the page never moves);
  - the scrollbar is hidden, and the edge with more steps beyond it fades (`fade-start` and `fade-end`, set from the scroll position on scroll and resize; a CSS mask, unprefixed and `-webkit-`);
  - the gap is 10 px on phones, so about four steps are in view.

  The divider moved to a new `.stepper-wrap`, so the fade never fades the line. Desktop is unchanged: no overflow, no fade. Checked at 375 px: Bulk sale centred (116 and 117 px either side), Compost at the right end with only the left edge faded, Keep at the start with only the right edge faded; the page's scroll position didn't change.
- **Selling time as a duration:** the same fresh banana read "sells until 12:47 tomorrow" with "Now" (real time 03:12) and "sells until 04:36 in 2 days" with "4 h left" (simulated 19:00). Both were right, since the profile gives the same 33.6 h (1–3 days band × 0.7 for mid), but the clock time depended on which "now" was meant, and the header clock shows the real one. Reasons now say how long it sells, "Fresh: sells for about 34 h, still fine at tomorrow's 09:00 opening.", the same in both settings and comparable with the "4 h to closing" chip. `selling_time` rounds: under an hour; to the half hour under 10 h; whole hours under 48 h; then days. Halves round up, without Python's banker's rounding. The date juggling ("tomorrow", "in 2 days") is gone from the engine. Text only: the chosen step, discount and prices use the same numbers as before. Tests check the rounding, and that a kept item's reason is identical at 20 h and 4 h to closing.
- **Kept:** the stepper, the "4 h to closing" chip, the Re-decide flow and the lock once calls start (D58). The lock code is unchanged, and the elements it disables are the same.
- **Removed styles:** `.price-cards-grid`, `.price-card*`, `.decision-meta-box`, `.profile-line`, `.price-override-input` (no element used it).
- **Checks:** pytest 427 passed, 20 skipped; `node --test` 26 passed (one project test caught an inline CSS variable; replaced by CSS auto columns); ruff clean. In the preview, real Gemini readings of Day 4 showed tomato on keep and banana on bulk sale. Discount, "Price not set", compost and donate were rendered from edited decision data; at 1280 and 375 px there was no sideways scroll, and the phone price input is 185 px wide.

# Round 23: Buyers section, in the page's design language, by Claude (2026-10-15)

The Buyers list was the busiest section: about 20 indigo marks (an uppercase "NEXT TO CALL", a left bar, avatars, the call button, 5 "Likely fit" chips, 5 Maps links), the same labels on every row ("Open now", "Likely fit", "Google Maps", "Play this buyer"), initials avatars that said nothing (two "JH"), a third "selected" style, and a three-line footer that counted the same nine businesses twice.

- **Rows:** one card per buyer, 8 px apart, like the reading's items and the photo picker. Each card has:
  - the rank number on its own (the order is the information);
  - the name;
  - Gemini's reason with the AI sparkle (the row's most useful line);
  - one quiet facts line: type · km · masked phone · Google Maps ↗.
  
  On a phone the facts wrap, so they are spaced apart rather than dotted (a dot would start a line).
- **Only exceptions are labelled:** "Closed now" (red), "Hours unknown" (grey) and "Possible fit" (before the reason). An open, likely buyer needs neither label; the subtitle and the footer already say Gemini screened them.
- **Next buyer:** the page's mint ring (the same "selected" style as the open item and the selected photo), a small sentence-case "Next to call" in emerald, and the page's green **Start call** button. The other rows get a quiet **Call** (same action, `startCallForItem`), with an aria-label naming the buyer. As before, the next buyer always gets the button, even after an earlier "call back", and its name is never dimmed like a finished row.
- **Indigo** now marks only Gemini (the sparkle). The shared `.btn-ai` style is unchanged, because the call result screen uses it for "Next buyer · #2…" (`call.js` → `renderNextActionRow`); that screen is for the live call round.
- **Footer:** one quiet line, "**Results from Google Maps** · within 10 km · searched just now", with Refresh. The Google Maps attribution stays visible. The branch is no longer repeated (the header chip names it). The Skipped line and the screened-out list are merged into one disclosure: "26 not shown: 16 without a phone, 1 closed for good and 9 screened out by Gemini ▸", which opens Gemini's reasons. It counts the listed screened-out businesses even if the skip counts were to miss them; it says "Showing the nearest 10." when not all are listed; and it is a plain line when Gemini gave no reasons.
- **Unchanged:** the call flow, next actions, outcome chips, the stock progress, the quantity input, the staff-check hold, the hours banner and the lock while a call runs.
- **Removed:** initials avatars, `.ai-tag`, the uppercase eyebrow, `.buyers-skipped`, "Open now", and four unused rules (`.buyer-head`, `.buyer-row-title`, `.buyer-heading-name`, `.buyer-remaining`). `initials()` stays in `ui.js` for the call screen.
- **Checks:**
  - pytest and `node --test` pass; ruff is clean.
  - The preview used fictional sample buyers (a fake Scout, no Google Maps calls). It covered the next buyer, closed, hours unknown, possible fit, a deal, a "call back" buyer who is next again (Start call shown) and a declined one.
  - At 1280 and 375 px there was no sideways scroll.

# Round 24: one stylesheet per part of the page (D67), by Claude (2026-10-15)

- **Why:** `demo.css` was 2,150 lines. The sections were in order up to Impact, but the last 300 lines were a catch-all: hidden-by-default states for every section, "replacements for removed inline styles", button sizes apart from the buttons, and a phone block mixing the header, section heads, the step row and the price row. Unused rules collected there.
- **How:** a script parsed the file into its 410 top-level blocks (exact round trip) and gave each one to a file by index. The one mixed `@media` block was split rule by rule into the matching files under the same query. A check confirmed the nine files hold exactly the original 456 rules. The files are in `static/css/`, linked in cascade order: base, layout, hero, setup, reading, decision, buyers, call, impact.
- **Proof that nothing changed:** in the preview, with the page holding a reading, a decision, fictional buyers, transcript lines and a toast, the computed style of every element and its `::before`/`::after` (1,479) was compared between the nine files and the original `demo.css`, on the same page. A control run (new files off) showed 1,482 differences, so the check works.
  - **First result:** one difference, the quantity input (`input-number qty-input`). Originally `.qty-input` came before `.input-number` and lost on every property, so it did nothing; after the split it came later and won. It was removed (and the class in `buyers.js`), which restores the original exactly.
  - **Final result:** 0 differences at 1280, 800, 600 and 375 px (each breakpoint combination), both before and after removing the unused rules.
- **Removed (no markup or JS uses them; checked against class names built in JS, like `fill-${stage}`):** `.metrics-summary-grid`, `.metric-item-group/-label/-value`, `.evidence-box/-text/-title/-list`, `.item-expanded-details`, `.staff-check-notice`, `.text-emerald/-indigo/-amber`, `.btn-block`, `.call-stock-info`, `[data-mono]`, `.qty-input`.
- **Deploy:** the Dockerfile copies `services/api/` whole, so `css/` ships. `test_static_and_demo_cache_control` now checks all nine linked stylesheets are served with `no-cache`.
- **Review pass (comments only):** comments travel with the block after them, so a few no longer fit after the move. Fixed:
  - the hero banner comment sat above the section scroll offset in `layout.css`;
  - stale or historical headings ("Price Cards Grid", "Replacements for removed inline styles", "Section Footer Telemetry", "Phone layout" above a rule for every width);
  - each file's old "SECTION N" line duplicated its new header.
  
  Each file's hidden-by-default states now open with the same one-line comment. With comments stripped, the rules are identical to before.

# Round 25: a number and its unit never split across lines, by Claude (2026-10-15)

- **Why:** the page writes quantities in the SI style, with a space between number and unit ("4 h", "0.4 km", "2.5 dozen", "Rs 180"). An ordinary space allows a line break, and on a phone the closing-time buttons can wrap, so "4 h left" could split as "4" / "h left".
- **What:** a non-breaking space (U+00A0) between every displayed number and its unit (h, min, s, km, kg, dozen, days, pieces, MB), and between "Rs" and the amount. It renders exactly like a space. Places:
  - `index.html`: the closing-time labels, the upload hint, Impact's initial "Rs 0", as `&nbsp;`;
  - JS formatters and renderers in `format.js`, `decision.js`, `buyers.js`, `call.js`, `impact.js` and `reading.js`, written as the visible escape ` `. A first pass wrote invisible characters, which made the diff unreadable, so it was converted;
  - the engine's `selling_time` ("about 34 h", "about 3 days"), the only server text with units that the page shows.
  
  Counts that are not measurements ("5 votes", "2 calls") keep ordinary spaces.
- **Left alone on purpose:**
  - the hidden closing-time `<select>`, which is never displayed;
  - the Scout's internal `reason` line, which the page doesn't show;
  - the Inspector prompt's "about 25 kg", which is text sent to Gemini.
- **Edge cases checked:**
  - a review sweep found five more places the first pass missed ("Donated 2 dozen" twice, "1.9 of 2.9 dozen left", the call screen's "Banana · 2.5 dozen", the upload error "8 MB");
  - no code reads these strings back (the only text parsing splits branch names on "(");
  - the masked phone keeps ordinary spaces but its element never wraps;
  - in the preview, every place shows U+00A0, including the server reason after JSON.
- **Tests:** the formatter and `selling_time` expectations now spell out the non-breaking space. pytest 427 passed, 20 skipped; `node --test` 26 passed; ruff clean.

# Round 26: call section, consistent with the page, by Claude (2026-10-15)

The call screen was already the page's strongest section (a dark "call mode": caller, live status, Hang up, the deal sheet with "Floor · never told to the AI", the conversation and the result banner). No redesign, three consistency fixes:

- **Sentence-case labels:** the caller line, the deal-sheet labels and the speaker labels drop `text-transform: uppercase` and letter-spacing (12 px, muted), like every other label on the page. The words in the markup and JS were already in sentence case.
- **Indigo means the AI here too:**
  - the agent's bubbles have a faint indigo tint;
  - yours become neutral slate, still on the right as in any chat;
  - the buyer's avatar is neutral (it showed the AI colour on the human side);
  - the waveform (the AI speaking) and the tool notices ("Price check · counter") stay indigo.
  
  Text contrast: 9.9:1 on your bubbles, about 14:1 on the agent's.
- **"Next buyer" uses the page's green button:** `renderNextActionRow` uses `btn-primary`, like "Start call" in Buyers. The indigo `.btn-ai` style had no other use and is removed from `base.css`.
- **Checked** in the preview with a fictional call (caller, deal sheet, transcript, a tool notice, a deal result) at 1280 and 375 px, with no sideways scroll. A pickup window that wrapped mid-range was the fake data's format; the real one is words ("… to …") and also goes into the agent's prompt, so it is unchanged.

# Round 27: the Buyers list marks the right buyer during and after a call, by Claude (2026-10-15)

- **Bug:** the page only refetches the batch when a call ends, so during a call the Buyers list showed the pre-call state. Calling #3 from its "Call" button left #1 highlighted as "Next to call" and #3 unmarked; calling #1 left it labelled "Next to call" while on the call.
- **Fix (page):**
  - `startCallForItem` records who the call is with (`state.currentActiveCall`) as soon as it starts, with the buyer ID the page passes; it is confirmed (or filled in, when the server picks) from the server's answer, which then redraws the list.
  - While this item's call runs, `renderActiveBuyers` highlights that buyer (the same mint ring) as "On the call now · In progress…", and no row says "Next to call".
  - A call on another item doesn't mark this item's list.
  - A failed start clears the record.
- **Robustness (server + page):**
  - the batch's `next_action` named the next buyer by rank only, and the page matched the rank against its own copy of the list, both for the highlight and for the result screen's "Next buyer" button. A stale list (a search refreshed elsewhere) could point at a different business;
  - `next_action` now also carries `buyer_id` (an added field). The page matches by ID only when there is one: no highlight rather than a rank guess if the buyer isn't in its list, and the button then calls the server's buyer ID exactly. Rank is used only for a response without an ID.
- **Tests:**
  - `test_batch_next_action_names_the_buyer_by_id`.
  - In the preview, with fictional buyers, each case gave the expected result: no calls yet; calling #3; an ID that disagrees with a stale rank (the ID wins); an ID not in the list (no guess, the button keeps the server's ID); rank only; a call on another item.

# Round 28: a steady transcript, and one click moves one ladder step, by Claude (2026-10-15)

- **Transcript:** it was `min-height: 300px; max-height: 420px`, so it grew with each message and the call panel got taller mid-call before a scrollbar appeared. It now has a fixed height from the start (420 px; 360 px at ≤760 px) and scrolls inside. Each new message still scrolls to the bottom (checked: 0 px from the bottom; smooth in a visible browser).
- **"Next step: find charities":**
  - the server already moves a step only when the current one is used up (otherwise 409);
  - but the call result's button was never redrawn after a click. After the first click moved the batch to Donate, it still said "find charities", and if the charity search found nobody usable, a second click legitimately moved on to animal feed;
  - now the click disables the button at once ("Finding charities…"), scrolls up to Buyers where the new list appears, and, after the move and the search, redraws that row from the fresh batch (for example "Next buyer · #1 …");
  - if the server refuses, the row shows the batch's current state instead of the old button. `advanceBatchStep` returns whether it moved.
- **Checked** in the preview, with the server's step responses stubbed on the page:
  - a fast triple click sent one step change, scrolled to Buyers, and redrew the row as the next buyer;
  - a 409 redrew the row from the current batch;
  - the transcript is 420 px empty and after 12 messages (360 px on a phone), with no sideways scroll.
- **Refactor:** the "scroll a section into view, smooth unless reduced motion" logic was in `reading.js` (the reading after Inspect) and `buyers.js` (this button). It is now one helper, `scrollToSection(el)` in `ui.js`, also used when a call starts (`call.js`), which used to scroll smoothly even with reduced motion. In the preview, the reading reveal and the next-step button both go through the helper (smooth, `block: start`); the page's only console error was the test's own stubbed 404.
- **Checked:** the fixed 420 px transcript beside the deal sheet. The deal sheet is 382 px typically and 402 px with an unusually long pickup text, and the column bottoms line up.

# Round 29: Impact in the page's style, and one shared stat strip, by Claude (2026-10-15)

- **Before:** six separate grey boxes with uppercase labels ("MONEY RECOVERED", and a title-case "Deals Closed"). "Stock placed" already included what was donated and fed, so three boxes overlapped. Bare "0"s showed before any call.
- **After:** one stat strip with the three headline results, a detail line where it helps, and the disclaimer as the section's quiet footer line (like the reading's and Decision's):
  - **Money recovered:** "Rs 135".
  - **Stock placed:** "2 dozen, 3.5 kg", with "1 dozen donated · 3.5 kg as animal feed", or "all sold to businesses" once there are deals.
  - **Deals closed:** "3", with "of 4 calls".
  
  The numbers come from the unchanged `computeImpact`; only the presentation changed. "Start a call to see the impact here." stays in the footer until the first deal.
- **Shared component:** Decision's price strip became the generic **stat strip** (`.stat-strip`, `.stat-cell`, `.stat-label`, `.stat-value`, `.stat-unit`, `.stat-hint`, plus a new `.stat-detail`) in `base.css`, used by Decision and Impact. Decision keeps only its own margin and its "Price not set" style. Before the move, the computed styles of Decision's strip (bulk sale and "Price not set" at 1280 px, bulk sale at 375 px) were saved; after it they are identical.
- **Removed:** `.impact-grid`, `.impact-metric-*`, `.impact-disclaimer`, and the Donated, Animal feed and Calls made boxes with their DOM lookups (nothing else used them).
- **Checked** in the preview with fictional call results (empty; one deal; a donation plus feed in two units) at 1280 and 375 px, with no sideways scroll. The money adds up: Rs 100 sold, plus 3.5 kg of feed at Rs 10, plus a free donation, is Rs 135.
- **Follow-up, at the user's request:** the number of calls was only a small "of 4 calls" detail under Deals closed, and hidden before the first call. Calls are the product's core action, so **Calls made** is a headline again. The strip now reads as a funnel, left to right: **Calls made → Deals closed → Stock placed → Money recovered** ("4 calls → 3 deals → 2 dozen, 3.5 kg placed → Rs 135"), ending on the money. Deals closed drops its detail line, since the call count sits next to it. Checked at 1280 px (four columns) and 375 px (stacked, no sideways scroll).

# Round 30: whole-page design review, desktop and phone, by Claude (2026-10-15)

The whole page was walked at 375 px and 1280 px with every section filled: a real reading and decision, fictional buyers, a fictional call and results. The same patterns now run through every section: cards; the mint "selected" ring; soft stat strips; sentence-case labels; indigo only for the AI; one quiet footer line per section; green main buttons. There was no sideways scroll at either width. Four things looked off and were fixed:

- **Impact before any reading:** the page jumped from section 1 to section 6, showing "0 · 0 · 0 · Rs 0" while sections 2–5 were hidden. Impact is now hidden by default (CSS, so it never flashes), and `renderImpact` shows it once there is a reading and hides it again on New shelf.
- **Title Case left over:**
  - "Inspect Shelf Photo" became "Inspect shelf photo";
  - the call status pill said "Live Call", "Call Ended", "Server Busy", "Auth Failed", "Token Expired / Reused", "Batch Locked" and "Connection Error", and some statuses used "..." instead of "…". They are now sentence case, in plain words and with the page's ellipsis: "Live" (the line above already says "Live call"), "Call ended", "Server busy", "Access refused", "Session expired", "Another call is on", "Connection lost", "Starting…", "Saving the result…".
- **Buyers on a phone:** every "Call" became a full-width 44 px pill, so four stacked outlined buttons dominated the list. Now only the next buyer's "Start call" spans the card (235 × 44 px). The quiet "Call" buttons (66 × 40 px) and the outcome chips sit under the name, aligned with the text, as on desktop.
- **Seen and left as is:** the call's deal sheet wraps "Banana · / 2.9 dozen" in its narrow phone column (readable, and the number and unit stay together); Impact stacks four rows on a phone (the stat strip's standard phone layout).
- **Final look (less common states):** loading and error banners, toasts, tooltips on a phone, outcome chips after calls, an empty buyer list, and the locked "New shelf". Fixed:
  - **Toasts were the one off-style element:** solid red, green and bright blue (`#3B82F6`, a colour used nowhere else), and white on red was about 3.8:1, below AA. They are now one calm style: dark slate like the call screen, light text (16.3:1), a coloured dot for the kind, and a real fade-out (the `toast-fading` class had no CSS). On a phone the toast is full width with 16 px margins; before, a long message could start off-screen. Errors use `role="alert"`, anything else `role="status"`.
  - **Duplicate error messages:** a failed Inspect showed the same text in the banner under the button and in a toast. The three toasts in `handleInspect` are removed. The three error banners (Inspect, Decide, Buyers) now have `role="alert"`, so screen readers announce them; before, Decide and Buyers errors were not announced at all.
  - **Call errors in plain words:** "WebSocket Auth failed (Code 4401)" became "This call was refused. Please start it again.", and likewise for an expired session, another call already running, an unexpected close, and busy lines.
  - **The deal chip** said "Deal 1 dozen @ Rs 100"; it now says "at", like the result screen.
  
  Checked and fine: three tooltips open within a 375 px screen; outcome chips are compact under the name; the empty list explains itself ("No suitable buyers found nearby", then "9 not shown: 6 without a phone and 3 too far").

# Round 31: a new inspection clears the previous call, by Claude (2026-10-15)

- **Bug (reported):** after a call, inspecting a new photo kept the old call section on screen (caller, transcript, "Call ended", result) until a reload. `handleInspect` reset the state (`currentActiveCall` among it) but never the call section; only New shelf hid it, and none of the resets cleared the transcript (the next call did).
- **Fix:** one `resetCallPanel()` in `call.js` puts the call section back to how the page starts (hidden; caller "—"; deal sheet "—"; timer stopped at 00:00; the transcript back to its placeholder; the result cleared). It does nothing during a live call. Used by all three resets: a new inspection (`reading.js`), New shelf and a branch change (`main.js`, replacing their own partial copies). `call.js` and `reading.js` now import each other; this is safe in ES modules because both functions are used only at run time.
- **Checked** in the preview: with an ended call on screen, Inspect resets the whole section; a live call is never reset; New shelf resets it the same way; the page loads without errors. The one console 404 is the browser asking for `/favicon.ico` (the page declares no icon), which is unrelated.
- **Review pass:** the transcript's starting content is taken from `index.html` once when the module loads: every node, whitespace included, cloned on each reset. So the placeholder text isn't duplicated in JS. The capture is defensive (`dom.transcript?.childNodes ?? []`) because the module can load without the real page: the first version read the transcript at import time and failed the export test (`static.test.mjs`), which imports the modules in Node with a minimal fake page. Checked: two resets in a row restore the original markup byte for byte, with a fresh element each time. Also checked: no reset can fall between a call ending and its result appearing (same synchronous step); the branch path now resets the whole section, which only happens before any call (the branch locks once calls start, D58); the section is hidden before the transcript changes, so screen readers don't announce the reset.

# Round 32: tab icon, the site root, and an honest "Gemini busy" message, by Claude (2026-10-15)

- **Tab icon:** `static/favicon.svg` is the header logo (the white leaf on the emerald tile, `#047857`), linked as `<link rel="icon" type="image/svg+xml">`. Browsers still ask for `/favicon.ico`, so that path now answers with the same SVG; before, every visit logged a 404 in the console.
- **Site root:** `/` was a JSON 404 (the page lives at `/demo`), which is what anyone sees if they trim the link. It now redirects to `/demo` (307).
- **"Gemini busy" (D70):** when Gemini EU was overloaded, judges saw "Inspection failed", which reads as our bug. Now `/demo/inspect` answers 503 "Gemini is busy or slow right now. Please try again in a minute." (with `Retry-After: 60`), but only on Gemini's own load signals: a timeout, or 429, 503 or 504 on the last attempt. A rejected request, a 500, an invalid answer, or a budget spent before Gemini was asked stay "Inspection failed". On any other 503 the page shows a neutral "The service is busy right now", not a guess that it is Gemini. A scout test built `GeminiCallError` with a keyword that does not exist (`status_code`) and passed only because the scout falls back on any exception; it now raises the real error.
- **Tests:** the icon is declared and served at both paths as SVG; `/` redirects to `/demo`; the busy rule has one case per signal (429, 503, 504 and a timeout are busy; 500, 400, an empty answer and a budget spent before asking are not); the route returns 503 with `Retry-After` only when the flag is set.
- **Review pass:** the `GeminiCallError` docstring said a spent time budget counts as busy; it now matches the strict rule (only if the last attempt itself timed out or got 429/503/504). A busy Gemini is logged as a WARNING (`inspector_gemini_busy`), not an ERROR, since it is expected, temporary and outside our control; real failures keep `inspector_call_failed` at ERROR, so error alerts stay meaningful (nothing in the repo or infra watched the old event). Also checked: hedged requests that both time out count as busy (a TimeoutError); the `/` redirect is a temporary 307, so browsers won't cache it; `/favicon.ico` serves a fixed file path.

# Round 33: Impact without the stock breakdown, by Claude (2026-10-15)

- **Change (the user's call):** the line under "Stock placed" ("1 dozen donated · 1.1 dozen as animal feed", or "all sold to businesses") is removed. The strip is now four plain numbers on one baseline: Calls made → Deals closed → Stock placed → Money recovered.
- **Removed with it:** `donatedByUnit` and `feedByUnit` from `computeImpact` (nothing else read them), the `impactPlacedDetail` element and lookup, and the `.stat-detail` style (Impact was its only user). The money rule is unchanged: every deal except a donation adds price × quantity; a donation still counts as stock placed. The tests keep both cases.
- **Checks:** ruff clean; pytest 440 passed, 20 skipped; `node --test` 26 passed. In the preview, with fictional results (a sale, a decline, a donation and an animal-feed deal), the strip reads "4 · 3 · 2.9 dozen · Rs 111" at 1280 and 375 px, with no sideways scroll and no console errors.

# Round 34: Find buyers shows that it is working, by Claude (2026-10-15)

- **Problem (reported):** after Find buyers, only the button's text changed ("Searching Google Maps…", dimmed like any disabled button) while the Scout ran for several seconds, so the page looked stuck.
- **Searching state, in the page's style:**
  - **Button:** "Searching…" with a small white spinner, at full strength (`.btn-primary.is-busy`, in `base.css` for any primary button). This is the one spinner per search.
  - **Where the list will appear:** one line that says what is really happening, in order: "Searching Google Maps for juice shops, restaurants and bakeries near Demo Mart Johar Town", then "✦ Gemini then checks that each business is a real fit" (indigo sparkle = the AI, as elsewhere). There are no fake progress steps or timers, since the server sends no progress.
  - **Under it:** three placeholder cards with the buyer rows' exact shape (rank, name, reason, facts). Each fades more than the one above, and a soft light sweeps across them (1.6 s, staggered). With reduced motion the sweep is off and the button spinner stays.
  - The head chip reads "Searching · <branch>". The list has `aria-busy` during the search, the line has `role="status"`, and the placeholders are `aria-hidden`.
  - A Refresh, "Search again" or "Next step" search replaces the old list with the same state, so stale buyers are never shown as current. A repeat click within the hour answers from the stored list at once, as before.
- **Bug fixed on the way:** the button always said "Find juice shops & bakeries" for a bulk sale, but the Ladder picks the types per produce and can include restaurants (`engine.py` step 8). `getFindBuyersLabel` now takes the step's real buyer types (the batch's snapshot once calling has started, D54, else the decision's), through a new `buyerTypesPhrase`. For example "Find juice shops, restaurants and bakeries", "Find restaurants" or "Find cattle farms". On a phone the button is full width and may take two lines.
- **Checks:** ruff clean; pytest 440 passed, 20 skipped; `node --test` 26 passed (the label test now covers 1, 2 and 3 types and none). In the preview (fake Inspector, Ladder and a Scout that waits 6 s, with fictional businesses), at 1280 and 375 px: the searching state, the finished list, a Refresh, no sideways scroll and no console errors.
