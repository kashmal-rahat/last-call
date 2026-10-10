# Produce Profiles Accuracy & Consistency Report (Step 6)

## Summary
- **Model**: `gemini-3.8-flash` (Vertex AI `eu`)
- **Produce tested**: 12 items
- **Run 1 Latency**: 12496 ms | Tokens: 1422 in, 1830 out | Cost: $0.007929
- **Run 2 Latency**: 12983 ms | Tokens: 1422 in, 1824 out | Cost: $0.007907
- **Raw Variation (Run 1 vs Run 2)**: 9/12 produce varied (75.0%), with 15 total differing fields.

> [!IMPORTANT]
> **Why We Store Produce Profiles:**
> Without storing profiles, decisions would inherit raw model jitter across queries. Storing Gemini profiles once under `{produce}__v1` eliminates per-batch API calls, brings decision latency down to sub-millisecond code execution, guarantees 100% decision repeatability, and allows instant manager overrides (`__manager`).

## Generated Profiles (Run 1)
| Produce | Fresh Band | Ripening Band | Overripe Band | Uses (Fresh) | Uses (Ripe) | Uses (Overripe) | Cattle (Over/Spoiled) | Note | Sense check (user) |
|---|---|---|---|---|---|---|---|---|---|
| spinach | `6_to_24h` | `under_6h` | `under_6h` | juice_shop, restaurant, charity | restaurant, charity | charity | True/False | Leafy green; wilts and yellows rapidly in room temperature heat | |
| coriander | `6_to_24h` | `under_6h` | `under_6h` | restaurant, charity | restaurant, charity | charity | True/False | Delicate herb; rapidly loses moisture and wilts within hours without refrigeration | |
| banana | `1_to_3_days` | `1_to_3_days` | `6_to_24h` | juice_shop, charity | juice_shop, bakery, charity | juice_shop, bakery, charity | True/True | Fast ripening tropical fruit; quickly bruises and blackens in ambient heat | |
| mango | `1_to_3_days` | `1_to_3_days` | `6_to_24h` | juice_shop, charity | juice_shop, bakery, charity | juice_shop, bakery, charity | True/False | Climacteric fruit; softens quickly and ferments under high room temperatures | |
| guava | `1_to_3_days` | `6_to_24h` | `under_6h` | juice_shop, charity | juice_shop, charity | juice_shop, charity | True/False | Thin-skinned fruit; bruises easily and turns mushy quickly in ambient warm conditions | |
| tomato | `1_to_3_days` | `1_to_3_days` | `6_to_24h` | restaurant, charity | restaurant, charity | restaurant, charity | True/False | Soft fruit vegetable; easily bruises, softens, and leaks in uncooled shelf heat | |
| okra | `1_to_3_days` | `6_to_24h` | `under_6h` | restaurant, charity | restaurant, charity | restaurant, charity | True/False | Tender pod vegetable; turns fibrous, blackens at tips, and wilts within 1-2 days | |
| onion | `over_3_days` | `over_3_days` | `1_to_3_days` | restaurant, charity | restaurant, charity | restaurant, charity | False/False | Dry bulb vegetable; sturdy shelf life, primarily limited by humidity and sprouting | |
| potato | `over_3_days` | `over_3_days` | `1_to_3_days` | restaurant, charity | restaurant, charity | restaurant, charity | False/False | Tuber vegetable; stable shelf life, limited by heat-induced greening and sprouting | |
| kinnow | `over_3_days` | `1_to_3_days` | `6_to_24h` | juice_shop, charity | juice_shop, charity | juice_shop, charity | True/False | Thick-skinned citrus; holds up well to heat but gradually loses moisture and shrinks | |
| apple | `over_3_days` | `1_to_3_days` | `6_to_24h` | juice_shop, bakery, charity | juice_shop, bakery, charity | juice_shop, bakery, charity | True/False | Firm pome fruit; holds moisture well even at room temperature before softening | |
| bottle gourd | `over_3_days` | `1_to_3_days` | `6_to_24h` | juice_shop, restaurant, charity | juice_shop, restaurant, charity | restaurant, charity | True/False | Dense gourd; maintains firm flesh but surface wrinkles and softens over several days | |

## Variation Analysis Across Uncached Runs
| Produce | Run 1 == Run 2 | Differing Fields |
|---|---|---|
| spinach | ✗ Differed (2) | ripening.juice_shop: False vs True; overripe.restaurant: False vs True |
| coriander | ✗ Differed (1) | overripe.restaurant: False vs True |
| banana | ✗ Differed (1) | overripe.sellable_for: '6_to_24h' vs 'under_6h' |
| mango | ✗ Differed (4) | ripening.bakery: True vs False; overripe.sellable_for: '6_to_24h' vs 'under_6h'; overripe.bakery: True vs False; spoiled_ok_for_cattle: False vs True |
| guava | ✗ Differed (1) | spoiled_ok_for_cattle: False vs True |
| tomato | ✗ Differed (1) | overripe_ok_for_cattle: True vs False |
| okra | ✓ Identical | None |
| onion | ✓ Identical | None |
| potato | ✓ Identical | None |
| kinnow | ✗ Differed (2) | ripening.sellable_for: '1_to_3_days' vs 'over_3_days'; overripe.sellable_for: '6_to_24h' vs '1_to_3_days' |
| apple | ✗ Differed (2) | ripening.sellable_for: '1_to_3_days' vs 'over_3_days'; overripe.sellable_for: '6_to_24h' vs '1_to_3_days' |
| bottle gourd | ✗ Differed (1) | overripe.charity: True vs False |

## Step 4 Worked Examples Decisions (Using Generated Profiles)
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
