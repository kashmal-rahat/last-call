# Module 9: Phone demo through Twilio (for the demo video only)

Built directly by Claude at the user's request on 2026-10-13 (the user said "implement it carefully"). This file records what was built, the switch-on and switch-off steps, and the live checks.

## What it is (D61)
- **One phone call, to the presenter's own SIM, started from the real demo page,** so the video can show the phone ringing next to the live Urdu transcript and the result.
- **Judges only ever get the browser call.** The phone module is off by default and switched on with `gcloud` only while recording.
- **It's still a role-play:** the person answering is the presenter playing the shop. So D55 applies unchanged: no buyer history, no do-not-call entry, masked phone in the call record, 24 h expiry.
- **Not built (it stays in the design, for the deck):** scheduled calling (Cloud Tasks), calling hours, calling real buyers.

## How it is kept separate

| Part | New file | Change to existing files |
|---|---|---|
| `api` | `lastcall_api/phone_demo.py`: `GET /demo/phone/config`, `POST /demo/phone/dial`, `GET /demo/phone/calls/{id}` | `main.py`: one `include_router` block at the end. `/demo/calls` is unchanged |
| `voice` | `lastcall_voice/phone/audio.py` (mu-law 8 kHz ↔ PCM 16/24 kHz), `phone/bridge.py` (Twilio socket adapter) | `main.py`: one `/phone/stream` route. **`live_session.py` is unchanged** |
| store | — | `append_live_line` and `get_live_lines` added to the protocol and both stores. Lines live on the call doc, so they inherit its TTL |
| page | `static/js/phone.js` | `index.html`: a hidden switch in the buyers section and an id on the caller caption. `dom.js`: 3 lookups. `call.js`: one import and one 4-line hook in `startCallForItem`. `main.js`: one import and one `initPhoneDemo()` call. `demo.css`: the switch's style |

### Three locks keep judges on the browser call
1. **`PHONE_DEMO_ENABLED`** (default off). When it's off, every `/demo/phone/*` endpoint answers 404 and `/phone/stream` closes at once.
2. **`?phone=1` in the page address.** Without it the switch never shows and the page makes no phone request, even if the flag is left on.
3. **A fixed number.** The number to ring lives only in the `phone-demo-config` secret, never in a request. If someone triggered it, only your own SIM could ring.

### How a phone call runs
1. "Start call" creates the call through `/demo/calls`, exactly as today: same buyer, deal, price floor, daily cap and lock.
2. `phone.js` sends the call ID and its 120 s token to `/demo/phone/dial`. The API checks the token belongs to that call and that the call hasn't started, then asks Twilio to ring your SIM. Twilio rings for 30 s, with recording off.
3. When you answer, Twilio opens `wss://<voice>/phone/stream` and passes the token as a Stream `<Parameter>`.
4. The bridge hands the token to the unchanged call handler as the browser's auth message. It converts the audio both ways and passes interruptions to Twilio as `clear`.
5. Each transcript line is written to the call doc in order by one background writer. The page fetches new lines every second.
6. **Ending the call:**
   - If you hang up, Twilio sends `stop` and the handler finishes the call as on a browser hang-up.
   - If the AI ends the call, the bridge sends a `mark` and waits up to 5 s for Twilio to finish playing the goodbye, then closes; Twilio then ends the call.
7. The page shows the normal result card through the existing `pollBatchUntilCompleted`.

## Set up once (you, about 10 minutes)
1. **Twilio console:** Account → API keys → create a **Standard** key. Note its SID (`SK…`) and secret. Pakistan voice permission is already on (your test call worked).
2. **Create the secret from a file outside the repo**, so it never reaches git or your shell history. Write `~/phone-demo-config.json`:
   ```json
   {"account_sid": "AC…", "api_key_sid": "SK…", "api_key_secret": "…", "from_number": "+1…", "to_number": "+92…"}
   ```
   Both numbers must be in E.164 format. Then:
   ```bash
   gcloud secrets create phone-demo-config --data-file="$HOME/phone-demo-config.json" --project=kayrox-last-call
   ```
   ```bash
   gcloud secrets add-iam-policy-binding phone-demo-config --member="serviceAccount:api-sa@kayrox-last-call.iam.gserviceaccount.com" --role="roles/secretmanager.secretAccessor" --project=kayrox-last-call
   ```
   ```bash
   rm "$HOME/phone-demo-config.json"
   ```
3. **Commit, then deploy both services:** `./scripts/deploy.sh api` and `./scripts/deploy.sh voice`. The deploy doesn't touch environment variables, so the module is still off.

## Switch on (before recording)
```bash
gcloud run services update api --region=europe-west1 --project=kayrox-last-call --update-env-vars=PHONE_DEMO_ENABLED=true --update-secrets=PHONE_DEMO_CONFIG=phone-demo-config:latest
```
```bash
gcloud run services update voice --region=europe-west1 --project=kayrox-last-call --update-env-vars=PHONE_DEMO_ENABLED=true
```
Open `<api-url>/demo?phone=1`, tick **Ring my phone**, then **Start call**.

## Switch off (after recording)
```bash
gcloud run services update api --region=europe-west1 --project=kayrox-last-call --update-env-vars=PHONE_DEMO_ENABLED=false
```
```bash
gcloud run services update voice --region=europe-west1 --project=kayrox-last-call --update-env-vars=PHONE_DEMO_ENABLED=false
```
**Check:** `curl -s -o /dev/null -w "%{http_code}" <api-url>/demo/phone/config` must print `404`.

A later `terraform apply` drops these `gcloud`-set variables, which also leaves the module off (the safe direction).

## Checks
- **Local:**
  - `pytest` 386 passed, 20 skipped (new: `test_phone_demo.py` 9, `test_phone_bridge.py` 7, store contract `test_live_lines_for_phone_demo`); `node --test` 21 passed.
  - **The full call through the unchanged handler:** `test_phone_call_runs_through_the_unchanged_handler`. Twilio handshake, agent audio converted to mu-law, buyer hang-up, goodbye mark, call `completed`, transcript line saved.
  - **The page flow in the local preview with a fake Twilio:** the switch is hidden without `?phone=1`, then "Ringing your phone…", "Call answered", five live Urdu lines, "Call ended", then the normal "Deal agreed" card and "All stock placed".
  - **The judges' page:** the switch stays hidden, phone mode is off and no `/demo/phone/*` request is made.
  - **`git diff`:** `live_session.py` unchanged; every other existing file only gained lines.
- **Fixed on the way:** `test_orchestration.py::test_build_call_record` failed about 1 run in 30. It asserted "65" (the floor) was absent from the agent's view, but the random `call_id` sometimes contains "65". It now checks for `:65` (the floor as a value).
- **Not verifiable locally (check live):**
  - Real Twilio audio quality and delay over the Pakistan route.
  - How well Gemini hears Urdu over 8 kHz phone audio.
  - The live Firestore contract test (`RUN_FIRESTORE_TESTS=1`): it hung because the local Google login has expired. Run it after `gcloud auth application-default login`.

## Live check (you, while switched on)
1. `/demo` without `?phone=1`: no switch shows; a browser call works as before.
2. `/demo?phone=1`, switch ticked, Start call:
   - your SIM rings within a few seconds
   - after you answer, the AI greets you in Urdu
   - the transcript lines appear on the page
3. Interrupt the AI mid-sentence: it should stop talking.
4. Agree a deal:
   - the AI's goodbye is heard in full before the call drops
   - the result card shows the deal, and "Next buyer" or "All stock placed" works
5. Note the delay between you finishing a sentence and the AI answering, and whether it misheard anything. If it's poor, we tune it before recording takes.
6. Switch off, then check `/demo/phone/config` returns 404.
