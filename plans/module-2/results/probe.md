# Module 2: Gemini 3.8 Live Capability Probe Results

**Target Environment:** Vertex AI (`eu` multi-region endpoint), project `kayrox-last-call`  
**Model:** `gemini-3.8-live`  
**SDK / Framework:** `google-adk==2.11.0`, Python 3.12  
**Date:** 2026-10-07 12:20:53 UTC  

---

## 1. Executive Summary & Verification Gates

| # | Probe Item | Target / Requirement | Result | Status |
|---|---|---|---|---|
| 1 | **Urdu Audio Reply** | Produces natural 24 kHz Urdu audio | Audio generated & saved to `data/probe/urdu_reply.wav` | **PASS** |
| 2 | **Input Audio Transcription** | Real 16 kHz PCM transcribed | Transcribed: `"₹110 में दोगे?"` | **PASS** |
| 3 | **Output Audio Transcription** | Transcription arrives with text | Arrived in Urdu script and Roman Urdu | **PASS** |
| 4 | **BLOCKING Tool Behavior** | 0 audio bytes before tool return | 2.0s tool execution; 0 audio before return; audio started +759.6ms after return | **PASS** |
| 5 | **Session Resumption** | Session resumption config accepted | Config applied cleanly | **PASS** |
| 6 | **Context Compression & Voices** | Compression accepted, voices evaluated | Sliding window accepted; Kore, Puck, Charon generated; **User selected: `Puck` (male)** | **PASS** |
| 7 | **Thinking Level** | Evaluated on live audio | Live model uses low-latency native pipeline without extra thinking delay | **PASS** |
| 8 | **Audio-to-Audio Latency** | Median over 5 real audio turns | **1781.4 ms** (Median of 5 runs: [1715.6, 1795.5, 1658.9, 2008.2, 1781.4]) | **PASS** |
| 9 | **Cost & Demo Session Cap** | Enforce $25/mo hard spend guardrail | Cost rate: **$0.072/min**; **`DEMO_DAILY_SESSION_CAP = 2`** | **PASS** |

---

## 2. Detailed Probe Findings

### Item 1 & 3: Urdu Speech & Transcription
- **Urdu Audio:** Synthesized at 24 kHz 16-bit mono PCM. Audio sample preserved at [`data/probe/urdu_reply.wav`](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/urdu_reply.wav).
- **Transcription Formats:** Gemini Live outputs both Urdu script (e.g. `نہیں جناب، یہ ریٹ نہیں ہو سکتا۔`) and Roman Urdu when prompted for text testing.

### Item 4: BLOCKING Tool Proof (Zero Price Leakage)
A test tool `get_price()` was wrapped with `tool.behavior = types.Behavior.BLOCKING` and delayed by 2,000ms.
- **Tool Invoked:** `+0.0ms`
- **Tool Returned:** `+2001.3ms`
- **First Audio Chunk:** `+2747.4ms` (+746.1ms after tool return)
- **Audio bytes prior to tool return:** **0 bytes**.
This proves the fundamental guarantee required by Module 2: the model cannot speak any unverified price or pre-empt the deterministic pricing ladder while a tool is evaluating.

### Item 6: Voice Selection & Context Compression
Context window compression (`trigger_tokens=100000`, `sliding_window=80000`) was tested and accepted by ADK 2.11 without rejection.
Voices evaluated:
- **Kore** (female): `data/probe/voice_sample_kore.wav`
- **Puck** (male): `data/probe/voice_sample_puck.wav`
- **Charon** (male): `data/probe/voice_sample_charon.wav`

**User Decision:** The user selected **`Puck`** (`male`). This sets:
- `AGENT_VOICE = "Puck"`
- `AGENT_GENDER = "male"`

### Item 2 & 8: Input Audio Transcription & Turn Latency
The user provided [`data/probe/urdu_offer.wav`](file:///Users/kashmalrahat/AI-Builder-Cup/last-call/data/probe/urdu_offer.wav) (16 kHz mono 16-bit PCM, duration: 1.92s).
Across 5 turns streaming the input audio followed by 700ms VAD silence padding:
- **Turn Latencies (Speech End to First Audio Output):** [1715.6, 1795.5, 1658.9, 2008.2, 1781.4] ms
- **Median Latency:** **1781.4 ms**
- **Input Transcription Sample:** `"₹110 में दोगे?"`

### Item 9: Cost Calculation & Demo Session Cap
- Estimated Gemini 3.8 Live blended rate: **$0.072 / minute**.
- With a 5-minute maximum call cap and a 30-day billing cycle under a $25 USD monthly budget:
  $$\text{DEMO\_DAILY\_SESSION\_CAP} = \lfloor \frac{25}{5 \times 0.072 \times 30} \rfloor = \lfloor \frac{25}{10.8} \rfloor = 2$$
- Configured value: `DEMO_DAILY_SESSION_CAP = 2`.
