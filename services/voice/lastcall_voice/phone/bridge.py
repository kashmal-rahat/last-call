"""Twilio Media Stream bridge for the phone demo (Module 9, D61).

When the presenter answers, Twilio opens `/phone/stream` and sends `connected`, `start`
(carrying the call token as a Stream <Parameter>), `media` frames and finally `stop`.
`TwilioStreamAdapter` turns that into the `CallSocket` contract, so the unchanged browser
handler runs the negotiation:

    Twilio `start`  -> auth message with the call token
    Twilio `media`  -> 16 kHz PCM in        agent audio (24 kHz PCM) -> Twilio `media`
    Twilio `stop`   -> disconnect           `interrupted` -> Twilio `clear`
                                            `transcript`  -> live line on the call doc

Privacy: never logs audio, transcript text or phone numbers.
"""

import asyncio
import base64
import json
import logging
from typing import Any, Mapping

from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from lastcall_shared.config import get_settings
from lastcall_shared.firestore_store import FirestoreStore
from lastcall_shared.session_tokens import verify as verify_session_token
from lastcall_shared.store import CallStore
from lastcall_voice.live_session import handle_live_call_websocket
from lastcall_voice.phone.audio import InboundConverter, OutboundConverter

logger = logging.getLogger("lastcall_voice.phone")

GOODBYE_WAIT_S = 5.0  # Twilio drops queued audio on close; let the goodbye finish playing
LINE_DRAIN_S = 3.0
_END_MARK = "end"


class TwilioStreamAdapter:
    """A Twilio Media Stream presented as a `CallSocket`."""

    def __init__(self, ws: WebSocket, *, store: CallStore, signing_key: str) -> None:
        self._ws = ws
        self._store = store
        self._signing_key = signing_key
        self._inbound = InboundConverter()
        self._outbound = OutboundConverter()
        self._stream_sid: str | None = None
        self._call_id: str | None = None  # set only for a validly signed token
        self._audio_sent = False
        self._closed = False
        self._next_line = 0
        self._lines: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._line_writer: asyncio.Task | None = None

    # --- CallSocket ----------------------------------------------------------------

    @property
    def app(self) -> Any:
        return self._ws.app

    @property
    def headers(self) -> Mapping[str, str]:
        return self._ws.headers

    @property
    def client_state(self) -> WebSocketState:
        return self._ws.client_state

    async def accept(self) -> None:
        await self._ws.accept()

    async def receive_text(self) -> str:
        """Waits for Twilio's `start` and hands its call token to the handler's auth step."""
        while True:
            msg = await self._next_message()
            event = msg.get("event")
            if event == "start":
                return self._on_start(msg)
            if event == "stop":
                raise WebSocketDisconnect(code=1000)

    async def receive(self) -> Mapping[str, Any]:
        """Phone audio as 16 kHz PCM; Twilio's `stop` (the presenter hung up) ends the call."""
        while True:
            try:
                msg = await self._next_message()
            except (WebSocketDisconnect, RuntimeError):
                return {"type": "websocket.disconnect"}
            event = msg.get("event")
            if event == "media":
                payload = (msg.get("media") or {}).get("payload")
                if payload:
                    return {"type": "websocket.receive", "bytes": self._inbound.convert(base64.b64decode(payload))}
            elif event == "stop":
                return {"type": "websocket.disconnect"}

    async def send_bytes(self, data: bytes) -> None:
        mulaw = self._outbound.convert(data)
        if mulaw and self._stream_sid:
            await self._send({"event": "media", "media": {"payload": base64.b64encode(mulaw).decode("ascii")}})
            self._audio_sent = True

    async def send_json(self, data: Any) -> None:
        kind = data.get("type") if isinstance(data, dict) else None
        if kind == "interrupted" and self._stream_sid:
            await self._send({"event": "clear"})  # the presenter talked over the agent
        elif kind == "transcript" and self._call_id:
            self._queue_line(str(data.get("speaker")), str(data.get("text", "")))
        # "busy" and anything else: nothing a phone caller can be shown.

    async def close(self, code: int = 1000) -> None:
        if self._closed:
            return
        self._closed = True
        await self._wait_for_goodbye()
        await self._drain_lines()
        try:
            if self._ws.client_state == WebSocketState.CONNECTED:
                await self._ws.close(code=code)
        except Exception:
            pass

    # --- Twilio messages -----------------------------------------------------------

    async def _next_message(self) -> dict[str, Any]:
        return json.loads(await self._ws.receive_text())

    async def _send(self, message: dict[str, Any]) -> None:
        await self._ws.send_text(json.dumps({**message, "streamSid": self._stream_sid}))

    def _on_start(self, msg: dict[str, Any]) -> str:
        start = msg.get("start") or {}
        self._stream_sid = start.get("streamSid") or msg.get("streamSid")
        token = str((start.get("customParameters") or {}).get("token", ""))
        # The handler verifies the token again and rejects a bad one; this only decides
        # whether transcript lines may be written, and for which call.
        if token:
            valid, payload, _ = verify_session_token(token, key=self._signing_key)
            if valid and payload:
                self._call_id = payload["call_id"]
        logger.info("phone_stream_started", extra={"call_id": self._call_id})
        return json.dumps({"type": "auth", "token": token})

    async def _wait_for_goodbye(self) -> None:
        """Sends a mark after the last audio and waits until Twilio has played up to it."""
        if not (self._audio_sent and self._ws.client_state == WebSocketState.CONNECTED):
            return
        try:
            await self._send({"event": "mark", "mark": {"name": _END_MARK}})

            async def mark_played() -> None:
                while True:
                    msg = await self._next_message()
                    if msg.get("event") == "stop":
                        return
                    if msg.get("event") == "mark" and (msg.get("mark") or {}).get("name") == _END_MARK:
                        return

            await asyncio.wait_for(mark_played(), timeout=GOODBYE_WAIT_S)
        except Exception:
            pass  # hung up already, or Twilio never confirmed: close anyway

    # --- Live transcript lines -----------------------------------------------------

    def _queue_line(self, speaker: str, text: str) -> None:
        """One background writer keeps lines in order without holding up the audio."""
        self._lines.put_nowait({"i": self._next_line, "speaker": speaker, "text": text})
        self._next_line += 1
        if self._line_writer is None:
            self._line_writer = asyncio.create_task(self._write_lines())

    async def _write_lines(self) -> None:
        while (line := await self._lines.get()) is not None:
            try:
                await self._store.append_live_line(self._call_id or "", line)
            except Exception as exc:
                logger.warning("phone_live_line_write_failed", extra={"call_id": self._call_id, "error": str(exc)})

    async def _drain_lines(self) -> None:
        if self._line_writer is None:
            return
        self._lines.put_nowait(None)
        try:
            await asyncio.wait_for(self._line_writer, timeout=LINE_DRAIN_S)
        except Exception:
            self._line_writer.cancel()


async def handle_twilio_stream(websocket: WebSocket) -> None:
    """`/phone/stream`: closes at once unless the phone demo is switched on."""
    settings = get_settings()
    if not settings.PHONE_DEMO_ENABLED:
        await websocket.close(code=4404)
        return
    store: CallStore = getattr(websocket.app.state, "store", None) or FirestoreStore()
    adapter = TwilioStreamAdapter(
        websocket,
        store=store,
        signing_key=settings.APP_SIGNING_KEY.get_secret_value(),
    )
    # Twilio sends no Origin header; the single-use call token is the check.
    await handle_live_call_websocket(adapter, store=store, check_origin=False)
