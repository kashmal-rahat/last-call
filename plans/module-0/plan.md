# Module 0: Foundations (final, approved plan)

> Read [plans/README.md](README.md) first: it has the working rules, project facts and decision log (D1–D13).

**Done when:** we've confirmed `europe-west1` has the services we need, a basic app is running on Cloud Run with its infrastructure managed by Terraform, Gemini on Vertex AI is proven to work from the project, and the three shared formats are defined and tested.

## Inputs

| Item | Value |
|---|---|
| Account | kashmal@kayroxco.com |
| Project ID | `kayrox-last-call` |
| Billing account | `01C776-42EDFC-E7E33A` |
| Region | `europe-west1` (regional services), `eu` (Vertex AI multi-region) |
| Budget | Already created by the user in the console. **Don't create it in Terraform** |

Starting state of this Mac (2026-10-06): Homebrew and Node are installed. `gcloud`, `terraform`, `uv` and Docker are missing, and Python is only 3.9.6. The git repo has a remote but no commits yet.

---

## Implementation steps (in order)

The steps marked 🛑 are stop points: wait for the user before going on.

### Step 1: Install local tools

- `brew install uv`
- `brew install --cask google-cloud-sdk`
- `brew tap hashicorp/tap && brew install hashicorp/tap/terraform` (Homebrew's own Terraform is outdated)
- `uv python install 3.12`
- Docker isn't needed, because Cloud Build builds the images.

### Step 2: 🛑 User login and manual checks

Give the user these commands to run themselves (they open a browser login):

```
gcloud auth login                      # as kashmal@kayroxco.com
gcloud config set project kayrox-last-call
gcloud auth application-default login
gcloud auth application-default set-quota-project kayrox-last-call
```

Then run these read-only checks:
- `gcloud projects describe kayrox-last-call` confirms the project exists and the user is Owner. If the project doesn't exist yet, give the user steps to create it.
- `gcloud billing projects describe kayrox-last-call` shows `billingEnabled: true` with account `01C776-42EDFC-E7E33A`.
- Org policy check: Cloud Run needs `allUsers` as invoker because both services are public. Check whether `iam.allowedPolicyMemberDomains` (domain restricted sharing) applies to the project. If it does, give the user the console steps to add an exception for this project, and wait.
- `gcloud billing budgets list --billing-account=01C776-42EDFC-E7E33A` confirms the user's budget exists. This only reads it; Terraform doesn't manage it.

Also give the user steps to turn on **GitHub secret scanning and push protection**: `kashmal-rahat/last-call` → Settings → Code security.

### Step 3: Terraform state bucket

Show this command, get approval, then run it:

```
gcloud storage buckets create gs://kayrox-last-call-tfstate \
  --project=kayrox-last-call --location=asia-southeast1 \
  --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://kayrox-last-call-tfstate --versioning
```

### Step 4: Terraform, first apply (APIs only)

`infra/terraform/` uses the GCS backend (`kayrox-last-call-tfstate`, prefix `main`). The first version contains only `google_project_service` resources for:

`run`, `cloudbuild`, `artifactregistry`, `secretmanager`, `aiplatform`, `iam`, `iamcredentials`, `logging`, `cloudtrace`, `serviceusage`, `cloudresourcemanager`

Set `disable_on_destroy = false`.

🛑 Show the `terraform plan` output, get approval, then apply.

### Step 5: Region check

Write `scripts/region_check.py` (Python 3.12, `google-genai` SDK with `vertexai=True`, `location="asia-southeast1"`, using the user's login credentials). It checks:

1. **Gemini Flash**: one text call, one image call, and one call with structured output against a small Pydantic schema
2. **Gemini Live native audio**: open a Live session, send a short Urdu text turn, and confirm an audio or text reply comes back
3. **Other services**: confirm `asia-southeast1` is supported for Cloud Run, Cloud Tasks, Firestore, Cloud Storage, Artifact Registry, Secret Manager and BigQuery, using `gcloud` location lists where possible and the docs otherwise. Firebase Hosting and Places API are global.

Look up the current model IDs in the Vertex AI docs at the time of implementation; don't guess them. Keep model IDs in config (`.env` / env vars), not hard-coded.

Save the results, including model IDs, latency and pass/fail, to `plans/module-0/results/region-check.md`.

🛑 If any Gemini model fails in `asia-southeast1`, stop and ask the user whether to use the `global` endpoint for that model or switch region.

### Step 6: Repo scaffolding

```
last-call/
├── docs/                      # existing concept docs
├── plans/module-0/results/    # region-check.md
├── plans/                     # plans + README (decision log)
├── infra/terraform/
├── shared/lastcall_shared/    # shared formats (Pydantic v2)
├── services/api/              # FastAPI, Dockerfile
├── services/voice/            # FastAPI, Dockerfile
├── scripts/                   # region_check.py, smoke_gemini.py, deploy.sh
├── data/shelf_photos/         # README.md (photo guide) + labels.csv (headers only)
├── data/buyer_notes/          # TEMPLATE.md
├── .env.example, .gitignore, README.md
```

- Use a `uv` workspace so `shared` is a local dependency of both services. The Dockerfiles copy `shared/` into the image, so the build context is the repo root.
- `.gitignore` covers `.env`, `.venv`, `__pycache__`, `.terraform/`, `*.tfstate*` and `*.tfvars` (but not `*.tfvars.example`).
- The README covers what the project is, setup steps, how to deploy, and a module status table.

### Step 7: Shared formats (`shared/lastcall_shared/`)

These are Pydantic v2 models. Every model includes `schema_version` and, where relevant, `mart_id` and `batch_id`. Currency is PKR.

- `Unit = Literal["kg", "dozen"]` (D4)
- `QuantityEstimate {unit, low, high}`, where `low ≤ high` and both are ≥ 0
- `ConfirmedQuantity {unit, value, confirmed_by_staff: bool}`
- **`ItemAssessment`** has:
  - `name` and `position` (a normalised bounding box from 0 to 1)
  - `stage`: one of `fresh | ripening | overripe | spoiled | unsafe`
  - `score` from 0 to 100, and `change_since_last` (points, nullable) with a short `change_note`
  - `issues`: a list of D5 values
  - `quantity: QuantityEstimate`
  - `confidence` from 0 to 1, and `needs_staff_check`
- **`FreshnessResult`** has `mart_id`, `batch_id`, `photo_uri`, `taken_at`, `items: list[ItemAssessment]`, and `photo_issues` (for example blurry or no produce).
- **`DealBrief`** has:
  - `mart_id`, `batch_id`, `call_id`
  - `item`, `condition`, and `quantity` (confirmed or the low end of the estimate) with its unit
  - `buyer {name, type, phone}`, where type is one of `juice_shop | restaurant | bakery | charity | dairy_farm | other`
  - `opening_price_per_unit` and **`floor_price_per_unit`**, both in the quantity's unit, with opening ≥ floor (validated)
  - `pickup_window` and `pickup_deadline`, plus `mart {name, location}`
  - `payment_terms`, `language` (default `ur`) and `calling_hours`
  - **`agent_view()`** returns everything except `floor_price_per_unit`
- **`CallResult`** has:
  - `call_id`, `batch_id`, `mart_id`
  - `status` and `outcome` (D6)
  - `agreed_price_per_unit`, `agreed_quantity` with its unit, and `pickup_time`
  - `transcript: list[{speaker, text, at}]` and `summary`
  - `flags`, for example `floor_correction`
  - Validation: `deal` and `partial_deal` require a price, quantity and pickup time
- Export JSON Schemas to `shared/schemas/*.json` with a script.
- Example data lives in `shared/tests/fixtures/`.
- **Tests** (`pytest`) must cover:
  - valid and invalid examples for each model
  - the floor price never appearing anywhere in `agent_view()`, including its serialised JSON
  - a price unit that doesn't match the quantity unit being rejected
  - a deal without terms being rejected

### Step 8: Service skeletons

- `services/api` and `services/voice`: FastAPI on Python 3.12, with `GET /healthz` returning `{service, version, commit}`. Nothing public spends money.
- Shared helper: structured JSON logs (compatible with Cloud Logging) and a function that masks phone numbers in logs.
- `api` reads the `APP_SIGNING_KEY` environment variable (mounted from Secret Manager) and only logs whether it's present. It never logs the value.

### Step 9: Terraform, second apply (everything else)

| Resource | Details |
|---|---|
| Artifact Registry | Docker repository `last-call` in `asia-southeast1` |
| Service accounts | `api-sa` and `voice-sa`, each with `roles/aiplatform.user`, `logging.logWriter`, `cloudtrace.agent`, and secret accessor **only on their own secrets**. Plus `deployer-sa` for Cloud Build, with Run admin, Artifact Registry writer, and actAs on the two runtime service accounts. **No keys are created** |
| Secret Manager | Secret `app-signing-key` (container only, so the value never goes into state). `api-sa` can read it |
| Cloud Run `api` | Public (`allUsers` invoker). Scales to zero, CPU only during requests, **maximum 2 instances**. Secret mounted as an environment variable |
| Cloud Run `voice` | Public. **Minimum 0, maximum 2** for now. Module 2 changes it to one warm instance, CPU always on, session affinity and a long timeout |
| Image | Both services start from a public placeholder image. `lifecycle { ignore_changes = [template[0].containers[0].image] }` so deploys don't fight Terraform |
| Gemini quota cap | Try `google_service_usage_consumer_quota_override` for Vertex AI generate-content requests per minute. If that doesn't work, give the user console steps and note it in the report |

🛑 Show the `terraform plan` output, get approval, then apply.

Then 🛑 give the user the command to add the secret value:

```
openssl rand -base64 32 | gcloud secrets versions add app-signing-key --data-file=-
```

### Step 10: Deploy and verify

- `scripts/deploy.sh <api|voice>` builds with Cloud Build from the repo root, pushes to Artifact Registry, and runs `gcloud run deploy --image ...` using the service's runtime service account.
- `scripts/smoke_gemini.py` repeats the Flash and Live checks using the models in config.

## How I'll check it works

- [x] `plans/module-0/results/region-check.md` shows every service passing, or the user has decided on a fallback
- [x] `terraform plan` shows no changes after the second apply (zero drift confirmed)
- [x] `curl <api-url>/health` and `curl <voice-url>/health` both return 200
- [x] The `api` logs show the signing key is present, without ever showing its value
- [x] The user's budget exists (checked read-only, $50/mo limit verified)
- [x] `scripts/smoke_gemini.py` passes for both Flash and Live (on `eu` multi-region)
- [x] `uv run pytest shared/` passes (12/12 domain tests passing)
- [x] The README and the module status table in `plans/README.md` are updated

## Plan Compliance & Implementation Audit

| Step | Requirement in Plan | Audit Status | Evidence / Verification |
|---|---|:---:|---|
| **Step 1: Tools** | Python 3.12, `uv`, Terraform (`hashicorp/tap`), `gcloud` | **PASSED** | Python 3.12.15, `uv` 0.12.23, Terraform v1.16.4, Google provider `v8.5.0`, `gcloud` 587.0.0. |
| **Step 2: Checks & Policies** | Project ownership, billing active, Org policy override, budget check | **PASSED** | Project `kayrox-last-call`, billing `01C776-42EDFC-E7E33A`, `iam.allowedPolicyMemberDomains` overridden to `allValues: ALLOW`, read-only budget check confirmed `$50/month`. |
| **Step 3: State Bucket** | `gs://kayrox-last-call-tfstate` with versioning, UBLA, and PAP | **PASSED** | State bucket configured as remote backend in `versions.tf`. Remote state locking functioning. |
| **Step 4: APIs** | 11 core GCP APIs enabled via Terraform (`disable_on_destroy = false`) | **PASSED** | `run`, `cloudbuild`, `artifactregistry`, `secretmanager`, `aiplatform`, `iam`, `iamcredentials`, `logging`, `cloudtrace`, `serviceusage`, `cloudresourcemanager` all active in project. |
| **Step 5: Region & Models** | Vertex AI models probe & documentation in `results/region-check.md` | **PASSED** | Standardized on `europe-west1` and `eu` multi-region (Decision D13). Flash and Live probes passing. Verified in `plans/module-0/results/region-check.md`. |
| **Step 6: Repo Scaffolding** | `uv` workspace, data templates, `.env.example`, `.gitignore`, root `README.md` | **PASSED** | `pyproject.toml` workspace, `data/shelf_photos/labels.csv`, `data/buyer_notes/TEMPLATE.md`, `.gitignore` strictly ignores secrets/state. `uv.lock` validated. |
| **Step 7: Shared Domain** | Pydantic v2 models, strict units (D4), issues list (D5), status vs outcome (D6), `agent_view()` floor isolation | **PASSED** | `shared/lastcall_shared/models.py`, JSON schemas in `shared/schemas/`, fixtures in `shared/tests/fixtures/`, 12/12 unit tests passing in pytest. |
| **Step 8: Service Skeletons** | FastAPI on Python 3.12, `/health` and `/healthz`, structured JSON logging with PII phone masking | **PASSED** | `services/api/main.py` and `services/voice/main.py`. `APP_SIGNING_KEY` presence logged securely without secret leakage. |
| **Step 9: Terraform Apply** | Single region `europe-west1` for Cloud Run, AR, SAs, Secrets | **PASSED** | Artifact Registry `europe-west1-docker.pkg.dev/kayrox-last-call/last-call`, `api` & `voice` Cloud Run services with max instances = 2, `deletion_protection = false`. |
| **Step 10: Deploy & Smoke** | Automated build & deploy via `scripts/deploy.sh` | **PASSED** | Both containers built via Cloud Build and serving in `europe-west1`. Live health probes return HTTP 200. Zero drift in `terraform plan`. |

### Verified Endpoints & Verification Details
- **API Health**: `https://api-cujkm3kt5q-ew.a.run.app/health` -> `{"service":"api","version":"0.1.0","commit":"6a80a9d","status":"healthy"}`
- **Voice Health**: `https://voice-cujkm3kt5q-ew.a.run.app/health` -> `{"service":"voice","version":"0.1.0","commit":"6a80a9d","status":"healthy"}`
- **Gemini Live & Flash Probes**: `gemini-3.8-flash` (vision + structured output) and `gemini-3.8-live` (Urdu audio) passing in `location="eu"`.
- **Cloud Run Log Verification**: Verified `app_signing_key_present: true` in Cloud Logging jsonPayload for `serviceContext.service="api"`.
- **Terraform Drift**: Confirmed `Plan: 0 to add, 0 to change, 0 to destroy` (`No changes. Your infrastructure matches the configuration`).

## Final report to the user

Module 0 is completed, verified, and locked. **Don't start Module 2** until the user says so.

## Not in Module 0

Firestore (Module 2), Cloud Tasks, photo storage buckets, Firebase Hosting, Auth and App Check, Places API, Twilio and BigQuery. Each is added through Terraform in the module that first needs it.
