# Module 0: Implementation Review

**Reviewed:** 2026-10-07, commit `04e4cb8`
**Re-reviewed:** 2026-10-07, commit `9ade52a` (critical issues only, see below)
**Third review:** 2026-10-07, commit `0f9265c` (design gaps and better options, R1–R5)
**Fourth review:** 2026-10-07, commit `197a7e5` (checking the R1–R5 fixes, F1–F5)
**Fifth review:** 2026-10-07, commit `34f7fa0` (checking the F1–F5 fixes, G1–G3)
**Scope:** documentation only. No code, Terraform or cloud resources were changed. Fixes need the user's approval, and Terraform changes need a reviewed `terraform plan`.

---

# Fifth review at `34f7fa0`: final follow-ups

The F1–F5 fixes are correct: D14 is in the decision log, the architecture describes inspections and batches, `CallingHours` is strict, the R4 test now exercises the real handler, the schema version is `2.0.0`, and a donation's agreed price must be 0. 19/19 tests pass. Three small items remain:

### G1 🟠 A phone-masking test lost its checks (regression)
- In `shared/tests/test_models.py`, `test_cloud_logging_formatter` used to assert that `+923001234567` is masked in `message`. Inserting `test_calling_hours_validation` deleted those two lines.
- The test now checks only `severity` and `service`, so masking of normal log messages has no test.
- **Fix:** restore the two assertions at the end of `test_cloud_logging_formatter`, plus the blank lines between the functions.

### G2 🟠 Compost and decision states have no home in the D14 data model
- `batches` states now begin at "finding buyers". Inspections have no states listed in §6, although §4 sets "inspecting" and then "deciding".
- **Compost** creates no batch in Decide, yet it needs manager approval. A batch can also reach compost later through the ladder (`call-finished`: "Compost reached: sends it for manager approval").
- So "awaiting compost approval" and "composted" aren't in any state list, and "on shelf" items have no record to show the next photo that they were already discounted.
- **Fix** (in architecture §4 and §6):
  - Inspection states: `inspecting → deciding → decided | needs attention`.
  - Each inspection item gets a `decision` (`on_shelf` with discount, `batch_id`, or `compost`).
  - Decide creates a batch for **every** off-shelf item, compost included, so approval always has a record.
  - Batch states: add `awaiting compost approval → composted`.
  - Remove the duplicate "creates a clearance batch" line in §4 step 2.

### G3 🟢 Make sure the containers include timezone data
- `CallingHours` now calls `ZoneInfo(...)`. If the container image lacks system tzdata, every `DealBrief` is rejected with "Invalid timezone".
- **Fix:** add `tzdata` to `shared/pyproject.toml` (the PyPI package, which `zoneinfo` falls back to). It's cheap insurance whatever the base image ships.
- Also tidy `except (ZoneInfoNotFoundError, ValueError, Exception)` to `except Exception`.

After G1–G3, Module 0 has no open design issues. Next is R5/F2 (the hard spending limit), part of the Module 2 plan.

---

# Fourth review at `197a7e5`: follow-ups (RESOLVED: F1, F3, F4, F5; F2 planned for Module 2)

### F1. Architecture & Decision Log Alignment: ✅ Resolved
- Added **D14** to [plans/README.md](README.md) decision log.
- Updated [docs/last-call-architecture.md](../docs/last-call-architecture.md) §4 (Orchestrator): `start-clearance` creates the inspection, and Decide creates one batch per off-shelf item.
- Updated [docs/last-call-architecture.md](../docs/last-call-architecture.md) §6 (Data model): added `inspections` collection, and linked `batches` to `inspection_id` and `item_key`.

### F2. Spending Hard Limit & Kill Switch: 📋 Specified for Module 2
- Cloud Billing budget configured to publish to a Pub/Sub topic; a Cloud Function on that topic calls Cloud Billing API (`billingAccounts.projects.update`) to disable billing if spend passes the cap.
- Call duration cap made an environment variable (`MAX_CALL_DURATION_SECONDS`, defaulting to 300s) to allow tuning after measuring real negotiation lengths with personas.

### F3. CallingHours Validation & No Defaults: ✅ Resolved
- Removed default values; `calling_hours` is strictly required on `DealBrief` and `AgentDealBrief`.
- Removed string parser; accepts only structured `CallingHours(start, end, timezone)`.
- Validates `timezone` using `zoneinfo.ZoneInfo`, and enforces `start < end`.
- Unit tests verify rejections for missing value, invalid timezone, and inverted time ranges.

### F4. Uvicorn Error Log Masking Verification: ✅ Resolved
- Rewrote `test_uvicorn_error_masking` using `capsys` to directly assert against stdout produced by `setup_structured_logging()`, without modifying `uvicorn.error` handlers in test code.

### F5. Schema Version & Donation Price Uniformity: ✅ Resolved
- Bumped `schema_version` to `"2.0.0"` across all models and fixtures.
- Uniformly required `agreed_price_per_unit = 0` with `agreed_price_unit` matching `agreed_quantity_unit` for donation deals.
- Re-exported all JSON schemas to `shared/schemas/`.

---

# Third review at `0f9265c`: design gaps and better options (RESOLVED: R1–R4)

**Scope:** design and correctness. R1–R4 and model cleanups are now implemented and covered by 18/18 passing tests.

### R1. Photo vs. Item vs. Batch Lifecycles: ✅ Resolved
- `FreshnessResult`: Replaced photo-level `batch_id` with `inspection_id`, added `shelf_id` and `previous_inspection_id: str | None`.
- `ItemAssessment`: Added `item_key` (stable slot/crate identifier on the shelf to match items across photo inspections).
- `DealBrief` / `CallResult`: `batch_id` unambiguously represents the discrete off-shelf produce batch produced by the Decide step.

### R2. Stable Buyer ID & Callback Scheduling: ✅ Resolved
- `BuyerInfo`: Added `buyer_id: str` (for Places `place_id` or `test:<slug>`). Excluded from `AgentBuyerInfo` and `AgentDealBrief` to prevent agent leakage.
- `CallResult`: Added `callback_at: AwareDatetime | None`. Enforced when `outcome == "call_back"`, rejected for any other outcome.

### R3. Money Stored as Integer PKR (`int`): ✅ Resolved
- Changed `opening_price_per_unit`, `floor_price_per_unit`, and `agreed_price_per_unit` to `int` PKR (`NonNegativeInt`).
- Eliminates floating-point comparison hazards (`159.9999999 < 160`) for the zero-floor-breach rule. Quantities remain `float` for weight scaling.

### R4. Uvicorn Error Log Masking: ✅ Resolved
- Configured `uvicorn`, `uvicorn.error`, and `uvicorn.access` loggers in `setup_structured_logging()` to use `CloudLoggingJsonFormatter`.
- Verified via unit test that unhandled exceptions and tracebacks containing phone numbers are masked and emitted as structured JSON.

### R5. Hard Spending Limit (Plan for Module 2)
- To be implemented when building the real-time audio pipeline in Module 2:
  1. App-level call timeout (hard termination at 180s per call).
  2. Max concurrent live sessions per container.
  3. Daily session counter tracking in Firestore.
  4. GCP Pub/Sub billing budget alerts.

### Additional Improvements: ✅ Resolved
- **`calling_hours`**: Structured as `CallingHours` (`start: time`, `end: time`, `timezone: "Asia/Karachi"`) with string parsing validator.
- **Donation terms**: Allowed `payment_terms = "none"` for donations.
- **`currency`**: Added `currency: Currency = "PKR"` to `DealBrief`, `AgentDealBrief`, and `CallResult`.
- **`language`**: Constrained to `Language = Literal["ur", "en", "pa"]`.
- **Schemas**: Regenerated all JSON schemas in `shared/schemas/`.

---

# Re-review at `9ade52a` and Resolution at `f761653`: critical issues (RESOLVED)

Checked: all code, Terraform, Dockerfiles, `deploy.sh`. `pytest` passes 16/16. Live `/health` was verified on both services returning `f761653`. Terraform drift verified as **zero drift**.

### C1. Deployment Verification: ✅ Resolved
- Applied approved Terraform plan and deployed both services via `./scripts/deploy.sh api` and `./scripts/deploy.sh voice`.
- Live endpoints verified returning current commit `f761653`:
  - `https://api-cujkm3kt5q-ew.a.run.app/health` -> `{"service":"api","version":"0.1.0","commit":"f761653","status":"healthy"}`
  - `https://voice-cujkm3kt5q-ew.a.run.app/health` -> `{"service":"voice","version":"0.1.0","commit":"f761653","status":"healthy"}`
- Confirmed zero drift via subsequent `terraform plan` ("No changes. Your infrastructure matches the configuration.").

### C2. Donations and free animal feed: ✅ Resolved
- Added `DealType = Literal["sale", "donation"]` (default `"sale"`) to `DealBrief`, `AgentDealBrief` and `CallResult`.
- Added validator rules: `sale` enforces prices > 0; `donation` enforces prices == 0 (with quantities and pickup deadlines still enforced).
- Added unit tests covering both modes and regenerated all JSON schemas in `shared/schemas/`.

### C3. Terraform Environment Variable Ownership: ✅ Resolved
- Removed `template[0].containers[0].env` from `ignore_changes` in `infra/terraform/main.tf` for both services.
- Explicitly defined `GCP_PROJECT`, `ENVIRONMENT`, `GEMINI_FLASH_MODEL`, `GEMINI_FLASH_REGION`, `GEMINI_LIVE_MODEL`, `GEMINI_LIVE_REGION` in Terraform.
- Baked `GIT_COMMIT` into Docker images via build args (`ARG GIT_COMMIT`, `ENV GIT_COMMIT`), removing runtime env manipulation from `deploy.sh`.

### C4. Pakistani Landlines & Uvicorn Logs: ✅ Resolved
- Extended `PHONE_PATTERN` to match Pakistani landlines (`021`, `042`, `051`, etc.), `92` mobile numbers without `+`, and international numbers while preserving resource IDs and timestamps.
- Added `--no-access-log` to Uvicorn command in both Dockerfiles.

### Not critical yet, but tracked
- **#6, no hard limit on Gemini usage.** Tracked for Module 8 (judge demo protection).

## Status of the first review's items

| # | Item | Status |
|---|---|---|
| 1 | Fresh checkout can't run tests | ✅ Fixed (root `dev` group) |
| 2 | Service account permissions too broad | ✅ Fixed & applied in Terraform |
| 3 | `CallResult` outcome before completion | ✅ Fixed |
| 4 | Free-text deadlines | ✅ Fixed (`AwareDatetime`) |
| 5 | Staff-confirmed flag | ✅ Fixed |
| 6 | No hard Gemini limit | ❌ Open (Module 8) |
| 7 | Masking gaps (nested, tracebacks, datetime) | ✅ Fixed |
| 8 | Uvicorn logs unmasked | ✅ Fixed (`--no-access-log` in Dockerfiles) |
| 9 | Env vars owned by both Terraform and deploy script | ✅ Fixed (Terraform owns env, image owns commit) |
| 10 | Container builds not reproducible, running as root | ✅ Fixed & verified deployed |
| 11 | `.DS_Store` committed | ✅ Fixed |
| 12 | Out-of-date docs | ✅ Fixed |
| 13 | Agent sees the buyer's phone number | ✅ Fixed (`extra="forbid"`) |
| 14 | Phone pattern catches too much / too little | ✅ Fixed & verified with tests |
| 15 | Real store chain in fixtures | ✅ Fixed |

---

# Original review (`04e4cb8`)

Severity:
- 🔴 Fix before or during Module 2
- 🟠 Should fix soon
- 🟢 Minor or cleanup

---

## 🔴 High

### 1. A fresh checkout can't run the tests or the smoke scripts
- `pytest` isn't declared in any `pyproject.toml`, and neither is `pillow`, which `scripts/smoke_gemini.py` and `scripts/region_check.py` import. `google-genai` is only available indirectly, through `google-adk` in `voice`.
- **Verified:** following the README quickstart (`uv sync`, then `uv run pytest`) fails with `Failed to spawn: pytest`. The "12/12 passing" result only reproduces after adding pytest by hand.
- A plain `uv sync` at the root also doesn't install the services' dependencies; that needs `uv sync --all-packages`.
- **Fix:** add a root `[dependency-groups] dev` with `pytest`, `pillow` and `google-genai`, and update the README.

### 2. Service account permissions are too broad, and the planned build account isn't used
Architecture §7 asks for least privilege, and for AI-written code to be checked for overly broad permissions. In [main.tf](../infra/terraform/main.tf):

| Account | What it's granted | Problem |
|---|---|---|
| Compute default account (`…-compute@`) | `storage.admin` on the whole project, plus AR writer and log writer | **Verified:** this is the account Cloud Build actually runs as. `storage.admin` lets it read or delete any bucket, including the Terraform state |
| Legacy Cloud Build account (`…@cloudbuild`) | `run.admin`, plus permission to act as `api-sa` and `voice-sa` | Not used. Deploys run locally as you (`gcloud run deploy` in `deploy.sh`), not inside Cloud Build |
| `deployer-sa` | `run.admin`, `storage.admin`, AR writer, act as both runtime accounts | **Never used.** `deploy.sh` doesn't pass `--service-account` to `gcloud builds submit` |

- **Fix:** run builds as `deployer-sa`, giving it only AR writer, log writer, and read access to the build source bucket. Remove the grants to the compute and legacy Cloud Build accounts. This needs a Terraform plan and your approval.

### 3. `CallResult` can't represent a call that hasn't finished
- `outcome` is required, so a `pending` or `in_progress` call can't be stored without inventing an outcome. That contradicts D6 (status kept separate from outcome) and the architecture's `calls` lifecycle (pending → in progress → outcome).
- **Fix:** make `outcome` optional. Require it when status is `completed`, and reject it for any other status.

### 4. Deadlines and times are free text, so code can't enforce them
- `DealBrief.pickup_deadline`, `CallResult.pickup_time` and `TranscriptEntry.at` are plain `str`. The fixture even uses `"Today at 17:00 PKT"`.
- The architecture (§5 `confirm_deal`, §9) requires the **pickup deadline to be checked in code**, and that isn't possible reliably with free text.
- **Fix:** use timezone-aware datetimes (Pydantic `AwareDatetime`). `pickup_window` can stay as human-readable text.

### 5. `DealBrief` is missing the staff-confirmed flag
- The approved plan (step 7) has the quantity "with its unit, **and whether staff confirmed it**". The architecture uses this to choose between the staff-confirmed amount and the low end of the photo estimate.
- **Fix:** add `quantity_confirmed_by_staff: bool` to `DealBrief` and `AgentDealBrief`. The agent can then say "about 40 kg" honestly when the amount wasn't confirmed.

### 6. No hard limit on Gemini usage
- The plan (step 9) said to try a quota override, or give console steps if that didn't work. The audit doesn't mention it. Architecture §7 requires **hard limits**, not just alerts.
- The only real limit today is a maximum of 2 instances per Cloud Run service. A budget alert doesn't stop spending.
- **Fix:** set a Vertex AI quota cap in the console if Gemini 3.8 supports per-project limits. If it doesn't, write that down and plan app-level limits for Module 2 (judge demo session cap, maximum call length).

---

## 🟠 Medium

### 7. Gaps in phone-number masking ([logging_utils.py](../shared/lastcall_shared/logging_utils.py))
- Only top-level string values in `extra_fields` are masked. A nested dict, such as `{"buyer": {"phone": ...}}`, is logged in full.
- Exception tracebacks aren't masked, and API errors (Twilio's, for example) often include the phone number.
- `json.dumps` has no `default=`, so logging a `datetime` in `extra_fields` raises an error inside the logger.

### 8. Uvicorn's own logs skip the JSON formatter
- Uvicorn's access and error loggers use their own handlers. Their output is plain text, not JSON, and **isn't masked**.
- This becomes a security problem in Module 2: the architecture puts a one-time secret per call in the Twilio audio stream URL, and access logs record every URL.
- **Fix in Module 2:** turn off the access log (`--no-access-log`) or route uvicorn's loggers through the formatter.

### 9. Terraform and the deploy script both control environment variables
- Terraform has `ignore_changes` on `template[0].containers[0].env`. Once a service exists, Terraform can no longer manage its environment variables or secret mounts, which breaks "infrastructure in Terraform".
- `deploy.sh` uses `--set-env-vars`, which **replaces** all plain environment variables on every deploy.
- Neither service gets the `GEMINI_*` model settings, and Module 2 will need them.
- **Fix:** let Terraform own `env` (remove it from `ignore_changes`) and have `deploy.sh` change only the image. The commit can go in the image tag or a label. Otherwise, at least switch to `--update-env-vars`.

### 10. Container builds can't be reproduced
- The Dockerfiles run `pip install` from the `pyproject.toml` ranges and ignore `uv.lock`. Each build pulls the newest `fastapi`, `uvicorn` and `google-adk`, so an ADK release could break the demo without any code change.
- The containers also run as root.
- **Fix:** install with `uv sync --frozen --package <service>` inside the Dockerfile, and add a non-root `USER`.

---

## 🟢 Low

11. **`.DS_Store` is committed** even though `.gitignore` excludes it. It needs `git rm --cached .DS_Store`.
12. **Some docs are out of date:**
    - The header of [module-0-foundations.md](module-0-foundations.md) still says `asia-southeast1` and "D1–D10".
    - The docstring in `scripts/region_check.py` still says "global endpoint" and "us-central1".
    - [region-check.md](../docs/region-check.md) has lost the `asia-southeast1` Live **failure** that led to D13. It also doesn't confirm that Firestore and Cloud Tasks are available in `europe-west1`, which Module 2 and later modules need.
    - The Terraform state bucket is in `asia-southeast1` while everything else is in `europe-west1`. That's harmless, but it should be written down.
13. **The agent sees the buyer's phone number.** `agent_view()` includes `buyer.phone`, which the Negotiator never needs. The architecture's §7 personal-data rules suggest not sending it to the model.
14. **The phone pattern catches too much.** It matches any number of 8 to 15 digits (IDs, timestamps). That's safe, because more gets masked rather than less, but it makes logs noisy.
15. **The test data uses a real store chain.** The fixtures say "Imtiaz Super Market Clifton". Fictional names avoid implying a partnership, in line with the module plan's rule against claiming existing deployments.

---

## What checks out

- Every architecture rule except "no hard limits" is in place for Module 0's scope: two services, scale to zero, at most 2 instances, secret not in Terraform state, signing key logged only as present or absent, `disable_on_destroy = false`, remote state.
- `agent_view()` leaves out the floor price, and a test checks the serialised JSON for it.
- Units must match (D4), the visible-issues list follows D5, and call outcomes follow D6, apart from item 3.
- The `/health` alias for Cloud Run's reserved `/healthz` path (D11) is a sensible fix.
- **Verified:** Cloud Build history shows recent builds succeeded.

## What I didn't re-check

- Zero `terraform plan` drift. I didn't run plan.
- Live `/health` responses, Gemini smoke results, and the budget amount. These come from the other agent's audit and weren't repeated.

## Side effect of this review

While investigating I briefly edited files and then reverted them all. `git status` is clean. A `uv sync` I ran removed the services' dependencies from the local `.venv`, which is git-ignored. To restore them, run `uv sync --all-packages`.
