# Model & Region Verification Report

**Date:** 2026-10-06 21:16:38 UTC  
**GCP Project:** `kayrox-last-call`  

## 1. Selected Gemini Models (Vertex AI Live Probes)

| Model | Capability / Turn | Location Endpoint | Status | Latency | Details |
|---|---|---|---|---|---|
| `gemini-3.8-flash` | Text Turn (Urdu) | `eu` | PASS | 5683.1 ms | Assalam-o-Alaikum. Plump with smooth, vibrant golden-red skin. |
| `gemini-3.8-flash` | Image Vision Turn | `eu` | PASS | 1915.9 ms | Output: "Green" |
| `gemini-3.8-flash` | Structured Output | `eu` | PASS | 3822.9 ms | Valid JSON schema parsed |
| `gemini-3.8-live` | Bidirectional Native Audio | `eu` | PASS | Connect: 1579.3ms, Total: 5889.8ms | Native Audio received: 182880 bytes |

## 2. Infrastructure Services in `europe-west1`

| Service | Region | Status | Notes |
|---|---|---|---|
| Cloud Run (`api` & `voice`) | `europe-west1` | Deployed & Active (HTTP 200) | Public ingress enabled |
| Artifact Registry (`last-call`) | `europe-west1` | Active | Docker repo |
| Secret Manager (`app-signing-key`) | `europe-west1` / Global | Active | Secret version 1 provisioned |
| Cloud Storage (`kayrox-last-call-tfstate`) | `asia-southeast1` | Active (Remote Backend) | Pre-existing state bucket retained to avoid state migration risk |
| Firestore (Native) | `europe-west1` | Confirmed Available | Verified offered in `europe-west1` for Module 2 |
| Cloud Tasks | `europe-west1` | Confirmed Available | Standard regional support for Module 2 |

## 3. Region Selection History (Decision D13)

- **Initial Check (`asia-southeast1`)**: Probe for `gemini-3.8-live` failed in `asia-southeast1` because Gemini Live native audio bidirectional streaming is only deployed on Vertex AI multi-region endpoints (`eu` and `us`).
- **Endpoint Comparison**:
  - `us-central1`: Live connect latency ~2,959 ms.
  - `eu`: Live connect latency ~849 - 1,579 ms (significant reduction for users connecting from Pakistan / South Asia).
- **Consolidation**: Rather than maintaining a fragmented multi-region architecture (services in Singapore, models in US/EU), all regional infrastructure was consolidated into `europe-west1` (Belgium) paired with Vertex AI `eu` multi-region. Firestore and Cloud Tasks are both supported in `europe-west1`.