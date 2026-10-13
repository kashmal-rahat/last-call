# Scripts

Run from the repository root with `uv run python scripts/<name>.py`. Scripts that call Google
(Gemini, Places, Firestore) need `gcloud auth application-default login` and a filled-in `.env`.

## Operations
| Script | What it does |
|---|---|
| `deploy.sh api\|voice` | Builds the image with Cloud Build and deploys it to Cloud Run. Environment variables and secrets are managed by Terraform, not here |
| `seed_demo.py` | Writes the demo mart document to Firestore |
| `produce_profiles.py` | Shows, warms, sets or deletes the stored produce profiles the Ladder uses |
| `export_schemas.py` | Regenerates `shared/schemas/*.json` from the Pydantic models (run after changing a model) |

## Evaluation (results in `plans/module-*/results/`)
| Script | What it measures |
|---|---|
| `eval_inspector.py` | Freshness Inspector accuracy against labelled shelf photos |
| `simulate_negotiations.py` | Negotiator against simulated buyers: price discipline, closing, tone |
| `recheck_sim_run.py` | Re-checks a saved simulation run offline (no Gemini calls) |
| `check_profiles.py` | Produce-profile consistency (single call versus 5-vote consensus) and cost |
| `check_scout.py` | The Scout end to end for several items and branches |

## One-off probes (kept as the record behind early design decisions)
| Script | Question it answered |
|---|---|
| `smoke_gemini.py`, `region_check.py` | Do Gemini Flash and Live work from our Vertex AI region (D12, D13)? |
| `latency_probe.py` | How fast is Gemini Flash for an inspection call? |
| `smoke_inspector.py` | Does the two-pass Inspector work on sample photos? |
| `probe_live_3_8.py` | What can Gemini Live do in Urdu through ADK (voices, latency, interruptions)? |
| `probe_places.py`, `probe_p1_p2.py` | How dense and reliable are Google Places results for buyers in Lahore? |
