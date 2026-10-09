# Module 1: Latency Diagnosis Probe
Tested on: 2026-10-09 14:18:10 UTC
Photo: `smoke3.png`
Model: `gemini-3.8-flash` on Vertex AI (`eu`)
Configuration: `thinking_level=low`, single pass, timeout=60s, retries=0

## Summary Statistics

| Metric | Value (s) |
|---|---|
| **Calls** | 12 |
| **Errors** | 0 |
| **Min Latency** | 4.39s |
| **p50 Latency (median)** | 6.69s |
| **p90 Latency** | 10.80s |
| **Max Latency** | 12.14s |

## Per-Call Latency Log

| # | Status | Latency (s) | Items | In Tok | Out (Thoughts / Cand) | Error |
|---|---|---|---|---|---|---|
| 1 | ok | 8.68 | 3 | 6492 | 684 (0 / 684) | - |
| 2 | ok | 7.50 | 5 | 6492 | 684 (0 / 684) | - |
| 3 | ok | 6.31 | 5 | 6492 | 684 (0 / 684) | - |
| 4 | ok | 4.92 | 2 | 6492 | 465 (0 / 465) | - |
| 5 | ok | 4.43 | 2 | 6492 | 457 (0 / 457) | - |
| 6 | ok | 7.07 | 2 | 6492 | 467 (0 / 467) | - |
| 7 | ok | 11.04 | 4 | 6492 | 871 (0 / 871) | - |
| 8 | ok | 8.51 | 5 | 6492 | 673 (0 / 673) | - |
| 9 | ok | 4.43 | 2 | 6492 | 456 (0 / 456) | - |
| 10 | ok | 4.39 | 2 | 6492 | 470 (0 / 470) | - |
| 11 | ok | 12.14 | 5 | 6492 | 654 (0 / 654) | - |
| 12 | ok | 5.48 | 3 | 6492 | 677 (0 / 677) | - |
