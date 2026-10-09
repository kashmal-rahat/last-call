# Module 1: Freshness Inspector — Context

## 5 Key Design Rules
1. **Perception only via Gemini 3.8 Flash (`eu`)**: Inspects shelf photos into structured `InspectorOutput` with zero sampling parameters (D30: no temp/top_p/top_k/seed/candidate_count/penalties), `thinking_level="medium"`, and `media_resolution=HIGH`.
2. **Two-Pass Zoom Architecture (D29)**: Pass 1 scans the whole shelf; code selects doubtful groups (up to 6), crops them from full resolution, and pass 2 re-inspects them in parallel. Code merges findings; the worse `worst_stage` always wins.
3. **Worst Piece vs Typical Piece (D24)**: `stage` reflects the typical produce; `worst_stage` captures defects. Spoiled/unsafe worst pieces trigger `needs_staff_check` without condemning an entire crate to compost.
4. **Code Enforces Rules & Determinism**: Output schema has zero Field constraints or validators for Gemini compatibility. Code computes deterministic scores (0–100), clamps quantities, applies safety overrides (mould/rot), generates stable keys, and matches past photos.
5. **Strict Operational Budgets & Privacy**: 60s hard ceiling per inspection; max 12 groups per photo; no images, produce names, evidence, or notes in logs (only counts, stages, latency, tokens).

## Files to Create and Modify
- **Shared Models & Config**: Reshape `shared/lastcall_shared/models.py` to v3, update `shared/lastcall_shared/__init__.py`, update `scripts/export_schemas.py`, `shared/schemas/*.json`, `shared/tests/fixtures/valid_freshness.json`, `shared/tests/test_models.py`, `.gitignore`.
- **Inspector Service**: `services/api/pyproject.toml` (add `google-genai`, `pillow`, `python-multipart`), `services/api/lastcall_api/inspector/__init__.py`, `schema.py`, `system_prompt.md`, `prompt.py`, `images.py`, `guardrails.py`, `matching.py`, `zoom.py`, `inspector.py`, `eval_metrics.py`.
- **Tests & Scripts**: `services/api/tests/test_inspector_*.py`, `scripts/smoke_inspector.py`, `scripts/eval_inspector.py`.

## Blockers / Conflicts
- None. Requirements align with shared libraries, D1–D33 decisions, and Gemini 3.8 Flash Vertex API constraints.
