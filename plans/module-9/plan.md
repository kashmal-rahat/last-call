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
| `api` | `lastcall_api/phone_demo.py`: `PhoneDemoConfig` (validated secret), `GET /demo/phone/config`, `POST /demo/phone/dial`, `GET /demo/phone/calls/{id}` | `main.py`: one `include_router` block at the end. `/demo/calls` is unchanged |
| `voice` | `phone/audio.py` (mu-law 8 kHz ↔ PCM 16/24 kHz), `phone/bridge.py` (`TwilioStreamAdapter`), `call_socket.py` (the `CallSocket` protocol the handler needs) | `main.py`: one `/phone/stream` route. `live_session.py`: the parameter is typed `WebSocket \| CallSocket`, and a keyword `check_origin: bool = True` is added. The browser route doesn't pass it, so browser behaviour is unchanged (test `test_browser_route_still_checks_origin`) |
| shared | — | `Settings`: `PHONE_DEMO_ENABLED: bool = False` and `PHONE_DEMO_CONFIG: SecretStr \| None`. Store: `append_live_line` and `get_live_lines` (lines live on the call doc and inherit its TTL) |
| page | `static/js/phone.js` | `index.html`: a hidden switch in the buyers section and an id on the caller caption. `dom.js`: 3 lookups. `call.js`: one 4-line hook in `startCallForItem`. `main.js`: `initPhoneDemo()`. `demo.css`: the switch's style |
| Terraform | — | `variable "phone_demo_enabled"` (default false). Secret `phone-demo-config` (container only) plus read access for `api-sa`. `PHONE_DEMO_ENABLED` on both services. `PHONE_DEMO_CONFIG` attached to `api` only while enabled |

### Three locks keep judges on the browser call
1. **`phone_demo_enabled = false`** (the default). Every `/demo/phone/*` endpoint answers 404 and `/phone/stream` closes at once.
2. **`?phone=1` in the page address.** Without it the switch never shows and the page makes no phone request.
3. **A fixed number.** The number to ring lives only in the `phone-demo-config` secret, never in a request.

### How a phone call runs
1. "Start call" creates the call through `/demo/calls`, exactly as today: same buyer, deal, price floor, daily cap and lock.
2. `phone.js` sends the call ID and its 120 s token to `/demo/phone/dial`. The API checks the token belongs to that call and the call hasn't started, then asks Twilio to ring the SIM. Twilio rings for 30 s, with recording off.
3. When you answer, Twilio opens `wss://<voice>/phone/stream` with the token as a Stream `<Parameter>`.
4. `TwilioStreamAdapter` gives the token to the unchanged handler's auth step (`check_origin=False`, because Twilio sends no Origin header). It converts audio both ways and passes interruptions to Twilio as `clear`.
5. Transcript lines are written in order by one background writer; the page fetches them every second.
6. **Ending the call:** if you hang up, Twilio sends `stop`. If the AI ends it, the bridge waits up to 5 s for a `mark` so the goodbye plays, then closes, and Twilio ends the call.
7. The page shows the normal result card.

### Deliberately not built
- **Twilio status callbacks** (no-answer or failed): they would need a public webhook plus signature checking. The page treats "not answered within 75 s" as no answer.
- **Twilio request-signature validation:** it needs the main Auth Token, which we don't store. The single-use, 120 s, per-call token authenticates the stream.
- **Managing the Twilio API key in Terraform:** its secret would end up in Terraform state.
- **A new service account:** `api-sa` reads the secret; `voice` needs no new permission.
- **Scheduled calling, calling hours, calling real buyers:** production design, described in the deck.

## WhatsApp: item photo and deal confirmation (D62)
**What happens in a call:**
- **The buyer asks to see the produce:** the agent calls `send_photo`. It finds the batch's inspection and item, and checks the shelf photo was kept (`FreshnessResult.photo_stored`). It signs a 1-hour link to `/demo/item-photos/{inspection}/{item}.jpg`, which the api serves as a crop of just that item. If no photo was kept, the tool returns `ok=false` and the agent says so honestly.
- **A deal is confirmed:** `confirm_deal` also sends the buyer a WhatsApp confirmation (goods, price and total, pickup time in mart time, payment, address).
- **How it reaches the buyer:** both tools emit one `whatsapp` event through `CallContext.notify`.
  - **Browser call:** the page shows a "WhatsApp to buyer" message, so judges see it.
  - **Phone demo:** the bridge saves a live line for the page **and** sends a real WhatsApp message to the SIM through Twilio (`TwilioClient.send_whatsapp`, shared with the dialler).
- **Outbox:** both are recorded in the outbox with status `sent_in_call`. The browser's view of the photo and the WhatsApp delivery use the same signed link.

| Part | Files |
|---|---|
| shared | `item_photos.py` (signed links), `twilio.py` (`PhoneDemoConfig`, `TwilioClient`: calls and WhatsApp), `Settings.SHELF_PHOTO_BUCKET` / `API_PUBLIC_URL`, `FreshnessResult.photo_stored` |
| api | `item_photos.py` (`PhotoStore` on GCS or in memory, `save_shelf_photo`, `crop_item` reusing the Inspector's `crop_group`, the signed photo endpoint). `main.py`: saves the photo after each inspection (best effort) and mounts the router |
| voice | `negotiator/buyer_messages.py` (event, signed link, confirmation text), `tools.py` (`send_photo`, `confirm_deal`), `call_context.notify`, `live_session.py` passes `notify`, `phone/bridge.py` forwards to WhatsApp, one prompt line for `ok=false` |
| page | `call.js` `appendWhatsApp` (browser), `phone.js` (phone lines), `demo.css`, a `message` icon |
| Terraform | bucket `<project>-shelf-photos` (private, uniform access, public access blocked, 1-day delete), `api-sa` object create and read, `voice-sa` read on `phone-demo-config`, `SHELF_PHOTO_BUCKET` on api, `API_PUBLIC_URL` on voice, `PHONE_DEMO_CONFIG` on voice while the phone demo is on |

**WhatsApp setup for the phone demo (once):**
1. Twilio console → Messaging → Try it out → **Send a WhatsApp message**. Note the sandbox number (`+14155238886`) and your join code.
2. From your phone's WhatsApp, send `join <code>` to the sandbox number. The sandbox session lasts 3 days, and free-form messages need your message within the last 24 h, so **send any message to the sandbox shortly before recording**.
3. Add `"whatsapp_from": "+14155238886"` to the JSON and add it as a new version:
   ```bash
   gcloud secrets versions add phone-demo-config --data-file="$HOME/phone-demo-config.json" --project=kayrox-last-call
   ```
   Then delete the file. Without `whatsapp_from`, the page still shows the messages and only the real WhatsApp send is skipped.

## Switching on and off: Terraform
The secret value already exists (version 1+, created with `gcloud`). Once, bring the existing secret into Terraform state:
```bash
cd infra/terraform && terraform import google_secret_manager_secret.phone_demo_config projects/kayrox-last-call/secrets/phone-demo-config
```
**On (recording):**
```bash
terraform plan -var="phone_demo_enabled=true" -out=phone-on.tfplan
```
Review the plan, then:
```bash
terraform apply phone-on.tfplan
```
**Off (judging):**
```bash
terraform plan -out=phone-off.tfplan
```
Review the plan, then:
```bash
terraform apply phone-off.tfplan
```
**Check:** `curl -s -o /dev/null -w "%{http_code}" <api-url>/demo/phone/config` must print `404` when off.

**Changing the number:** `gcloud secrets versions add phone-demo-config --data-file=<file>`, then apply with the feature on. Each apply that changes the service creates a new revision, which reads `latest`. If nothing else changed, run `terraform apply -replace=google_cloud_run_v2_service.api` with the same `-var`.

## Checks
- **Local:**
  - (round 1) `pytest` 386 passed, 20 skipped (new: `test_phone_demo.py` 9, `test_phone_bridge.py` 7, store contract `test_live_lines_for_phone_demo`); `node --test` 21 passed.
  - **The full call through the unchanged handler:** `test_phone_call_runs_through_the_unchanged_handler`. Twilio handshake, agent audio converted to mu-law, buyer hang-up, goodbye mark, call `completed`, transcript line saved.
  - **The page flow in the local preview with a fake Twilio:** the switch is hidden without `?phone=1`, then "Ringing your phone…", "Call answered", five live Urdu lines, "Call ended", then the normal "Deal agreed" card and "All stock placed".
  - **The judges' page:** the switch stays hidden, phone mode is off and no `/demo/phone/*` request is made.
  - **`git diff`:** `live_session.py` unchanged; every other existing file only gained lines.
- **Fixed on the way:** `test_orchestration.py::test_build_call_record` failed about 1 run in 30. It asserted "65" (the floor) was absent from the agent's view, but the random `call_id` sometimes contains "65". It now checks for `:65` (the floor as a value).
- **Not verifiable locally (check live):**
  - Real Twilio audio quality and delay over the Pakistan route.
  - How well Gemini hears Urdu over 8 kHz phone audio.
  - The live Firestore contract test (`RUN_FIRESTORE_TESTS=1`): it hung because the local Google login has expired. Run it after `gcloud auth application-default login`.

### Round 2: refactor to production shape (2026-10-13)
- **Settings:** the flag and config moved into `Settings`. The config is now a validated pydantic model (`PhoneDemoConfig`, `extra="forbid"`, E.164 and Twilio ID patterns, the key secret held as `SecretStr`). Validation errors name the fields only and never echo the numbers or secret (test `test_config_errors_never_echo_numbers_or_secrets`).
- **Bridge:** the faked Origin header is gone, replaced by the explicit `check_origin=False` for `/phone/stream`. The duck typing with `# type: ignore` is replaced by the `CallSocket` protocol.
- **Terraform:** the switch moved from `gcloud` to Terraform: the variable, the secret container, `api-sa` read access, and the env vars on both services.
- **Checks:** `pytest` 388 passed, 20 skipped, on three runs; `node --test` 21 passed; `terraform fmt` and `validate` clean. `terraform plan` could not be run here (the local Google login has expired), so the user runs it and shows the output before any apply.

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
