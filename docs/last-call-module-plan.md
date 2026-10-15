# 🛠️ Last Call — Module Plan

> 🧩 Module plan for the idea above. Focus first on **Module 1 (Freshness Inspector)** and **Module 2 (Negotiator)**. For technical details, the Architecture page is the reference.

## Module 0: Foundations

- Google Cloud project, Gemini access, repo, basic deploy to Cloud Run
- Secrets in Secret Manager, budget alert on the project
- Shared formats passed between modules: freshness result, deal brief, call result
- Test data: shelf photos of produce at different stages, and notes from buyer conversations on how they bargain
- **Done when:** a basic app deploys, and every module agrees on the shared formats

## Module 1: Freshness Inspector (focus)

**Input:** one shelf photo with several items, plus the previous result for the same shelf (if any).

**Output, per item:**

- Item name and position in the photo
- Freshness stage (fresh, ripening, overripe, spoiled, unsafe) and a 0–100 score
- Change since the last photo (for example, "dropped 20 points since morning")
- Visible issues (bruising, browning, mould, wilting)
- Estimated quantity as a range: counting for large items, fill level for small ones
- Confidence, and whether staff should check

**Build steps**

1. Clear definitions of each freshness stage, with general signs plus specific signs for tested items
2. Structured output in a fixed format
3. Edge cases: no produce in the photo, blurry photo, mixed items in one crate, several crates of the same item
4. Optional bin capacity input to improve quantity estimates

**Testing**

- Labelled set of about 50 photos: tested items at every stage, plus 10–15 untested items
- Track: stage accuracy (target 80% or better), never calling spoiled produce fresh, low confidence on hard cases, the same result when a photo is run twice
- A repeatable test script to rerun after every prompt change; results double as a slide for judges

**Done when:** a shelf photo returns sensible results for every item quickly, meets the accuracy target, and honestly flags unclear or unknown items.

## Module 2: Negotiator (focus, the hero)

**Input: deal brief**

- Item, condition, quantity (confirmed by staff, or the low end of the photo estimate, rounded down as people say it; D71)
- Buyer name and type (juice shop, restaurant, charity, dairy farm)
- Opening price per kg and floor price (kept in code, never given to the agent)
- Pickup window and pickup deadline, mart name and location
- Payment terms (for example, cash on pickup)
- Language
- Calling hours from the manager's rules

**Output: call result**

- Outcome: deal, partial deal, declined, call back later, wants a photo, wants the manager, do not call again, no answer
- Agreed price per kg, approximate quantity, pickup time
- Transcript and short summary

**Call flow**

1. **Introduce** as the mart's AI assistant
2. **Pitch** what, how much, what condition, and why it suits this buyer
3. **Negotiate:** start above the floor; a few concessions, each smaller than the last; give reasons; price per kg, final weight settled at pickup; flexible on quantity
4. **Handle objections:** price, quality doubts, smaller quantity, pickup timing, "who is this?", "call later", not interested
5. **Confirm** by repeating price, quantity, pickup time and payment terms, stating the pickup deadline and why (otherwise the stock goes to another buyer), and getting a clear yes
6. **Close politely,** deal or not, then send a WhatsApp confirmation for deals

**Situations to handle**

- **"Send me a photo first":** send the shelf photo on WhatsApp, then continue or call back
- **"Let me talk to the manager":** record the request so the manager calls back
- **"Don't call me again":** add to a do-not-call list the Scout respects
- **Partial deal:** the remaining quantity goes back for the next buyer; stop calling once everything is sold
- **Language switch:** follow the buyer if they answer in Punjabi or English
- **Voicemail, no answer, dropped call:** record it, then retry later or move on
- **Long calls:** cap call length, and stay within Gemini Live session limits

**Key design decisions**

- **Floor price enforced in code:** every price the agent proposes or accepts passes through a check that rejects anything below the floor
- **Pitch tailored to buyer type:** juice quality for a juice shop, cheap daily feed for a dairy farm, no price for a charity
- **Tool calls during the call:** check an offer, record the outcome, schedule a callback, send a photo, send a confirmation

**Language and tone**

- Everyday market vocabulary and phrases in the instructions (for example "aakhri rate", "munasib daam", per-crate and per-kg talk), so it doesn't sound like a news reader
- Friendly and respectful, but firm on price
- Handles Urdu, English and Punjabi mixed in the same sentence
- Tested with native speakers who actually bargain, not only the team

**Build order**

1. Text-only version to get the behaviour right
2. Urdu voice in the browser (also the deployed-link version)

**Testing**

- Role-play eight buyer personas: easy yes, hard bargainer pushing below the floor, quality sceptic, wants half the quantity, "call me tomorrow", rude or not interested, "send me a photo first", "let me speak to the manager"
- Automated test: Gemini plays the buyer in text across about 50 negotiations. Track floor breaches (must be zero), deal rate, and whether every deal is confirmed back.

**Done when:** across all personas the agent never breaks the floor, always confirms deals, sounds natural in Urdu, and handles every situation above without getting stuck.

## Module 3: Ladder ("Gemini knows, code decides")

Plan: [plans/module-3/plan.md](../plans/module-3/plan.md) (D38–D42).

- **Input:** freshness result, hours until closing, the mart's rules and shelf prices, and a produce profile for each item
- **Produce profile:** written by Gemini the first time a produce is seen (shelf-life band and which buyers can use it, per stage), as the consensus of 5 parallel answers merged in code, stored and shared by every mart, with uncertain fields flagged and fixable by the manager. A direct structured Gemini call, not an ADK agent
- **Decision:** pure code, so the same input always gives the same decision: keep, discount, bulk sale, donate, animal feed or compost, with prices, buyer types, next steps, staff actions and a reason built from the facts
- **Output:** shelf or off-shelf, discount, which off-shelf steps apply, opening and floor price, and a reason for each
- Items kept on the shelf are re-checked at the next photo
- **Code guardrails:** allowed steps come from the inspector's stage and issues (mould or slime means compost); low confidence means staff check before off-shelf steps; discount and price kept within the manager's limits; compost needs approval
- **Fallback:** a generic, cautious profile if Gemini can't write one
- **Future (documented, not built):** manager "Correct this" on a decision; the next photo and call outcomes refine profiles

## Module 4: Scout ("Google finds, Gemini screens, code decides")

Plan: [plans/module-4/plan.md](../plans/module-4/plan.md) (D46–D51).

- **Input:** what to find buyers for (from the Ladder decision in the demo, or a next step such as donate in Module 6): the step, buyer types and buyer condition, plus the chosen branch and the mart's rules
- **Output:** up to 5 ranked buyers with name, type, phone number (E.164, masked on screen), distance, open now, and a reason each
- **Search:** one Google Places search per buyer type (at most 3): Nearby Search (nearest first) for juice shops, restaurants and bakeries, Text Search for charities ("dastarkhwan") and dairy farms; phone and hours in the same request and a strict field mask
- **Code filters:** skips businesses that aren't operating, are too far away, have no phone number, are on the do-not-call list (by place ID or by a hash of the phone), share a phone with a nearer listing, or were called in the last 24 h without a deal
- **Gemini screening:** one structured call rates each remaining business likely, possible or unlikely for this produce and deal (e.g. drops national chains and milk shops listed as "dairy"); it judges only the specific business (the Ladder already chose the kinds of buyer), only reorders and drops, never bypasses a filter, and the card shows what it screened out and why
- **Ranking:** past successful buyers first, then open or hours unknown before closed now (closed buyers are kept, so the list isn't empty at night; phone calls in Module 9 skip them at call time, the browser demo only notes it, D56), then fit, then distance
- **Cost:** no cross-batch cache (Places policy allows storing only place IDs); every new batch searches fresh (new shops appear the same day); the per-batch list is reused for 1 h (one freshness rule); buyer history and do-not-call are kept; at most about $0.11 per Find buyers; demo cap 200 Places requests a day (sized so it never blocks judging)
- **Judge demo:** a Find buyers button on off-shelf decision cards, with real business names, masked phones and "Google Maps" attribution; a branch selector (3 Lahore branches: Johar Town by default, Bahria Town, Gulberg) shows that the buyers really come from the chosen location (locked once calls start; New shelf starts over, D58); never dials
- **Later:** the manager's buyer-list review ("review every list" or "only new buyers") comes with Module 5; the Call handoff with Module 6 (done in its plan, D53–D57)

## Module 5: Manager rules and screen

- **Rules:** maximum automatic discount, floor price per item type, calling hours, which actions need approval, buyer-list review setting, "always confirm quantity" setting (off by default)
- **Screen:**
    - Shelf photo with freshness results
    - Suggested actions and approvals for exceptions
    - Buyer list review
    - Live call transcript
    - Discounted price and printable discount tag
    - Staff tasks (compost, "please check this item," quantity checks, manager callbacks)
    - End-of-day summary

## Module 6: Orchestration and the Call handoff

Plan: [plans/module-6/plan.md](../plans/module-6/plan.md) (D53–D57).

- Connects everything in the judge demo: photo → freshness → ladder → scout → negotiator → result → next buyer → next step
- **One pure function decides what happens next** (`next_action`: call the next buyer, busy, search again, next step, compost approval, no buyer, sold). In the prototype the judge's clicks call it; from Module 9, Cloud Tasks calls the same function for phone calls (D53)
- **Batches** are created when calling starts, keyed like the Scout's list (`{inspection_id}__{item_key}__{branch_id}`), with a snapshot of the step plans (each step's buyer types, opening and floor) and the quantity (D54)
- **Escalation:** one call per buyer, at most 5 calls per ladder step, then the next step (e.g. bulk sale → charities → cattle farms); compost needs approval
- **Handoff:** the deal brief takes the item and condition from the decision, the prices from the step plan, the buyer from the Scout, the branch as the mart, and payment terms, calling hours and the Lahore city style from the mart rules
- Locks a batch during a call and **always releases it when the call ends**, so after a partial deal the remaining stock goes to the next buyer at once
- Fixes first: `create_call` no longer resets `remaining_quantity`
- **A role-play never changes a real business's records:** no buyer history or do-not-call entry from browser calls, masked phones only, call records kept 24 h (D55)
- **Judge demo:** quantity field, "Staff checked" when on hold, **Start calling** (#1) or **Play this buyer**, a status chip per called buyer, then **Next buyer** / **Next step**. Calling hours and closed buyers are shown as notes, not enforced; pickup follows the mart's real hours (D56). The old practice-scenario section is removed (D57)
- **Later:** pickup follow-up (collected, actual weight, no-show back on the ladder) and waiting for quantity checks, buyer list review and calling hours come with real phone calls (Module 9) and the manager screen (Module 5)

## Module 7: Data and learning

- Logs every photo result, decision, call, deal and pickup
- Records actual weight and amount paid, not just the agreed deal, so impact numbers are real
- Feeds back into the system: pricing stats in Firestore (which buyers said yes, at what price, and which discounts worked) inform the Ladder's prices; BigQuery is for reporting
- Powers the daily summary and impact numbers (kg saved, money recovered)

## Module 8: Judge demo experience (UI redesign)

Plan: [plans/module-8/plan.md](../plans/module-8/plan.md) (D59). Design: [design/stitch/](../design/stitch/) (desktop and mobile, one `DESIGN.md`).

- One responsive, light, premium page in six sections: Shelf setup → AI reading → Decision → Buyers → Live call → Impact, with a progress bar
- Sections 3–5 follow the **active item** chosen from the AI reading (click a row or a photo box)
- Decision shown as a ladder stepper (Keep → Discount → Bulk sale → Donate → Animal feed → Compost) with a one-line reason and a price strip (shelf · AI opening · floor never told to the AI)
- Buyers: the next buyer as a highlighted card, the rest as rows; Google Maps attribution and Gemini's screened-out list kept
- Live call as a dark panel: info tiles, an agent-audio waveform, the Urdu transcript, the result and the next action
- Impact: this shelf's real call outcomes only (money recovered, stock placed, donated, animal feed, calls, deals), labelled as demo role-play
- Real data only; no server change; sample photos, upload, editable quantity and usage limits as before; never places real calls

## Module 9: Real phone calls (demo video)

- **As built (D61):** a separate phone-demo add-on for the video only. Twilio rings the presenter's own SIM from the real demo page (`?phone=1`), switched on with `gcloud` only while recording; judges keep the browser call. Scheduled calling, calling hours and calls to real buyers remain design (see `plans/module-9/plan.md`)
- Connects the same Negotiator to a real phone call to a SIM through Twilio
- Same agent, same rules, just a different audio connection
- **Demo number override:** calls go to your test numbers while showing real business names
- The AI conversation starts only once the call is answered
- Verify the SIM number (trial account) or enable Pakistan in calling permissions
- Test call quality and latency early; measure the delay rather than assume it
- Caller ID will likely show a foreign Twilio number. In the pitch, say that in production calls would go out from the mart's own local business number (don't describe it as an existing deployment)
- In the video, show the phone ringing and being answered alongside the live transcript and agreed price; record several takes and use the cleanest full call

## Module 10: Submission

- Deck as a PDF: problem, solution, feasibility, scalability
- 3-minute public video, opening with the problem and giving the call the most time
- Deployed link
- Theme: Retail & Commerce
- Test results as slides: freshness accuracy, negotiation results
- **Competitive framing:** recommendation platforms and markdown tools serve staff and in-store shoppers, and surplus-food apps sell to consumers; Last Call closes deals with offline business buyers who trade by phone
- Describe the camera as a trigger that spots produce going bad, not as a stock-counting system
- No statistics or sweeping claims without a source; use buyer conversation results instead

## Build order

1. Modules 0, 1 and 2 (in parallel if there are two people)
2. Connect 1 and 2 using the stand-ins in modules 3 and 4
3. Real Ladder and Scout (3, 4), manager rules and screen (5), orchestration (6)
4. Judge demo experience (8) and data and learning (7)
5. Real phone calls for the video (9)
6. Submission (10)
