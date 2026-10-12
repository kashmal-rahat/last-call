# Module 6 review: Milestone 6A, Steps 1–5 (2026-10-11)

Reviewer: Claude. Scope: commit `9287011` ("Module-6A: Implemented"), checked against `plan.md` Steps 1–5.

Method:
- read the diffs (stores, models, `ladder/engine.py`, `orchestration/handoff.py`, `orchestration/loop.py`, `live_session.py`, `text_session.py`, `tools.py`) and the new tests
- `uv run pytest`: **363 passed, 19 skipped in 19 s**
- `RUN_FIRESTORE_TESTS=1 uv run pytest shared/tests/test_store.py`: **40 passed** (live Firestore, `test_` prefix, cleaned up)
- `scripts/export_schemas.py` gives no diff

**Verdict: 6A is built as planned and works. Two small fixes (R1, R2, about 10 minutes) before 6B; nothing blocking.**

---

## Verified OK
- **Step 1, stores**
  - `create_call` creates the batch only if absent (Firestore `create` + `AlreadyExists`), and stores the record's own `expire_at` instead of a fixed 30 days. Both have contract tests, green against live Firestore.
  - `release_batch` sets `partly_sold`, `sold` or `finding_buyers` from the stock (both stores, tested).
  - `create_batch`, `add_batch_attempt`, `advance_batch_step` (transaction, succeeds once per `from_index`) and `get_calls` (one `get_all`) are in the protocol and both stores, with contract tests.
  - The lock is always released at the end of a call, in `live_session.py` and `text_session.py`; there is a test for the text path.
- **Step 2, models**
  - `StepPlan`, `BatchAttempt`, the `BatchRecord`, `CallRecord` and `MartRules` additions all have defaults; `calling_hours` uses `default_factory`.
  - `demo_mart.json` has `lahore`, 09:00–21:00 and "Cash on pickup". Schemas regenerated.
- **Step 3, handoff**
  - `step_prices` is used by `decide_item` with no behaviour change: every engine test passes, including the exhaustive loop.
  - `build_step_plans` matches the worked example (110/65 · 0/0 · 25/10) and the compost case.
  - `pickup_window` gives the 4 table rows in mart time, and the 21:30 window string names 12 October.
  - `build_call_record`: the quantity comes from the batch; `agent_view()` has no floor and no phone; donation is 0/0; channel `browser`, `city_style` `lahore`, 24 h expiry for `places:` buyers.
- **Step 4, loop:** `next_action` follows rules 1–7 in order. It also handles a step index past the last plan safely (an addition, fine).
- **Step 5, voice**
  - The city style is read from the call record.
  - `record_outcome(do_not_call)` writes nothing for a `places:` browser buyer and adds the flag. `test:` buyers still write an entry; both cases are tested.

---

## Fix before 6B (small)
- **R1. Two different `ScoutNotApplicable` classes.**
  - `orchestration/handoff.py:36` defines its own, while `main.py` imports the one from `scout/scout.py`.
  - In 6B, `/demo/calls` catches `ScoutNotApplicable` to return 409 "This item stays in store". With two classes, one of them would fall through to the generic handler and return 502.
  - **Fix:** delete the class in `handoff.py` and `from lastcall_api.scout.scout import ScoutNotApplicable`. Keep `NeedsPrice` in `handoff.py`.
- **R2. The wrong phone mask.**
  - `handoff.py` imports `mask_phone` from `logging_utils`. That function keeps the first 5 characters and the last 2 (`+9230*******67`), which shows the mobile operator code.
  - It is also a different format from the masked phone the page already shows (`ScoutCandidate.public_view`, `buyer_keys.mask_phone`: `+92 ••••••• 567`).
  - **Fix:** `from lastcall_shared.buyer_keys import mask_phone`. In `test_build_call_record`, replace `"*" in phone` with `phone == buyer_keys.mask_phone("+923001234567")`.

## Minor (same pass)
- **m1. Three `next_action` branches have no test.** Add three asserts to `test_next_action_table_driven`:
  - 5 completed calls in the step, with buyers still on the list → `next_step` (rule 4; set `scout_max_buyers` or make 5 attempts)
  - a scout list for another step (`donate` list while on `bulk_sale`) → `needs_search`
  - an empty buyer list → `next_step`

## No change needed
- **City-style test.** The test checks `render_instruction` with `"lahore"`; the live-session change is one line (`call.city_style or env`). That's acceptable. The deployed check in Step 8 ("the call opens in Lahori Urdu") covers the rest.
- **Floor check in the brief test.** `"65" not in view_json` is a weak check on its own, but `agent_view()` drops the floor fields by construction (`extra="forbid"`), and the Module 2 floor-isolation test still passes.

**Next:** fix R1, R2 and m1, run `uv run pytest`, then start 6B (Steps 6–8). No re-review is needed for these three unless a test fails.

---

# Round 2: review fixes and Milestone 6B code, before deploy (2026-10-11)

Scope: commit `7945945`.

Method:
- read the diffs of `orchestration/handoff.py`, `test_orchestration.py`, `main.py`, `test_demo_routes.py`, and the call-flow parts of `static/index.html`
- `uv run pytest`: **367 passed, 19 skipped**
- `export_schemas.py` gives no diff

**Verdict: the server side is correct and well tested. The page has three bugs that would break or mislead the judge flow (P1–P3), plus one smaller one (P4). Fix them, check by hand in a local run, then deploy. Don't deploy before P1–P3 are fixed.**

## Round-1 fixes: verified
- **R1:** there is now one `ScoutNotApplicable`, imported from `scout/scout.py`.
- **R2:** `buyer_keys.mask_phone` is used, and the test compares the exact masked string.
- **m1:** the three missing `next_action` branches are tested (5 calls used up, a list for another step, an empty list).

## Endpoints: verified OK
- **`POST /demo/calls`** follows the planned order: access code → validation → IP bucket `call` → decision and inspection lookup → branch → batch.
  - An existing batch is used as it is.
  - On creation it checks the step plans, the staff check and the quantity.
  - Then `next_action`, with every other kind returning 409 in plain words, and a chosen buyer must be on the list and not already called.
  - The daily cap is checked **last** (tested: a refusal doesn't use it up).
  - Then the call record, `create_call`, `add_batch_attempt` and a 120 s token.
  - The response has a masked phone only; the stored call has a masked phone, `city_style="lahore"` and a 24 h expiry (tested).
- **`GET /demo/batches/{id}` and `POST …/next-step`:** access code, ID regex, `demo_mart` check. No phones; names come from the live scout list, else "Buyer #rank". `next-step` requires `next_step` and uses the transaction.
- **`/demo/scout`** builds the target from the batch's current step when a batch exists (tested: after `next-step` it searches `charity`).
- `/demo/sessions` and `/demo/scenarios` are gone, and the page has no stale references or `innerHTML`.
- The call panel shows "(from Google Maps)". The WebSocket close handler polls the batch, as planned.

## Must fix before deploy (page, `static/index.html`)
- **P1. The page builds the wrong batch ID.**
  - `loadBatchesForBranch` (~line 1877) and `fetchScoutBuyers` (~line 1937) use `` `${branchId}:${inspection_id}:${item_key}` ``. The server's ID is `{inspection_id}__{item_key}__{branch_id}`, and its regex rejects `:`, so both requests always return 400 and fail silently.
  - **Effect:** after Find buyers, a branch switch or a re-render, the card never loads its batch. The called-buyer chips, "Remaining X of Y" and the next button disappear, and the card falls back to the no-batch view. It only looks right straight after a call, because the polling uses the server's `batch_id`.
  - **Fix:** one helper, `batchIdFor(itemKey) = `${currentInspection.inspection_id}__${itemKey}__${branchSelect.value}``, used everywhere a batch ID is built.
- **P2. The next-action kinds don't match the server.**
  - Both renderers (~lines 2569–2583 and 3615–3629) check `sold_out`, `compost` and `no_buyers`. The server sends `sold`, `compost_approval` and `no_buyer`.
  - **Effect:** after the last sale, the last step or an empty last step, the card shows **nothing**: no "Sold out ✓", no "Compost: needs manager approval", no "No more buyers nearby".
  - **Fix:** use the server's names. Better still, render the action row from **one** function called from both places, so they can't drift apart again.
- **P3. Quantity is always sent, so it is always marked "confirmed by staff", and it can be invented.**
  - The field defaults to `Math.round(item.quantity.low)`, or **20** when `low` is 0. `startCallForItem` always sends it, falling back to 20 again.
  - **Effect:** every batch gets `quantity_confirmed=True`, so the agent never says "taqreeban" for a photo estimate. A display with `low = 0` is offered as 20 units nobody counted, and rounding changes 2.5 dozen to 3.
  - **Fix:**
    - show `low` if above 0, else `high` if above 0, else an empty field (no rounding, no 20)
    - track `quantityEdited[itemKey]`, and send `quantity` **only** when the judge changed the field; otherwise send `null` and let the server use `initial_quantity` (`quantity_confirmed=False`)
    - with an empty field and no estimate, the server's 409 "Enter the quantity" shows as the banner
  - Also remove the `branchSelect.value || 'branch_jt'` fallback (~line 3322). `branch_jt` doesn't exist; send the selected value, or `null` for the default.

## Should fix (same pass)
- **P4. Close codes that mean "no call happened" still poll for 8 s.**
  - In `ws.onclose`, codes `1013` (busy, a retry is already scheduled), `4401` and `4409` also run `pollBatchUntilCompleted`. That waits 8 s and then shows "Saving the call result…" for a call that never started.
  - With `1013` it can also re-enable the buttons while the retry connects.
  - **Fix:** poll only for normal closes (no 4xxx code, not 1013). For `1013`, do nothing (the retry handles it). For 4401, 4409 and 4423, show the message, set `isCallInProgress=false` and re-render.

## Notes (no change now)
- **A 4423 close (lock taken) uses up a buyer.** `voice` has already set the call to `in_progress` (`start_session`) when `lock_batch` fails, and nothing marks it finished, so that buyer counts as called. This was already in Module 2. It only happens when two calls race for the same batch, which the endpoint's `busy` check makes rare. Record it for Module 9.
- `/demo/calls` uses `^[a-z0-9_-]{1,60}$` for `inspection_id` rather than Module 4's `^insp_[a-z0-9_]{1,80}$`. Real IDs (`insp_YYYYMMDD_HHMMSS_xxxxxx`, 27 characters) pass, so it's fine as it is.

## Before deploy
1. Fix P1–P4, then `uv run pytest`.
2. **Check locally by hand** (the page has no automated tests). Run the API, then:
   - inspect the overripe sample, Find buyers, then reload the batch by switching the branch away and back: the chips and "Remaining X of Y" are still there (P1)
   - call and decline until the step is used up: the "Next step" button appears; at the last step, the final chip appears (P2)
   - in the network tab, the first `/demo/calls` has `"quantity": null` unless you edited the field (P3)
3. The user commits; then follow plan Step 8 (deploy `api` **and** `voice`, then the manual checks).

---

# Round 3: P1–P4 re-check (2026-10-12)

Scope: commit `3ab2143`. `uv run pytest`: **367 passed, 19 skipped**. The page's inline script passes `node --check`.

| Item | Status | Checked |
|---|---|---|
| P1 | ✅ | One `batchIdFor(itemKey)` = `{inspection_id}__{item_key}__{branch_id}`, used by both the branch reload and the post-search batch fetch |
| P2 | ✅ | One `renderNextActionRow(...)` with the server's names (`sold`, `compost_approval`, `no_buyer`), covering every kind including `needs_search` and `busy` |
| P3 | ✅ | The field shows `low`, else `high`, else empty (no rounding, no 20). `quantity` is sent only after an edit, else `null`. The `branch_jt` fallback is gone |
| P4 | ✅ | Only normal closes poll. 4xxx codes show the message, clear `isCallInProgress` and re-render. 1013 returns early |

**Verdict: ready to deploy.** One small leftover, already in the Module 2 page, that is optional before deploy.

## Optional (5 minutes; fine to do after deploy)
- **B1. The busy-retry path still breaks the call.**
  - On close code 1013, `ws.onclose` runs `cleanupAudio()` **before** returning. That stops the microphone and closes the `AudioContext`, so a retried connection has no audio in either direction.
  - After the 3rd failed retry, `isCallInProgress` stays `true`, so every call button stays disabled until a page reload.
  - `retryCount` is also never reset between calls.
  - **When it happens:** only when a `voice` instance already has 4 live calls; rare with a few judges.
  - **Fix:**
    - for 1013, return **before** `cleanupAudio()`
    - in `handleBusyRetry`'s give-up branch, also set `isCallInProgress = false` and re-render
    - set `retryCount = 0` at the start of `startCallForItem`

## Not reported by the agent
- The three local manual checks from round 2 ("Before deploy", item 2) aren't in the report. They are repeated in plan Step 8's deployed checks, so do them there and watch for P1 (chips survive a branch switch) and P3 (`"quantity": null` in the network tab).

## Next
1. Optional B1, then `uv run pytest`.
2. The user commits. Deploy **both** services (`./scripts/deploy.sh api` and `./scripts/deploy.sh voice`); `/health` shows HEAD on both.
3. Plan Step 8 manual checks on the deployed `/demo`, and report the number of calls a full run used (cap 50/day).

---

# Round 4: B1 re-check (2026-10-12)

Scope: uncommitted change to `static/index.html` (+10/−3). `uv run pytest`: **367 passed, 19 skipped**. The page's inline script passes `node --check`.

- ✅ **1013:** `ws.onclose` now returns **before** `cleanupAudio()`, so the microphone and both audio nodes survive the retry. Every other close code keeps the old behaviour.
- ✅ **Giving up after 3 retries:** the page cleans up the audio, clears `isCallInProgress`, disables Hang up, sets "Server Busy" and re-renders, so the buttons come back.
- ✅ **`retryCount = 0`** at the start of `startCallForItem`.
- ✅ **One listener:** `captureNode.port.onmessage` is only assigned (once per `onopen`); no listener is added on top, so a retry doesn't double the audio.
- Note, no change needed: the retry starts only when the server's `{"type":"busy"}` message arrives before the 1013 close. `live_session.py` always sends it first, so this holds.

**Verdict: Module 6 code is complete. Commit and deploy (plan Step 8).**

---

# Round 5: shelf lock (D58), before deploy (2026-10-12)

Scope: uncommitted change to `static/index.html` (it replaces the per-branch-progress version). `uv run pytest`: **367 passed, 19 skipped**. The page's inline script passes `node --check`.

**Verdict: D58 is built as specified. One small fix (L1, 2 minutes), then commit and deploy the API.**

## Verified OK
- **B removed:** no branch note, no `branchesMap`, no automatic list reload after a switch. `loadBatchesForBranch()` stays, because two things still use it: the "Call in progress… · Refresh" button and the load after a decide.
- **Branch change** (only possible when unlocked) keeps the photo and decisions and clears only the buyer lists, the batches and the call card.
- **`isShelfLocked()`** is true during a live call or once any batch has attempts. **`updateShelfLock()`** disables the branch, closing time, every `.price-override-input` and every `.btn-redecide` (these class names match the card code), and shows the note. It runs at the end of `renderResults` and on every way a call ends.
- **New shelf** does nothing during a call. Otherwise it starts a new shelf ID, clears all page state, hides the result area and unlocks.
- **A new inspection** clears the call state and unlocks, and keeps the shelf ID.
- The "Play this buyer" CSS fix is kept.

## Fix before deploy
- **L1. The Inspect button is re-enabled while an inspection is running.**
  - `handleInspect` sets `btnInspect.disabled = true` (line ~3306), then calls `updateShelfLock()` (line ~3321), which sets `btnInspect.disabled = isCallInProgress`, i.e. **false**.
  - So during the 4–10 s inspection the judge can click Inspect again. That fires a second inspection, which uses the daily inspect cap twice and makes the two results race.
  - **New shelf** is also clickable mid-inspection: it clears the page, and then the late result renders anyway.
  - **Fix:** add `let isInspecting = false;`. Set it to true where `btnInspect.disabled = true` is today, and back to false where it's re-enabled (line ~3369, every path). In `updateShelfLock()`, use `btnInspect.disabled = isCallInProgress || isInspecting;` and the same for `btnNewShelf`.

## Next
1. Fix L1, then run `uv run pytest` and `node --check`.
2. The user commits everything (page, D58, docs) and deploys the API only (`./scripts/deploy.sh api`).
3. Test 9 (lock) on the deployed `/demo`, then the remaining Step 8 checks (3, 4, 5, 10, 11 and Firestore).

---

# Round 6: L1 re-check (2026-10-12)

`uv run pytest`: **367 passed, 19 skipped**. The page's inline script passes `node --check`.

- ✅ **L1:**
  - `isInspecting` is set to true right where the Inspect button is disabled, and reset to false in the `finally` block, so every path clears it (success, HTTP error, network error).
  - `updateShelfLock()` keeps both **Inspect** and **New shelf** disabled while `isCallInProgress || isInspecting`.
  - The New shelf handler also returns early in that state.
  - `renderResults` during the inspection no longer re-enables the button.

**Verdict: Module 6 code is complete.** The user commits everything (page, D58, docs, this review) and deploys the API only. Then test 9 (lock) and the remaining plan Step 8 checks on the deployed `/demo`.

---

# Round 7: deployed checks by the user (2026-10-12)

All plan Step 8 checks were run by the user on the deployed `/demo` (screenshots in the chat).

| Check | Result |
|---|---|
| Find buyers, Start calling, Lahori greeting at the opening price | ✅ |
| Decline → Next buyer #2; partial deal (0.65 dozen @ Rs 110) → next buyer offered at once | ✅ |
| "Don't call again" → "Asked not to be called"; **no `do_not_call` collection exists** in Firestore, so nothing was written (D55) | ✅ |
| Next step → Find charities → donation deal; stock reaches 0 | ✅ |
| Last hour → discount, no call buttons | ✅ |
| Lock (D58): branch, closing time and shelf price disabled after calls; New shelf unlocks | ✅ |
| `/demo/calls` payload `quantity: null`; response has `phone_masked` only; a network search for the last digits finds only masked forms; `/demo/branches` has no coordinates | ✅ |
| `calls/{id}`: channel browser, city_style lahore, masked phone, `expire_at` = `created_at` + 24 h, `quantity_confirmed_by_staff` false | ✅ |
| `batches/{id}`: `quantity_confirmed` false, lock released, plans 110/65 → 0/0 → 25/10 (the worked example) | ✅ |
| Calls used today: `daily_sessions/2026-10-12` count = 10 (cap 50) | noted |

**Pending (page text, no server change):**
- the donation chip shows "Deal 0.8 dozen @ Rs —"; it should be "Donated 0.8 dozen"
- "Sold out ✓" should be "All stock placed ✓"
- remove the 404 batch lookups after decide and after the first Find buyers

**Note:** `test_daily_sessions` in the production database is a leftover from a live contract-test run. It is harmless and can be deleted.

**Module 6: implemented and deployed.**
