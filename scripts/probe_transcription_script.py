"""Which script does Gemini Live write Urdu speech in, per transcription language setting? (round 57)

The page shows the call transcript to judges, and the spoken-price safety net (`price_guard`) reads the agent's
transcript for price cues in Roman Urdu or Urdu script ("rupay" / "روپے"). The agent's transcription has no language
set (Module 2), and once came out in Hindi script. This probe measures, on the same model, voice and ADK path as real
calls:

1. Agent speech (output transcription): the agent says fixed Urdu sentences under each setting (unset, ["ur"], ["en"],
   ["ur", "en"]); each transcript is classified as Roman Urdu, Urdu script, Hindi script or English (translated), and
   checked for a price cue the safety net would catch.
2. Buyer speech (input transcription): `data/probe/urdu_offer.wav` under the deprecated `language_hints` field (today)
   and the current top-level `language_codes`, to show the migration changes nothing.

Run: uv run python scripts/probe_transcription_script.py [--runs 2]
Writes plans/module-8/results/transcription-script.md. Costs a few cents of Live API use.
"""

import argparse
import asyncio
import os
import re
import time
import wave
from collections import Counter
from pathlib import Path

os.environ.setdefault("APP_SIGNING_KEY", "default-app-signing-key-for-offline-scripts-32chars")
from lastcall_shared.config import get_settings  # noqa: E402  (needs the env default above)

settings = get_settings()
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
os.environ["GOOGLE_CLOUD_PROJECT"] = settings.GOOGLE_CLOUD_PROJECT
os.environ["GOOGLE_CLOUD_LOCATION"] = settings.GOOGLE_CLOUD_LOCATION

from google.adk import Runner  # noqa: E402
from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.agents.run_config import RunConfig  # noqa: E402
from google.adk.runners import LiveRequestQueue  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from lastcall_voice.negotiator.price_guard import has_spoken_price_cue  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RESULTS = REPO / "plans/module-8/results/transcription-script.md"
BUYER_WAV = REPO / "data/probe/urdu_offer.wav"

# What the agent says on real calls: the pitch with a price, the confirmation, and the deadline line
SENTENCES = [
    "Humare paas do darjan kele hain, bas thoray pakke huay aur daaghi hain, lekin juice aur shake ke liye bilkul "
    "theek. Aik sau das rupay darjan. Chahiye?",
    "Toh do darjan, nauvey rupay darjan ke hisaab se, aaj raat das baje tak utha lein, cash on pickup. Pakka?",
    "Soch lein, par maal aaj raat das baje tak hi ruk sakta hai.",
]

OUTPUT_SETTINGS: dict[str, list[str] | None] = {
    "unset (today)": None,
    'language_codes ["ur"]': ["ur"],
    'language_codes ["en"]': ["en"],
    'language_codes ["ur", "en"]': ["ur", "en"],
}

ROMAN_URDU_WORDS = {"hain", "hai", "rupay", "darjan", "aap", "ke", "tak", "lein", "maal", "humare", "paas", "aur"}


def classify(text: str) -> str:
    if re.search(r"[ऀ-ॿ]", text):
        return "Hindi script"
    if re.search(r"[؀-ۿ]", text):
        return "Urdu script"
    words = set(re.findall(r"[a-z]+", text.lower()))
    return "Roman Urdu" if len(words & ROMAN_URDU_WORDS) >= 2 else "English (translated)"


async def run_turn(
    runner: Runner, sessions: InMemorySessionService, run_config: RunConfig, *, text=None, pcm=None, rate=16000
):
    """One turn; returns (output transcript, input transcript)."""
    session_id = f"s{time.monotonic_ns()}"
    await sessions.create_session(session_id=session_id, user_id="probe", app_name="probe")
    queue = LiveRequestQueue()
    out_parts: list[str] = []
    in_parts: list[str] = []

    async def collect():
        async for event in runner.run_live(
            session_id=session_id, user_id="probe", live_request_queue=queue, run_config=run_config
        ):
            if event.output_transcription and event.output_transcription.text:
                out_parts.append(event.output_transcription.text)
            if event.input_transcription and event.input_transcription.text:
                in_parts.append(event.input_transcription.text)
            if event.turn_complete:
                break

    task = asyncio.create_task(collect())
    if text is not None:
        queue.send_content(types.Content(role="user", parts=[types.Part.from_text(text=text)]))
    else:
        mime = f"audio/pcm;rate={rate}"
        chunk = rate // 10 * 2  # 100 ms of 16-bit mono, sent in real time
        for i in range(0, len(pcm), chunk):
            queue.send_realtime(types.Blob(data=pcm[i : i + chunk], mime_type=mime))
            await asyncio.sleep(0.1)
        queue.send_realtime(types.Blob(data=b"\x00" * (rate * 2), mime_type=mime))  # 1 s of silence
    try:
        await asyncio.wait_for(task, timeout=30)
    except asyncio.TimeoutError:
        task.cancel()
    finally:
        queue.close()
    return "".join(out_parts).strip(), "".join(in_parts).strip()


def base_config(output_codes, input_cfg) -> RunConfig:
    return RunConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=settings.AGENT_VOICE)
            )
        ),
        output_audio_transcription=types.AudioTranscriptionConfig(language_codes=output_codes)
        if output_codes
        else types.AudioTranscriptionConfig(),
        input_audio_transcription=input_cfg,
    )


async def main(runs: int) -> None:
    sessions = InMemorySessionService()
    speaker = LlmAgent(
        name="speaker",
        model=settings.GEMINI_LIVE_MODEL,
        instruction="You are a Pakistani shopkeeper. Say the user's Roman Urdu sentence aloud in Urdu, word for word, "
        "and nothing else.",
    )
    speaker_runner = Runner(agent=speaker, session_service=sessions, app_name="probe")
    lines = [
        "# Transcription script per language setting (round 57)",
        "",
        f"Model `{settings.GEMINI_LIVE_MODEL}`, region `{settings.GOOGLE_CLOUD_LOCATION}`, voice `{settings.AGENT_VOICE}`, "
        f"ADK `run_live` as in real calls. {runs} run(s) per sentence and setting. Run on {time.strftime('%Y-%m-%d %H:%M')}.",
        "",
        "## 1. Agent speech (output transcription)",
        "",
        "| Setting | Roman Urdu | Urdu script | Hindi script | English (translated) | Empty | Price cue caught |",
        "|---|---|---|---|---|---|---|",
    ]
    samples: list[str] = []
    for name, codes in OUTPUT_SETTINGS.items():
        counts: Counter[str] = Counter()
        cues = total_priced = 0
        cfg = base_config(codes, types.AudioTranscriptionConfig())
        for _ in range(runs):
            for i, sentence in enumerate(SENTENCES):
                out, _ = await run_turn(speaker_runner, sessions, cfg, text=sentence)
                kind = classify(out) if out else "Empty"
                counts[kind] += 1
                if i < 2:  # the two sentences with a spoken price
                    total_priced += 1
                    cues += bool(out) and has_spoken_price_cue(out)
                samples.append(f"- {name} · {kind}: {out[:140]}")
                print(f"{name:28} {kind:22} {out[:80]}")
        lines.append(
            f"| {name} | {counts['Roman Urdu']} | {counts['Urdu script']} | {counts['Hindi script']} | "
            f"{counts['English (translated)']} | {counts['Empty']} | {cues}/{total_priced} |"
        )

    lines += ["", "## 2. Buyer speech (input transcription, `data/probe/urdu_offer.wav`)", ""]
    if BUYER_WAV.exists():
        with wave.open(str(BUYER_WAV), "rb") as w:
            pcm = w.readframes(w.getnframes())
            rate = w.getframerate()
        listener = LlmAgent(
            name="listener", model=settings.GEMINI_LIVE_MODEL, instruction="Reply with one short Urdu sentence."
        )
        listener_runner = Runner(agent=listener, session_service=sessions, app_name="probe")
        inputs = {
            'deprecated language_hints ["ur", "pa", "en"] (before)': types.AudioTranscriptionConfig(
                language_hints=types.LanguageHints(language_codes=["ur", "pa", "en"])
            ),
            'language_codes ["ur", "en"] (current field)': types.AudioTranscriptionConfig(language_codes=["ur", "en"]),
        }
        lines += [f"Sample rate {rate} Hz.", "", "| Setting | Transcripts |", "|---|---|"]
        for name, input_cfg in inputs.items():
            heard = []
            for _ in range(runs):
                _, inp = await run_turn(listener_runner, sessions, base_config(None, input_cfg), pcm=pcm, rate=rate)
                heard.append(f"{classify(inp) if inp else 'Empty'}: {inp}")
                print(f"{name:50} {heard[-1][:90]}")
            lines.append(f"| {name} | {'<br>'.join(heard)} |")
    else:
        lines.append("Skipped: `data/probe/urdu_offer.wav` not found.")

    lines += ["", "## Samples (agent speech)", "", *samples, ""]
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {RESULTS}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--runs", type=int, default=2)
    asyncio.run(main(parser.parse_args().runs))
