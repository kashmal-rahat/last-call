# Last Call 🍌📞

**Last Call** is an autonomous inventory rescue and voice negotiation system for grocery marts in Pakistan. It identifies near-expiry produce batches using computer vision (Gemini Flash on Vertex AI) and negotiates bulk salvage deals directly with local commercial buyers via real-time conversational phone calls in Urdu (Gemini Live native audio on Vertex AI with Google Agent Development Kit).

---

## Architecture Overview

- **`services/api`**: REST service (FastAPI, Python 3.12) handling produce assessment, photo evaluation, deal brief preparation, and mart operations. Deployed to Google Cloud Run in `europe-west1`.
- **`services/voice`**: Real-time voice agent service (FastAPI, Python 3.12, `google-adk`) driving live Urdu negotiation sessions with buyers over WebSockets/SIP. Deployed to Google Cloud Run in `europe-west1`.
- **`shared/lastcall_shared`**: Pydantic v2 domain schemas (`FreshnessResult`, `DealBrief`, `CallResult`), strict unit/pricing validations (D4), security isolation (`agent_view()` isolating floor prices), and Cloud Logging with PII masking.
- **`infra/terraform`**: Infrastructure as Code with Terraform Google Provider `v8.5.0` backed by remote GCS bucket `gs://kayrox-last-call-tfstate`.

---

## Local Development & Setup

### Prerequisites
- macOS or Linux with Homebrew
- Python 3.12 managed via `uv`
- Terraform `>=1.16` (`hashicorp/tap/terraform`)
- Google Cloud SDK (`gcloud`)

### Quickstart
```bash
# Clone the repository
git clone https://github.com/kashmal-rahat/last-call.git
cd last-call

# Install tools (if not present)
brew install uv
uv python install 3.12

# Sync dependencies across the uv workspace (including dev tools and service members)
uv sync --all-packages

# Run tests
uv run pytest shared/tests
```

### Environment Configuration
Copy `.env.example` to `.env` and fill in necessary values:
```bash
cp .env.example .env
```

---

## Verification & Smoke Scripts

- **Region & Model Benchmark**:
  ```bash
  uv run python scripts/region_check.py
  ```
- **Gemini Vertex AI Smoke Test**:
  ```bash
  uv run python scripts/smoke_gemini.py
  ```
- **Export JSON Schemas**:
  ```bash
  uv run python scripts/export_schemas.py
  ```

---

## Deployments

Deploy services using Google Cloud Build and Cloud Run:
```bash
./scripts/deploy.sh api
./scripts/deploy.sh voice
```

Active service URLs:
- **API Service**: [https://api-cujkm3kt5q-ew.a.run.app/health](https://api-cujkm3kt5q-ew.a.run.app/health)
- **Voice Service**: [https://voice-cujkm3kt5q-ew.a.run.app/health](https://voice-cujkm3kt5q-ew.a.run.app/health)

---

## Module 1: Freshness Inspector

Module 1 turns raw grocery shelf photos into structured produce assessments using two-pass vision on Gemini 3.8 Flash (`gemini-3.8-flash` on Vertex AI `eu`). It determines produce stages, worst-piece conditions, bounding boxes, quantitative ranges, safety flags, and temporal changes across shelf inspections.

Interactive inspection is available on the deployed demo page at `/demo` under **"1 · Inspect a shelf"** (requires the demo access code).

Run inspector verification scripts (outputs and reports are written to `plans/module-1/results/`):
```bash
# Two-pass smoke test on sample shelf photos
uv run python scripts/smoke_inspector.py --zoom

# 12-call latency benchmark probe
uv run python scripts/latency_probe.py

# Comparative evaluation against ground-truth labels (needs data/shelf_photos/labels.csv)
uv run python scripts/eval_inspector.py --split dev --compare-zoom
```

---

## Module Status

| Module | Title | Status |
|---|---|---|
| **0** | **Foundations** | **Completed** |
| **2** | **Negotiator** | **Implemented and deployed** (pending native-speaker test) |
| **1** | **Freshness Inspector** | **Implemented and deployed** (eval pending labels & decay photos) |
| **3** | **Ladder** | **Planned** ([plan](plans/module-3/plan.md): Gemini writes produce profiles once, code decides) |
