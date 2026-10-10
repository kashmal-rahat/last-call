# Profile check (Step 6 & 6B)

## Summary
- **Model**: `gemini-3.8-flash` (Vertex AI `eu`)
- **Produce tested**: 12 items
- **Raw Single-Call Runs**: 8/12 produce varied (66.7%), with 16 differing fields.
- **5-Vote Consensus Runs**: 3/12 produce varied (25.0%), with 5 differing fields.
- **Raw Latency & Cost (per call)**: ~13965 ms | Cost: $0.008072
- **5-Vote Consensus Latency & Cost**: 14955 ms (5 parallel requests) | Tokens: 7110 in, 9171 out | Cost: $0.039724

> [!IMPORTANT]
> **Why We Store Produce Profiles & Use 5-Vote Consensus:**
> Raw single-call variation (8/12 varied) produces model jitter. A 5-vote consensus stabilizes the profile (3/12 varied), records uncertain fields, and storing once under `{produce}__v1` eliminates per-request API calls while allowing instant manager overrides (`__manager`).

## Generated Profiles (5-Vote Consensus Run 1)
| Produce | Fresh Band | Ripening Band | Overripe Band | Uses (Fresh) | Uses (Ripe) | Uses (Overripe) | Cattle (Over/Spoiled) | Note | Votes | Uncertain Fields | Sense check (user) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| spinach | `6_to_24h` | `under_6h` | `under_6h` | restaurant, charity | restaurant, charity | charity | True/False | Leafy green; wilts and yellows rapidly in room heat. | 5 | fresh.juice_shop | |
| coriander | `6_to_24h` | `under_6h` | `under_6h` | restaurant, charity | restaurant, charity | charity | True/False | Delicate herb; prone to rapid wilting and blackening in warmth. | 5 | none | |
| banana | `1_to_3_days` | `1_to_3_days` | `6_to_24h` | juice_shop, charity | juice_shop, bakery, charity | juice_shop, bakery, charity | True/True | Fast-ripening fruit; softens and darkens quickly at ambient temperatures. | 5 | fresh.bakery | |
| mango | `1_to_3_days` | `1_to_3_days` | `6_to_24h` | juice_shop, restaurant, charity | juice_shop, restaurant, bakery, charity | juice_shop, charity | True/False | Softens and ferments rapidly in hot conditions. | 5 | fresh.restaurant, fresh.bakery, ripening.restaurant, overripe.bakery | |
| guava | `1_to_3_days` | `6_to_24h` | `under_6h` | juice_shop, charity | juice_shop, charity | juice_shop, charity | True/False | Quick to soften, bruise, and turn pulpy in heat. | 5 | none | |
| tomato | `1_to_3_days` | `1_to_3_days` | `6_to_24h` | restaurant, charity | restaurant, charity | restaurant, charity | True/False | Softens, thins at skin, and leaks fluid quickly in warmth. | 5 | none | |
| okra | `1_to_3_days` | `6_to_24h` | `under_6h` | restaurant, charity | restaurant, charity | charity | True/False | Tender pod; toughens, dries out, and blackens in ambient heat. | 5 | none | |
| onion | `over_3_days` | `over_3_days` | `1_to_3_days` | restaurant, charity | restaurant, charity | restaurant, charity | False/False | Dry bulb; lasts long but rots or sprouts if warm and humid. | 5 | none | |
| potato | `over_3_days` | `over_3_days` | `1_to_3_days` | restaurant, charity | restaurant, charity | restaurant, charity | False/False | Starchy tuber; durable but prone to softening, greening, and sprouting. | 5 | none | |
| kinnow | `over_3_days` | `1_to_3_days` | `6_to_24h` | juice_shop, charity | juice_shop, charity | juice_shop, charity | True/False | Thick-skinned citrus; gradually loses moisture and dries out internally. | 5 | ripening.sellable_for, overripe.sellable_for | |
| apple | `over_3_days` | `1_to_3_days` | `6_to_24h` | juice_shop, bakery, charity | juice_shop, bakery, charity | juice_shop, bakery, charity | True/False | Firm pome fruit; slowly wrinkles and loses crispness in warmth. | 5 | ripening.sellable_for, overripe.sellable_for, spoiled_ok_for_cattle | |
| bottle gourd | `over_3_days` | `1_to_3_days` | `6_to_24h` | restaurant, charity | restaurant, charity | restaurant, charity | True/False | Dense squash; slowly loses moisture and shrivels over several days. | 5 | fresh.sellable_for | |

## Variation Comparison: Raw (Single-Call) vs 5-Vote Consensus
| Produce | Raw (Single-Call) Variation | 5-Vote Consensus Variation |
|---|---|---|
| spinach | ✗ Differed (1): fresh.juice_shop: False vs True | ✓ Identical |
| coriander | ✗ Differed (1): fresh.juice_shop: False vs True | ✓ Identical |
| banana | ✗ Differed (2): fresh.bakery: False vs True; spoiled_ok_for_cattle: True vs False | ✗ Differed (1): spoiled_ok_for_cattle: True vs False |
| mango | ✗ Differed (3): fresh.restaurant: False vs True; fresh.bakery: False vs True; ripening.restaurant: False vs True | ✓ Identical |
| guava | ✓ Identical | ✓ Identical |
| tomato | ✓ Identical | ✓ Identical |
| okra | ✓ Identical | ✓ Identical |
| onion | ✓ Identical | ✓ Identical |
| potato | ✗ Differed (2): fresh.bakery: False vs True; ripening.bakery: False vs True | ✓ Identical |
| kinnow | ✗ Differed (2): ripening.sellable_for: '1_to_3_days' vs 'over_3_days'; overripe.sellable_for: '6_to_24h' vs '1_to_3_days' | ✗ Differed (2): ripening.sellable_for: '1_to_3_days' vs 'over_3_days'; overripe.sellable_for: '6_to_24h' vs '1_to_3_days' |
| apple | ✗ Differed (2): ripening.sellable_for: '1_to_3_days' vs 'over_3_days'; overripe.sellable_for: '6_to_24h' vs '1_to_3_days' | ✗ Differed (2): ripening.sellable_for: '1_to_3_days' vs 'over_3_days'; overripe.sellable_for: '6_to_24h' vs '1_to_3_days' |
| bottle gourd | ✗ Differed (3): fresh.sellable_for: 'over_3_days' vs '1_to_3_days'; fresh.juice_shop: False vs True; overripe.charity: True vs False | ✓ Identical |

## Step 4 Worked Examples Decisions (Using 5-Vote Consensus Profiles)
| Case | Produce | Stage & Level | H to Closing | Shelf Price | Engine Step | Pricing / Discount | Buyer Types | Reason |
|---|---|---|---|---|---|---|---|---|
| Fresh banana in morning (H=14) | banana | fresh (early) | 14.0h | Rs 180 | `keep` | - | - | Banana, fresh: sells for about 48 h; lasts past tomorrow opening → keep on shelf |
| Late-ripening banana at 3h to closing (H=3) | banana | ripening (late) | 3.0h | Rs 180 | `keep` | - | - | Banana, ripening: sells for about 19 h; lasts past tomorrow opening → keep on shelf |
| Late-ripening banana at 14h to closing (H=14) | banana | ripening (late) | 14.0h | Rs 180 | `keep` | - | - | Banana, ripening: sells for about 19 h; lasts until closing; discount decided closer to closing |
| Overripe spinach at 8h to closing (H=8) | spinach | overripe (mid) | 8.0h | Rs 70 | `donate` | - | charity | Spinach, overripe: won't last to closing; charities can use it → donate |
| Fresh early spinach at 13h to closing (H=13) | spinach | fresh (early) | 13.0h | Rs 70 | `keep` | - | - | Spinach, fresh: sells for about 15 h; lasts until closing; discount decided closer to closing |
| Fresh early spinach at 4h to closing (H=4) | spinach | fresh (early) | 4.0h | Rs 70 | `discount` | -10% (Rs 65) | - | Spinach, fresh (early): sells for about 15 h; 4 h to closing → 10% off |
| Overripe potato at 8h to closing (H=8) | potato | overripe (early) | 8.0h | Rs 80 | `discount` | -10% (Rs 70) | - | Potato, overripe: sells for about 48 h; lasts past opening but overripe → 10% off |
| Spoiled tomato without mould (H=4) | tomato | spoiled (early) | 4.0h | Rs 120 | `compost` | - | - | Tomato, spoiled: not suitable for food or feed → compost |
