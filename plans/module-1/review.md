# Module 1 review

## Follow-up F1: same-photo reading cache (D45), before deploy (2026-10-10)

Method: read-only review of the uncommitted diff against `plans/module-1/followup-reading-cache.md`. I didn't run the tests; use the agent's pytest and live Firestore output for that.

**Verdict: correct and limited to the right files. Approve: commit, then deploy.**

### Files changed: all relevant
| File | Change | Expected? |
|---|---|---|
| `services/api/lastcall_api/inspector/inspector.py` | `READING_CACHE_VERSION`, `ReadingCache` protocol, `reading_key()`, optional `reading_cache` argument, hit/miss branches, `from_cache` in meta and log | ✅ |
| `shared/lastcall_shared/store.py`, `firestore_store.py` | `get_reading`, `create_reading` (create-if-absent), `inspector_readings` in `clean_prefix`; the in-memory store deep-copies | ✅ |
| `shared/lastcall_shared/models.py` + `shared/schemas/InspectorMeta.json`, `FreshnessResult.json` | `InspectorMeta.from_cache: bool = False`, schemas regenerated | ✅ |
| `services/api/lastcall_api/main.py` | `/demo/inspect` passes `reading_cache=store` | ✅ (see F1-1) |
| `services/api/lastcall_api/static/index.html` | footer message when `from_cache` | ✅ |
| `shared/tests/test_store.py`, new `services/api/tests/test_inspector_cache.py` | readings contract test; the 9 planned tests | ✅ |
| `docs/last-call-architecture.md`, `plans/README.md`, `plans/module-1/followup-reading-cache.md` | the reviewer's planning edits (D45) | ✅ |

**Not touched, as required:** `scripts/` (smoke, eval and latency probe never get the cache), and the existing `test_inspector.py` and `test_demo_inspect.py`. Nothing in Modules 2 or 3 changed.

### Checked in the code
- The key covers the prepared image's SHA-256, model, prompt version, thinking level, zoom on/off, bin capacity and `READING_CACHE_VERSION`.
- A hit skips both Gemini passes and rebuilds `zoom_results`. `apply_guardrails` and `assign_keys` still run with the current `previous`, so change notes stay correct.
- **Only complete readings are stored:** not after a zoom failure, and not when zoom was skipped for time (a new `zoom_skipped_for_time` flag).
- Every cache error (read, validate, write) is logged by error type only and falls back to a normal inspection.
- The non-cache path is the same logic as before. Most of the 269-line diff is the existing pass-1/pass-2 block re-indented under `if not from_cache:`; the zoom condition was split into two nested `if`s with the same meaning.
- Logs add only `from_cache`; no key and no reading content.

### Notes (not blocking)
- **F1-1.** `main.py` decides whether to pass `reading_cache` by inspecting the function's signature (`inspect.signature`), so the old test fakes without that argument keep working. It works, but it's indirect: if the parameter were ever renamed, the cache would silently switch off in the demo. A later clean-up could always pass `reading_cache=store` and give the test fakes `**kwargs`. `test_9` already confirms the real path passes the store.
- **F1-2.** No test covers "zoom skipped for time → not stored". The code path is simple and mirrors the zoom-failure case (test 4); add a test in a later pass.
- **F1-3.** `get_genai_client()` is still called on a cache hit. It's cached with `lru_cache`, so it costs nothing; no change needed.

### Before and after deploy
1. Confirm the agent's `uv run pytest` and live Firestore contract run are green (the plan's stop point).
2. **Commit**, then let the agent deploy, so `/health` shows the real commit.
3. On the deployed `/demo`:
   - inspect "Bananas & Apples" twice → the second shows "stored reading reused", identical stages, and under ~1 s;
   - the closing-time selector works on it;
   - a new photo is inspected normally.
