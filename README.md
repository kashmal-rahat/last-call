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

Interactive inspection is available on the deployed demo page at `/demo` under **"1 · Inspect a shelf"** (requires the demo access code). To ensure consistent demonstration results when evaluating borderline produce photos multiple times, `/demo/inspect` caches complete inspection readings per exact image hash in Firestore (`inspector_readings/`, decision D45). Repeated inspections of the same photo reuse the stored Gemini reading while re-running deterministic safety guardrails, matching, and change tracking. All evaluation, benchmarking, and smoke scripts bypass this cache entirely to continue measuring raw Gemini model behavior.

Run inspector verification scripts (outputs and reports are written to `plans/module-1/results/`):
```bash
# Two-pass smoke test on sample shelf photos
uv run python scripts/smoke_inspector.py --zoom

# 12-call latency benchmark probe
uv run python scripts/latency_probe.py

# Comparative evaluation against ground-truth labels (needs data/shelf_photos/labels.csv)
uv run python scripts/eval_inspector.py --split dev --compare-zoom
```

## Module 3: Ladder

Module 3 decides what happens to each inspected item: `keep`, `discount`, `bulk_sale`, `donate`, `animal_feed`, or `compost`, with deterministic floor prices, buyer types, and auditable reasons. Following the design principle *"Gemini knows, code decides"*, Gemini Flash 3.8 writes structured produce profiles (shelf life and viable buyer uses per stage) once per produce type via 5-vote parallel consensus, stored in Firestore (`produce_knowledge/`). The clearance ladder engine itself is 100% deterministic pure code, enforcing strict safety bounds, monotonic freshness progression, and commercial price tiers.

Interactive decision ranking is available on the deployed demo page at `/demo` under **"1 · Inspect a shelf"** (after inspection, decisions update reactively with closing-time selection and manual price overrides).

### How decisions are made

The clearance ladder uses a deterministic timing schedule based on hours until closing ($H$), overnight hours ($O$, closing to opening), and the evening discount window ($W = 6\text{ h}$):
- **"Sells for" calculation:** The stored produce profile defines nominal shelf life from the *start* of a freshness stage (`under_6h`: 4 h, `6_to_24h`: 15 h, `1_to_3_days`: 48 h, `over_3_days`: 96 h). The Inspector's `stage_level` indicates progress within that stage; code scales the nominal band by a level factor (`early`: 1.0, `mid`: 0.7, `late`: 0.4) to estimate how much marketable time remains before decay to the next stage. Spoiled and unsafe produce have life = 0 (never kept or discounted).
- **Fresh & Ripening:** Ripe produce remains sound to sell, so it never leaves the shelf. If it still sells past tomorrow's opening ($H + O$), it is kept at full price. Otherwise, before the evening window ($H > W$), it is kept for now. Inside the evening window ($H \le W$), discounts start at 10% and deepen by +5% per hour towards closing (clamped at 40%), or jump directly to 40% if the produce stops selling before closing.
- **Overripe:** Sent to `bulk_sale` for commercial buyers (juice shops, bakeries, restaurants) if at least 2 hours remain for pickup ($H \ge 2\text{ h}$); otherwise discounted at 40% to clear before closing, falling back to donation.
- **Spoiled & Unsafe:** Evaluated for cattle feed if certified cattle-safe without mould or slime; otherwise directed to compost with manager approval.

Run Ladder profile inspection and verification scripts:
```bash
# Check profile variations (single-call vs 5-vote consensus)
uv run python scripts/check_profiles.py

# Manage stored produce profiles (warm, show, set, delete)
uv run python scripts/produce_profiles.py warm banana apple tomato cucumber guava
uv run python scripts/produce_profiles.py show banana
```

---

## Module Status

| Module | Title | Status |
|---|---|---|
| **0** | **Foundations** | **Completed** |
| **2** | **Negotiator** | **Implemented and deployed** (pending native-speaker test) |
| **1** | **Freshness Inspector** | **Implemented and deployed** (eval pending labels & decay photos) |
| **3** | **Ladder** | **Implemented and deployed** (consensus profiles + deterministic decision engine) |
