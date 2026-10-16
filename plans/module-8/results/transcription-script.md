# Transcription script per language setting (round 57)

Model `gemini-3.8-live`, region `eu`, voice `Puck`, ADK `run_live` as in real calls. 2 run(s) per sentence and setting. Run on 2026-10-16 17:53.

## 1. Agent speech (output transcription)

| Setting | Roman Urdu | Urdu script | Hindi script | English (translated) | Empty | Price cue caught |
|---|---|---|---|---|---|---|
| unset (today) | 1 | 4 | 1 | 0 | 0 | 3/4 |
| language_codes ["ur"] | 0 | 2 | 1 | 0 | 3 | 2/4 |
| language_codes ["en"] | 1 | 2 | 1 | 0 | 2 | 3/4 |
| language_codes ["ur", "en"] | 1 | 2 | 0 | 0 | 3 | 2/4 |

## 2. Buyer speech (input transcription, `data/probe/urdu_offer.wav`)

Sample rate 16000 Hz.

| Setting | Transcripts |
|---|---|
| deprecated language_hints ["ur", "pa", "en"] (before) | Empty: <br>Empty:  |
| language_codes ["ur", "en"] (current field) | Empty: <br>Empty:  |

## Findings

- **No setting makes the agent's transcript consistent.** All four produced a mix of Urdu script, Hindi script and Roman Urdu for the same sentences; none was reliably Roman Urdu. The script follows the transcriber's own detection of Urdu speech (Urdu and Hindi sound alike), not the hint.
- **Setting language codes made it worse:** half the turns came back with no transcript at all under `["ur"]` and `["ur", "en"]`, against none unset.
- **Keep the agent's transcription unset** (the Module 2 setting). Roman Urdu in live calls is common but not guaranteed; a Hindi-script line can appear.
- **Safety-net gap found:** a price spoken in Hindi script ("एक सौ दस रुपये") has no cue `price_guard.has_spoken_price_cue` knows ("rupay" / "روپے", "sau" / "سو", "hazaar" / "ہزار"), so the spoken-price fallback can't trigger on it (unset: 3 of 4 priced sentences caught; the miss is the Hindi one). Prices still come only from `verify_offer`, so this is the backstop, not the guard.
- **Buyer speech:** inconclusive. The recording produced no transcript under either the deprecated field or the current one (the same for both, so it shows no regression either way; the probe's audio feed, not the setting, is the likely cause). The migration rests on the SDK's deprecation notice (google-genai 2.31.0: "Deprecated: Use top-level language_codes instead") and Google's best-practices example for `gemini-3.8-live`.

## Samples (agent speech)

- unset (today) · Hindi script: हमारे पास दो दर्जन केले हैं, बस थोड़े पक्के हुए और दागी हैं, लेकिन जूस और shake के लिए बिल्कुल ठीक। एक सौ दस रुपये दर्जन। चाहिए?हमारे पास दो
- unset (today) · Urdu script: تو دو درجن، نوے روپے درجن کے حساب سے، آج رات دس بجے تک اٹھا لیں، کیش آن پک اپ۔ پکا؟ تو دو درجن، نوے روپے درجن کے حساب سے، آج رات دس بجے تک ا
- unset (today) · Urdu script: سوچ لیں، پر مال آج رات دس بجے تک ہی رک سکتا ہے۔سوچ لیں، پر مال آج رات دس بجے تک ہی رک سکتا ہے۔
- unset (today) · Roman Urdu: Humare paas do darjan kele hain, bas thoray pakke huay aur daaghi hain, lekin juice aur shake ke liye bilkul theek. Aik sau das rupay darjan
- unset (today) · Urdu script: تو دو درجن، نوے روپے درجن کے حساب سے، آج رات دس بجے تک اٹھا لیں، کیش آن پک اپ۔ پکا؟ تو دو درجن، نوے روپے درجن کے حساب سے، آج رات دس بجے تک ا
- unset (today) · Urdu script: سوچ لیں، پر مال آج رات دس بجے تک ہی رک سکتا ہے۔سوچ لیں، پر مال آج رات دس بجے تک ہی رک سکتا ہے۔
- language_codes ["ur"] · Hindi script: हमारे पास दो दर्जन केले हैं, बस थोड़े पक्के हुए और दागी हैं, लेकिन जूस और शेक के लिए बिल्कुल ठीक। एक सौ दस रुपए दर्जन। चाहिए?हमारे पास दो दर
- language_codes ["ur"] · Urdu script: تو دو درجن، نوے روپے درجن کے حساب سے، آج رات دس بجے تک اٹھا لیں، کیش آن پک اپ۔ پکا؟ تو دو درجن، نوے روپے درجن کے حساب سے، آج رات دس بجے تک ا
- language_codes ["ur"] · Empty: 
- language_codes ["ur"] · Urdu script: ہمارے پاس دو درجن کیلے ہیں، بس تھوڑے پکے ہوئے اور داغی ہیں، لیکن جوس اور شیک کے لیے بالکل ٹھیک۔ ایک سو دس روپے درجن۔ چاہیے؟ہمارے پاس دو درجن
- language_codes ["ur"] · Empty: 
- language_codes ["ur"] · Empty: 
- language_codes ["en"] · Urdu script: ہمارے پاس دو درجن کیلے ہیں، بس تھوڑے پکے ہوئے اور داغی ہیں، لیکن جوس اور شیک کے لیے بالکل ٹھیک۔ ایک سو دس روپے درجن۔ چاہیے؟ہمارے پاس دو درجن
- language_codes ["en"] · Empty: 
- language_codes ["en"] · Empty: 
- language_codes ["en"] · Roman Urdu: Humare paas do darjan kele hain, bas thoray pakke huay aur daaghi hain, lekin juice aur shake ke liye bilkul theek. Aik sau das rupay darjan
- language_codes ["en"] · Urdu script: تو دو درجن، نوے روپے درجن کے حساب سے، آج رات دس بجے تک اٹھا لیں، کیش آن پک اپ۔ پکا؟تو دو درجن، نوے روپے درجن کے حساب سے، آج رات دس بجے تک اٹ
- language_codes ["en"] · Hindi script: सोच लें، पर माल آج رات دس بجے تک ہی رک سکتا ہے۔ सोच लें، पर माल آج رات دس بجے تک ہی رک سکتا ہے۔
- language_codes ["ur", "en"] · Roman Urdu: Humare paas do darjan kele hain, bas thoray pakke huay aur daaghi hain, lekin juice aur shake ke liye bilkul theek. Aik sau das rupay darjan
- language_codes ["ur", "en"] · Urdu script: تو دو درجن، نوے روپے درجن کے حساب سے، آج رات دس بجے تک اٹھا لیں، کیش آن پک اپ۔ پکا؟تو دو درجن، نوے روپے درجن کے حساب سے، آج رات دس بجے تک اٹ
- language_codes ["ur", "en"] · Urdu script: سوچ لیں، پر مال آج رات دس بجے تک ہی رک سکتا ہے۔سوچ لیں، پر مال آج رات دس بجے تک ہی رک سکتا ہے۔
- language_codes ["ur", "en"] · Empty: 
- language_codes ["ur", "en"] · Empty: 
- language_codes ["ur", "en"] · Empty: 
