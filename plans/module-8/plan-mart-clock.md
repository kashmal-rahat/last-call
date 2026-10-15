# Plan: one mart clock for the time-of-day presets (proposed D74)

Status: **built 2026-10-16 (D74)**, after the user's review. Written 2026-10-16 before any code changes; see "As built" at the end.

## The problem

"Preset" in this plan means the **Time of day** buttons in Shelf setup (Now, 12 h, 4 h, 1 h left; the field was called
"Time until closing" until 2026-10-16, and the buttons now read Now, 11:00, 19:00 and 22:00 PKT). The
12 h, 4 h and 1 h presets change only the Ladder decision. Everything after it
runs on the real clock in Pakistan. With "Now" the two agree; with a preset they can contradict each other, and the
judge can't see why. Judges may well be in other time zones, so the real time in Lahore can be anything, including
night.

What reads the clock today:

| Where | Clock | Effect |
|---|---|---|
| Ladder decision (`engine.py`, `hours_until_closing`) | **preset** (or real with "Now") | step, discount, bulk sale only with ≥ 2 h for pickup |
| Pickup window (`handoff.pickup_window`, D56) | real | the window the agent offers and the page shows |
| "Outside calling hours" note (`loop.outside_calling_hours`) | real | the note on the call panel |
| Agent prompt, "Current time" (`agent.py` → `render_instruction`) | real | what the agent believes the time is |
| `confirm_deal`: pickup must be after now and by the deadline (`tools.py`) | real | refuses or accepts the buyer's time |
| `schedule_callback`: rolls forward, calling hours (`tools.py`) | real | the call-back time saved and shown |
| WhatsApp confirmation, "Pickup: today / date" (`buyer_messages.py`) | real | the buyer's message |
| Page header clock (`setup.updateClock`) | real (browser) | "23:59 PKT" beside a 19:00 decision |
| Scout "open now" (`places.py`, Google's `openNow`) | real | ranking and the "closed now" note |
| Tokens, locks, cooldowns, daily caps, `created_at` | real | system mechanics |

## Edge cases found (preset in use; mart opens 09:00, closes 23:00, calls 09:00–21:00, pickup 4 h)

1. **Real 22:30, "12 h left" (decided as 11:00).** Overripe → bulk sale (11:00 leaves time for pickup). The real
   clock has 30 min left, so the pickup window is tomorrow 09:00–13:00, and the agent says "current time 10:30 PM".
   The decision was made because there was time for pickup today.
2. **Real 02:00 (an evening judge in Europe), "4 h left" (19:00).** The agent says it's 2 AM, pickup is "today 9 AM
   to 1 PM". The decision and the page say evening.
3. **Real 11:00, "1 h left" (22:00), spoiled → animal feed.** Pickup offered 11:00–15:00 today; in the mart's
   simulated world it's the last hour, so pickup should be tomorrow morning.
4. **The deal is refused by our own check.** Real 22:00, "12 h left" (11:00): the buyer agrees "aaj 3 baje"; the
   agent sends 15:00 today; `confirm_deal` refuses it as "in the past" (real 22:00). The agent then fumbles a deal
   the buyer already said yes to. This is the most damaging case, on the hero feature.
5. **Call-back.** Same setup: "call me at 5" becomes tomorrow 17:00 (rolled past real now), not today 17:00.
6. **WhatsApp says "Pickup: today" or a date** from the real clock, which can differ from what was agreed in the
   simulated day.
7. **Calling-hours note** is right or wrong by chance: at "1 h left" (22:00) a real mart wouldn't call, yet the note
   follows the real time.
8. **Header clock** shows real time beside a decision for another time of day.
9. **"Open now"** follows the real time: at real night every buyer reads "closed now" although the simulated time is
   11:00.

Cases that are **fine today**: "Now" everywhere (including before opening and after closing: pickup moves to the next
opening); presets while the real time happens to match; everything system-side (tokens, locks, caps, cooldowns).

## Options considered

- **A. Drop the presets; real time only.** Simplest, no mismatch. But judges abroad would mostly see the mart at
  night (pickup tomorrow, calls outside hours), and the evening discounts, the 1 h case and bulk sale would be hard to
  show. Rejected: it removes what makes the Ladder visible.
- **B. Avoid clock times (say "within 4 hours").** Buyers and the agent talk in clock times ("3 baje"), and
  `confirm_deal` needs an absolute time to check. Doesn't fix 4–6. Rejected.
- **C. Move the whole service to a fake clock.** Tokens, locks, caps and cooldowns would break or need exceptions
  everywhere. Rejected.
- **D. A mart clock, separate from the system clock (recommended).** The mart's world (decision, pickup, calling
  hours, call-backs, the agent's "now", WhatsApp wording, the header) reads one clock: the real time shifted by a
  fixed offset. The system keeps real time. With "Now" the offset is 0, so nothing changes from today.

## The design (option D)

**Mart time = real time + `clock_offset_s`.** One number, worked out once, copied along; one helper reads it. It keeps
ticking, so a 5-minute call or a second call 20 minutes later moves on naturally, and every check inside a call
(pickup after now, by the deadline) compares times on the same clock. With "Now" the offset is 0, so mart time is the
real time and everything behaves exactly as today.

1. **One helper** in `lastcall_shared/clock.py`: `mart_now(offset_s, now=None)` = (`now` or the real time) +
   offset. Every mart-world caller uses it; nothing else adds offsets.
2. **The decision works the offset out, once.** In `ladder.py`, with a preset the simulated time is today's closing
   (on the real date in Lahore) minus the preset hours: 11:00, 19:00 or 22:00, all inside opening hours and on the
   real calendar day, so "today" and "tomorrow" stay true. `offset = simulated − real` (may be negative). With "Now",
   0. Stored as `LadderResult.clock_offset_s` (bounded to ±24 h in the model, default 0). The decision itself is
   unchanged: it still uses the preset hours.
3. **The batch copies it** at the item's first call: `BatchRecord.clock_offset_s` (default 0; D54 already snapshots
   plans and quantity at that moment). Later calls on the same batch use the batch's value, even if the shelf is
   re-decided. This adds no restriction for the judge: the page already disables Time of day once any call
   exists on the shelf (`lock.js`), and only New shelf unlocks it; before the first call they can change it freely.
   Keeping it on the server means consistency doesn't depend on the page's lock.
4. **The call copies it from the batch:** `CallRecord.clock_offset_s` (default 0), so the voice service (browser
   and phone) has it without another lookup. Old records read 0.
5. **The api uses mart time only for the mart's world:** `pickup_window` and `outside_calling_hours` in
   `demo_create_call`, and `outside_calling_hours` in `_batch_view` (the buyer list's note), each with the batch's
   offset. `created_at`, `expire_at`, tokens, caps, locks, cooldowns and attempts stay real.
6. **The voice service keeps two named clocks, each with one meaning.** `now_fn` stays real (tokens, the lock, record
   timestamps, the summary). A `mart_now` (real + the call's offset) goes to:
   - `build_negotiator(clock=mart_now)`: the prompt's "Current time";
   - a new `CallContext.mart_clock`, read only by `confirm_deal` (pickup after now, by the deadline, and the WhatsApp
     wording's "today") and `schedule_callback` (rolling forward, calling hours). `CallContext.clock` stays real, so
     `DealRecord.created_at` and staff tasks keep real timestamps.
   `pickup_time` and `callback_at` are mart times, on the same clock as the brief's deadline, so they compare and
   display correctly. The text session and the simulator pass a fixed clock and have offset 0; unchanged.
7. **The page uses the decision's offset.** `state.currentLadderResult.clock_offset_s` (0 without a decision, so New
   shelf returns to real time):
   - the header clock shows mart time, plain "19:00 PKT", ticking, with the tooltip and accessible name "Set by Time
     until closing" (decided). It changes when the decision arrives, the moment the preset takes effect;
   - `formatCallbackTime` gets mart time as its `now`, so "today / tomorrow" is judged on the mart's day;
   - the pickup window on the call panel already comes from the server;
   - the Time of day info tip (`#tipClosing`) says today "…Pickup times stay real.", which becomes false. New
     text: "The mart closes at 23:00. Pick a time of day to see how the AI's decision, the pickup time and the call
     change as closing nears." This tip is where judges learn what the setting does, so it matters more than the
     header's tooltip.
8. **Find buyers doesn't change** (decided): the open/closed tag stays real; the note above the list covers it.

## What doesn't change

The Ladder rules (D44) and the decision for any preset, prices, the negotiation, step plans, quantities, the D55
role-play rules, Find buyers, tokens, locks, caps, cooldowns and record timestamps. "Now" behaves exactly as today
(offset 0 everywhere).

## Tests (written first; today's suite must still pass unchanged)

- `mart_now` and the offset: presets give 11:00, 19:00, 22:00 on the real date for real times of 02:00, 11:00 and
  23:30; "Now" gives 0; the model rejects more than ±24 h.
- `pickup_window` at mart 11:00, 19:00 and 22:00 → today 11:00–15:00, today 19:00–23:00, tomorrow 09:00–13:00.
- `demo_create_call` with a preset decision at a fixed real 02:00: the brief's window and the calling-hours note
  follow mart time; `created_at` and the token stay real; a second call on the same batch uses the batch's offset
  even after a re-decide; the batch view's note follows mart time.
- Voice tools with `mart_clock` 11 h behind real (edge case 4): `confirm_deal` accepts "today 15:00", still refuses a
  past time and one after the deadline, the WhatsApp line says "today", and `created_at` is real;
  `schedule_callback` keeps "today 17:00".
- The prompt's "Current time" is mart time; the token check and the lock use real time.
- Page (`node --test`): the header shows mart time with an offset and real time without; `formatCallbackTime` with a
  mart `now`.
- Final check, live: a browser call with each preset (and one phone-demo call if it is switched on).

## Size and risk

About 10 files across the shared models and clock, the api, the voice service and the page, plus regenerated schemas
and tests: roughly half a day. The risk is in the voice tools (the hero call), so they are covered first by tests at
fixed clocks, and the rule is narrow: only `confirm_deal` and `schedule_callback` read `mart_clock`, and only for the
mart's own times. A live browser call with each preset is the final check, plus one phone-demo call if it is
switched on.

## Review notes (2026-10-16)

- **Simpler than the first draft:** the offset is worked out once, by the decision, and copied (decision → batch →
  call → voice and page) instead of a "preset used" flag recomputed later; one helper adds it.
- **Two clocks, never swapped:** the voice tools' existing clock also stamps records, so mart time gets its own
  `mart_clock`, read only by the two tools that check pickup and call-back times.
- **Re-deciding:** each decision works the offset out again, so before the first call the header returns to the
  preset's time (for example 11:00) after a re-decide, the same moment the server would use. After the first call the
  page disables Time of day, price changes and re-decide (`lock.js`), and the batch keeps its offset, so the
  header and the calls can't drift apart.
- **Days:** a preset's time is always on the real calendar day in Lahore (no daylight saving), so the page's
  "today / tomorrow" and the WhatsApp "today" agree with the agent.
- **Not added on purpose:** no new endpoint, no Scout change, no per-call recalculation, no label on times.

## Final review from scratch (2026-10-16)

Every reader of the time was listed again from the code (`git grep` for `now`, clocks and time fields across the api,
the voice service, the shared models and the page). Each is either covered above or deliberately real. Three details
the steps above didn't spell out:

1. **The call route must read the offset from the LadderResult.** `get_decision` (`deps.py`) returns only the item's
   decision today; the route needs the result's `clock_offset_s` too when it creates the batch (same single read,
   returned alongside). `ladder.py` builds a LadderResult in two places (the normal path and the early return); both
   set the offset.
2. **Fallback order in the tools:** `ctx.mart_clock or ctx.clock or real time`. The text session and the simulator
   set only `clock` (a fixed time), so they keep exactly today's behaviour; existing voice tests need no change.
3. **The header takes the current moment from the device, adds the offset and shows it in Lahore time,** as it does
   today. The device's time zone never matters (it is always formatted for `Asia/Karachi`). Only a device whose clock
   is set wrong (say 5 minutes fast) shows the header that much off from the agent's time, which comes from the
   server's clock; harmless, and the same as today with "Now".

Checked and fine as they are:

- **No model validator compares times** (`CallResult`, `DealRecord`, `DealBrief`), so mart-time `pickup_time` and
  `callback_at` next to real `created_at` can't fail validation. `validate_deal_terms` takes `now` from
  `confirm_deal`, which passes mart time.
- **The phone demo** goes through the same `handle_live_call_websocket` (`phone/bridge.py`) and has no clock of its
  own, so it is covered. The scenario loader's `CallRecord`s default to 0.
- **Both stores save whole records** (`model_dump`), so the new fields are kept; old documents read the default 0.
- **Near midnight:** a decision at real 23:59 with "12 h left" gives mart 11:00 on that date; a call at real 00:05 is
  at mart 11:06 on the same mart date. The agent, WhatsApp and the page's "today / tomorrow" all use mart time, so
  they agree with each other.
- **Ticking past closing:** at "1 h left" (22:00), a call made 90 minutes later is at mart 23:30; `pickup_window`
  already moves pickup to the next opening.
- **Every preset × step** gives a sensible window: 12 h → today 4 h from now; 4 h (bulk sale allowed) → today until
  23:00; 1 h (overripe is discounted, so only feed or donation calls) → tomorrow 09:00–13:00.

## Decisions for the user

1. ~~Build option D now.~~ **Decided (user, 2026-10-16): build it.**
2. ~~The header clock for a preset.~~ **Decided (user, 2026-10-16): plain "19:00 PKT", ticking, with a tooltip;**
   no visible label.
3. ~~Scout "open now" at the simulated time.~~ **Decided (user, 2026-10-16): Find buyers doesn't change.** The
   open/closed tag stays real; the note above the list already says the demo lets you call anyway.

## As built (2026-10-16)

As designed above, with two additions found while building:

- **A dropped call's retry** (the voice service's "call back in 2 h" when a call ends mid-conversation with no outcome,
  `live_session.py`) is a call-back time, so it is on the mart's time too. Without it, "12 h left" at real 22:00 would
  show "Call back tomorrow 09:00" instead of 13:00.
- **`CallContext.now()` and `mart_now()`** replace the three copies of `ctx.clock() if ctx.clock else …` in the tools,
  so each tool says which clock it means: `confirm_deal` checks and words the pickup on mart time and stamps the deal in
  real time; `schedule_callback` uses mart time; `record_outcome` stamps its staff task in real time.
- **The header clock** is formatted as UTC+5 arithmetic (Pakistan has no daylight saving) instead of `Intl` with a
  fallback that used the device's own time zone.
- **Senior review (same day):** the dropped-call retry existed twice (live session and text session), and after the
  change the two copies used different clocks. It is now one method, `CallContext.retry_after_drop`, used by both, on
  the mart's time (the text session's simulator has offset 0, so its behaviour is unchanged), with boundary tests
  (inside, before and after calling hours). The text session's other clock reads use `ctx.now()`. A JS test that
  compared against the clock after the call could fail on a turning minute; it now accepts the minute before or after.
- **Header from the moment a preset is picked (user, same day):** before, the header changed only when a decision
  arrived, so the page opened on 19:00 selected with the real time in the header. Now the header shows the selected
  preset's time at once (on load and on every pick), holds it until a decision for that preset arrives, then ticks
  from the decision. A decision for another option (a new one still on its way) doesn't count, so the header never
  shows a stale time. Each option carries its time (`data-time` on the hidden select). Counting from the call instead
  was considered and declined: the reading time moves every display together, and a shelf-wide "clock started"
  moment would need a database write at the first call and a second header state.

