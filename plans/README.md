# Plans

One plan per module. The agent writes a plan, the user approves it, and only then is it built. Any agent or model picking up this repo must read this file first.

## Source of truth

1. `docs/last-call-idea.md`
2. `docs/last-call-architecture.md`
3. `docs/last-call-module-plan.md`
4. The approved plan in `plans/module-N/plan.md` for the current module
5. The decision log below

If any of these conflict, **ask the user. Don't choose silently.**

## Working rules (from the user)

- Each module keeps its plan, review and results in `plans/module-N/`.
- Work on **one module at a time**: plan, wait for approval, then implement.
- After implementing, report **what works, what doesn't, and what couldn't be verified**.
- **Never plan or build the next module** until the user names it. Where a later module is needed, use a simple stand-in.
- Module order so far: **0 (Foundations), then 2 (Negotiator), then 1 (Freshness Inspector), then 3 (Ladder)**. The user names the modules after that.
- All Google Cloud resources are managed with **Terraform, kept in the repo**.
- **Never run `terraform apply` or `terraform destroy`** without first showing the plan output and getting approval.
- For anything that needs the user's login or the Cloud console, give exact steps and wait.
- Don't commit or push unless the user asks.

## Project facts

| Item | Value |
|---|---|
| Google account | kashmal@kayroxco.com |
| Project ID | `kayrox-last-call` |
| Billing account | `01C776-42EDFC-E7E33A` |
| Region | `europe-west1` (Belgium) |
| GitHub repo | `kashmal-rahat/last-call` |
| Budget | Created by the user in the console. **Not managed by Terraform** |

## Decision log

| # | Date | Decision | Why |
|---|---|---|---|
| D1 | 2026-10-06 | Module order is 0, then 2, not 0, 1, 2 as in the module plan | User's instruction. Module 2 uses a hand-written stand-in deal brief instead of Module 1 output |
| D2 | 2026-10-06 | Gemini through **Vertex AI**, using service accounts and no API keys | User's choice |
| D3 | 2026-10-06 | Region `asia-southeast1`, checked with real calls first. If a Gemini model is missing, ask the user before using the `global` endpoint or another region | User's choice |
| D4 | 2026-10-06 | Quantity and price units are **`kg` or `dozen`**, set per item. A price's unit must match its quantity's unit, checked in code | User's answer. The docs only mentioned kg |
| D5 | 2026-10-06 | Visible issues: `bruising, browning, mould, rot, wilting, other` (superseded by D25) | Combines the architecture's and module plan's lists, which differed |
| D6 | 2026-10-06 | Call **status** (`pending, in_progress, completed`) is kept separate from call **outcome** (`deal, partial_deal, declined, call_back, wants_photo, wants_manager, do_not_call, no_answer`) | The architecture listed 4 end states and the module plan listed 8 outcomes |
| D7 | 2026-10-06 | Python **3.12** for local work and containers, managed with `uv` | Still includes `audioop` for μ-law audio, which 3.13 removed |
| D8 | 2026-10-06 | Firestore is added in Module 2, not Module 0 | User agreed |
| D9 | 2026-10-06 | Module 0 test data is **folders and templates only**. The user supplies real photos and buyer notes | User's choice |
| D10 | 2026-10-06 | Budget alerts are created by the user in the console, not by Terraform | User already set them up |
| D11 | 2026-10-06 | Terraform Google Provider pinned to `~> 8.0` (`v8.5.0`), `google-adk` (`v2.11.0`) used for agents, and `/health` supported alongside `/healthz` to prevent GFE reserved-path 404s | User's feedback & Cloud Run GFE path discovery |
| D12 | 2026-10-06 | Standardize exclusively on `gemini-3.8-flash` and `gemini-3.8-live` | User's direction to use only the latest 3.8 models |
| D13 | 2026-10-06 | Standardize single regional infrastructure on `europe-west1` (Cloud Run, Artifact Registry, Secrets, future Firestore) and multi-region `eu` for both `gemini-3.8-flash` and `gemini-3.8-live` | User preference for closest single EU region to PK/SG, cutting Live latency (849ms connect vs ~3,000ms in US) and confirming europe-west1 offers Firestore |
| D14 | 2026-10-07 | An inspection is one photo (`inspection_id`, `shelf_id`). A batch is one off-shelf item from one inspection, created by Decide and holding `inspection_id` and `item_key`. | Separates photo inspection lifecycle from discrete item clearance lifecycles (mangoes vs spinach on same shelf), allowing independent pricing, locks, and temporal produce comparison across shelf photos |
| D15 | 2026-10-07 | `voice` `min_instances` is a Terraform variable, default 0. Set to 1 only for judging windows | Avoid idle container billing during normal development |
| D16 | 2026-10-07 | Build billing kill switch with `SIMULATE_DEACTIVATION=true`. Terraform owns topic, function and IAM. User links budget in console | Automated cost safety backstop without accidental disruption |
| D17 | 2026-10-07 | Demo page protected by Secret Manager access code, global daily session cap, and 5-minute call cap | Spend guardrails for public demo |
| D18 | 2026-10-07 | All Negotiator tools are BLOCKING. Model only ever sees `agent_view()`, and every price comes from `verify_offer` | Hard zero-floor-breach guarantee and zero price leakage |
| D19 | 2026-10-07 | `api` serves demo page at `/demo`. Page talks to `voice` over WebSocket authenticated by short-lived HMAC token in first message | Secure voice session handoff without tokens in request URLs |
| D20 | 2026-10-07 | WhatsApp and photo sends are stubs written to `outbox`. Do-not-call entries are written in Module 2 and enforced by Scout in Module 4 | Clear module boundaries |
| D21 | 2026-10-09 | Kill switch armed: SIMULATE_DEACTIVATION=false, KILL_RATIO=1.0 (fires at the $50 budget). Testing limits: daily cap 50, IP 20/h, to be lowered after testing. | Production safety hardening per user review |
| D22 | 2026-10-09 | The Inspector is one `google-genai` `generate_content` call with a response schema on `gemini-3.8-flash` (Vertex `eu`), not ADK | One photo in, one JSON out; ADK adds a Runner and sessions for nothing here |
| D23 | 2026-10-09 | Generic inspector with produce **families** in the prompt only (Appendix A). No per-item catalogue, and code never branches on produce type | User's choice; uses the model's own produce knowledge |
| D24 | 2026-10-09 | `ItemAssessment` v3: `stage` is the typical piece, `worst_stage` the worst piece; `score` is computed in code from `stage` + `stage_level`; `confidence` is high/medium/low mapped to a number in code | Repeatable scores; one bad piece doesn't compost a whole display |
| D25 | 2026-10-09 | `ProduceIssue` is extended to the 13 visible issues in Appendix A (supersedes D5) | Finer signs for the evidence and the eval |
| D26 | 2026-10-09 | Code, not the model, owns `item_key`, matching with the previous photo, `change_since_last`, staff-check reasons and safety overrides | "Agents decide, code enforces"; avoids anchoring on old scores |
| D27 | 2026-10-09 | Module 1 doesn't store photos: `photo_uri = "upload:sha256:<hex>"`. The bucket and signed uploads come in Module 8 | No Terraform change in Module 1 |
| D28 | 2026-10-09 | Results go to `inspections/{inspection_id}`, with a pointer `shelves/{mart_id}__{shelf_id}` → `latest_inspection_id`. Inspection states are added in Module 6 | Previous-photo lookup without a composite index |
| D29 | 2026-10-09 | Two passes: pass 1 reads the whole shelf; code picks doubtful groups (at most 6), crops them from the full-resolution photo, and pass 2 reads each crop in parallel. Code merges, and the worse `worst_stage` always wins | A shelf shot gets only 1120 image tokens, so small mould or rot is missed. Clear photos of sound stock still take one call |
| D30 | 2026-10-09 | No sampling parameters (`temperature`, `top_p`, `top_k`, `seed`, `candidate_count`, penalties) in any Gemini call. `media_resolution=high` and `thinking_level=low` always (measured: medium was 3–5× slower with no better readings) | Deprecated and ignored on 3.6+, an error on future models; Google's determinism advice is explicit system instructions |
| D31 | 2026-10-09 | Quantity is the photo estimate as a range (counts taken from close-ups when zoomed). Staff can edit it, and the final weight is settled at pickup. No ERP in the prototype | An exact count from one photo isn't reliable (hidden layers, piece weight varies); a range plus confirmation is honest and enough for the demo |
| D32 | 2026-10-09 | **Superseded by D38.** The Ladder is a Gemini agent (not code rules), making **one call per inspected item, run in parallel** (at most 4 at a time). Code still enforces the money and safety rules. Details in the Ladder module plan | What a freshness stage means depends on the produce, so hard-coded rules don't fit; per-item parallel calls keep latency flat as items grow and contain failures to one item |
| D33 | 2026-10-09 | No cap on batches per photo. In the judge demo, the Scout agent (with Places API) runs **only when the judge clicks "Find buyers"** for a batch, and the Negotiator only on "Call". In production, the Scout runs for every off-shelf batch through Cloud Tasks. The screen shows the 3 most actionable items first | Cost is controlled where it is spent (Scout and Negotiator), not by dropping produce; a fixed cap would leave rescuable stock unhandled |
| D34 | 2026-10-10 | merge_neighbours. Code merges neighbouring groups of the same produce (same name, boxes touching or within 30 on the 0–1000 scale; never "unknown produce" or mixed crates) | Gemini returned 2–5 groups for the same photo across 12 identical calls; one group per display prevents duplicate batches |
| D35 | 2026-10-10 | Zoom only for doubtful groups whose box covers ≤ 40% of the photo (MAX_ZOOM_BOX_AREA = 0.40) | Every image gets a fixed 1,120 tokens at media_resolution=high, so a crop of a large group adds little detail; full-frame photos now take one call (~4 s) |
| D36 | 2026-10-10 | Hedged requests. If a Gemini call hasn't answered after 12 s (HEDGE_AFTER_S), start one identical second request and take whichever succeeds first; 30 s per attempt, 3 attempts, 60 s total budget per inspection | Occasional Vertex slow responses (38–60 s seen once) while typical calls are p50 6.7 s, p90 10.8 s, max 12.1 s (plans/module-1/results/latency.md) |
| D37 | 2026-10-10 | At most 2 inspections at once per api instance (asyncio.Semaphore) and one shared Firestore client | Default Cloud Run memory is 512 MB and a full-size phone photo needs ~150–200 MB while processing; avoids crashes without a Terraform change |
| D38 | 2026-10-10 | No per-item decision agent (supersedes D32). Gemini writes a **produce profile** once per produce (shelf-life band and buyer uses per stage) with a direct structured `google-genai` call (not ADK), stored in `produce_knowledge` and shared by all marts; **the Ladder decision is pure code** | Consistent (same input → same decision), generic (any produce, no hand-written catalogue), simple, and cheap at scale |
| D39 | 2026-10-10 | Allowed ladder steps come only from the Inspector's `stage` and `issues` in code; the profile only chooses among them | A wrong profile can't send spoiled food to people or mouldy food to animals; cattle suitability defaults to "no" when unsure |
| D40 | 2026-10-10 | Profiles are checked in code before saving and never expire. Gemini profiles are keyed `{produce}__v{N}` (a prompt fix regenerates them); a manager's fix is keyed `{produce}__manager`, looked up first and never overwritten | Mistakes are rare, visible, contained to one produce, and fixed once |
| D41 | 2026-10-10 | Ladder prices are percentages of the shelf price from mart rules (a demo price list in the prototype). A missing price or unit mismatch means `needs_price`, entered by the user in the demo | Money never depends on a model guess; in production prices come from the POS |
| D42 | 2026-10-10 | Ladder decisions are saved as one `LadderResult` in `decisions/{inspection_id}`, overwritten on re-decide. No batches until Module 6 | Keeps `FreshnessResult` v3 untouched |
| D43 | 2026-10-10 | A new produce profile is the consensus of 5 Gemini answers sent in parallel, merged in code (majority for uses, median for shelf life, 4 of 5 for cattle). It stores the vote count and uncertain fields; fewer than 3 answers → fallback profile | Raw answers varied for 9 of 12 produce between runs; voting makes the stored answer stable and shows the manager where to check. Gemini's consensus is accepted as the answer; the manager can overwrite it |

## Module status

| Module | Plan | Status |
|---|---|---|
| 0: Foundations | [module-0/plan.md](module-0/plan.md) | Completed |
| 2: Negotiator | [module-2/plan.md](module-2/plan.md) | Implemented and deployed (2B). Pending: user's native-speaker test, then lower the demo limits |
| 1: Freshness Inspector | [module-1/plan.md](module-1/plan.md) | Implemented and deployed (cleanup 2026-10-10). Pending: eval once labels and home decay photos arrive. |
| 3: Ladder | [module-3/plan.md](module-3/plan.md) | Implemented and deployed (3B, 2026-10-10) |
