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
- Module order so far: **0 (Foundations), then 2 (Negotiator)**. The user names the modules after that.
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
| D5 | 2026-10-06 | Visible issues: `bruising, browning, mould, rot, wilting, other` | Combines the architecture's and module plan's lists, which differed |
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
| D32 | 2026-10-09 | The Ladder is a Gemini agent (not code rules), making **one call per inspected item, run in parallel** (at most 4 at a time). Code still enforces the money and safety rules. Details in the Ladder module plan | What a freshness stage means depends on the produce, so hard-coded rules don't fit; per-item parallel calls keep latency flat as items grow and contain failures to one item |
| D33 | 2026-10-09 | No cap on batches per photo. In the judge demo, the Scout agent (with Places API) runs **only when the judge clicks "Find buyers"** for a batch, and the Negotiator only on "Call". In production, the Scout runs for every off-shelf batch through Cloud Tasks. The screen shows the 3 most actionable items first | Cost is controlled where it is spent (Scout and Negotiator), not by dropping produce; a fixed cap would leave rescuable stock unhandled |

## Module status

| Module | Plan | Status |
|---|---|---|
| 0: Foundations | [module-0/plan.md](module-0/plan.md) | Completed |
| 2: Negotiator | [module-2/plan.md](module-2/plan.md) | Implemented and deployed (2B). Pending: user's native-speaker test, then lower the demo limits |
