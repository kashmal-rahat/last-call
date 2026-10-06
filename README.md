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

# Sync dependencies across the uv workspace
uv sync

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

## Module Status

| Module | Title | Status |
|---|---|---|
| **0** | **Foundations** | **Completed** |
| **2** | **Negotiator** | Pending planning approval |
