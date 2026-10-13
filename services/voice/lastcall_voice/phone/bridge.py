"""Twilio Media Stream bridge for the phone demo (Module 9).

Twilio connects to /phone/stream once the presenter answers their SIM. This module
presents that socket to the unchanged browser handler (`handle_live_call_websocket`)
as if it were the browser: the call token arrives as a Stream <Parameter>, phone
audio is converted both ways, and transcript lines are saved for the demo page.

Privacy: never logs audio, transcript text or phone numbers.
"""

import asyncio
import base64
import json
import logging
import os
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from lastcall_shared.config import get_settings
from lastcall_shared.firestore_store import FirestoreStore
from lastcall_shared.session_tokens import verify as verify_session_token
from lastcall_shared.store import CallStore
from lastcall_voice.live_session import handle_live_call_websocket
from lastcall_voice.phone.audio import InboundConverter, OutboundConverter

logger = logging.getLogger("lastcall_voice.phone")

_TAIL_WAIT_S = 5.0  # let Twilio finish playing the goodbye before hanging up
_WRITER_DRAIN_S = 3.0


def phone_demo_enabled() -> bool:
    return os.getenv("PHONE_DEMO_ENABLED", "").strip().lower() == "true"


class TwilioStreamAdapter:
    """Looks like the browser WebSocket to `handle_live_call_websocket`."""

    def __init__(self, ws: WebSocket, *, store: CallStore, signing_key: str) -> None:
        self._ws = ws
        self._store = store
        self._key = signing_key
        self._inbound = InboundConverter()
        self._outbound = OutboundConverter()
        self._stream_sid: str | None = None
        self._call_id: str | None = None
        self._audio_sent = False
        self._closed = False
        self._line_index = 0
        self._lines: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._writer: asyncio.Task | None = None

    # --- What the handler reads --------------------------------------------------

    @property
    def app(self) -> Any:
        return self._ws.app

    @property
    def client_state(self) -> WebSocketState:
        return self._ws.client_state

    @property
    def headers(self) -> dict[str, str]:
        # Twilio sends no Origin header. The handler's origin check guards browsers;
        # here the single-use call token is the check, so present the demo page origin.
        allowed = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
        return {"origin": allowed[0]} if allowed else {}

    async def accept(self) -> None:
        await self._ws.accept()

    async def receive_text(self) -> str:
        """Auth handshake: wait for Twilio's `start` and hand over the call token."""
        while True:
            msg = json.loads(await self._ws.receive_text())
            event = msg.get("event")
            if event == "start":
                start = msg.get("start") or {}
                self._stream_sid = start.get("streamSid") or msg.get("streamSid")
                token = str((start.get("customParameters") or {}).get("token", ""))
                valid, payload, _ = verify_session_token(token, key=self._key) if token else (False, None, None)
                if valid and payload:
                    self._call_id = payload["call_id"]
                logger.info("phone_stream_started", extra={"call_id": self._call_id})
                return json.dumps({"type": "auth", "token": token})
            if event == "stop":
                raise WebSocketDisconnect(code=1000)

    async def receive(self) -> dict[str, Any]:
        """Phone audio in, as 16 kHz PCM; Twilio's `stop` (hang-up) ends the call."""
        while True:
            try:
                raw = await self._ws.receive_text()
            except (WebSocketDisconnect, RuntimeError):
                return {"type": "websocket.disconnect"}
            msg = json.loads(raw)
            event = msg.get("event")
            if event == "media":
                payload = (msg.get("media") or {}).get("payload")
                if payload:
                    pcm = self._inbound.convert(base64.b64decode(payload))
                    return {"type": "websocket.receive", "bytes": pcm}
            elif event == "stop":
                return {"type": "websocket.disconnect"}

    # --- What the handler sends --------------------------------------------------

    async def send_bytes(self, data: bytes) -> None:
        mulaw = self._outbound.convert(data)
        if not mulaw or not self._stream_sid:
            return
        await self._ws.send_text(
            json.dumps(
                {
                    "event": "media",
                    "streamSid": self._stream_sid,
                    "media": {"payload": base64.b64encode(mulaw).decode("ascii")},
                }
            )
        )
        self._audio_sent = True

    async def send_json(self, data: dict[str, Any]) -> None:
        kind = data.get("type")
        if kind == "interrupted" and self._stream_sid:
            # Buyer talked over the agent: drop the agent audio Twilio still has queued.
            await self._ws.send_text(json.dumps({"event": "clear", "streamSid": self._stream_sid}))
        elif kind == "transcript" and self._call_id:
            line = {"i": self._line_index, "speaker": data.get("speaker"), "text": data.get("text", "")}
            self._line_index += 1
            if self._writer is None:
                self._writer = asyncio.create_task(self._write_lines())
            self._lines.put_nowait(line)
        # "busy" and anything else: nothing to tell a phone caller.

    async def close(self, code: int = 1000) -> None:
        if self._closed:
            return
        self._closed = True
        await self._wait_for_audio_tail()
        await self._stop_writer()
        try:
            if self._ws.client_state == WebSocketState.CONNECTED:
                await self._ws.close(code=code)
        except Exception:
            pass

    # --- Internals ---------------------------------------------------------------

    async def _write_lines(self) -> None:
        """One writer, so lines reach the store in order without delaying audio."""
        while True:
            line = await self._lines.get()
            if line is None:
                return
            try:
                await self._store.append_live_line(self._call_id or "", line)
            except Exception as exc:
                logger.warning("phone_live_line_write_failed", extra={"call_id": self._call_id, "error": str(exc)})

    async def _stop_writer(self) -> None:
        if self._writer is None:
            return
        self._lines.put_nowait(None)
        try:
            await asyncio.wait_for(self._writer, timeout=_WRITER_DRAIN_S)
        except Exception:
            self._writer.cancel()

    async def _wait_for_audio_tail(self) -> None:
        """Twilio drops queued audio when the socket closes; wait for a mark so the goodbye plays."""
        if not (self._audio_sent and self._stream_sid and self._ws.client_state == WebSocketState.CONNECTED):
            return
        try:
            await self._ws.send_text(
                json.dumps({"event": "mark", "streamSid": self._stream_sid, "mark": {"name": "end"}})
            )

            async def _until_mark() -> None:
                while True:
                    msg = json.loads(await self._ws.receive_text())
                    if msg.get("event") == "stop":
                        return
                    if msg.get("event") == "mark" and (msg.get("mark") or {}).get("name") == "end":
                        return

            await asyncio.wait_for(_until_mark(), timeout=_TAIL_WAIT_S)
        except Exception:
            pass


async def handle_twilio_stream(websocket: WebSocket) -> None:
    """Entry point for /phone/stream."""
    if not phone_demo_enabled():
        await websocket.close(code=4404)
        return
    settings = get_settings()
    store: CallStore = getattr(websocket.app.state, "store", None) or FirestoreStore()
    key = settings.APP_SIGNING_KEY.get_secret_value() if settings.APP_SIGNING_KEY else ""
    adapter = TwilioStreamAdapter(websocket, store=store, signing_key=key)
    await handle_live_call_websocket(adapter, store=store)  # type: ignore[arg-type]
