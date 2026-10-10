# Module 3 review: Milestone 3A (2026-10-10)

Reviewer: Claude. Scope: the 3A code, `results/report-3a.md` and `results/profiles.md`, checked against `plan.md`.
Method: code read-through, plus one read-only check of the Firestore client API. I did **not** run the test suite.

**Verdict:** the structure is right and close to the plan. The refactor is clean, the engine is pure, profiles are stored and versioned, and there's no branching on produce names. But there is **one blocking bug** that the green test run hides, and **one decision-quality gap** that breaks the "people first" rule. Fix both before starting 3B.

---

## Critical (fix before 3B)

### C1. `FirestoreStore.get_profiles` crashes on every call
`shared/lastcall_shared/firestore_store.py`, `get_profiles`:
```python
snaps = await self.client.get_all(doc_refs)
```
`AsyncClient.get_all` is an **async generator** (checked: `inspect.isasyncgenfunction(AsyncClient.get_all) == True`). You can't `await` it; this raises `TypeError` the first time it runs. Every `decide_inspection` in production would fail, so `/demo/decide` would return 502 for every request.

**Why the tests are green:** the Firestore contract tests are skipped without `RUN_FIRESTORE_TESTS=1`, and `check_profiles.py` never saves. So the Firestore path never ran.

**Fix:**
```python
out = {}
async for snap in self.client.get_all(doc_refs):
    if snap.exists:
        data = snap.to_dict()
        if data:
            out[snap.id] = ProduceProfile.model_validate(data)
return out
```
**Required check:** run the store contract suite against real Firestore (`RUN_FIRESTORE_TESTS=1 uv run pytest shared/tests/test_store.py`) and report the result. It must cover `get_profiles` (including missing keys), `create_profile` (doesn't overwrite), `set_profile` and `delete_profile`. Do the same for `save_decisions` / `get_decisions` in Step 7.

### C2. Overripe produce that's still edible skips donation and goes to animal feed
From `profiles.md`: Gemini gave overripe **spinach and coriander** no human use (`restaurant: false, charity: false`). As a result the worked example "overripe spinach, 8 h to closing" → **animal feed at Rs 10/kg**, skipping both restaurants and charities.

That contradicts our own stage definition, which both prompts share: *overripe = "clearly past its best but still edible"*. Giving edible food to cattle breaks the food-waste hierarchy the idea doc promises (people first, then animals). The likely cause is the prompt's "when unsure, say false" rule pushing `charity` to false.

**Fix (generic code rule, no produce knowledge, one line in `check_profile`):** set `charity = True` for fresh, ripening and overripe. By the Inspector's definitions every one of those stages is still edible, and spoiled or unsafe produce can never reach people because of the allowed-steps table. Log the correction like the shelf-life rule. Add a test: a profile with `overripe.charity=False` becomes `True` after `check_profile`.
(Leave `juice_shop`, `restaurant` and `bakery` to Gemini; those are real produce knowledge.)

---

## Important (fix in the same pass; each is small)

### I1. A lost create race uses an unsaved profile
`resolve_profiles` ignores the return value of `store.create_profile`. If another request stored the profile first (`False`), this request uses its own freshly generated profile, which may differ (33% of produce varied between runs). That one decision then won't match every later one.
**Fix:** if `create_profile` returns `False`, read the stored `__v{N}` profile back and use that.

### I2. A Firestore write error fails the whole decision
An exception from `create_profile` (network, permissions) propagates and turns the whole decide into a 502.
**Fix:** wrap the save in `try/except Exception`, log a warning (counts only), and still use the generated profile for this request.

### I3. The cost and latency numbers in `LadderMeta` are guessed, not counted
`ladder.py` works out `profile_calls` from "were there tokens" and counts `profiles_generated` as every Gemini-sourced profile whenever a call happened. That **includes profiles that were read from the store**. These numbers appear in the demo footer and in any cost slide.
**Fix:** have `resolve_profiles` return explicit counts (`calls`, `generated`, `fallbacks`), and copy them into `LadderMeta`.

### I4. `next_steps` for "keep" leaves out "discount"
For `keep`, `next_steps` contains only off-shelf steps. The plan says "remaining fitting allowed steps after `step`", so a kept fresh item's next step should start with `discount`.
**Fix:** when the step is `keep` and `discount` is allowed, put `discount` first in `next_steps`. Add a test.

### I5. Remove the label comparison; replace it with a review table
Decision (user, 2026-10-10): there will be **no labels CSV**. Shelf-life bands and buyer fit are judgement calls, so labels written by the user (or by another AI) would be a second guess, not ground truth. Comparing two guesses gives a misleading "accuracy" number.
**Fix:**
- Remove the `--labels-csv` option, the label-reading code and every "labels pending" wording from `scripts/check_profiles.py`, `profiles.md` and the report.
- In `profiles.md`, keep the generated-profiles table, the run-to-run variation table and the worked examples, and add a **"Sense check (user)"** column to the profiles table, left blank, for the user to mark ✓ or write a correction.
- Keep the variation numbers. They are real and they justify storing profiles.

---

## Minor (cheap; do if convenient)

- **M1.** `decide_inspection` sets its deadline with `asyncio.get_event_loop().time()`, while `call_structured` measures it with `time.monotonic()`. They're the same clock on the default event loop, but use `time.monotonic()` for both; `get_event_loop()` is also deprecated in this context.
- **M2.** The demo mart is "Demo Mart Gulberg, Lahore", but the Negotiator scenarios and its default `CITY_STYLE` are Karachi. Make the demo mart Karachi now, so the Module 6 handoff doesn't pitch Lahore stock in a Karachi style.
- **M3.** Units in the price list: kinnow has only `dozen`, and lemon, guava and the rest have only `kg`. If the Inspector estimates kinnow in kg, the demo shows "needs shelf price". Add both units for produce commonly sold either way (kinnow, lemon, guava, mango if added).
- **M4.** `engine.py` imports `produce_key` from `profiles.py`, which imports the Gemini SDK and reads the prompt file at import time. The engine is still pure in behaviour; moving `produce_key` into a small helper module would keep it free of those imports. Optional.

---

## Not code bugs: notes for the user

- **Raw variation is high, which is expected and justifies storing profiles.** 4 of 12 produce changed between two uncached runs, so whichever answer is stored first sticks. There's no ground truth for shelf life, so we don't claim an accuracy number; the user sense-checks the stored profiles and fixes any clear error with `scripts/produce_profiles.py set` (Step 7).
- **With real profiles, bananas rarely leave the shelf.** Gemini says ripening bananas sell for 1–3 days, so the "late-ripening banana" examples resolve to keep. That's a reasonable reading, not a bug. It does mean the demo needs the **Step 0 overripe/spoiled photo** to show the off-shelf ladder.
- The report says "no deviations". That's accurate except for the issues above.

## Verified OK
- `call_structured` is a faithful move of `inspector._call`. The error messages are kept through `label`, the inspector wrapper converts to `InspectorError`, and the re-exports are in place.
- The allowed-steps table, Cases A/B/C, the discount formula and clamping, price rounding, the floor ≤ opening rule, buyer types, the on-hold rules, compost approval, and the `buyer_condition` filtering when bad pieces are removed all match the plan.
- No produce-name branching, no sampling parameters, the model comes from settings, logs contain no names or evidence, and `shared` doesn't import from `services`.
- The `LadderDecision` and `MartRules` validators match the plan.

## Before approving 3B
1. C1 and C2 fixed, plus I1–I5. Add a unit test for each.
2. The Firestore contract tests run live and green (C1), with the output pasted in the report.
3. `uv run pytest` green, with the Module 1 and 2 tests unchanged.
4. The user skims the generated profiles in `profiles.md` and fixes anything clearly wrong with `scripts/produce_profiles.py set` (built in Step 7). Optional real evidence: the banana time-lapse (daily photos of one tray) compared with the banana profile's bands.

---

# Round 2: re-review of the fixes (2026-10-10)

Method: read-only code review of the changes, plus the round-1 report and the regenerated `profiles.md`. The agent reports 225 passed and 7 skipped (the 7 are the Firestore tests the default run skips), and **16/16 live Firestore contract tests passed**.

**Verdict: Milestone 3A is approved. 3B can start.** Every Critical and Important item is fixed correctly, and nothing new is blocking.

| Item | Status | Checked |
|---|---|---|
| C1 | ✅ | `get_profiles` uses `async for … in self.client.get_all(...)`; live Firestore run green |
| C2 | ✅ | `check_profile` sets `charity=True` for edible stages and logs it; overripe spinach now → **donate** (was animal feed) |
| I1 | ✅ | a lost create race reads the stored profile back |
| I2 | ✅ | save errors are logged (error type only) and don't fail the decision |
| I3 | ✅ | `ResolveProfilesStats(calls, generated, fallbacks)` copied into `LadderMeta` |
| I4 | ✅ | `keep` → `next_steps` starts with `discount` |
| I5 | ✅ | labels removed; "Sense check (user)" column added |
| M1–M4 | ✅ | monotonic deadline; demo mart now "Demo Mart Clifton, Karachi"; dual units; `produce_key` moved to `ladder/keys.py`, so the engine no longer imports the Gemini SDK |

## Small notes (not blocking; fold into 3B)
- **N1. Dozen and kg prices disagree with each other.** A dozen should cost about (kg price × kg per dozen):
  - guava: Rs 140/kg but Rs 100/dozen (a dozen guavas weigh roughly 1.5–2 kg)
  - kinnow: Rs 140/kg vs Rs 200/dozen (a dozen weighs roughly 2 kg)

  These are demo values, but a judge comparing two cards would notice. **The user** sets them consistently when checking the price list.
- **N2. `check_profile` logs `produce_key` (e.g. `banana__v1`),** which is a produce name. The "no names in logs" rule was about untrusted photo text, and the key is sanitised, so this is acceptable. Either log only `corrections` or accept it. No action needed.
- **N3. `profiles.md` is still titled "Accuracy & Consistency Report".** Rename it "Profile check" to match the no-labels decision, so the slide doesn't claim accuracy.
- **N4. `profiles_generated` also counts a profile that lost the create race** (the stored one is used instead). A footer number is off by one in a rare race. Ignore.

## For the user: sense check (`results/profiles.md`)
Raw variation went **from 4/12 to 9/12** produce between two uncached runs, so whichever answer gets stored first is partly a coin flip. That's exactly why profiles are stored, and why your skim matters. Entries worth a look:
- **kinnow, apple:** the ripening and overripe bands flipped between runs (`1_to_3_days` vs `over_3_days`). Pick the one you believe.
- **spinach fresh → juice shop**, **bottle gourd → juice shop:** plausible in Pakistan (green juice, lauki juice). Keep or remove.
- **banana spoiled → OK for cattle (True)**, while mango and guava flipped between runs. Decide what you're comfortable with; "no" is the cautious choice.
- **Tomato and the other produce marked "not OK for cattle when spoiled"** → spoiled tomatoes go to compost. Cautious and fine.

Profiles are generated in production on first sight, so these exact answers won't automatically be the stored ones. After 3B, run `scripts/produce_profiles.py warm` for the demo produce, skim the stored profiles, and fix anything with `scripts/produce_profiles.py set`.

## Before the 3B deploy
- The Step 0 photo is still needed. The banana tray (day 1 now, plus a photo in 2–3 days) gives the overripe sample and a time-lapse pair.

---

# Additions for Milestone 3B (2026-10-10)
Build these together with Steps 7–10:
- **Step 6B (new, D43): 5-vote consensus profiles.** See `plan.md` Step 6B for the exact merge rules, the parallel-call rules (no hedging, `max_attempts=1`, at least 3 answers) and the tests. Measure raw vs consensus variation in `profiles.md`.
- **N1:** make the demo dozen and kg prices consistent (a dozen ≈ kg price × typical weight of 12 pieces). **The user** checks the final price list.
- **N3:** rename `profiles.md`'s title to "Profile check" and remove "accuracy" wording.
- **Simulated sample:** the user's AI-generated overripe banana tray (`data/probe/simulated_overripe_banana.webp`) goes in `static/samples/` as `sample_overripe_banana_simulated.jpg` (run through `prepare_image`), labelled **"Simulated overripe tray (AI-generated)"** in `samples.json`. It's for testing the off-shelf paths only: don't pair it with a real photo as a time-lapse, and keep it out of any eval. If the Inspector returns `no_produce` for it, report that; it's the safety rule working, not a bug.

---

# Round 3: Milestone 3B review (before deploy, 2026-10-10)

Method: read-only review of the 3B code and `results/report-3b.md`. I didn't run tests; the agent reports 240 passed, 8 skipped, and 18/18 live Firestore contract tests passed.

**Verdict: well built. Fix B1 and B2 (both small, both visible to judges), then deploy.** Step 6B voting, the decisions store, `/demo/decide`, the profiles script and the decision panel match the plan. The one deviation (votes and uncertain fields copied onto each decision) is sensible. The simulated-banana table shows the ladder working: bulk sale when the bananas won't last until closing, 40% off in the last hour.

## Fix before deploy
### B1. Judges will hit the hourly limit quickly
`/demo/decide` uses the same per-IP limit as inspections and voice sessions (`IP_RATE_LIMIT_PER_HOUR`, default 20). Every photo triggers one decide, and **every closing-time change or typed price triggers another**. A judge trying 3–4 photos and the selector will get 429s within minutes. Yet a decide costs nothing once profiles are warm.
**Fix:**
- give decide its own setting, `DECIDE_IP_LIMIT_PER_HOUR: int = 120`, in `config.py` (a default in code; no Terraform change)
- raise `DEMO_DAILY_DECIDE_CAP` to 1000

The Gemini cost is still bounded: only a first sighting of new produce calls Gemini (5 votes), and inspections keep their own limits.

### B2. A failed decide is silent and shows the old decisions
In `triggerDecide()`, a non-OK response only goes to `console.error`, and `currentLadderResult` **keeps the previous result**. So after a 429 or 502, the cards still show the "Morning" decisions while the selector says "Last hour". That's a wrong answer on screen, not just a missing one.
**Fix:**
- on any failure, clear `currentLadderResult` and show a visible banner with the server's `detail` (e.g. "Hourly limit reached", "Decision failed, please try again")
- also ignore out-of-order responses when the selector is changed quickly: keep a request counter and apply a response only if it's the latest

## Minor (cheap; do in the same pass)
- **B3.** Validate `inspection_id` in step 2 of the endpoint (`^insp_[a-z0-9_]{1,80}$`, matching how the Inspector builds ids). An id containing `/` is an invalid Firestore path and currently becomes an unhandled 500.
- **B4.** In the vote collection, one answer can list the same produce twice, and each copy counts as a vote. Count at most one answer per produce per vote (keep the first).
- **B5.** `produce_profiles.py set` keeps `uncertain_fields` from the input file. If the manager copied the output of `show`, the card would still say "uncertain" after the manager decided. For manager profiles, set `uncertain_fields = []`.
- **B6.** The Docker packaging check couldn't run (no local Docker). Accept that; the first `/demo/decide` on the deployed service proves `demo_mart.json` and `profile_prompt.md` are in the image. If it fails with `FileNotFoundError`, that's the cause.

## Notes (no change needed)
- With the stored banana profile, the simulated tray goes to **bulk sale even at "Now", about 1.8 h before closing**. That's correct by our rules (it won't last until closing). Whether a buyer can collect that late is the pickup window's job in Module 6. For the demo, the clearest contrast is **Morning → bulk sale** vs **Last hour → 40% off**.
- Consensus variation is down from 8/12 (raw) to 3/12 (5-vote). The rest is removed by storing the profile; that's the intended design.
- The final price list (N1) looks consistent: banana 180/dozen ≈ 150/kg × 1.2 kg, guava 210/dozen ≈ 140 × 1.5, kinnow 280/dozen ≈ 140 × 2. **The user** confirms the values.

## Then deploy (the agent's stop point, with user approval)
1. `uv run pytest` green after B1–B5.
2. Delete any old single-call `produce_knowledge/*__v1` docs in the real collection, if any exist.
3. `produce_profiles.py warm` with the produce names the Inspector actually returns for the demo samples (run each sample once locally, or use the names in their saved inspections, e.g. banana, apple, tomato, cucumber, guava). Show the warmed profiles (votes, uncertain fields) in the report.
4. `./scripts/deploy.sh api`, then the Step 10 checks on the deployed `/demo`:
   - the simulated tray: Morning → bulk sale, Last hour → discount
   - the selector changes a decision
   - repeating the same photo gives identical decisions
   - a typed price re-decides
   - a forced failure (wrong access code) shows the B2 banner
   - Firestore has `produce_knowledge/…` and `decisions/…`
5. The Step 10 docs: Module 3 status and the README section.

---

# Round 4: Fixes and deploy check (2026-10-10)

Method: read-only review of the round-3 fixes and the deploy section of `results/report-3b.md`.

**Verdict: Module 3 is done and deployed** (`api-00020-w75`). B1–B6 are fixed, the docs show Module 3 as deployed, and the live checks show the intended behaviour:
- the simulated tray: Morning → bulk sale (opening Rs 110, floor Rs 65), Last hour → 40% off;
- the real shelf sample: banana overripe (mid), Morning → bulk sale, Last hour → 35% off; the apples are kept;
- repeating a decision gives an identical result, and a typed price re-decides.

Checked in code:
- **B2:** request counter, old decisions cleared, visible banner.
- **B1:** a separate 120/h limit and a 1000/day cap.
- **B3–B5:** fixed as described.

## Small leftovers (not blocking; any later pass)
- **R1.** The B2 banner was only checked by calling the API directly (401 with `curl`), not by clicking in the browser. **The user** should check it once on `/demo`: enter a wrong access code → decide → the banner appears and no decisions show.
- **R2.** A FastAPI validation error (422) returns `detail` as a list, so the banner would show "[object Object]". In the page, when `detail` isn't a string, show "Decision failed, please try again." This only happens with malformed requests, which the page doesn't send.
- **R3.** The deployed revision was built from **uncommitted** changes, so git doesn't yet contain the code that is live. **The user** should commit Module 3 now, so the repo matches what's deployed.

## Notes
- Cattle suitability for spoiled banana, apple and guava came out **uncertain**, so the consensus is "no" (needs 4 of 5 votes) and those produce go to compost when spoiled. That's the cautious outcome by design. If you want spoiled bananas to go to cattle feed, set a manager profile with `scripts/produce_profiles.py set`.
- The warmed profiles cover the produce in the current samples (banana, apple, tomato, cucumber, guava). Any new produce in an uploaded photo is generated on first sight (5 votes, about 5–8 s for the first decide).

---

# Round 5: Timing rules v2 (D44), after manual testing (2026-10-10)

**Why:** testing the deployed demo with the "Bananas & Apples" sample, ripening (mid) bananas got a **bulk sale at 12 h before closing** and a **smaller discount at 1 h (10%) than at 4 h (20%)**. Both follow the old rules, but the rules were wrong:
1. Ripe produce was allowed off the shelf, although the Inspector defines `ripening` as "ripe and good to sell".
2. "Won't last until closing" sent produce away in the morning, losing a day of full-price sales; the next photo would have caught the change.
3. The discount depth came from an invented "how close to surviving overnight" measure, so it shrank near closing.

**The new rules** are in `plan.md` Step 4 (D44): ripening never leaves the shelf, the evening window discount deepens 5% per hour towards closing, and overripe produce goes to bulk sale while there's time for pickup. Quantity is still ignored (user decision: fine for the demo).

## Scenario table (must become one table-driven test)
Mart rules: closes 23:00, opens 09:00 (O = 10 h), window W = 6 h (from 17:00), pickup 2 h, discounts 10–40%. "Sells for" = band hours (4 / 15 / 48 / 96) × level factor (early 1.0, mid 0.7, late 0.4). The photo time sets `H` = hours until 23:00.

| # | Produce, stage (level) | Profile used | Sells for | Photo | H | Expected step | Discount / flags |
|---|---|---|---|---|---|---|---|
| 1 | onion, fresh (mid) | fresh `over_3_days` | 67.2 h | 10:00 | 13 | keep | |
| 2 | banana, ripening (mid) | ripening `6_to_24h` | 10.5 h | 10:00 | 13 | keep (for now) | `recheck_next_photo` |
| 3 | same as 2 | | 10.5 h | 19:00 | 4 | discount | 20% |
| 4 | same as 2 | | 10.5 h | 22:00 | 1 | discount | 35% |
| 5 | banana, ripening (mid) | ripening `1_to_3_days` | 33.6 h | 19:00 | 4 | keep | |
| 6 | tomato, fresh (early) | fresh `1_to_3_days` | 48 h | 19:00 | 4 | keep | |
| 7 | spinach, fresh (early) | fresh `6_to_24h` | 15 h | 10:00 | 13 | keep (for now) | |
| 8 | same as 7 | | 15 h | 17:00 | 6 | discount | 10% |
| 9 | same as 7 | | 15 h | 22:00 | 1 | keep | still fine at 09:00 tomorrow |
| 10 | spinach, ripening (mid) | ripening `under_6h` | 2.8 h | 19:00 | 4 | discount | 40% (stops before closing) |
| 11 | same as 10 | | 2.8 h | 10:00 | 13 | keep (for now) | |
| 12 | banana, overripe (mid) | overripe: juice_shop, bakery | n/a | 10:00 | 13 | bulk_sale | buyers juice_shop, bakery |
| 13 | same as 12 | | | 20:30 | 2.5 | bulk_sale | |
| 14 | same as 12 | | | 21:30 | 1.5 | discount | 40% (too late for pickup) |
| 15 | coriander, overripe (mid) | overripe: no business use, cattle no | | 10:00 | 13 | discount | 40%; next_steps [donate] |
| 16 | potato, overripe (early) | overripe: restaurant | | 10:00 | 13 | bulk_sale | buyers restaurant |
| 17 | tomato, spoiled, no mould | spoiled_ok_for_cattle yes | | any | 4 | animal_feed | |
| 18 | tomato, spoiled, no mould | spoiled_ok_for_cattle no | | any | 4 | compost | needs_approval |
| 19 | tomato, spoiled, `mould` in issues | spoiled_ok_for_cattle yes | | any | 4 | compost | needs_approval |
| 20 | apple, fresh (mid), worst_stage spoiled | fresh `over_3_days` | 67.2 h | 10:00 | 13 | keep | remove_bad_pieces |
| 21 | banana, overripe, staff reason `low_confidence` | as 12 | | 10:00 | 13 | bulk_sale | on_hold, check_before_off_shelf |
| 22 | "unknown produce", overripe | fallback profile | | 10:00 | 13 | bulk_sale | buyers restaurant; on_hold, identify_item, enter_shelf_price |
| 23 | produce not in the price list, ripening (mid) | ripening `1_to_3_days` | 33.6 h | 10:00 | 13 | keep | needs_price, enter_shelf_price |
| 24 | banana, ripening (mid), photo after closing | as 2 | 10.5 h | 00:30 | 22.5 | keep (for now) | |

Expected property, shown by rows 7–9: the same reading can be discounted at 17:00 and kept at 22:00 (at 22:00 it still sells until 13:00 tomorrow). This is correct; the reason text must make it clear with clock times.

## What to change (code)
1. **Engine (`ladder/engine.py`):** implement `plan.md` Step 4 v2 exactly. Remove the old Case A/B/C logic, the `min_discount` branch for overripe, and the fresh `check_before_off_shelf` fallback. Update the `allowed_steps` table (ripening: keep, discount).
2. **`MartRules` and `demo_mart.json`:** replace `overnight_hours` with `opening_time` (09:00), so overnight hours = closing → next opening, and add `bulk_pickup_hours = 2`. Validators: opening ≠ closing; `bulk_pickup_hours` in 0–6. Regenerate the schemas.
3. **Reason text:** clock times as in Step 4 item 10 (photo time = closing − H; "today"/"tomorrow").
4. **Document the "sells for" calculation:** a comment above `BAND_HOURS` / `LEVEL_FACTOR` in `engine.py`, and a short "How decisions are made" paragraph in the README's Module 3 section: the time rules, the discount schedule, and why level scales the band (profile = time from the start of a stage; level = how far into it; factor = how much is left).
5. **Tests:** the scenario table above as one table-driven test; the exhaustive loop with the new H values and "fresh/ripening never off-shelf"; the monotonic-discount test. Remove or rewrite tests that encode the old rules.
6. **`scripts/check_profiles.py`:** replace the old worked examples with rows 2–4, 12, 14 and 17 of the table, run with the generated profiles.
7. **R2 (from round 4):** in `triggerDecide()`, if `detail` isn't a string, show "Decision failed, please try again."

## Deploy and verify
- `uv run pytest` green, with the Module 1 and 2 tests unchanged.
- Deploy `api`. Stored profiles are unaffected (no prompt change), so there's no need to re-warm.
- On the deployed `/demo`, run the "Bananas & Apples" sample once and switch the selector on the **same inspection**. If the bananas read ripening (mid) again, expect: Morning (12 h) → keep for now; Evening (4 h) → 20%; Last hour (1 h) → 35%. The apples stay keep. Run the simulated tray: Morning → bulk sale; Last hour → 40% off. Report the actual Inspector stage with each result, since the reading can vary between inspections.

---

# Round 6: D44 check (2026-10-10)

Method: read-only review of `engine.py`, the scenario tests and the round-5 report, plus the live `/health`.

**Verdict: D44 is implemented correctly and live.**
- `decide_item` follows plan Step 4 v2 branch for branch: ripening never off-shelf, the evening-window schedule, 40% when produce stops selling before closing, overripe bulk only with ≥ 2 h for pickup, spoiled → feed or compost.
- All 24 scenario rows are in the table-driven test.
- The exhaustive loop asserts "fresh/ripening never off-shelf" (2,880 combinations, 0 violations), and the monotonic-discount test exists.
- Reason lines use clock times ("sells until 06:12 in 3 days; still fine at tomorrow's 09:00 opening → keep").

## Notes
- **S1. The live commit label is wrong again.** `/health` reports `96f0375`, but the D44 code was committed later (`475cedb`), so the deploy was built from uncommitted files. The working tree is clean now, so **redeploy once** (`./scripts/deploy.sh api`) to make the label match. Optional: have `deploy.sh` refuse to run with uncommitted changes.
- **S2. The live check didn't exercise the main fix.** This time the Inspector read the "Bananas & Apples" bananas as **overripe (mid)**, not ripening, so the live run shows overripe behaviour (Morning/Evening → bulk sale, Last hour → 40%). That's correct, but the "ripening stays on the shelf" fix is proven only by the unit tests. **The user** can check it live by re-running that sample until the bananas read ripening, or with any fresh/ripening photo.
- **S3. Inspector readings vary between inspections of the same photo.** The same bananas read ripening (mid) earlier and overripe (mid) now. The simulated tray went from overripe (late) to **spoiled (mid) → compost**. This is Module 1 behaviour, not the Ladder. The Ladder is deterministic for a given reading, but a different reading gives a different card. The Module 1 eval target (same stage ≥ 90% when a photo is run twice) is still pending. Worth measuring before the demo video, because a judge re-running a sample may see a different stage.
- **S4. (cosmetic)** `engine.py` uses a hard-coded `datetime(2026, 10, 10)` only to format clock times. It's harmless (only time differences matter), but any fixed date or plain `timedelta` arithmetic would read better.

**Module 3 is complete.** S1 is a one-command redeploy; S2 is a quick manual check; S3 belongs to Module 1.
