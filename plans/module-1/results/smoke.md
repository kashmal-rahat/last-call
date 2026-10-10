# Module 1: Freshness Inspector Smoke Verification
Tested on: 2026-10-09 11:23:26 UTC
Model: `gemini-3.8-flash` on Vertex AI (`eu`), `media_resolution=HIGH`, `thinking_level=medium`

## Single Pass Baseline

| # | Photo | Status | Groups | Zoomed | Latency (s) | Calls | Input Tok | Output Tok | Cached Tok | Cost ($) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `smoke1.png` | ok | 2 | 0 | 22.25 | 1 | 6501 | 2244 | 4006 | $0.01329 |
| 2 | `smoke2.png` | ok | 2 | 0 | 27.48 | 1 | 6500 | 3536 | 0 | $0.01814 |
| 3 | `smoke3.png` | ok | 3 | 0 | 32.95 | 1 | 6492 | 4291 | 0 | $0.02096 |
| 4 | `smoke4.png` | ok | 2 | 0 | 31.76 | 1 | 6476 | 4451 | 0 | $0.02155 |
| 5 | `smoke5.png` | ok | 1 | 0 | 51.91 | 1 | 6485 | 5938 | 0 | $0.02713 |
| 6 | `smoke6.png` | ok | 1 | 0 | 48.94 | 1 | 6500 | 5580 | 4005 | $0.02580 |

### Detailed Findings per Photo

#### Photo 1: `smoke1.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_1.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_1.jpg)`
- **Groups Detected**:
  - **banana**: stage `ripening` (`late`), worst stage `overripe`, score `62.0`, confidence `high`, observed `50-75 (count)`, quantity `4.0-6.0 dozen`
  - **apple**: stage `ripening` (`early`), worst stage `ripening`, score `76.0`, confidence `medium`, observed `15-30 (count)`, quantity `2.5-5.5 kg`

#### Photo 2: `smoke2.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_2.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_2.jpg)`
- **Groups Detected**:
  - **banana**: stage `ripening` (`mid`), worst stage `overripe`, score `69.0`, confidence `high`, observed `14-20 (count)`, quantity `1.0-1.5 dozen`
  - **apple**: stage `fresh` (`mid`), worst stage `fresh`, score `88.0`, confidence `high`, observed `120-180 (count)`, quantity `20.0-30.0 kg`

#### Photo 3: `smoke3.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_3.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_3.jpg)`
- **Groups Detected**:
  - **cucumber**: stage `fresh` (`mid`), worst stage `fresh`, score `88.0`, confidence `high`, observed `40-60 (count)`, quantity `6.0-10.0 kg`
  - **guava**: stage `ripening` (`mid`), worst stage `ripening`, score `69.0`, confidence `low`, observed `10-25 (count)`, quantity `1.5-3.5 kg` *(Staff check: Crate is cut off at the edge of the frame.)*
  - **tomato**: stage `ripening` (`early`), worst stage `ripening`, score `76.0`, confidence `high`, observed `120-180 (count)`, quantity `10.0-16.0 kg` *(Staff check: Discarded packaged candy items are resting on top of the tomatoes.)*

#### Photo 4: `smoke4.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_4.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_4.jpg)`
- **Groups Detected**:
  - **banana**: stage `ripening` (`early`), worst stage `ripening`, score `76.0`, confidence `low`, observed `3-8 (count)`, quantity `0.0-0.5 dozen` *(Staff check: Only partially visible at the edge of the frame.)*
  - **persimmon**: stage `ripening` (`early`), worst stage `ripening`, score `76.0`, confidence `high`, observed `80-110 (count)`, quantity `14.0-22.0 kg`

#### Photo 5: `smoke5.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_5.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_5.jpg)`
- **Groups Detected**:
  - **banana**: stage `ripening` (`mid`), worst stage `ripening`, score `69.0`, confidence `high`, observed `210-270 (count)`, quantity `17.5-22.5 dozen`

#### Photo 6: `smoke6.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_6.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_6.jpg)`
- **Groups Detected**:
  - **tomato**: stage `ripening` (`early`), worst stage `ripening`, score `76.0`, confidence `high`, observed `80-120 (count)`, quantity `5.0-9.0 kg`


---

## Zoom Pass (Pass 1 + Pass 2)

| # | Photo | Status | Groups | Zoomed | Latency (s) | Calls | Input Tok | Output Tok | Cached Tok | Cost ($) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `smoke1.png` | error | 0 | 0 | 122.01 | 1 | 0 | 0 | 0 | $0.00000 |
| 2 | `smoke2.png` | ok | 2 | 0 | 60.00 | 3 | 6500 | 2540 | 0 | $0.01440 |
| 3 | `smoke3.png` | ok | 3 | 0 | 58.26 | 1 | 6492 | 3681 | 0 | $0.01867 |
| 4 | `smoke4.png` | error | 0 | 0 | 122.00 | 1 | 0 | 0 | 0 | $0.00000 |
| 5 | `smoke5.png` | error | 0 | 0 | 122.01 | 1 | 0 | 0 | 0 | $0.00000 |
| 6 | `smoke6.png` | error | 0 | 0 | 122.00 | 1 | 0 | 0 | 0 | $0.00000 |

### Detailed Findings per Photo

#### Photo 1: `smoke1.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_1.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_1.jpg)`
- **Groups Detected**:
  - *No items detected*

#### Photo 2: `smoke2.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_2.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_2.jpg)`
- **Groups Detected**:
  - **apple**: stage `fresh` (`mid`), worst stage `fresh`, score `88.0`, confidence `medium`, observed `120-200 (count)`, quantity `18.0-30.0 kg`
  - **banana**: stage `ripening` (`mid`), worst stage `overripe`, score `69.0`, confidence `medium`, observed `12-20 (count)`, quantity `1.0-1.5 dozen`

#### Photo 3: `smoke3.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_3.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_3.jpg)`
- **Groups Detected**:
  - **cucumber**: stage `fresh` (`mid`), worst stage `fresh`, score `88.0`, confidence `high`, observed `40-70 (count)`, quantity `7.0-13.0 kg`
  - **guava**: stage `ripening` (`mid`), worst stage `ripening`, score `69.0`, confidence `medium`, observed `20-35 (count)`, quantity `3.0-6.0 kg`
  - **tomato**: stage `fresh` (`mid`), worst stage `fresh`, score `88.0`, confidence `high`, observed `120-200 (count)`, quantity `12.0-20.0 kg` *(Staff check: Packaged confectionary packaging is resting on top of the tomatoes and should be removed.)*

#### Photo 4: `smoke4.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_4.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_4.jpg)`
- **Groups Detected**:
  - *No items detected*

#### Photo 5: `smoke5.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_5.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_5.jpg)`
- **Groups Detected**:
  - *No items detected*

#### Photo 6: `smoke6.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_6.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_6.jpg)`
- **Groups Detected**:
  - *No items detected*


---

## Single Pass (thinking=low)

| # | Photo | Status | Groups | Zoomed | Latency (s) | Calls | Input Tok | Out (Thoughts / Ans) | Cached Tok | Cost ($) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `smoke1.png` | ok | 2 | 0 | 6.66 | 1 | 6501 | 290 (0 / 290) | 0 | $0.00596 |
| 2 | `smoke2.png` | ok | 2 | 0 | 4.98 | 1 | 6500 | 284 (0 / 284) | 0 | $0.00594 |
| 3 | `smoke3.png` | ok | 3 | 0 | 7.60 | 1 | 6492 | 706 (0 / 706) | 0 | $0.00752 |
| 4 | `smoke4.png` | ok | 1 | 0 | 4.04 | 1 | 6476 | 254 (0 / 254) | 0 | $0.00581 |
| 5 | `smoke5.png` | ok | 1 | 0 | 3.88 | 1 | 6485 | 262 (0 / 262) | 0 | $0.00585 |
| 6 | `smoke6.png` | ok | 1 | 0 | 13.58 | 1 | 6500 | 171 (0 / 171) | 0 | $0.00552 |

### Item Comparisons per Photo

#### Photo 1: `smoke1.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_1.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_1.jpg)`
- **Groups Detected**:
  - **banana**: stage `ripening` (`late`), worst stage `overripe`, confidence `high`, score `62.0`, observed `55-75 (count)`, quantity `4.5-6.0 dozen`
  - **red apple**: stage `fresh` (`mid`), worst stage `fresh`, confidence `medium`, score `88.0`, observed `15-25 (count)`, quantity `2.5-4.0 kg`

#### Photo 2: `smoke2.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_2.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_2.jpg)`
- **Groups Detected**:
  - **apple**: stage `fresh` (`mid`), worst stage `fresh`, confidence `high`, score `88.0`, observed `110-150 (count)`, quantity `18.0-25.0 kg`
  - **banana**: stage `ripening` (`mid`), worst stage `ripening`, confidence `high`, score `69.0`, observed `15-25 (count)`, quantity `1.0-2.0 dozen`

#### Photo 3: `smoke3.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_3.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_3.jpg)`
- **Groups Detected**:
  - **cucumber**: stage `fresh` (`mid`), worst stage `fresh`, confidence `high`, score `88.0`, observed `50-80 (count)`, quantity `7.0-12.0 kg`
  - **unknown produce**: stage `ripening` (`mid`), worst stage `ripening`, confidence `low`, score `69.0`, observed `15-30 (count)`, quantity `1.0-2.5 kg` *(Staff check: Round yellowish fruit partially cut off at frame edge, possibly guava or lemon.)*
  - **tomato**: stage `fresh` (`mid`), worst stage `ripening`, confidence `high`, score `88.0`, observed `120-180 (count)`, quantity `10.0-16.0 kg` *(Staff check: Foreign packaging debris is resting on top of the tomato display.)*

#### Photo 4: `smoke4.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_4.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_4.jpg)`
- **Groups Detected**:
  - **persimmon**: stage `fresh` (`mid`), worst stage `fresh`, confidence `high`, score `88.0`, observed `85-110 (count)`, quantity `14.0-18.0 kg`

#### Photo 5: `smoke5.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_5.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_5.jpg)`
- **Groups Detected**:
  - **banana**: stage `ripening` (`mid`), worst stage `ripening`, confidence `high`, score `69.0`, observed `180-240 (count)`, quantity `15.0-20.0 dozen`

#### Photo 6: `smoke6.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_6.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_6.jpg)`
- **Groups Detected**:
  - **tomato**: stage `fresh` (`mid`), worst stage `ripening`, confidence `high`, score `88.0`, observed `100-130 (count)`, quantity `8.0-11.0 kg`


---

## Zoom Pass (thinking=low)

| # | Photo | Status | Groups | Zoomed | Latency (s) | Calls | Input Tok | Out (Thoughts / Ans) | Cached Tok | Cost ($) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `smoke1.png` | ok | 2 | 1 | 11.05 | 2 | 13046 | 470 (0 / 470) | 0 | $0.01155 |
| 2 | `smoke2.png` | ok | 2 | 1 | 7.53 | 2 | 13024 | 441 (0 / 441) | 0 | $0.01142 |
| 3 | `smoke3.png` | ok | 2 | 1 | 9.01 | 2 | 13025 | 612 (0 / 612) | 0 | $0.01206 |
| 4 | `smoke4.png` | ok | 1 | 0 | 4.37 | 1 | 6476 | 254 (0 / 254) | 0 | $0.00581 |
| 5 | `smoke5.png` | ok | 1 | 0 | 3.99 | 1 | 6485 | 263 (0 / 263) | 0 | $0.00585 |
| 6 | `smoke6.png` | ok | 1 | 0 | 3.85 | 1 | 6500 | 205 (0 / 205) | 0 | $0.00564 |

### Rule 8 Analysis (Box Area > 40% Filter)
- **Photos with Zoomed Groups**:
  - `smoke1.png`: **apple** zoomed (box area <= 0.40). **banana** skipped by Rule 8 (box area > 0.40).
  - `smoke2.png`: **banana** zoomed (box area <= 0.40). **apple** skipped by Rule 8 (box area > 0.40).
  - `smoke3.png`: **cucumber** zoomed (box area <= 0.40). **tomato** skipped by Rule 8 (box area > 0.40).
- **Photos with 0 Zoomed Groups (Skipped by Rule 8)**:
  - `smoke4.png`: **persimmon** skipped by Rule 8 (single display covering > 0.40 of frame).
  - `smoke5.png`: **banana** skipped by Rule 8 (single display covering > 0.40 of frame).
  - `smoke6.png`: **tomato** skipped by Rule 8 (single display covering > 0.40 of frame).
- **Impact**: Single-display shelf photos (photos 4–6) ran in single pass with ~3.8–4.3 s latency, completely eliminating redundant close-up crops of wide-angle crates.

### Item Comparisons per Photo

#### Photo 1: `smoke1.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_1.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_1.jpg)`
- **Close-up Crops**:
  - `[data/probe/inspector_crop_1_1.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_crop_1_1.jpg)`
- **Groups Detected**:
  - **banana**: stage `overripe` (`early`), worst stage `overripe`, confidence `high`, score `55.0`, observed `55-75 (count)`, quantity `4.5-6.0 dozen`
  - **apple**: stage `fresh` (`late`), worst stage `ripening`, confidence `high`, score `81.0`, observed `20-30 (count)`, quantity `3.0-4.5 kg` **[Zoomed]**

#### Photo 2: `smoke2.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_2.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_2.jpg)`
- **Close-up Crops**:
  - `[data/probe/inspector_crop_2_1.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_crop_2_1.jpg)`
- **Groups Detected**:
  - **apple**: stage `fresh` (`mid`), worst stage `fresh`, confidence `high`, score `88.0`, observed `110-140 (count)`, quantity `16.5-21.0 kg`
  - **banana**: stage `overripe` (`early`), worst stage `overripe`, confidence `high`, score `55.0`, observed `12-20 (count)`, quantity `1.0-1.5 dozen` **[Zoomed]**

#### Photo 3: `smoke3.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_3.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_3.jpg)`
- **Close-up Crops**:
  - `[data/probe/inspector_crop_3_0.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_crop_3_0.jpg)`
- **Groups Detected**:
  - **cucumber**: stage `fresh` (`mid`), worst stage `ripening`, confidence `high`, score `88.0`, observed `55-75 (count)`, quantity `10.0-15.0 kg` **[Zoomed]**
  - **tomato**: stage `fresh` (`mid`), worst stage `fresh`, confidence `high`, score `88.0`, observed `100-140 (count)`, quantity `10.0-14.0 kg` *(Staff check: Foreign packaging/candy wrappers left resting directly on the tomatoes.)*

#### Photo 4: `smoke4.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_4.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_4.jpg)`
- **Groups Detected**:
  - **persimmon**: stage `fresh` (`mid`), worst stage `fresh`, confidence `high`, score `88.0`, observed `100-140 (count)`, quantity `15.0-25.0 kg`

#### Photo 5: `smoke5.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_5.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_5.jpg)`
- **Groups Detected**:
  - **banana**: stage `ripening` (`mid`), worst stage `ripening`, confidence `high`, score `69.0`, observed `250-350 (count)`, quantity `21.0-29.0 dozen`

#### Photo 6: `smoke6.png`
- **Overlay Box Image**: `[data/probe/inspector_boxes_6.jpg](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/inspector_boxes_6.jpg)`
- **Groups Detected**:
  - **tomato**: stage `ripening` (`mid`), worst stage `ripening`, confidence `high`, score `69.0`, observed `120-160 (count)`, quantity `10.0-14.0 kg`

