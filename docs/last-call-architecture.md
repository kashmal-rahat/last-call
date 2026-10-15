# 🏗️ Last Call — Architecture

## Flowchart:

![](last-call-simple-flow.jpg)

## Architecture:

![](last-call-architecture.jpg)

> 🏗️ Final hackathon architecture. **Agents decide, code enforces.** No long requests anywhere: every step is a short task that saves its result and schedules the next one.

## 1. Components

| Need | Service |
|---|---|
| Frontend | Firebase Hosting, Firebase Authentication, Firebase App Check, Firestore live listeners |
| Business logic and agents | Cloud Run `api` (Freshness Inspector, Ladder profiles and the Scout's fit screening as direct Gemini calls with structured output; Scout search, filters and ranking in code; Orchestrator) |
| Live calls | Cloud Run `voice` (ADK live: Negotiator Agent, price tools, audio gateway) |
| Steps and anything that happens later | Cloud Tasks (from Module 9; the prototype's steps are driven by the judge's clicks through the same `next_action` code, D53) |
| AI | Gemini Flash (vision and reasoning), Gemini Live native audio (voice) |
| Buyer discovery | Places API (New) |
| State and fast lookups | Firestore |
| Photos | Cloud Storage |
| Reporting | BigQuery via the Firestore export extension |
| Calls and confirmations | Twilio voice and WhatsApp |
| Operations | Secret Manager, Cloud Logging, Cloud Trace, budget alerts |

## 2. Frontend (Firebase Hosting)

- **Reads** come straight from Firestore through live listeners: batch status, decisions, live transcript, deals.
- **Writes** always go through the `api`, so every rule is enforced in one place.
- **App Check** ensures only the real web app can call the `api`.
- **Manager portal** (login required): shelf results with reasons, quantity checks, buyer list review, live call transcript, discount tags, approvals (compost), rules and floor prices, daily summary.
- **Judge demo** (public): runs as its own isolated **demo mart** in Lahore with test rules and 3 branches the judge picks from a dropdown (Johar Town by default, Bahria Town, Gulberg; D51); switching branch before calling shows that branch's real buyers for the same photo, so nothing is hard-coded; once calls start, the branch, closing time and shelf prices are locked, and New shelf starts over (D58). Buyers are real nearby businesses from Google Maps, shown with "Google Maps" attribution and **masked phone numbers**; the demo never dials them.
    - Upload a shelf photo or choose a sample; the Inspector and then the Ladder run automatically on every item. The screen shows the 3 most actionable items first, with the rest collapsed.
    - For each off-shelf batch, the judge clicks **Find buyers** to run the Scout (up to 5 ranked buyers, each with a reason and a "View on Google Maps" link), then **Start calling** (rank #1) or **Play this buyer** on any row to start the Negotiator at the Ladder's prices. After each call: **Next buyer**, then **Next step** (e.g. find charities) once the step's buyers are used up (D53, D54). Paid steps run only on these clicks (D33).
    - The estimated quantity is shown as an editable field (until calling starts) that doesn't block the flow.
    - The call happens in the browser, with the judge playing the buyer. A role-play never changes a real business's records: no buyer history, no do-not-call entry, masked phone only, call record kept 24 h (D55). Calling hours and "closed now" are shown as notes, not enforced; pickup times follow the mart's hours (D56). With a Time until closing preset the whole call runs on the mart's time: the time the preset stands for (11:00, 19:00 or 22:00 that day), still ticking, for the pickup window, the calling-hours notes, the agent's "current time", the pickup and call-back checks, WhatsApp's "today" and the header clock; the system (tokens, locks, caps, cooldowns, record timestamps) stays on real time (D74).
    - Look (D59): one light, responsive page (design in `design/stitch/`) in six sections, Setup → AI reading → Decision → Buyers → Live call → Impact; sections 3–5 follow the active item; the impact panel counts only this shelf's real call outcomes, labelled as demo role-play.
    - No route to Twilio; never touches real marts or real stock.
    - 5-minute session limit, plus a global daily session limit stored in Firestore.

## 3. Photo upload

1. The client asks the `api` for a signed upload link: short-lived, images only, size-limited, restricted to that mart's or judge demo session's folder.
2. It uploads the photo straight to a private Cloud Storage bucket.
3. It calls `start-clearance` with the photo's location. The `api` creates the batch, schedules the first step, and **returns immediately**.
4. The screen follows the batch's progress through its Firestore listener.

## 4. `api` service (Cloud Run)

Request-based CPU, scales to zero, many requests per instance, capped maximum instances. Every endpoint does one step, saves state to Firestore, and returns.

### Freshness Inspector (two-pass vision, structured output)

- **Input:** the shelf photo, plus the previous result for the same shelf
- **Implementation:** direct `google-genai` `generate_content` call with Pydantic structured output on `gemini-3.8-flash` in multi-region Vertex `eu` (D22, D13), with `media_resolution=high` and `thinking_level=low` (D30).
- **Two-pass pipeline (D29):** pass 1 reads the full shelf; code picks doubtful groups (at most 6), crops them from the full-resolution photo, and pass 2 reads crops in parallel. Code merges results with worse `worst_stage` winning.
- **Output per item:** name, bounding box (`box_2d`), freshness stage (`stage` typical piece, `worst_stage` worst piece, D24), 0–100 score computed deterministically in code, change since the last photo (matched by IoU overlap and produce name in code, D26), visible issues from 13 signs (D25), estimated quantity range in selling units (D31), confidence, staff check flag with plain English reasons.
- **Quantity in production:** quantity comes from the mart's ERP (stock received − sold); the camera decides the condition, and the remaining stock goes down the ladder (D31).
- **Neighbour merging (D34):** code merges neighbouring groups of the same produce (same name, boxes touching or within 30 on the 0–1000 scale) to guarantee one group per display.
- **Zoom area rule (D35):** only doubtful groups whose box covers $\le 40\%$ of the photo are zoomed (`MAX_ZOOM_BOX_AREA = 0.40`), avoiding redundant crops on wide-angle crates.
- **Hedging & budget (D36):** identical hedge request starts after 12 s; 30 s per attempt, 3 attempts, with a 60 s total deadline per inspection to absorb tail latency.
- **Concurrency limit and memory (D37, D64):** at most 2 simultaneous inspections per `api` instance via `asyncio.Semaphore` and one shared Firestore store. `api` has 1 GiB: a 24 MP phone photo needs ~130 MB to inspect (each decoded copy replaces the previous one), and the stored shelf photo is decoded at reduced size.
- **Same photo → same reading (D45):** the demo endpoint stores each complete reading under a hash of the exact photo plus model, prompt version and settings, and reuses it when the identical file comes again. Safety rules, keys and change notes are recomputed. New photos are unaffected (about 20–50 ms of Firestore time); the evaluation scripts never use it. A switch turns it off to re-test the same photos (`INSPECTOR_READING_CACHE`, Terraform `inspector_reading_cache`, D63); it stays on for judging.
- Perception only

### Ladder ("Gemini knows, code decides")

- **Two parts (D38):**
    1. **Produce profile (Gemini, once per produce, stored).** The first time a produce name is seen, one direct `google-genai` call on `gemini-3.8-flash` with structured output (text only, `thinking_level=low`, no sampling parameters, D30) writes its profile. For fresh, ripening and overripe, the profile gives a shelf-life band (`under_6h`, `6_to_24h`, `1_to_3_days`, `over_3_days`) and which buyers can use it (juice shop, restaurant, bakery, charity), plus whether cattle can eat it when overripe or spoiled. Each new profile is the **consensus of 5 identical calls sent in parallel** (all new names on a shelf in each call), merged in code field by field: majority for buyer uses, median for shelf life, 4 of 5 for cattle safety (D43). The profile records how many votes it used and which fields were uncertain, so the manager knows where to check. Not ADK: one request in, one structured answer out, no tools or turns (as D22 for the Inspector).
    2. **Decision engine (pure code, every time).** From the Inspector's stage and level, the profile, the hours until the next closing and the mart's rules, code picks the step, discount, prices, buyer types, next steps, staff actions and a reason built from those facts. Same input → same decision; instant once profiles exist.
- **Safety in code (D39):** allowed steps come only from the Inspector's `stage` and `issues`: fresh → keep, discount; ripening → keep, discount (ripe produce never leaves the shelf, D44); overripe → discount, bulk sale, donate, animal feed; spoiled → animal feed or compost (compost only with mould or slime); unsafe → compost. The profile only chooses among allowed steps. When only `worst_stage` is spoiled or unsafe, staff remove those pieces and the rest is decided normally (D24). Staff-check reasons put off-shelf steps on hold; compost needs manager approval.
- **Timing (D44), using the mart's closing and opening times:**
    - **Fresh or ripening:** keep if it still sells when the mart reopens after tonight's closing. Otherwise keep at full price until the evening discount window (6 h before closing), then discount 10% rising 5% per hour to 40% at closing, or 40% from the start of the window if it stops selling before closing. Before the window it stays at full price even if the estimate says it won't last until closing: the estimate is rough, and the next photo re-decides (D44).
    - **Overripe:** bulk sale while there is time for pickup (at least 2 h before closing) and a business buyer fits; otherwise 40% off in store, with donation and animal feed as the next steps.
    - **Spoiled:** animal feed if cattle-safe, otherwise compost.
    - Every photo re-decides, so produce moves keep → evening discount → overripe bulk sale → donate on its own.
- **"Sells for" estimate:** the profile's shelf-life band (counted as 4, 15, 48 or 96 h) is how long produce sells **from the start** of a stage; it is multiplied by how much of the stage is left from the Inspector's stage level (early 1.0, mid 0.7, late 0.4). Approximate on purpose: bands are wide and each photo re-decides. Reasons give this as a rounded duration, never a clock time ("Ripening: sells for about 2 h, so it stops selling before the 23:00 closing"), so they read the same whichever time the page simulates and line up with the "h to closing" chip. They start with the stage and never repeat the item's name or the step, which the page shows beside them.
- **Prices (D41):** percentages of the shelf price from the mart's rules (prototype: a demo price list; production: the POS). Discount clamped to the manager's limits; opening price at or above the floor; a missing price means "needs shelf price". The demo list holds 56 common Lahore produce under the English names the Inspector uses (plus English alternatives such as aubergine, brinjal and eggplant); a name may appear under only one entry (ignoring case, spaces and plurals), checked when the rules load. If the full name has no price, the lookup removes descriptive words only (white, red, baby, desi…) and tries again, so "white radish" is priced as radish while "black plum" or "custard apple" stay unpriced (D66). The price must be in the item's sale unit (kg or dozen, set by the Inspector's prompt rule) and is never converted; with no price in that unit the page shows "Price not set" and staff enter it. In production the sale unit would come from the POS with the price.
- **Profiles are trusted data (D40):** checked in code before saving (a worse stage never lasts longer), keyed `{produce}__v{prompt version}` so a prompt fix regenerates them, never expire, shown on every decision, and fixable by script; a manager's fix (`{produce}__manager`) is looked up first and never overwritten. If Gemini fails, a generic cautious profile is used and not saved.
- **Output:** a `LadderResult` saved in `decisions/{inspection_id}` (D42). Off-shelf decisions carry what the Scout and Negotiator need: `buyer_types`, `buyer_condition` (what the buyer will receive; worst-piece details left out when staff remove them), `opening_price`, `floor_price`, `next_steps`.
- **Discount path:** the `api` saves the new price and creates a discount tag; the item stays on the shelf and the next photo re-evaluates it.

### Scout ("Google finds, Gemini screens, code decides")

Plan: [plans/module-4/plan.md](../plans/module-4/plan.md) (D46–D51). Not an ADK agent: the flow is fixed, so it is code plus one structured Gemini call (D46).

- **Input:** a scout target (the step `bulk_sale`, `donate` or `animal_feed`, its buyer types, the item and its `buyer_condition`), the branch (its coordinates are the search centre) and the mart's rules. The demo builds the target from the current `LadderDecision`; Module 6 builds one for a next step (donate is only ever a next step under D44).
- **1. Google finds (D47):** one Places search per buyer type (at most 3), 20 results each, `regionCode=PK` (D52). Business types (`juice_shop`, `restaurant`, `bakery`) use **Nearby Search (New)** with a type filter, nearest first, inside a 10 km circle; the probe showed Text Search's distance ranking missing shops 40 m from the branch. Charity and dairy farm have no Places type, so they use **Text Search (New)** with free text (`"dastarkhwan"`, `"dairy farm cattle farm"`) inside a rectangle around the branch. The 40 nearest candidates left after the filters go to Gemini. One constant **Enterprise field mask** (ID, name, types, location, business status, international phone number, open now, Maps link; never Atmosphere fields), so phone and hours come in the same request. No Place Details step: Places bills per request, so this is $0.035 per search against $0.132 for a two-step lookup.
- **2. Code filters (D50):** skips businesses that are not operating, are farther than 10 km straight-line (about 13–15 km by road; a manager setting that can be lowered, one limit for every buyer type), have no valid phone, are on the do-not-call list (checked under the place ID and under a keyed hash of the phone number, so an opt-out survives a changed place ID or a second listing), share a phone with a nearer listing, or were called within 24 h without a deal. Every skip is counted and shown. "Closed now" is not a skip: it decides when to call, not whether the buyer fits, so it only lowers the rank (and the list is never empty just because it's night in Lahore); phone calls (Module 9) skip closed buyers at call time, while the browser demo calls them anyway with a note (D56).
- **3. Gemini screens (D46, D73):** `google-genai` structured calls on `gemini-3.8-flash`, one per even group of at most 10 businesses (dealt round-robin), all in parallel under the Scout's 25 s deadline; a group that fails falls back on its own (`thinking_level=low`, no sampling parameters, D30) rates each remaining business `likely`, `possible` or `unlikely` with a one-line reason. The Ladder already chose the kinds of buyer, so Gemini judges only whether this business is a real, independent example of the kind it was searched as (each business is sent with its `searched_as` type) (e.g. a local shake shop for very ripe bananas is likely; a national chain or a milk shop named "Dairy" is not). Gemini sees only names and types under short refs, never phones or place IDs. It only orders and drops `unlikely`; it can't add a business or bypass a filter. If it fails, every business is `possible`. The judge demo shows a "Screened out by Gemini" list (up to 10 names with reasons), so the AI's judgement is visible.
- **4. Code ranks (D50):** past buyers with a deal at this mart first, then open or hours unknown before closed now, then fit, then open before hours unknown, then distance; ties by place ID. Keeps 5 (= calls per ladder step). Each buyer gets a checkable reason built from facts ("Juice shop · 0.6 km · open now"), plus Gemini's line. Phones are stored in E.164 for Twilio.
- **Storage (D48):** Places policy lets only place IDs be stored indefinitely, so there is **no cross-batch cache**. Every new batch searches Google fresh, so shops added to Maps appear the same day. The per-batch list `scout_results/{inspection_id}__{item_key}__{branch_id}` (the same key as its batch, D54; one list per branch) is reused for 1 h (one freshness rule for repeat clicks and, in Module 6, for calls); after that the code treats it as gone and Firestore TTL deletes it. Our own data is kept: `buyers` documents (place ID and our call history only) and `do_not_call` are never cleared on a timer.
- **Auth and cost (D49):** `api-sa` calls Places with its OAuth token (no API key, D2). Per Find buyers: at most 3 Places requests (≤ $0.105) and up to 4 small Flash calls (~$0.005 together). Demo cap 200 Places requests a day in code (counted per Pacific-time day, like Google's quotas), plus Google-side quotas of 250 a day and 30 a minute for each of Text Search and Nearby Search; sized so they never block judging.
- **When it runs:** in production, for every off-shelf batch through Cloud Tasks; in the judge demo, only when the judge clicks Find buyers for a batch (D33). No cap on batches per photo
- **Output:** `ScoutResult` with up to 5 `ScoutCandidate`s; `ScoutCandidate.to_buyer_info()` gives the Negotiator's `BuyerInfo`. API responses carry only masked phones.

### Orchestrator (event-driven, plain Python)

**Prototype (Module 6, D53–D57).** The orchestration is one pure function, `next_action(batch, scout list, call statuses, rules, now)`, which returns `call` (the next buyer), `busy`, `needs_search`, `next_step`, `compost_approval`, `no_buyer` or `sold`. In the judge demo it is called by the demo endpoints (`POST /demo/calls`, `GET /demo/batches/{id}`, `POST /demo/batches/{id}/next-step`) on the judge's clicks; there is no Cloud Tasks queue and no `call-finished` webhook, because `voice` finalises each call itself. A batch is created when calling starts, keyed like its scout list (`{inspection_id}__{item_key}__{branch_id}`), with a snapshot of its step plans (the current step plus the scout steps in `next_steps`, each with buyer types, opening and floor) and quantity. One call per buyer per step, at most 5 per step, then the next step. The deal brief takes the item and condition from the decision, the prices from the step plan, the buyer from the Scout (name re-sanitised, phone masked for browser calls), the branch as the mart, and payment terms, calling hours and city style (Lahore for the demo mart) from the mart rules. Pickup follow-up is deferred.

**Production (Module 9 and later)**, as designed below: Cloud Tasks drives the same `next_action` for phone calls, with calling hours, closed buyers, buyer history and phone-key do-not-call enforced.

Every step is its own Cloud Task.

**`start-clearance`:** creates an inspection record (`inspection_id`, `shelf_id`) with status "inspecting," schedules the inspect task, and returns immediately. Inspection states: `inspecting → deciding → decided | needs attention`.

**Step tasks** (each one short, retried independently by Cloud Tasks, and skipped if already done):

1. **Inspect:** runs the Freshness Inspector on the shelf photo, saves the `FreshnessResult` in `inspections`, sets status "deciding," schedules the Decide task.
2. **Decide:** runs the Ladder (produce profiles, then the code decision engine) for each assessed produce item and saves the `LadderResult` in `decisions`. Creates one batch for every off-shelf item (including compost, holding `inspection_id` and `item_key`), and saves the decision on each item:
    - **Stays on the shelf:** applies the discount, creates the tag, marks the item "on shelf." Done.
    - **Compost:** batch enters "awaiting compost approval," sends it for manager approval.
    - **Off the shelf:** batch enters "finding buyers," schedules the next task.
    Once all items are decided, sets inspection status "decided."
3. **Find buyers:** runs the Scout, saves the ranked list for that batch (`scout_results`, keyed like the batch). Then:
    - If the quantity estimate is unsure (low confidence, a wide range, or partly hidden produce), or "always confirm quantity" is on, waits as "awaiting quantity check" until staff confirm the amount.
    - If buyer list review is on, waits as "awaiting review"; the manager's approval schedules the next task.
    - If outside calling hours, waits as "scheduled," with a Cloud Task for when calling hours start.
    - Otherwise, schedules the next task.
4. **Start call:** locks the batch and asks the `voice` service to call the next buyer. The offer uses the confirmed quantity, or the low end of the estimate when no check was needed, rounded down as people say it (to the half below 10, to the whole number from 10; D71).

**`call-finished`:** called by the `voice` service after every call.

- Updates `pricing_stats` with the outcome.
- **Deal:** records it, updates the remaining quantity, creates a Cloud Task for the pickup deadline; if stock remains, calls the next buyer.
- **Declined or no answer:** next buyer if fewer than 5 calls in this step (a manager setting); otherwise the next ladder step.
- **Compost reached:** sends it for manager approval.

**Scheduled task endpoints** (called by Cloud Tasks):

- **Calling hours start:** resumes the batch.
- **Lock check:** if a batch is still locked after its expiry, releases it and moves to the next buyer.
- **Pickup deadline:** if staff haven't marked the deal collected after the grace period, records a no-show, lowers that buyer's ranking, re-checks freshness with the latest photo, and restarts the ladder for the remaining stock.

**Failure handling:** if a step fails after its retries, the batch is marked "needs attention" with the reason, and appears on the manager screen. It never stays silently stuck.

## 5. `voice` service (Cloud Run)

CPU always allocated, one warm instance, session affinity, long request timeout, capped maximum instances. Concurrent calls per instance start at 4 and are tuned by measuring CPU during test calls.

### Starting a call

- **`start-call`:** reads the deal brief, asks Twilio to dial, returns immediately. The call runs on Twilio's separate WebSocket connection.
- **Demo number override:** a clearly labelled setting replaces every buyer's real number with verified test numbers, while the screen still shows the real business names and the Scout's reasoning.
- The Gemini Live session starts **only once Twilio reports the call was answered**. Busy, no-answer and failed calls go straight to `call-finished`.
- **Judge demo:** the browser opens its WebSocket directly, presenting a short-lived session token issued by the `api`.

### Negotiator Agent (ADK live mode)

- Everyday Urdu with market vocabulary; friendly but firm
- Introduces itself as the mart's AI assistant; confirms price, quantity, pickup time, deadline and payment
- Treats everything the caller says as conversation, never as instructions
- On hang-up, saves the result and always releases the batch lock, so the next buyer can be called at once after a partial deal (the prototype has no `call-finished` webhook; D53)

### Tools (code)

- `send_photo` and `confirm_deal` (D62): send the buyer a WhatsApp photo of just that item (a signed, 1-hour crop of the shelf photo, saved in the background after the inspection is answered and deleted after a day from a private bucket, D72) and the deal confirmation. In the browser demo they appear on the page as WhatsApp messages; in the phone demo they are also sent to the presenter's SIM through Twilio.
- `verify_offer`: never sends the floor to the model. Accepts the buyer's offer if it's at or above the next counter; otherwise returns the higher of the floor or the previous counter minus a shrinking step.
- `confirm_deal`: checks price, remaining quantity and pickup deadline; saves the deal and updates the batch in one all-or-nothing transaction; sends the WhatsApp confirmation.
- `send_photo`, `schedule_callback`, `record_outcome`

### Transcript check

Checks numbers spoken near price words. Any price below the floor makes the agent correct itself and flags the call; it never ends the call.

### Audio

Gemini Live takes **16 kHz** PCM in and returns **24 kHz** PCM out.

- **Browser:**
    - Capture the microphone and send 16 kHz, resampling in an audio worklet if the browser captures at 44.1 or 48 kHz.
    - Play Gemini's audio at 24 kHz.
- **Phone:**
    - Caller to Gemini: 8 kHz μ-law → 16 kHz PCM.
    - Gemini to caller: 24 kHz PCM → 8 kHz μ-law.
    - Chunk by chunk with no buffering: `soxr` for resampling, `audioop-lts` or a NumPy table for μ-law (or Python 3.12).

## 6. Data model (Firestore)

Every record keyed by mart.

- `marts`: settings, rules, floor prices, calling hours, calls per step, review setting, quantity check setting
- `inspections`: stores `inspection_id`, `shelf_id`, `previous_inspection_id`, `photo_uri`, `taken_at`, `items` (each with `item_key`), `photo_issues`
    - Pointer: `shelves/{mart_id}__{shelf_id}` points to `latest_inspection_id` for fast sequential shelf lookup without composite index (D28)
    - Quantities: stored as estimated range in selling units (`kg` or `dozen`, D4, D31); staff can confirm/override; final actual weight settled at pickup (no ERP in prototype)
    - States: inspecting → deciding → decided | needs attention
- `inspector_readings/{key}`: the Inspector's stored reading for an exact photo (D45), created once and never overwritten
- `decisions/{inspection_id}`: the Ladder's `LadderResult` (one decision per item), overwritten when re-decided (D42)
- `produce_knowledge/{produce}__v{N}` and `{produce}__manager`: produce profiles shared by all marts (D38, D40)
- `batches`: discrete off-shelf produce batch, holding `inspection_id` and `item_key`. In the prototype it is created when calling starts, keyed `{inspection_id}__{item_key}__{branch_id}` like its scout list (D54). Stores the step plans (step, buyer types, opening, floor), the current step index, `then_compost`, the call attempts (call ID, place-based buyer ID, rank, type, step; no names or phones), total and remaining quantity, `locked_until`
    - States: finding buyers → awaiting quantity check / awaiting review / scheduled → in negotiation (locked) → sold / partly sold / next step, plus awaiting compost approval → composted, and needs attention from any step
- `calls`: pending → in progress → deal / declined / no answer / call back, with transcript, `channel` (`browser` or `phone`) and `city_style` (automatically deleted after 30 days; **24 h** for browser role-plays with real Places businesses, which also store only the masked phone, D55)
- `deals`: agreed terms, pickup deadline, collected or no-show, actual weight
- `pricing_stats`: running totals by item and buyer type (calls, deals, total accepted price), updated on every call outcome
- `scout_results/{inspection_id}__{item_key}__{branch_id}`: the Scout's ranked list for one batch at one branch, with names and phones for the call; reused for 1 h, then ignored by the code and deleted by Firestore TTL on `expire_at` (D48)
- `buyers/{mart_id}__{buyer_id}`: place ID plus our own call history (calls, deals, last called, last outcome, last deal price); no name or phone, because Places policy lets only place IDs be stored indefinitely (D48)
- `do_not_call/{mart_id}_{key}`: one doc per opt-out key, both `places:<place_id>` and `phone:<hmac>` (a keyed hash, not the number)
- `judge_demo_usage`
- No `places_cache`: Places names, phones and hours are never cached across batches (D48)

**BigQuery:** reporting only, such as the daily impact summary (kg saved, money recovered). Demo `pricing_stats` are seeded from buyer-simulator runs and labelled as simulated.

## 7. Security

### Access

- **Internal endpoints verify tokens themselves.** The step and scheduled task endpoints and `call-finished` on the `api`, and `start-call` on `voice`, check the request's identity token and accept only the expected service account. Cloud Run's built-in login applies to whole services, and both services must be publicly reachable.
- **Manager writes:** the `api` verifies the Firebase login token and the manager's role on every write.
- **Judge demo WebSocket:** requires a short-lived session token from the `api`, issued only after the session limits are checked.
- **Twilio web requests** are verified with Twilio's request signature.
- **Twilio's audio stream** includes a one-time secret per call in its address; `voice` accepts it only if the secret and call ID match a call it started.
- **Firestore rules:** no client writes; managers read only their own mart; judge demo users read only their own session's documents.

### Cost protection (hard limits, not just alerts)

- Maximum instance counts on both Cloud Run services
- Quota limits on the Gemini API and Places API (Places quota overrides in Terraform for both Text Search and Nearby Search: 250 a day and 30 a minute each, D49, D52)
- Judge demo daily cap of 200 Places requests, at most 3 Places requests per Find buyers, and 60 Find-buyers per IP per hour (D49)
- Places is called with the `api` service account's OAuth token; there is no Places API key to leak (D49)
- Global judge demo session limit and App Check
- Budget alerts at 50%, 75% and 90% as an early warning

### Untrusted input

Uploaded photos, caller speech and Places data are treated as data, never as instructions. Prices, quantities and safety rules are enforced in code, so injected text can't change them. Tested with a judge demo photo containing written instructions. Business names from Places are sanitised (control characters removed, length capped) before they reach Gemini or the Negotiator; Gemini's fit screening runs after the code filters and can only reorder or drop candidates (D46).

### Personal data

- Phone numbers masked in logs, and in every judge demo API response and screen (full numbers stay server-side, D51)
- Places results always shown with "Google Maps" attribution and a link to the place on Google Maps (Places policy)
- Twilio call recording off
- Transcripts automatically deleted after a set period
- AI disclosure at the start of every call

### Infrastructure

- Each service has its own service account with only the permissions it needs
- Secrets in Secret Manager; `.env.example` in the repo; secret scanning on the repository
- AI-generated code reviewed specifically for missing token checks and overly broad permissions

## 8. Reliability

- **Every endpoint is idempotent**, keyed by batch step, call or task ID, so retries never double-count a step, a call or a deal.
- **Lazy lock expiry** as a safety net alongside the Cloud Task lock check.
- Failed steps mark the batch "needs attention" instead of leaving it stuck.
- Structured logs for every tool call, decision and state change; Cloud Trace across agents.

## 9. Rules enforced in code

Floor price, accept and counter logic, ladder steps allowed by stage and issues, the ladder decision itself, discount limit, quantity and deadline checks, mould means compost, low confidence means staff check, calls per step, calling hours, compost approval, quantity check, lock expiry, demo number override, judge demo limits.

## 10. Fallbacks

- **Negotiator:** plain Gemini SDK if ADK live mode proves unstable
- **Voice quality:** Cloud Speech-to-Text (Chirp) → Gemini → Cloud Text-to-Speech if Gemini Live's Urdu isn't natural enough
- **Ladder:** a generic, cautious produce profile (not saved) when Gemini can't write one

## 11. Evidence in the repo

- Tests for price rules, deals, state transitions, locks, idempotency and endpoint authentication
- Freshness Inspector test set (about 50 labelled photos) with saved accuracy results
- Buyer simulator: 50 automated negotiations, floor breaches (target zero) and deal rate
- Measured cost per inspection and per call; measured audio delay on the phone path
- README with architecture, setup, and module status

## 12. Future: learning loop (not built for the hackathon)

- **"Correct this" (manager):** each Ladder decision shows the produce-profile facts it used; the manager corrects a wrong one, which saves the profile as manager-owned. It applies immediately to every future decision for that produce in every mart and is never overwritten by Gemini. One explicit correction instead of statistics from many ratings.
- **Next photo checks shelf life:** produce kept on the shelf is re-photographed; if it ages faster than its profile says, the shelf-life band is shortened.
- **Call outcomes check buyer fit and price:** repeated declines lower a buyer type's fit; accepted prices tune opening prices through `pricing_stats`.

## Key design decisions

- **Two services** because their scaling needs differ: the `api` scales to zero; `voice` needs CPU for whole calls.
- **No long requests anywhere:** every step, from inspection to the last call, is a short task that saves its result and schedules the next one.
- **Cloud Tasks is the only scheduler** once real phone calls exist (Module 9); Firestore states plus tasks form the workflow. In the prototype the judge's clicks call the same pure `next_action` function (D53).
- **Firestore for anything read during a decision;** BigQuery only for reporting.
- **The judge demo is just another mart**, so it runs the real pipeline with no special code paths.
- **Agents decide, code enforces:** every rule that protects money, stock or safety is checked in code.
- **ADK only where an agent is needed:** the Negotiator (live conversation with tools) uses ADK; the Inspector, the Ladder's produce profiles and the Scout's fit screening are single structured Gemini calls; the Ladder's decision and the Scout's search, filters and ranking are code.
