# Module 6: Orchestration and the Call handoff, plan (v1)

> Approved 2026-10-11. Claude plans and reviews; Gemini Flash in Antigravity implements. Follow the steps in order and stop at every 🛑.
> The docs (`docs/*.md`, `plans/README.md` D53–D57) were updated for this design on 2026-10-11, so they should agree with this plan.
>
> **Rules for the coding agent:**
> - Don't change Module 1, 3 or 4 behaviour. Their existing tests must pass unchanged. Module 2 changes only where this plan says so (Step 1 lock release, Step 5); all other Module 2 tests pass unchanged.
> - If this plan conflicts with `docs/` or `plans/README.md`, stop and ask the user. Don't choose silently.
> - No new external service or library is used. If you think one is needed, stop and ask.
> - Model IDs only through `get_settings()`. No sampling parameters (D30).
> - No Terraform change is planned. No commits or pushes unless the user asks. Deploy only from committed code.
> - Never write a full phone number into an API response, a call record, a log or a results doc (D51, D55). New endpoints log only IDs, kinds, counts and latencies: never business names, transcript text or prices next to the floor.
> - After each 🛑, report what works, what doesn't and what couldn't be verified, with the pytest output.
>
> **Stop rules:** if the same test fails twice for the same reason, stop and report. Don't tune in a loop. No live Places or Gemini calls are needed in 6A; in 6B only the manual checks in Step 8.
>
> **Read first:** `plans/README.md` (rules, D1–D57), this plan, `docs/last-call-architecture.md` §4 (Scout, Orchestrator), §5, §6, `plans/module-4/plan.md` ("How Module 6 follows", now superseded where this plan differs), `plans/module-2/plan.md` Steps 5, 6 and 10 (store, tools, live session).

## Context
The deployed demo stops at the Scout's buyer list. The Negotiator runs only from 5 hand-written Karachi scenarios (`/demo/sessions {scenario_id}` → `build_call`). Module 6 connects them in the judge demo: decision → ranked buyer → `DealBrief` → browser call (the judge plays the buyer) → result → next buyer → next step. It also fixes the known batch bug.

User decisions (2026-10-11):
- the batch is moved on by pure code driven by clicks, with no Cloud Tasks until Module 9
- demo calls go ahead at night and to closed buyers, with a note
- the old scenario section is removed
- pickup follow-up is deferred

## Decisions (already in `plans/README.md`)
| # | Decision | Why |
|---|---|---|
| D53 | **Orchestration is one pure function, `next_action(batch, scout, call_statuses, rules, now)`**, called by demo endpoints on the judge's clicks. **No Cloud Tasks until Module 9.** There Cloud Tasks only calls the same function. The `voice` service already finalises calls itself, so there is no `call-finished` webhook either. | A browser role-play needs a person for every call, so a scheduler has nothing to drive. Less infrastructure before 18 Oct, and the same logic serves both. Changes the architecture text ("Cloud Tasks is the only scheduler") |
| D54 | **A batch is created when calling starts**, keyed exactly like its scout list: `batch_id = {inspection_id}__{item_key}__{branch_id}` (this replaces "batch ID = inspection__item" in the M4 notes). At creation it takes a snapshot of its **step plans** (`[current step] + scout steps in next_steps`, each with buyer types, opening and floor; donate is 0/0) and of its quantity. Later re-decides don't change a started batch. **One call per buyer per step; at most `scout_max_buyers` (5) calls per step**, then the next step; after the last step, either compost needs approval or "no buyer found". | The batch ID equals the scout key, so there's no mapping code. In production one inspection only ever has one branch, so the key stays correct. In the demo, each branch is its own hypothetical shelf |
| D55 | **A role-play never changes a real business's records.** For `channel="browser"` calls to `places:` buyers: no `buyers` history and no `do_not_call` entry (the call result still records the outcome). The call record stores the **masked phone** only, and it **expires after 24 h** (`expire_at`). The phone channel (Module 9) adds `record_buyer_call`, the phone-key do-not-call entry and the full number. | Same reason as the Module 4 rule "never seed fake history". A judge saying "don't call again" would otherwise hide a real shop from every later judge, and a role-play deal would show "Bought from us" about a real business. The Places policy (checked 2026-10-11) still allows storing only place IDs indefinitely |
| D56 | **Demo calls ignore calling hours and "closed now", and show a note instead.** For example, a row says "Closed now: in a real mart the AI would call when they open", and a banner says "Outside calling hours (09:00–21:00): a real mart would wait until 09:00". **The pickup time uses the real clock and the mart's hours:** if the mart is open with at least `bulk_pickup_hours` left, pickup runs from now to `min(now + 4 h, closing)`; otherwise from the next opening to opening + 4 h. The closing-time selector only simulates the decision. | A judge testing at night can still try the main feature, and the promised pickup is never at a time when the mart is closed |
| D57 | **The old scenario section, `/demo/sessions` and `/demo/scenarios` are removed.** The scenario JSONs and `build_call` stay for the simulator and the tests. **Pickup follow-up (collected, no-show) is deferred**: the result shows the deal and its pickup deadline, and the remaining stock goes to the next buyer. | User's choices |

## Facts from the code that the plan fixes
1. `FirestoreStore.create_call` writes the batch with `merge=True`, which resets `remaining_quantity` (`shared/lastcall_shared/firestore_store.py:67`).
2. **New bug found:** after a deal, `live_session.py` (finally) and `text_session.py:230` **don't release the lock**. After a partial deal, the next buyer is blocked for about 6 minutes. Also, `release_batch` sets the status to `finding_buyers` even after an earlier partial deal.
3. City style comes from the `CITY_STYLE` environment variable, which defaults to Karachi (`live_session.py:262`). It has to travel with each call (D51: Lahore).
4. A `LadderDecision` has prices only for its chosen step, so escalating to animal feed needs feed prices.
5. `QuantityEstimate.low` can be 0, but a `DealBrief` needs a quantity above 0. There is no editable quantity field on the page.
6. `record_outcome(do_not_call)` always writes `do_not_call` under the buyer ID, which would put a real business on the list during a role-play (D55).
7. `FirestoreStore.create_call` overwrites `expire_at` with 30 days (`firestore_store.py:62`), which would break D55's 24 h expiry (found in the plan review).

No new external service or library is used. The Places storage policy was re-checked online on 2026-10-11 (only place IDs may be stored indefinitely), which led to D55.

---

# Milestone 6A: logic, no deploy (Steps 1–5)

### Step 1: Store fixes (`shared/lastcall_shared/store.py`, `firestore_store.py`)
- **`create_call`:** create the batch only if it doesn't exist. In Firestore, use `batch_ref.create(...)` and ignore `AlreadyExists`.
- **`create_call` must store the record's own `expire_at`.** Today `firestore_store.py:62` overwrites it with `created_at + 30 days`, which would silently break D55's 24 h expiry. Store `record.expire_at` as a real datetime (the `CallRecord` validator already defaults it to 30 days when unset, so scenario calls are unchanged).
- **`release_batch`:** when the status is `in_negotiation`, set the new status from the stock: `partly_sold` if 0 < remaining < total, `sold` if remaining = 0, otherwise `finding_buyers`.
- **Always release the lock at the end of a call,** with or without a deal: `live_session.py` finally and `text_session.py:230`. `save_deal_tx` has already set `sold` or `partly_sold`, and the release keeps it.
- **New methods** in the protocol and both stores:
  - `create_batch(batch) -> BatchRecord`: create if absent; return the stored batch
  - `add_batch_attempt(batch_id, attempt)`
  - `advance_batch_step(batch_id, from_index) -> bool`: a transaction; +1 only if `step_index == from_index`
  - `get_calls(call_ids) -> dict[str, CallRecord]`: one `get_all`
- **Contract tests (both stores):**
  - `create_call` twice after a deal leaves `remaining_quantity` reduced
  - a call record with `expire_at = created_at + 24 h` is stored with that value
  - after a partial deal and a release, the status is `partly_sold` and a second call can lock the batch at once
  - `advance_batch_step` succeeds only once for the same `from_index`
  - `create_batch` doesn't overwrite an existing batch
- **Run the live Firestore suite** (`RUN_FIRESTORE_TESTS=1`).

### Step 2: Models (`shared/lastcall_shared/models.py`; regenerate `shared/schemas/`)
```python
class StepPlan(BaseModel):
    step: ScoutStep
    buyer_types: list[BuyerType]
    opening_price: int            # 0 for donate
    floor_price: int              # 0 for donate; internal, never sent to the agent or the page's agent view

class BatchAttempt(BaseModel):
    call_id: str
    buyer_id: str                 # "places:<id>"; no name or phone (D48)
    rank: int
    buyer_type: BuyerType
    step: ScoutStep
    created_at: AwareDatetime

# BatchRecord: add (all with defaults, so the Module 2 code and tests keep working)
    branch_id: str | None = None
    plans: list[StepPlan] = []
    step_index: int = 0
    then_compost: bool = False
    quantity_confirmed: bool = False
    attempts: list[BatchAttempt] = []
    created_at: AwareDatetime | None = None

# CallRecord: add
    channel: Literal["browser", "phone"] = "browser"
    city_style: str | None = None   # None → CITY_STYLE env (scenarios unchanged)

# MartRules: add
    payment_terms: str = "Cash on pickup"
    calling_hours: CallingHours = Field(default_factory=lambda: CallingHours(start=time(9, 0), end=time(21, 0), timezone="Asia/Karachi"))
    city_style: Literal["karachi", "lahore", "islamabad"] = "karachi"
```
- `demo_mart.json`: `"city_style": "lahore"`, calling hours 09:00–21:00, payment terms "Cash on pickup".
- Tests: valid fixtures only. Keep it lean.

### Step 3: Step plans, pickup window and handoff (pure; new `services/api/lastcall_api/orchestration/handoff.py`)
- **`ladder/engine.py`:** move the bulk and feed price maths into `step_prices(step, shelf_price, rules) -> (opening, floor)` and use it in `decide_item`. **No behaviour change:** every engine test, including the exhaustive loop, passes unchanged.
- **`build_step_plans(decision, rules) -> (list[StepPlan], then_compost)`**
  - `decision.step` must be a scout step; otherwise `ScoutNotApplicable`. `needs_price` raises `NeedsPrice`.
  - Order: the chosen step, then each scout step in `next_steps`. `then_compost = "compost" in next_steps`.
  - Buyer types: bulk sale → `decision.buyer_types`; donate → `["charity"]`; animal feed → `["dairy_farm"]`.
  - Prices: donate is 0/0; otherwise `step_prices(...)`.
  - **Worked example:** banana, dozen, shelf Rs 180, bulk sale with next steps donate and animal feed:
    - bulk sale: opening 110, floor 65, buyers juice shops and bakeries
    - donate: 0/0, charities
    - animal feed: opening 25, floor 10, dairy farms
- **`initial_quantity(item) -> float | None`:** `low` if above 0, else `high` if above 0, else `None`.
- **`pickup_window(rules, now) -> (start, deadline)`** (D56; `PICKUP_HOURS = 4`; `now` is converted to the mart timezone first and both results are **in the mart timezone**, so `time_words` prints Lahore times; mart closing 23:00 and opening 09:00):

  | Time now | Pickup |
  |---|---|
  | 14:00 | 14:00–18:00 |
  | 20:00 | 20:00–23:00 |
  | 21:30 (less than 2 h before closing) | tomorrow 09:00–13:00 |
  | 03:00 | today 09:00–13:00 |
- **`build_call_record(*, batch, plan, candidate, decision, rules, branch, now) -> CallRecord`** (the deal brief comes from these sources):

  | DealBrief field | Source |
  |---|---|
  | deal_type | `donation` if the plan's step is donate, else `sale` |
  | item, condition | `decision.name`, `decision.buyer_condition` |
  | quantity | `batch.remaining_quantity` |
  | quantity_confirmed_by_staff | `batch.quantity_confirmed` |
  | unit | `decision.unit` |
  | buyer | `candidate.to_buyer_info()`, with the name passed through `sanitise_name` again and the **phone masked** (D55) |
  | opening, floor | the plan |
  | market_rate_per_unit | `decision.shelf_price` |
  | pickup window and deadline | `pickup_window`. The window string is `f"{time_words(start)} to {time_words(deadline)}"` (copy the small `time_words` helper from `services/voice/lastcall_voice/negotiator/prompt.py` into `handoff.py`, because `api` must not import from `voice`). It **must include the date**: at 21:30 the window is tomorrow 09:00–13:00, and a string without the day would let the agent offer "9 baje" today, which `confirm_deal` then rejects as past |
  | mart | `MartInfo(branch.name, branch.location)` |
  | payment_terms, calling_hours | the mart rules |

  The record also gets `channel="browser"`, `city_style=rules.city_style`, `init_negotiation`, a fresh `call_id` and nonce, and `expire_at = created_at + 24 h` for `places:` buyers.
- **Tests:**
  - the step-plans example above, plus a spoiled produce → animal feed with `then_compost=True`
  - `needs_price` and a keep decision both raise
  - the 4 pickup times in the table, and the window string at 21:30 names tomorrow's date
  - the brief:
    - `agent_view()` JSON contains neither the floor nor any phone digits
    - the stored brief has no full E.164 number
    - a donation is 0/0
    - the quantity is the batch's remaining quantity

### Step 4: The loop (`orchestration/loop.py`, pure)
```python
@dataclass(frozen=True)
class NextAction:
    kind: Literal["call", "busy", "needs_search", "next_step", "compost_approval", "no_buyer", "sold"]
    step: ScoutStep | None = None
    buyer: ScoutCandidate | None = None

def next_action(batch, scout: ScoutResult | None, call_status: dict[str, str], rules, now) -> NextAction
```
The rules apply in this order:
1. `remaining_quantity <= 0` → `sold`.
2. Locked with `locked_until > now` → `busy`.
3. `plan = plans[step_index]`. `called` = the buyer IDs of attempts in this step whose call status is `in_progress` or `completed`. Pending calls never count, because their token expires in 120 s.
4. If `len(called) >= scout_max_buyers`, go to rule 7.
5. If `scout is None`, or `scout.step != plan.step`, or its `buyer_types` differ → `needs_search`.
6. The first buyer in rank order who isn't in `called` → `call`. If there is none (including an empty list), go to rule 7.
7. Steps used up: if another step exists → `next_step` (its step). Else if `then_compost` → `compost_approval`. Else → `no_buyer`.

**Test:** one table-driven test covering every branch, plus "a pending call doesn't use up a buyer" and "after a partial deal the next buyer is offered".

### Step 5: Voice changes (`services/voice/`)
- **City style:** `live_session.py` uses `city_style = call.city_style or os.getenv("CITY_STYLE", "karachi")`.
- **Do-not-call during a role-play:** in `tools.record_outcome(do_not_call)`, if `call.channel == "browser"` and the buyer ID starts with `places:`, don't call `add_do_not_call`. Add the flag `dnc_roleplay_not_recorded` instead. The tool returns the same result, so the agent closes normally. `test:` scenario buyers keep today's behaviour, so the existing tests stay unchanged.
- **Tests:**
  - a `places:` browser call leaves no do-not-call entry, and a `test:` call still writes one
  - a call record with `city_style="lahore"` renders the "Lahori" line
  - the lock is released after a deal (Step 1)

🛑 **6A report:** pytest (all Module 1, 3 and 4 tests unchanged; Module 2 tests changed only for the lock release), the live Firestore suite, and the step-plan and pickup examples as printed.

---

# Milestone 6B: endpoints, page, deploy (Steps 6–8)

### Step 6: Endpoints (`services/api/lastcall_api/main.py`)
- **Remove** `/demo/scenarios` and `/demo/sessions`, and their tests in `test_demo_routes.py` (keep `test_get_demo_page`).
- **`POST /demo/calls`**
  - Body: `{inspection_id, item_key, branch_id?, buyer_id?, quantity?, staff_checked=false}`.
  - Checks, in this order:
    1. Access code → 401.
    2. Validation → 400: the Module 4 ID regexes; `buyer_id` `^places:[A-Za-z0-9_-]{1,300}$`; `0 < quantity ≤ 1000`.
    3. IP bucket `"call"` (`IP_RATE_LIMIT_PER_HOUR`) → 429.
    4. `get_decisions` (decision with `item_key`) and `get_inspection` (the item, for its quantity) → 404 if missing or not `demo_mart`.
    5. Branch (`rules.branch(branch_id)`), then `batch_id`.
    6. **If the batch exists, use it as it is** (D54 snapshot): its plans and quantity; `body.quantity` and `staff_checked` are ignored. **Otherwise create it**, in this order:
       - `build_step_plans(decision, rules)` → 409 "This item stays in store" (not a scout step) or "Enter the shelf price first" (`needs_price`)
       - `decision.on_hold` and not `staff_checked` → 409 "Waiting for staff check"
       - quantity: `body.quantity` → `quantity_confirmed=True` (the judge stands in for staff); else `initial_quantity(item)` → `quantity_confirmed=False`; `None` → 409 "Enter the quantity"
       - `create_batch(BatchRecord(batch_id, mart_id, inspection_id, item_key, item=decision.name, unit=decision.unit, total=remaining=quantity, branch_id, plans, then_compost, quantity_confirmed, created_at=now))`
    7. `get_scout_result(batch_id)`, `get_calls` for the attempts, then `next_action`. Every kind except `call` becomes a 409 with plain text. A given `buyer_id` must be on the list (else 400) and not already called in this step (else 409).
    8. **Only now** the daily session cap: the existing key and `DEMO_DAILY_SESSION_CAP` → 429. Refusals never use up the cap.
    9. `build_call_record` → `create_call` → `add_batch_attempt` → mint a 120 s token.
  - Returns `{call_id, ws_url, token, batch_id, buyer: candidate.public_view(), deal: {item, quantity, unit, deal_type, opening, floor, pickup_window, pickup_deadline, mart_name}, notes: {buyer_closed_now, outside_calling_hours}}`.
  - The floor is shown to the judge, as on the decision card; the agent never sees it.
- **`GET /demo/batches/{batch_id}`** (access code; batch-ID regex; 404 if missing or not `demo_mart`) returns:
  - remaining, total and unit
  - the current step and the plans
  - the attempts: rank, type, step, call status, outcome, agreed price and quantity, pickup time, `callback_at`. The name comes from the live scout list when it's present, else "Buyer #rank".
  - `next_action` (kind, step, buyer rank)
  - `outside_calling_hours`
  - **no phones**
- **`POST /demo/batches/{batch_id}/next-step`:** requires `next_action.kind == "next_step"` and `advance_batch_step` → else 409; returns the same body as the GET.
- **`/demo/scout`:** if a batch exists for the key, build the target from `batch.plans[step_index]` instead of `from_decision`. The reuse rule stays as it is.
- **Tests** (about 10, parametrize the errors):
  - 401, each 409, the 429 cap, and that a refusal doesn't increase the cap
  - 200: no E.164 string in the response or in the stored call; the call has `city_style="lahore"`, the batch's quantity and `expire_at` 24 h after `created_at`
  - an existing batch ignores a new `quantity` in the body
  - a second `/demo/calls` after a non-deal offers rank #2
  - `next-step` then `/demo/scout` searches `charity`
  - GET batch with no phones
- **Note:** no change to the socket-close order in `live_session.py` is needed; the page's polling handles it.

### Step 7: Demo page (`static/index.html`; plain JS; `textContent` only; works at 375 px)
- **Remove the scenario controls.** Keep the transcript, the result card and the audio code as a **"Live call"** panel shown during a call. Use one access-code field (`inspectAccessCode`). **Remove every reference** to the deleted elements, or the page throws on load: `accessCodeEl` (used in `fetchScoutBuyers`, `triggerDecide`, `handleInspect` and the code-sync listeners), `scenarioSelect`, `infoItem`, `infoQty`, `infoOpening`, `infoFloor`. Keep the `lc_code` localStorage memory on the one field.
- `startCall` keeps its order (fetch the session, then create the `AudioContext` and the microphone, then the WebSocket) and the `busy` retry; only the request changes to `POST /demo/calls`.
- The Find buyers label uses the **batch's current step** once a batch exists (after Next step it reads "Find charities"), else the decision's step.
- Remember the "Staff checked" tick per item while the page is open.
- **In each buyer list:**
  - a quantity field: defaults to `initial_quantity`, editable until the batch exists, then shows "remaining X of Y"
  - a "Staff checked this item" checkbox when the decision is `on_hold`
  - **"Start calling #1 <name>"**
  - a small **"Play this buyer"** on each uncalled row
  - a status chip on called rows (Deal 20 kg @ Rs 95 · Declined · Call back 11:00 · No answer · Asked not to be called)
  - closed-now notes and the calling-hours banner (D56)
  - the copy line: *"In a real mart, the AI calls these in order on its own; here you play the buyer."*
- **Call info** shows the buyer (with "from Google Maps", since it is Places content), opening, "floor Rs X (never told to the AI)", quantity and pickup.
- **When the WebSocket closes:** `voice` closes the socket *before* it releases the lock and saves the outcome (`live_session.py` finally: close at line 592, release at 621, `finish_call` at 673), and when the judge hangs up the socket is already closed. So **poll** `GET /demo/batches/{id}` every 1 s, up to 8 tries, until this call's attempt shows status `completed`; then re-render. If it still isn't completed, show "Saving the call result…" and a **Refresh** button. Then one next button: **Next buyer** · **Next step: find charities / cattle farms** (`next-step`, then Find buyers) · "Sold out ✓" · "Compost: needs manager approval" · "No more buyers nearby" · **"Search again"** for `needs_search` (the list is older than 1 h; runs Find buyers) · "Call in progress…" for `busy` (with Refresh).
- Changing branch loads that branch's batch (404 = no calls yet). Every button is disabled during a call. A per-item request counter ignores out-of-order responses, as in Module 4.

### Step 8: 🛑 Deploy, check, docs
1. `uv run pytest` green; `export_schemas.py` gives no diff.
2. The user commits. Deploy **both** `api` and `voice`; `/health` shows HEAD on both. No Terraform change. (Setting `voice_min_instances=1` for 18 Oct – 4 Nov is a separate decision for the user, D15.)
3. Manual checks on `/demo` (simulated overripe tray, Johar Town):
   - Find buyers, then Start calling: the call opens in Lahori Urdu at the plan's opening price
   - decline, then Next buyer offers #2
   - a partial deal: remaining stock goes down and the next buyer is offered at once
   - after 5 calls or the end of the list: Next step leads to Find charities and a donation call with no prices
   - "don't call again" on a real business: no `do_not_call` doc
   - the network tab shows no full phone; `calls/<id>` has a masked phone and `expire_at` in 24 h
4. **Limits to report (not changed in code):** each call counts against `DEMO_DAILY_SESSION_CAP` (50/day, Terraform env) and the IP limit (20/h). One judge escalating an item through 3 steps can make up to 15 calls. Report how many calls a full run used; the user decides whether to raise the cap for judging.
5. Docs: README status and a short Module 6 section. Report anything built differently.
6. 🛑 Final report: what works, what doesn't, what couldn't be verified.

## How Module 9 follows (documented, not built)
- Cloud Tasks calls `next_action` for `channel="phone"` batches.
- Calling hours and "closed now" are enforced.
- The full E.164 number goes in the brief only for phone calls.
- After a call: `record_buyer_call` and the phone-key do-not-call entry.
- Pickup follow-up: collected and no-show.

## Reuse, don't rewrite
- `ScoutCandidate.to_buyer_info` / `public_view`, `ScoutTarget`, `get_scout_result` (the 1 h expiry), `sanitise_name`, `mask_phone`
- `init_negotiation`, `mint`, `_verify_access_code`, `_check_ip_limit`, `incr_daily_sessions`, the `app.state` injection pattern
- the existing WebSocket and audio worklet code and the Module 4 request-counter and banner code in `index.html`

## Verification
- **6A:** pytest green; the live Firestore suite green (including the `create_call` and release fixes); the loop table test.
- **6B:** the endpoint tests; the deployed end-to-end checks in Step 8; no phone in responses or in stored calls; no do-not-call or buyer-history writes from role-plays.

Rough size: about 1.5–2 days for the implementer, so 6B lands by about 14 Oct, leaving time for Modules 8–10 before 18 Oct.

---

## Prompt for the coding agent (paste into a fresh chat)
````text
You are implementing Module 6 (Orchestration and the Call handoff) of "Last Call", a hackathon project in the repo /Users/kashmalrahat/AI-Builder-Cup/last-call. A planner (Claude) wrote the plan; you implement it exactly, step by step.

Read first, in this order:
1. plans/README.md: the working rules and the decision log D1–D57. They are binding (D53–D57 are this module).
2. plans/module-6/plan.md: the plan you implement. Follow its steps in order and stop at every 🛑.
3. docs/last-call-architecture.md §4 (Scout, Orchestrator), §5, §6.
4. The code you touch: shared/lastcall_shared/{models.py,store.py,firestore_store.py,marts/demo_mart.json}, shared/tests/test_store.py, services/api/lastcall_api/{main.py,ladder/engine.py,scout/scout.py,scout/rank.py,static/index.html}, services/voice/lastcall_voice/{live_session.py,text_session.py,negotiator/tools.py}.

Rules:
- Start with Milestone 6A only (Steps 1–5). Don't start 6B until the user approves the 6A report.
- The orchestration logic is pure code (next_action). Do NOT add Cloud Tasks, new endpoints beyond the plan, or Terraform changes.
- A browser role-play must never write buyer history or do_not_call for a "places:" buyer, and call records store only the masked phone (D55).
- Never write full phone numbers into API responses, call records, logs or results docs.
- Model IDs only via get_settings(). No sampling parameters.
- Don't change Module 1, 3 or 4 behaviour; their tests must pass unchanged. The Ladder price refactor (Step 3) must not change any engine test.
- Run the live Firestore suite (RUN_FIRESTORE_TESTS=1) at the 6A 🛑 and paste the result.
- No commits or pushes unless the user asks. Deploy only from committed code.
- Stop rules: if the same test fails twice for the same reason, stop and report.
- If the plan conflicts with docs/ or plans/README.md, stop and ask. Don't choose silently.
- At every 🛑, report what works, what doesn't and what couldn't be verified, with the pytest output.

Start now with Step 1 (store fixes and their contract tests).
````
