# Module 2: Negotiator prompt (change log from the user v1 draft)

This is the reference for `services/voice/lastcall_voice/negotiator/prompt.py` (step 6 of [module-2-negotiator.md](module-2-negotiator.md)). It's based on the user's v1 draft, with the slang kept.
- `{placeholders}` are filled by `render_instruction()` from `agent_view()` only.
- Blocks marked `[if …]` are included or left out in code.
- **The floor price and the price ladder never appear here.** They live in `verify_offer` (D18).

## What changed from the user's v1, and why

| # | v1 | v1.1 | Why |
|---|---|---|---|
| 1 | The floor (80) and the full ladder 120 → 105 → 95 → 88 → 83 → 80 are in the prompt | Removed. The agent calls `verify_offer` and says only the price it returns | Architecture §5 and D18: the floor is never sent to the model. A model that knows its floor can be talked down to it, or can let it slip ("80 se neechay nahi"). The code also needs the ladder so it can reject deals |
| 2 | No tool names ("send the photo", "record it") | Each situation names its tool | Otherwise the model only *says* it sent a photo or saved a callback |
| 3 | "Sauda pakka!" listed as a line for when a deal is agreed | Only after `confirm_deal` returns `ok` | Otherwise the agent could announce a deal that the code then rejects |
| 4 | Fixed price inside lines ("mai tau 120 pe keh raha tha") | "[the price verify_offer returned]", which the model fills in from the tool result | The price changes during the call. The prompt is rendered without reading the store |
| 5 | "Rate pehle hi mandi se neechay hai" and "well under the market" | Only used when the brief has `market_rate` | Otherwise it's an unchecked claim to a real business |
| 6 | Speaks as a man ("deta hoon", "keh raha tha"), while the plan's disclosure is feminine ("bol rahi hoon") | One `{agent_gender}` setting, matched to the voice chosen in the probe | Mixed genders sound wrong at once to a native speaker |
| 7 | "yr", "humie b wara nae khata" (texting spelling) | Standard Roman Urdu: "yaar", "humein bhi wara nahi khaata" | Native audio reads the text it generates. "yr" may be spoken as letters |
| 8 | "Text testing mode: write in Roman Urdu" is always on | Only in text mode | In voice mode the model should just speak |
| 9 | The buyer is assumed to be a man ("follow him") | `{buyer_honorific}` from the brief | Buyers vary |
| 10 | "Lowball = about half the opening price or less", worked out by the model | `verify_offer` returns `offer_band: "lowball"` | The model doesn't know the floor and shouldn't do the maths |
| 11 | Offer above the opening price → deal at the opening price | Kept. `verify_offer` now accepts at the current price when the offer is higher (plan step 4 updated) | It's honest and builds goodwill. The code and the joke now agree |
| 12 | Lahori Punjabi flavour hardcoded | `{city_style}` block per mart (Lahore here; Karachi is more Urdu, less Punjabi) | The test fixtures are Karachi marts |

## Template

The **authoritative template** is now Appendix A of [module-2-negotiator.md](module-2-negotiator.md) (Jinja2, v1.2). Implement `negotiator/prompt_template.j2` from there. The earlier v1.1 text was removed so the two copies can't drift apart.

## Tests to add (step 11)
- The rendered prompt for any scenario contains no floor value and none of the ladder rungs below the opening price.
- In voice mode the prompt has no "Text testing mode" line, and in text mode it does.
- The gender forms are consistent: render with `agent_gender=female` and check that no masculine forms ("deta hoon", "raha tha") remain. Do the same the other way round.
- A donation prompt contains no "rupay" or price line.
- Text simulator: whenever `offer_band=lowball` comes back, the next agent turn says the returned price (checked by the judge).
