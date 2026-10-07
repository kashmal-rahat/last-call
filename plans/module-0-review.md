# Module 0: Implementation Review

**Reviewed:** 2026-10-07, commit `04e4cb8`
**Re-reviewed:** 2026-10-07, commit `9ade52a` (critical issues only, see below)
**Scope:** documentation only. No code, Terraform or cloud resources were changed. Fixes need the user's approval, and Terraform changes need a reviewed `terraform plan`.

---

# Re-review at `9ade52a`: critical issues (fix before Module 2)

Checked: all code, Terraform, Dockerfiles, `deploy.sh`. `pytest` passes 15/15. Live `/health` was called on both services. `gcloud` couldn't be used (reauthentication failed), so IAM, Cloud Build history and Terraform drift were **not** checked.

### C1. The current code has never been deployed
- **Verified:** both `/health` endpoints return `"commit":"04e4cb8"`, not HEAD (`9ade52a`).
- What changed after that deploy:
  - Both Dockerfiles were rewritten to use `uv sync --frozen` and a non-root user. **Checked locally:** in a copy of the api build context, uv 0.6.5 installs `lastcall-api` from this `uv.lock` without errors. The image build itself hasn't been run.
  - `deploy.sh` now builds as `deployer-sa`, which relies on new bucket-level IAM.
  - The broad IAM grants were removed in `main.tf`.
- So Module 0's "done when: a basic app deploys" is **unverified for the current code**. It's also unknown whether `terraform apply` ran for the IAM change. If it didn't, the compute account still has `storage.admin` on the project, including the Terraform state.
- **Fix:**
  1. Optional: pin the uv image to the local version (`uv --version`) so local and container resolution match.
  2. 🛑 Run `terraform plan`, show the output to the user, then apply.
  3. Run `./scripts/deploy.sh api` and `./scripts/deploy.sh voice`.
  4. Confirm `/health` returns `commit` equal to `git rev-parse --short HEAD`, and that a second `terraform plan` shows no changes.

### C2. Donations and free animal feed can't be represented
- `DealBrief.opening_price_per_unit` and `floor_price_per_unit` are `gt=0`, and `CallResult` requires `agreed_price_per_unit > 0` for a deal.
- That rules out ladder steps 4 and 5 ("Donate", "sell **or give** as animal feed"). It also conflicts with the module plan's "no price for a charity", which Module 2's charity pitch needs.
- **Fix:**
  - Add `deal_type: Literal["sale", "donation"]` (default `sale`) to `DealBrief`, `AgentDealBrief` and `CallResult`.
  - `sale`: prices must be > 0, as today.
  - `donation`: opening, floor and agreed price must all be 0. A donation deal still needs a quantity and a pickup time.
  - Add tests, then regenerate `shared/schemas/`.

### C3. Terraform still ignores `env` on both Cloud Run services (first review's #9)
- `template[0].containers[0].env` is still in `ignore_changes`.
- In Module 2, any `GEMINI_*` variable or Twilio secret mount added in Terraform will be **silently dropped** from the running service, and `terraform plan` will still say "no changes".
- **Fix:**
  - Remove `env` from `ignore_changes`.
  - Define `GCP_PROJECT`, `ENVIRONMENT`, `GEMINI_FLASH_MODEL`, `GEMINI_FLASH_REGION`, `GEMINI_LIVE_MODEL` and `GEMINI_LIVE_REGION` in Terraform for both services.
  - In `deploy.sh`, set only the image and `GIT_COMMIT`. Note that `GIT_COMMIT` then needs to stay in `ignore_changes`, or go into a revision label or the image tag instead.

### C4. Business phone numbers aren't masked (a regression from fixing #14)
- The new `PHONE_PATTERN` matches only mobile numbers (`03xx…`) and numbers that start with `+`.
- It misses Pakistani landlines (`021 34567890`, `042-35761234`) and `923001234567` written without `+`. Buyers come from Places, and many of those businesses list landlines.
- Uvicorn's access log is also still plain text and unmasked (#8). Module 2 puts a one-time secret in the Twilio stream URL, so the access log would record it.
- **Fix:**
  - Extend the pattern to Pakistani landlines (`0` + 2–4 digit area code + 6–8 digits) and to `92` + mobile without `+`. Add tests for each format, plus a test that a plain ID or timestamp is **not** masked.
  - Add `--no-access-log` to the uvicorn command in both Dockerfiles.

### Not critical yet, but still open
- **#6, no hard limit on Gemini usage.** This must be in place before the public judge demo (Module 8).

## Status of the first review's items

| # | Item | Status |
|---|---|---|
| 1 | Fresh checkout can't run tests | ✅ Fixed (root `dev` group) |
| 2 | Service account permissions too broad | ✅ Fixed in code. ⚠️ Not confirmed as applied (C1) |
| 3 | `CallResult` outcome before completion | ✅ Fixed |
| 4 | Free-text deadlines | ✅ Fixed (`AwareDatetime`) |
| 5 | Staff-confirmed flag | ✅ Fixed |
| 6 | No hard Gemini limit | ❌ Open |
| 7 | Masking gaps (nested, tracebacks, datetime) | ✅ Fixed |
| 8 | Uvicorn logs unmasked | ❌ Open (C4) |
| 9 | Env vars owned by both Terraform and deploy script | 🟡 Partly fixed: `--update-env-vars` used, but `ignore_changes` is still on `env` (C3) |
| 10 | Container builds not reproducible, running as root | ✅ Fixed in code. ⚠️ Never built or deployed (C1) |
| 11 | `.DS_Store` committed | ✅ Fixed |
| 12 | Out-of-date docs | ✅ Mostly fixed |
| 13 | Agent sees the buyer's phone number | ✅ Fixed (`extra="forbid"` as well) |
| 14 | Phone pattern catches too much | ✅ Fixed, but now catches too little (C4) |
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
