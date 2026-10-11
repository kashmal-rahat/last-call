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
