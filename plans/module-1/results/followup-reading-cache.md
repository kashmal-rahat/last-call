# Module 1 Follow-up F1: Same Photo → Same Reading Cache (D45) Results

Implemented and deployed on **2026-10-10**.

## 1. Summary of Changes
- **Store Protocol & Implementations:**
  - Added `get_reading(key: str) -> dict[str, Any] | None` and `create_reading(key: str, data: dict[str, Any]) -> bool` (create-if-absent) to `CallStore` protocol, `InMemoryStore` (deep-copying), and `FirestoreStore` (`inspector_readings` collection).
  - Added `inspector_readings` to Firestore `clean_prefix` collections.
- **Inspector Reading Cache:**
  - Added `READING_CACHE_VERSION = "1"` and `reading_key(image_sha256, *, model, prompt_version, thinking_level, zoom, bin_capacity_kg)`.
  - Added optional `reading_cache: ReadingCache | None = None` kwarg to `inspect_photo`.
  - On cache hit: skips Gemini pass 1 and pass 2, rehydrates `InspectorOutput` and `zoom_results`, zeroes out call and token counts, sets `from_cache = True`, while deterministically re-evaluating `apply_guardrails`, `assign_keys` (preserving change notes), and freshness scoring.
  - On cache miss: executes pass 1 and pass 2 as before. Only complete readings (`zoom_failures == 0` and not skipped for time budget) are stored via `create_reading`.
  - Added `from_cache: bool = False` to `InspectorMeta` model and regenerated JSON schemas in `shared/schemas/`.
  - Structured logs record `from_cache` without ever logging image hashes, cache keys, or produce names.
- **Demo & Scripts:**
  - `/demo/inspect` passes `reading_cache=store` to `inspect_photo`.
  - Evaluation scripts (`eval_inspector.py`, `smoke_inspector.py`, `latency_probe.py`) remain completely unchanged and bypass the cache with default `reading_cache=None`.
  - `/demo` UI inspect footer displays `"Same photo as before: stored reading reused (no new Gemini call)"` when `meta.from_cache` is `true`.

---

## 2. Test Verification (`pytest`)

### Local & Contract Tests
- **Full Test Suite (`uv run pytest`)**:
  - **275 passed**, 9 skipped, 0 failed in 17.55s.
  - All existing Module 1, 2, and 3 unit and integration tests passed without changes.
  - All 9 new cache tests in `services/api/tests/test_inspector_cache.py` passed:
    1. Same image twice with cache: first makes Gemini calls; second makes 0 calls, `from_cache=True`, with identical stages, worst stages, issues, quantities, and staff-check reasons.
    2. Different image results in cache miss.
    3. Differing parameters (`bin_capacity_kg`, `zoom`, `prompt_version`) result in cache miss.
    4. Zoom failure on first run does not cache; second run calls Gemini again.
    5. Corrupted cache entry falls back to miss gracefully without crashing.
    6. Cache exceptions (`get_reading` or `create_reading` raising) fall back to normal inspection without failing.
    7. `previous` inspection correctly applies on cache hit (`previous_inspection_id` set, change note computed).
    8. Default `reading_cache` is `None` with zero caching behaviour.
    9. `/demo/inspect` passes `reading_cache=store`.

- **Live Firestore Contract Tests (`RUN_FIRESTORE_TESTS=1 uv run pytest shared/tests/test_store.py`)**:
  - **20 passed**, 0 failed in 170.15s.
  - Verified `test_readings_lifecycle` against live Google Cloud Firestore (`kayrox-last-call`).

---

## 3. Deployment & Live Verification

- **Deployed Revision**: `api-00023-mhs`
- **Git Commit**: `4341382`
- **Service URL**: `https://api-cujkm3kt5q-ew.a.run.app`
- **Health Check**:
  ```json
  {"service":"api","version":"0.1.0","commit":"4341382","status":"healthy"}
  ```

### Two-Click Live Test on Deployed `/demo` (Sample: "Bananas & Apples (Shelf B)")
1. **First Click (Cold / Fresh Inspection)**:
   - Backend Latency: `8,340 ms` (2 Gemini Flash calls: pass 1 + pass 2 crop zoom)
   - `from_cache`: `false`
   - Detected Items:
     - `apple`: stage `fresh`, worst_stage `fresh`
     - `banana`: stage `overripe`, worst_stage `overripe`
2. **Second Click (Cached Inspection)**:
   - Backend Latency: `56 ms` (0 Gemini calls, 0 token spend)
   - `from_cache`: `true`
   - Detected Items:
     - `apple`: stage `fresh`, worst_stage `fresh` (Identical)
     - `banana`: stage `overripe`, worst_stage `overripe` (Identical)
   - Change Indicator: `no change since [previous_id]`
   - Footer Message: `"Same photo as before: stored reading reused (no new Gemini call)"`
3. **Closing-Time Selector & Ladder Re-decision**:
   - Switched closing time on the cached inspection: Ladder decisions dynamically re-evaluated across both produce items (`apple` kept, `banana` bulk sale at Rs 110/dozen) instantly on top of the cached reading.
4. **New Unseen Photo**:
   - Uploaded a newly generated image: cache miss (`from_cache: false`, Gemini Flash called normally).
5. **Firestore Storage**:
   - Confirmed documents created in `inspector_readings`: e.g. `r_0fa2ade5b041feb1a8d29bccaed686b2f2fa1819d01aef1fe50f3c68fbde3545`, `r_cff24f1178ab7eff956b6a1f8d422fbe5769d20492715f55bfcd5ac693e843dd`.

---

## 4. What Works, What Doesn't, What Couldn't Be Verified
- **What Works:**
  - Deterministic repeatability on borderline demo sample photos.
  - Sub-100ms response time on repeated inspections.
  - Recomputed temporal change notes and Ladder decisions without re-calling vision models.
  - Complete error isolation (any Firestore read/write failure falls back to standard Gemini inspection).
  - Scripts and evals remain clean and isolated from caching.
- **What Doesn't:**
  - N/A.
- **What Couldn't Be Verified:**
  - Real-time Firestore document expiration (per plan D45, readings do not have an automated TTL policy as prompt changes bump keys automatically).
