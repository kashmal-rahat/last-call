# Module 4 review: Milestone 4A, Steps 0–4 (2026-10-11)

Reviewer: Claude. Scope: commit `16d0ee6` (Terraform, models, mart config, `buyer_keys.py`, `scout/specs.py`, `scout/places.py`, `scripts/probe_places.py`, the tests) and `results/probe.md`, checked against `plan.md`.
Method: code read-through; `uv run pytest` (**290 passed, 9 skipped**); a read-only check of the live Places quotas with `gcloud alpha services quota list`.

**Verdict: Steps 0–4 are built as planned and work. Proceed to Step 5** after two small live checks (P1, P2: 3 Places requests in total). Nothing here is blocking. The items marked "for Step 8/9" are notes for code that isn't written yet.

---

## Verified OK
- **Terraform (Step 1), live:** the Places API is enabled. The Text Search quotas are in force: **60/day** (default 50,000) and **10/min** (default 600). `api-sa` has `serviceUsageConsumer`. The `scout_results.expire_at` TTL field exists. `google-beta ~> 8.0` was added with the same pin as D11.
- **Field mask:** exactly the planned constant, accepted by the API (`currentOpeningHours.openNow` sub-field works), no Atmosphere fields, and a test guards it.
- **Auth:** OAuth through ADC with `X-Goog-User-Project`; no API key anywhere. The test checks the headers and that the URL has no `key=`.
- **Models:** `GeoPoint`, `Branch`, `MartRules` (branches, default, radius 0.5–10, cooldown, max buyers, all validators), `BuyerHistory`, `ScoutCandidate` (`to_buyer_info`, `public_view` drops the phone), `ScreenedOut`, `ScoutMeta`, `ScoutResult`. They match Step 2, and the schemas were regenerated.
- **`demo_mart.json`:** the 3 branches with the user's coordinates; Johar Town is the default.
- **`buyer_keys.py`:** `phone_key` (HMAC-SHA256, 32 hex characters, `phone:` prefix) and `mask_phone` work as planned.
- **Places client:** the request body matches Step 3 (rectangle maths tested, `pageSize` passed in, `regionCode=PK`); one retry on 429/5xx; `PlacesError` never carries the token.
- **Probe:** 7 requests, as allowed. There are no phone numbers in `probe.md`.

---

## Probe results: what they say
| Type (Johar Town) | Usable within 10 km | Reading |
|---|---|---|
| juice shop | 14 | Good. Real local juice corners, 1.3–4.5 km |
| restaurant | 20 | Good. A mix of dhabas, family restaurants and cafés |
| bakery | 15 | Good, and a useful test for the screening: **"Cakes & Bakes" appears 4 times** and Bundu Khan and Gourmet are chains. Duplicate-phone removal (if they share a number) and Gemini's "chain" screening should cut these down |
| charity | **3** (really 2) | Thin. "Cravins" is very likely not a charity; Saylani is at 10.17 km, just outside the radius. See P1 |
| dairy farm | 11 | Better than expected: real ranches and farms 2.5–6.5 km away. Some listings are offices or services, which is Gemini's job to screen |

**Branch contrast:**
- Bahria Town's and Gulberg's lists differ clearly from Johar Town's.
- Two names appear in both Johar Town's and Bahria Town's lists ("AH FRESHOP", "Tayyab Juice"), but their distances prove they are **different branches of the same chain**. For example, 1.40 km from Johar Town plus 4.87 km from Bahria Town is 6.3 km, less than the 11.7 km between the two centres, so they can't be one place.
- The overlap by actual place is about 0–2 of 10, so the branch contrast works.

---

## Before Step 5: two small live checks (3 requests, ≤ 53 left today)

### P1. Charity query: try the planned revision (2 requests)
`"charity food bank welfare dastarkhwan"` returned only 4 results. Long multi-word queries narrow Text Search. The plan allows one revised query per type with at most 2 requests. Try these two around Johar Town, with the same settings as the probe (`page_size=20`, RELEVANCE, no type filter):
- A: `"welfare trust dastarkhwan"`
- B: `"dastarkhwan"`

Keep whichever gives more plausible charities within 10 km, and report both in `probe.md`. If neither beats the current query, keep it. This isn't blocking: under D44, donate is only ever a Module 6 next step.

### P2. Gulberg: check that "nearest first" really is nearest (1 request)
In Gulberg, the densest commercial area of the three (the point is about 250 m from Liberty Market), **the nearest juice shop returned is 4.42 km away**, while Johar Town's nearest is 1.32 km. Either few Gulberg places are typed `juice_shop` (they may be typed `cafe`), or Text Search's `DISTANCE` ranking inside a 20 km rectangle doesn't return the truly nearest places. The second would affect every typed search.

One diagnostic request settles it: **Nearby Search (New)** at the Gulberg point, `includedTypes: ["juice_shop"]`, `rankPreference: DISTANCE`, circle radius 5,000 m, `maxResultCount: 20`, and the same field mask. Write it in a throwaway script, or behind a flag in the probe.
- **If Nearby finds typed juice shops closer than 4.42 km that Text Search missed:** stop and report. We'd switch the typed buyer types to Nearby Search, which costs the same and allows the same field mask.
- **If not:** typing is just thin in Gulberg; keep Text Search and note it in `probe.md`.

---

## Notes to build into later steps (not bugs today)
- **N1 (Step 8): the retry must respect the time budget.** `PlacesClient.search` always retries once on 429/5xx. Step 8 needs "retry only if ≥ 9 s remain", so add an `allow_retry` (or `deadline`) argument.
- **N2 (Step 8): one shared HTTP client.** With no `http_client` passed, `search` creates a new `httpx.AsyncClient` per request (8 s timeout). `run_scout` should create one shared `httpx.AsyncClient(timeout=8.0)` for its parallel searches. An injected client must also have the 8 s timeout.
- **N3 (Step 9): Google's daily quota resets at midnight Pacific time, not Pakistan time.** That's 12:00 PKT while daylight saving lasts, 13:00 PKT after it ends ([source](https://developers.google.com/workspace/guides/view-edit-quota-limits)). Our app cap resets at PKT midnight. So Google's 60/day can run out while our counter still shows room; the scripts (probe, check) also use Google's quota. When Places returns **429 `RESOURCE_EXHAUSTED`**, map it to the same friendly 429, "Daily buyer-search limit reached", not the 502 "search failed". Add a test.
- **N4 (Step 8): httpx network errors.** Timeouts and connection errors come out as `httpx` exceptions, not `PlacesError`. That's fine because `gather(return_exceptions=True)` counts them as a failed type, but log the exception class (not the message) so failures are visible.

## Minor (fix when convenient)
- **M1. The test fixtures use `"id": "places/ChIJ…"`.** In the API, `id` is the bare place ID (`ChIJ…`) and `name` is `places/ChIJ…`. The parser correctly reads `id`, so production is fine, but the fixtures teach the wrong shape. A `/` would also make the Firestore doc ID `{mart_id}__places:places/…` invalid. Fix the fixtures to bare IDs, and add an assertion in the Step 5 normalisation that a place ID contains no `/`.
- **M2. `probe.md` table broken by a name containing `|`.** "Bismillah Fresh Juice & Dahi bhally | Johar Town Lahore" adds a column. Escape `|` as `\|` in names in `probe_places.py` and in the coming `check_scout.py`. The UI is unaffected, because it uses `textContent`.
- **M3. The overlap report that Step 0 asked for is missing from `probe.md`.** From the data above it's about 0–2 of 10; have `check_scout.py` report it by place ID in Step 8.
- **M4.** In `PlacesClient.search`, the final `raise PlacesError(..., "Failed after retry")` after the loop can't be reached. Harmless; remove it or leave it.

## Answer to the agent's question
- **The current queries and densities are acceptable** for juice shops, restaurants, bakeries and dairy farms.
- **Run P1 (2 requests) and P2 (1 request), update `probe.md`, then continue to Step 5.** If P2 shows Text Search missing nearer typed places, stop and report instead.
- Build N1–N4 into Steps 8–9, and M1–M2 when you touch those files.

---

# Round 2: P1/P2 results (2026-10-11)

Method: read `results/probe.md` (the P1/P2 section) and `scripts/probe_p1_p2.py`. 3 live requests were used, as allowed.

**Verdict: both findings are real. Approved: typed buyers move to Nearby Search, and the charity query becomes `"dastarkhwan"`.** Recorded as **D52**, with the plan updated (Step 4b, and Steps 3, 5, 6, 8 and Appendix A). Proceed with Step 4b, then Step 5.

## What the data shows
- **P2 is decisive.** At the Gulberg point, Text Search's nearest typed juice shop was 4.42 km away, while Nearby Search found typed `juice_shop` places 40–50 m away (Siddique, Sajjan Allah, Markhor, …). So Text Search's `DISTANCE` ranking isn't nearest-first for typed queries. That affects every branch, not just Gulberg: Johar Town's real nearest shops were probably missed too.
- **P1:** `"dastarkhwan"` gives 17 results and 9 usable within 10 km, against 3 for the old query. The obvious risk is commercial restaurants named "… Dastarkhwan" (Hyderabadi Dastarkhwan, Online Dastarkhwan). The fit prompt now has that exact example under `unlikely`, and Gemini receives `searched_as: charity`.
- **New observation: phone coverage is low in dense areas.** Only 3 of Gulberg's nearest 10 juice shops have a phone on Maps. The old page-size rule (10–15 per type when 2–3 types are searched) would leave too few callable buyers. Hence D52 part 3: always 20 per search, then the 40 nearest after the filters go to Gemini (`not_screened` counts the rest).

## Approved changes (Step 4b in `plan.md`)
1. **Terraform:** Nearby Search quota overrides, 60/day and 10/min (without them, Nearby Search would run at Google's defaults of 600/min and 50,000/day). The `gcloud` metric names must be reported first. 🛑 for the plan.
2. **`SearchSpec.endpoint`**: Nearby for juice shop, restaurant and bakery (circle of `radius_km × 1000` m, DISTANCE, `maxResultCount` 20); Text for charity and dairy farm (rectangle, RELEVANCE, `pageSize` 20). Remove `page_size` from `search()`.
3. **M1, M2** from round 1, in the same pass.
4. **No new live calls**; `check_scout.py` (Step 8) is the first live test of the new client.

## Notes
- Google-side, the two methods each allow 60/day, so the worst Google-side total is 120/day ($4.20). The app's own cap stays at 60 Places requests a day across both methods, and that is what the demo enforces.
- Nearby Search Enterprise costs the same as Text Search Enterprise ($35 per 1,000) and has its own 1,000 free requests a month, so moving typed buyers there costs nothing extra.
- `scripts/probe_p1_p2.py` imports from `probe_places.py` through `sys.path`. That's fine for a one-off diagnostic script; keep it as the record of this run.

## Round 2 addendum: limits for testing and judging (user decision, 2026-10-11)
The user's priority: limits must never block testing or judging (18 Oct – 4 Nov). **D49 revised** (supersedes the 60/day and 10/min values above):
- App daily cap **200 Places requests**, counted per **Pacific-time day** (`places-{pacific_date}`), so it resets together with Google's quotas.
- Google-side, for **each** of Text Search and Nearby Search: **250/day, 30/min**. This is always above the app cap, so the friendly "Daily buyer-search limit reached" always shows before Google refuses.
- IP limit **60 Find-buyers/hour** (judges at one venue may share an IP).
- Step 4b now changes the two existing Text Search overrides and adds the two Nearby ones: 2 to add, 2 to change.
- Cost: about $0 in practice (1,000 free requests a month per search type, and the window spans two months); a runaway bug is stopped by Google at about $17/day.
- **Outside Module 4, for the user before 18 Oct:** the project-wide $50 kill switch (D21) is now the bigger risk to the demo. Check the October spend, decide on the budget for the judging window, and set `voice` min instances to 1 (D15).

---

# Round 3: Step 4b before `terraform apply` (2026-10-11)

Method: read the uncommitted diff (`infra/terraform/main.tf`, `scout/specs.py`, `scout/places.py`, `scripts/probe_places.py`, `test_scout_places.py`, `config.py`); ran `pytest` on the scout tests (17 passed).

**Verdict: the code changes are good. Do not apply the Terraform yet**: it still uses the old limits. The agent hadn't received the D49 revision (round 2 addendum).

## Must fix before `terraform apply`
- **T1. The quota values are outdated.** The two new Nearby overrides are `60`/day and `10`/min, and the two existing Text Search overrides are unchanged (60/10). Per D49 (revised), **all four** must be **`250`/day and `30`/min**. Expected `terraform plan`: **2 to add, 2 to change, 0 to destroy**.
- **T2. The config defaults are outdated.** `config.py` still has `DEMO_DAILY_PLACES_CAP = 60` and `SCOUT_IP_LIMIT_PER_HOUR = 30`. They must be **200** and **60**.

## Small robustness fix (same pass)
- **S1.** For `endpoint == "searchNearby"` with no `included_type`, the client sends `includedTypes: []`, which would search **every** place type. Validate in `SearchSpec.__post_init__`: `searchNearby` requires `included_type`; `searchText` requires a non-empty `text_query`. Add a test for each.

## Verified OK
- **The spec table matches D52:**
  - juice shop, restaurant and bakery use `searchNearby` (circle of 10,000 m, DISTANCE, `maxResultCount` 20)
  - charity uses `searchText` with `"dastarkhwan"` (RELEVANCE, rectangle, `pageSize` 20)
  - dairy farm keeps its query
  - `page_size` is removed everywhere
- **Tests:** both request bodies and headers are tested, and the circle maths is tested.
- **M1 fixed:** the fixtures use bare place IDs (`ChIJ…`).
- **M2 fixed:** `|` is escaped in names in the probe script.
- **Naming:** using `"searchNearby"` / `"searchText"` as the endpoint values (the plan said `"nearby"` / `"text"`) is a fine, clearer choice.

## Billing note (user, 2026-10-11)
The billing account was upgraded to paid; about $12 of the $300 credits is used. The budget includes savings (credits), so the $50 kill switch can't fire while credits cover the spend. The Free Trial risk is gone.

---

# Round 4: Steps 5–8 (2026-10-11)

Method: read `scout/rank.py`, `scout/fit.py`, `scout/scout.py`, the store changes, `results/scout-check.md` and the new tests. `uv run pytest`: **332 passed, 13 skipped in 19 s** (the 53 scout tests take about 2 s).

**Verdict: well built and close to the plan. One real problem shows up in the live check: the Gemini fit timed out on the main demo path (Run 1).** Fix F1 and F2, re-run Run 1 once, then start 4B.

## What the live check shows
- **Gemini screening works when it runs.**
  - **Gulberg bulk sale (Run 4):** it dropped 8 businesses with sound reasons (Shezan, Jalal Sons, Layers, Pie in the Sky as chains; jalebi, mithai and nankhatai shops) and kept 5 local juice shops, all "likely".
  - **Charity (Run 2):** it dropped "Hyderabadi Dastarkhwan" as a commercial restaurant, which is exactly the D52 risk.
  - **Dairy farms (Run 3):** it dropped a corporate head office and a veterinary supplier.
- **The branch contrast is real:** Gulberg and Bahria Town lists differ completely from Johar Town's (0 overlapping place IDs).
- **The filters and ranking follow D50.** Most drops are "no phone" (17–18 of 40 for juice shops and bakeries), which confirms D52's choice of 20 results per search.

## Must fix before 4B
- **F1. The fit call's timeouts are too tight; the main demo path fell back.**
  - **Run 1** (overripe banana → bulk sale at Johar Town, the default branch and the demo's main path): **19 s, 0 tokens, `fit_fallback=True`**. Every buyer came back "possible" with no reason, and a chain ("Cakes & Bakes") was ranked #5.
  - **Run 5** also took 15 s.
  - **Cause:** with 20–30 candidates the answer is about 400–950 output tokens, normally 5–6 s (Runs 2–4). But `per_attempt_timeout=8` with `hedge_after_s=5` gives the hedged copy only 3 s, so a slow first answer kills the attempt.
  - **Fix:**
    - `screen_fit`: `per_attempt_timeout=12`, `hedge_after_s=6`, `max_attempts=2`
    - the scout's total budget: **25 s** (was 20)
    - typical time stays at 5–8 s; the fallback only for real Vertex problems
  - **Verify:** re-run **only Run 1** of `check_scout.py` (2 Places requests and 1 Gemini call), and report latency, tokens and `fit_fallback`.
- **F2. `screen_fit` swallows every exception without logging** (`except (GeminiCallError, Exception)`). That's why we can't tell what failed in Run 1. Log a warning with the exception class and `GeminiCallError.reason` (never names or prompt text). Keep the fallback.

## Minor (fix in the same pass)
- **m1.** `scout-check.md`'s comparison table labels the rank-1 buyer as "Nearest Farm" (Butt Cattle Farm at 6.9 km, while Shandar is 2.5 km away). Rename the row to "Top-ranked buyer".
- **m2.** `apply_filters` uses `assert "/" not in p.id`. An assert in request code turns a bad record into a 502 (and asserts are stripped with `python -O`). Skip that place and log a warning instead.

## Verified OK
- **Filters:** the order, counts, dedupe by place ID, duplicate-phone removal (nearer kept) and the 40-nearest cap with `not_screened` all match Step 5.
- **Ranking:** the 6-key sort matches D50.
- **Reasons and screened-out list:** reasons are built in code; `screened_out` holds at most 10, nearest first, with no phone.
- **Gemini input:** refs only, `searched_as` included, no phones or place IDs, `thinking_level=low`, no sampling parameters, and the prompt matches Appendix A (including the dastarkhwan example).
- **Orchestration:**
  - `ScoutTarget.from_decision` rejects keep, discount and compost
  - the cap is reserved before searching
  - searches run in parallel on one shared `httpx` client
  - the retry happens only if at least 9 s remain (N1)
  - failed searches are logged by exception class (N4)
  - `ScoutFailed` is raised when every search fails
- **Store:**
  - `get_scout_result` returns `None` after `expire_at`, with `expire_at` stored as a datetime for the TTL
  - histories and do-not-call are each one batch read, and do-not-call covers both place-ID and phone keys
  - `record_buyer_call` is transactional
  - `incr_daily_sessions(amount)` respects the cap
- **Logs:** no names, phones or reasons.

## On testing effort (user question)
The suite is fast (19 s in total; the 53 scout tests take about 2 s). The time went into writing fakes and doing live runs, not into running tests. The density for filters, ranking and orchestration is justified: that's where a silent bug would put the wrong buyer in front of a judge. It's done; **don't add more there**. For 4B, test only what can break the demo or leak data (endpoint behaviour, masked phones, limits); no UI automation; iterate on single test files and run the full suite once per 🛑.

---

# Round 5: round-4 fixes and Milestone 4B code, before deploy (2026-10-11)

Method: read the diffs of `scout/fit.py`, `scout/scout.py`, `scout/rank.py`, `main.py` (`/demo/branches`, `/demo/scout`), `static/index.html`, `test_demo_scout.py` and `README.md`, plus the Run 1 re-run in `scout-check.md`. `uv run pytest`: **344 passed, 13 skipped in 18 s**.

**Verdict: ready to deploy after five small fixes (G1–G5, about 15 minutes).** No blocking issues.

## Round-4 fixes: verified
- **F1:** fit `per_attempt_timeout=12`, `hedge_after_s=6`; scout budget 25 s. **The Run 1 re-run works:** 11.9 s, 2,024/965 tokens, `fit_fallback=False`. The top 5 are local juice shops, all "likely". Gemini screened out 6 businesses with good reasons: Cakes & Bakes, Butt Sweets, Gourmet and Suleman Sweets as chains, a custom-cake studio, and a mall kiosk. This is the main demo path and it now shows the AI's judgement clearly.
- **F2:** the fallback logs a warning with the error class and reason.
- **m2:** a place ID containing `/` is skipped and logged, not asserted.

## 4B code: verified
- **`/demo/branches`:** returns names, locations and the default ID; **no coordinates**.
- **`/demo/scout`:**
  - follows Step 9's order: access code → validation (IDs, known branch) → IP limit 60/h → decision lookup → target (409 when not applicable) → reuse within 1 h, compared on step and buyer types as lists, with no cap used → cap counter keyed by the **Pacific date** → run → 429/502 mapping
  - responses go through `public_view()` (masked phones only), including on the reuse path
  - errors are logged by class only
- **Page:**
  - **Data loading:** a branch selector filled from `/demo/branches`; re-deciding or changing branch clears every buyer list; a per-item request counter ignores out-of-order responses.
  - **Buyer list:** the header "Call order (AI decides)", masked phones, fit chip with reason, the code reason, a Maps link only for `https://` URLs, "Results from Google Maps", "Near <branch> · within 10 km", "Searched … ago", Refresh, and the "Screened out by Gemini (n)" section.
  - **Safety and errors:** all text is set with `textContent`, and error banners handle a non-string `detail`.
- **Tests:** 6 compact endpoint tests covering errors (parametrized), both 429s plus the 502, the masked-phone response, reuse, the Pacific-date key and branches without coordinates. That's in line with the leaner testing rule.

## Fix before deploy (small)
- **G1. Double save.** `run_scout` already calls `save_scout_result`, and the endpoint saves the same result again (`main.py` step 8). Remove the endpoint's save: it's one wasted Firestore write per search.
- **G2. `ScoutNotApplicable` raised inside `run_scout` becomes a 502.** For example, when no buyer type has a search spec. The endpoint's generic `except Exception` catches it. Add `except ScoutNotApplicable` → 409 before the generic handler. (With the current Ladder this can't happen, but the mapping should be right.)
- **G3. Misleading 409 text when no branches are configured.** The endpoint reuses "This item stays in store; no buyers needed". Use "Buyer search isn't set up for this mart".
- **G4. A stale table in `scout-check.md`.** After the new Run 1 section, the **old** fallback table (B4 Bakers … all "possible", "No candidates screened out") is still there. Remove the old one so the results doc doesn't contradict itself.
- **G5. `README.md` misquotes the dairy-farm query** as `"dairy cattle farm"`; the spec is `"dairy farm cattle farm"`.

## Notes (no change needed now)
- **N-a. The main path takes about 12 s.** That's Places (~1 s) plus about 965 output tokens from Gemini for 38 candidates. It's acceptable with the "Searching Google Maps…" message. If judges find it slow, the simplest lever is to send Gemini fewer candidates (40 → 25). Measure on the deployed service first.
- **N-b. A Google per-minute 429 shows as 502 "try again"** rather than the daily-limit message. Since D49 aligned the clocks and Google's per-day limits sit above the app cap, only a per-minute burst (30/min per type) can trigger it, and "try again" is the right message for that. No change.

## Deploy checklist (Step 11; the user commits)
1. **Commit every new file, including the untracked ones:** `scout/fit.py`, `scout/rank.py`, `scout/scout.py`, `scout/fit_prompt.md`, the four new test files, `scripts/check_scout.py`, `scripts/probe_p1_p2.py`, `results/scout-check.md` and `review.md`. Deploys use committed code, and `fit.py` reads `fit_prompt.md` when it's imported.
2. `./scripts/deploy.sh api`; `/health` shows HEAD.
3. Then the Step 11 checks on `/demo`, by hand.

---

# Round 6: G1–G5 re-check (2026-10-11)

`uv run pytest`: **346 passed, 13 skipped in 19 s.**

| Item | Status | Checked |
|---|---|---|
| G1 | ✅ | `/demo/scout` no longer saves; it relies on `run_scout`'s save |
| G2 | ✅ | `except ScoutNotApplicable` → 409 sits before the generic `except Exception` |
| G3 | ✅ | No branches configured → 409 "Buyer search isn't set up for this mart" |
| G4 | ⚠️ partly | The stale Run 1 table is gone, but the **"Bulk Sale Contrast" section still uses the old fallback run** (see R1) |
| G5 | ✅ | The README quotes `"dairy farm cattle farm"` |
| m1 | ✅ | The row is now "Top-ranked buyer" |

## One leftover (docs only, not blocking deploy)
- **R1.** In `scout-check.md` → "Branch Contrast Analysis" → "Bulk Sale Contrast", the Johar Town column still shows the failed first run:
  - Top 1: B4 Bakers (0.2 km)
  - Top 2: Time out Shop (0.4 km)
  - skipped `{'no_phone': 17}`
  - average top-5 distance 0.44 km

  From the re-run (the current Run 1 section) it should be:
  - Top 1: **JuicePanda (0.6 km)**
  - Top 2: **Bismillah Fresh Juice (1.3 km)**
  - skipped **`{'no_phone': 17, 'unlikely_fit': 6}`**
  - average top-5 distance **1.22 km** (0.6, 1.3, 1.3, 1.4, 1.5)

  This doc may become a slide, so it must match the run above it.

**Verdict: the code is ready to deploy.** Fix R1 whenever convenient (a 1-minute doc edit), then follow the round-5 deploy checklist: commit everything including the untracked files, `./scripts/deploy.sh api`, and the Step 11 checks by hand.
