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

| Service | Region | Status |
|---|---|---|
| Cloud Run (`api` & `voice`) | `europe-west1` | Deployed & Active (HTTP 200) |
| Artifact Registry (`last-call`) | `europe-west1` | Active |
| Secret Manager (`app-signing-key`) | `europe-west1` / Global | Active |
| Cloud Storage (`kayrox-last-call-tfstate`) | `asia-southeast1` | Active (Remote Backend) |