# Module 2: Implementation Review (milestone 2B)

**Reviewed:** 2026-10-08, commit `88e45d7`
**Scope:** code, Terraform and docs. Nothing was changed except this file. The scenario removal is handled separately.
**Tests:** `84 passed, 1 failed, 5 skipped` (see M1). The results doc claims 85 passed, so it is out of date.

Overall, the 2B structure is solid:
- Every Negotiator tool is BLOCKING.
- Tokens are sent in the first WebSocket message, never in the URL.
- The semaphore is checked before `start_session`.
- Background tasks are wired with `asyncio.wait`, and every `finally` step has its own guard.
- Firestore writes are transactions, and the TTL field is stored as a real timestamp.
- The kill switch works in simulate mode.

The issues below must be fixed before the Urdu test is trusted, or before a judge link goes out.

---

## 🔴 Critical

### C0. The agent agreed to 60 kg when only 50 kg was available (found in the user's test), and `confirm_deal` hides bad inputs
The quantity check in `validate_deal_terms` is correct. But `tools.confirm_deal` **fills in missing or wrong arguments** instead of rejecting them, which goes against "agents decide, code enforces":
- `final_quantity` falls back to `call.brief.quantity` (the full stock) when the model leaves out `quantity`. The deal is then saved for an amount the buyer never agreed to.
- `buyer_confirmed: bool = True` is the default, so the confirmation check passes on its own.
- A missing or unreadable `pickup_time_iso` becomes `now + 2h`. A past time, or a past date or year, is quietly rewritten to today or `now + 2h`. The buyer never agreed to those times.
- The extra alias parameters (`agreed_price_per_unit`, `agreed_quantity`) and the default price of 0 widen the schema and hide model mistakes.
- **The prompt doesn't stop a verbal over-commitment.** The agent can say yes to 60 kg, and can say "sauda pakka" even when `confirm_deal` returns `ok:false`.

**Fix:**
1. **Signature:** `confirm_deal(price_per_unit: int, quantity: float, pickup_time_iso: str, buyer_confirmed: bool)`. All four arguments are **required**, with no defaults and no aliases.
2. **No fill-ins.** A missing timezone, an unparseable time, or a time in the past or after the deadline returns `{ok:false, reasons:["…ask the buyer for the pickup time again"]}`. Don't rewrite dates.
3. **Return available stock in plain words** when quantity fails: `{ok:false, reasons:["Only 50 kg is available"], available_quantity: 50}`.
4. **No new tool.** The available quantity is already in the brief, and the batch is locked to this call, so it can't change mid-call. A BLOCKING lookup would only add a pause in speech.
5. **Prompt v1.5:**
   - "Never agree to more than the available quantity in the brief. If the buyer asks for more, offer the full available amount instead."
   - "Never say 'sauda pakka' or close as a deal unless confirm_deal returned ok=true. If it returns ok=false, tell the buyer what changed and confirm again."
6. **Tests:**
   - asking for 60 when 50 is available → `ok:false` with `available_quantity=50`, and no deal saved
   - leaving out `quantity` or `buyer_confirmed` → a validation error, not a deal
   - a past or naive time → `ok:false`
   - **simulator scripted test B9:** the buyer asks for more than is available. Expected: the agent offers the available amount, and the saved deal is ≤ the stock.
7. **The user checks** `deals/` and the call's `flags` for the test call, to see whether code saved 50 or rejected the deal.

### C1. The live price guard compares against stale state
- `live_session.py` loads `call` once at the start of the session, then classifies every agent turn against `call.negotiation`. That's the ladder position at the start, with `approved_prices=[opening]`.
- `verify_offer` updates the negotiation in the store, but the session never reloads it.
- **Result:** after the first concession, any **correct** counter-offer written in digits (for example "Rs 165") is classed as `unapproved`. The agent is then told: "[SYSTEM] You said a wrong price … the price is {opening}". That pushes the agent back up to the opening price in the middle of a negotiation.
- **Fix:** read the current `NegotiationState` before each `classify` call. Load it from the store, or better, cache it on `CallContext` and update it in `verify_offer`. Add a test: after two counters, an agent turn with "Rs <second counter>" is classed as `ok`.

### C2. The voice price guard never checks spoken prices
- Live transcripts spell prices in words ("ek sau pentalis rupay"), so the digit regex finds nothing.
- The Step 4 fallback (`price_guard.fallback_extract_prices`, used when there's a price cue but no digits) is **never called** in `live_session.py`.
- **Result:** in voice calls the guard is effectively off. It only seemed to work in the human test because no digits were spoken.
- **Fix:** when `find_prices` returns nothing but `has_spoken_price_cue(text)` is true, start the fallback as a **background task** (Flash, 3-second timeout). Feed its result into the same `classify` and correction path, using the C1 fresh state. On a timeout, add the flag `price_unchecked`. Add a test with a faked Flash client.

### C3. A missing signing key leaves tokens open to forgery
- `api` mints tokens with `os.getenv("APP_SIGNING_KEY", "")`, and `voice` verifies them with the same default.
- If the secret isn't mounted, or its version is missing, both services silently use an empty key, and anyone can forge a valid token.
- **Fix:**
  - Add `APP_SIGNING_KEY: SecretStr` with a minimum length of 32 to `Settings`.
  - Both services must **fail at startup** if it's missing or too short.
  - `mint` and `verify` must raise on an empty key.
  - Add tests for both.

### C4. The cost per minute is circular, not measured
- `call_metrics_logged` computes `estimated_cost_usd = duration_min × 0.072`, a hardcoded estimate from the probe.
- The results doc then reports "$0.072 / minute" as if it were measured, and the daily-cap reasoning depends on that number.
- **Fix:**
  - Accumulate `usage_metadata` **by modality**: use `prompt_tokens_details` and `candidates_tokens_details` (or `response_tokens_details`), which give token counts per AUDIO and TEXT.
  - Price them with the Step 13 rates for `gemini-3.8-live`: audio in $3.00/M, audio out $12.00/M, text in $0.75/M, text out $4.50/M.
  - Log the per-modality counts and the computed cost.
  - Delete the 0.072 constant.
  - Re-state the numbers in the results doc from one real call. **The user sets `DEMO_DAILY_SESSION_CAP` afterwards.**

---

## 🟠 High

### H1. The latency figure isn't trustworthy
- The "~480 ms" is measured from when the **buyer's input transcription arrives**, which itself arrives late, to the first agent audio.
- The probe measured **1.78 s** from the end of the buyer's audio.
- Don't put 480 ms on a slide.
- **Fix:** measure on the client.
  - The page detects end of speech locally: mic energy below a threshold for 700 ms.
  - It records the time of the first playback sample after that.
  - It sends `{"type":"latency","ms":…}` over the WebSocket, and the voice service logs it.
  - Report the median and p90 over a real call.

### H2. The Urdu test isn't done yet, but the doc says "PASS"
- `docs/module-2-voice-results.md` shows **one** call (hard bargainer) as "Native Speaker Test Results: PASS".
- Step 13 needs 4 bargaining scenarios plus 3 situations, tested by 2 native speakers, with 1–5 ratings.
- The user is doing this test. The doc must label that section **"Pending: user's native-speaker test"** and keep the one call as a smoke check.

### H3. The agent bluffs that it can't go lower
- In the human-test transcript the agent said "rate ek sau paintis rupay per kilo se **neechay mumkin nahi hai**", then dropped to 130 on the next turn.
- That's the same credibility problem as the "aakhri" rule.
- **Fix:** widen the v1.4 rule to "Never say a price is the last or lowest ('aakhri', 'last', 'final', 'is se neechay nahi', 'mumkin nahi') unless verify_offer returned decision = final." Use PROMPT_VERSION 1.5, and update its test.

### H4. Check the agreed quantity in that call
- The buyer asked for **30 kg**. The agent's confirmation said "**teen-ees** kilo", which doesn't clearly mean 30.
- **Check:** in `deals/` for `call_hard_bargainer_d8e6ab9d`, the quantity must be 30.
- If it isn't, `confirm_deal` received a wrong quantity. Add to the prompt: "In the confirmation, say the quantity in digits-as-words exactly as given to confirm_deal."

---

## 🟡 Medium

- **M1. The failing test.** `test_model_policy.py::test_scan_tracked_files_for_unapproved_models` flags its **own** negative-test strings (`gemini-2.5-flash`, `gemini-2.0-flash-exp`). Build those strings at runtime (for example `"gemini-" + "2.5-flash"`), or exclude the test file from the scan.
- **M2. `deployer-sa` has project-wide `roles/storage.objectViewer`.** The plan asked for the function source bucket only. As it stands, it can read every bucket, including the Terraform state. Change it to `google_storage_bucket_iam_member` on `function_source`.
- **M3. The deployed voice `ALLOWED_ORIGINS` includes `http://localhost:8080` and `:8000`.** Remove them from the production default. Add a separate `dev_allowed_origins` variable, used only when `environment = "dev"`.
- **M4. The kill-switch threshold doesn't match the doc.** The doc says "hard kill switch at $25.00", but Terraform `KILL_RATIO=1.0` × your $50 budget means it fires at **$50**. It also only works once the budget is linked to `budget-alerts` in the console. **This is the user's decision:** keep $50, or set `KILL_RATIO=0.5`. Then fix the doc to match.

## 🟢 Low

- **L1.** `infra/terraform/billing_guard.zip` is a build artifact. Add it to `.gitignore` and `git rm --cached` it.
- **L2.** The Firestore contract tests (5) are skipped. Run them once with `RUN_FIRESTORE_TESTS=1` against the real database (with the `test_` prefix and clean-up), and record the result.
- **L3.** `POST /demo/sessions` adds to the daily cap before checking that the scenario is valid. Swap the order.
- **L4.** The transcript is stored twice, in `calls.transcript` and in `calls.result.transcript`. Keep only `calls.transcript`, with `result.transcript=[]`, to keep documents small.

---

## Checks I couldn't do
- **Firestore contents and Cloud Logging:** gcloud wasn't used in this review. H4 needs a quick look by the user.
- **Whether the budget is linked** to the `budget-alerts` topic in the console.
