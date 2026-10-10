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
