# Module 0: Implementation Review

**Reviewed:** 2026-10-07, commit `04e4cb8`
**Re-reviewed:** 2026-10-07, commit `9ade52a` (critical issues only, see below)
**Scope:** documentation only. No code, Terraform or cloud resources were changed. Fixes need the user's approval, and Terraform changes need a reviewed `terraform plan`.

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
