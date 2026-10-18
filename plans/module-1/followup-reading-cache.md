# Module 1 follow-up F1: same photo → same reading (D45)

> Planned 2026-10-10. Each step is planned and reviewed first, then implemented with Gemini Flash in Antigravity. Follow the steps in order and stop at the 🛑.
> **Read first:** `plans/README.md` (rules, D1–D45), `plans/module-1/plan.md` Step 4 (the two-pass pipeline), `services/api/lastcall_api/inspector/inspector.py`, `shared/lastcall_shared/store.py`, `shared/lastcall_shared/firestore_store.py`, `services/api/lastcall_api/main.py` (`/demo/inspect`).

## Context
Gemini isn't fully deterministic (we can't set temperature, D30), so inspecting the **same photo twice** can give different stages for borderline produce. In manual testing, the "Bananas & Apples" sample read ripening (mid) once and overripe (mid) another time. The Ladder then gives a different decision, so a judge clicking the same sample twice sees the system change its mind.

**Fix:** remember the Inspector's reading for each exact photo. If the same file is inspected again, reuse the stored reading instead of asking Gemini again. Everything after the reading (safety rules, scores, matching with the previous photo, change notes) still runs, and it's deterministic.

**What it is not:** a way to hide variation. Real shelf photos are never byte-identical, so every new photo still gets a fresh Gemini reading. The Module 1 consistency eval must keep measuring raw Gemini behaviour, so **the cache is only used by `/demo/inspect`, never by the scripts**.

**Cost:**
- **new photo:** one extra Firestore read (~10–30 ms) and one write (~10–30 ms) on top of a 5–15 s inspection. The SHA-256 of the photo is already computed today.
- **repeated photo:** ~0.1 s, no Gemini cost, identical reading.

## Decision (add to `plans/README.md`)
| # | Decision | Why |
|---|---|---|
| D45 | The demo endpoint caches the Inspector's **reading** per exact photo in `inspector_readings/{key}`. The key is a hash of: the prepared image's SHA-256, model, prompt version, thinking level, zoom on/off, bin capacity, and `READING_CACHE_VERSION`. A repeated photo reuses the reading; guardrails, keys and change notes are recomputed. Only complete readings are stored (no zoom failure, zoom not skipped for time). Scripts and evals never use the cache | The same photo must give the same answer in the demo, with no effect on new photos and no change to the measured consistency |

## Step 1: Store (`shared/lastcall_shared/store.py`, `firestore_store.py`)
Add to the `CallStore` protocol, `InMemoryStore` and `FirestoreStore` (collection `inspector_readings`, doc id = `key`). Data is a plain `dict`, because `shared/` can't import the inspector's schema:
- `get_reading(key: str) -> dict | None`
- `create_reading(key: str, data: dict) -> bool`: create-if-absent (Firestore `doc_ref.create()`, `AlreadyExists` → `False`), so the first stored reading for a photo always wins
- Add `inspector_readings` to `clean_prefix`.
- Contract tests in `shared/tests/test_store.py`: create then get; a second create doesn't overwrite; an unknown key → `None`. Run them live (`RUN_FIRESTORE_TESTS=1`).

## Step 2: Inspector (`services/api/lastcall_api/inspector/inspector.py`)
**Constants and key:**
```python
READING_CACHE_VERSION = "1"   # bump whenever code that runs BEFORE the cache point changes:
                              # clean_item, merge_neighbours, select_for_zoom, merge_zoom, crop_group,
                              # prepare_image or the Gemini schema

def reading_key(image_sha256: str, *, model: str, prompt_version: str, thinking_level: str,
                zoom: bool, bin_capacity_kg: float | None) -> str
    # sha256 of the canonical string
    # f"{image_sha256}|{model}|{prompt_version}|{thinking_level}|{int(zoom)}|{bin_capacity_kg or ''}|{READING_CACHE_VERSION}"
    # returns f"r_{hexdigest}"
```
**What is cached (the "reading"):** the state right before `apply_guardrails`:
```python
{
  "output": final_output.model_dump(mode="json"),   # InspectorOutput after clean/merge/zoom-merge
  "zoom": {"<idx>": {"reasons": [...], "zoomed": true}},   # zoom_results, idx as string
  "zoomed_groups": int,
  "created_at": iso8601
}
```
**`inspect_photo` changes** (all other behaviour unchanged):
- New keyword argument `reading_cache: ReadingCache | None = None`. `ReadingCache` is a small `Protocol` with `get_reading` and `create_reading`, which `CallStore` satisfies. The default `None` means exactly today's behaviour.
- After `prepare_image`, if `reading_cache` is set: compute the key and try `get_reading`.
  - **Hit:** validate with `InspectorOutput.model_validate(data["output"])`, rebuild `zoom_results` (int keys), and skip both Gemini passes. Any exception while reading or validating → log a warning (error type only) and treat it as a miss. A broken cache entry must never fail an inspection.
  - **Miss:** run pass 1 and pass 2 exactly as today.
- **Store only complete readings, after a miss:** `zoom_failures == 0`, and zoom wasn't skipped because of the time budget. Track that case with a new local flag `zoom_skipped_for_time`, set when zoom is enabled, the photo is `ok`, and fewer than 10 s were left. Then `create_reading(...)` inside `try/except Exception`: log a warning on failure and still return the result. Don't store when `reading_cache` is `None`.
- Then `apply_guardrails`, `assign_keys` (with the **current** `previous`, so change notes are correct for the shelf) and `FreshnessResult` exactly as today. Every request still gets a new `inspection_id` and `taken_at`.
- **`InspectorMeta`:** add `from_cache: bool = False` (`shared/lastcall_shared/models.py`; keep `schema_version` 3.0.0, since this is an optional field). On a hit: `from_cache=True`, `calls=0`, `hedges=0`, tokens 0, `zoomed_groups` from the stored reading, `zoom_failures=0`, and the real (small) `latency_ms`. Regenerate `shared/schemas/`.
- **Log:** add `from_cache` to the existing `photo_inspected` log. Never log the key or any reading content.

## Step 3: Endpoint and page
- `/demo/inspect` passes `reading_cache=store` to the inspect function. The access code, IP limit and daily cap stay exactly as they are and still count every request.
- **Scripts must not use the cache:** `scripts/smoke_inspector.py`, `scripts/eval_inspector.py` and `scripts/latency_probe.py` call `inspect_photo` without `reading_cache`. Leave them unchanged, and add a test that `inspect_photo`'s default is `None`.
- **Demo page footer:** when `inspector.from_cache` is true, show "Same photo as before: stored reading reused (no new Gemini call)" in place of the Gemini call count. Use `textContent`.

## Step 4: Tests (`services/api/tests/test_inspector.py` or a new `test_inspector_cache.py`, fake client and `InMemoryStore`)
1. The same image twice with a cache: the first makes Gemini calls and stores a reading; the second makes **0 calls**, `from_cache=True`, and has identical stages, worst stages, issues, quantities and staff-check reasons.
2. A different image → a new reading (calls > 0).
3. The same image with a different `bin_capacity_kg`, zoom setting or prompt version → a miss.
4. A zoom failure on the first run → nothing stored; the second run calls Gemini again.
5. A corrupted stored entry (invalid `output`) → treated as a miss; the inspection succeeds.
6. `get_reading` or `create_reading` raising → the inspection still succeeds.
7. `previous` is applied on a cache hit: inspect A on shelf X, then the same A on shelf X again → the second result has `previous_inspection_id` set and a change note ("no change since …").
8. Without `reading_cache` (the default), behaviour is exactly today's: existing tests unchanged, and two calls make two sets of Gemini calls.
9. `/demo/inspect` passes the store as `reading_cache` (test with a fake `inspect_fn` that records its kwargs).

## Step 5: 🛑 Verify, deploy, docs
1. `uv run pytest` green, with every existing Module 1, 2 and 3 test unchanged; the live Firestore contract tests are green.
2. Deploy from a **clean, committed** tree (ask the user to commit first), so `/health` shows the real commit.
3. On the deployed `/demo`:
   - inspect "Bananas & Apples" twice → the second footer shows the stored-reading message, the stages are identical, and the time is under ~1 s;
   - switch the closing-time selector → the Ladder works on the cached reading;
   - a new phone photo → a normal Gemini inspection;
   - Firestore has `inspector_readings/r_…` docs.
4. Docs:
   - `plans/README.md`: D45 is already added; set the Module 1 status to mention F1.
   - `README.md` Module 1 section: one paragraph on the reading cache, saying it's demo-only and evals bypass it.
   - Architecture §4 and §6: already updated by the reviewer; check they match what was built.
5. 🛑 Report in `plans/module-1/results/followup-reading-cache.md`: what works, what doesn't, what couldn't be verified; pytest summary; the deployed revision; the two-click timing and identical-stage check.

## Not in this follow-up
- Voting on the Inspector's stage (several readings per photo). Deferred until the Module 1 consistency eval shows it's needed.
- An expiry time for readings. They are small, contain no photo, and a prompt or code change creates new keys anyway.

## Switch (D63, 2026-10-14)
- `INSPECTOR_READING_CACHE` (default `true`) turns the cache off for `/demo/inspect`, so the same photo is read fresh each time. It is set by the Terraform variable `inspector_reading_cache` on `api`.
- Off only while re-testing photos; **on for judging**, so a repeated sample gives the same answer.
- Test: `test_10_demo_inspect_without_cache_when_switched_off`.
