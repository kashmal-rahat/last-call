"""The socket contract `handle_live_call_websocket` needs.

Starlette's WebSocket (the browser call) satisfies it as is; the phone demo's
`TwilioStreamAdapter` satisfies it by translating Twilio Media Stream messages.
"""

from typing import Any, Mapping, Protocol

from starlette.websockets import WebSocketState


class CallSocket(Protocol):
    @property
    def app(self) -> Any: ...

    @property
    def headers(self) -> Mapping[str, str]: ...

    @property
    def client_state(self) -> WebSocketState: ...

    async def accept(self) -> None: ...

    async def receive_text(self) -> str:
        """The first message: `{"type": "auth", "token": ...}`."""
        ...

    async def receive(self) -> Mapping[str, Any]:
        """ASGI-style: `{"bytes": <16 kHz PCM16>}`, `{"text": ...}` or `{"type": "websocket.disconnect"}`."""
        ...

    async def send_bytes(self, data: bytes) -> None:
        """Agent audio, 24 kHz PCM16."""
        ...

    async def send_json(self, data: Any) -> None:
        """`transcript`, `interrupted` and `busy` events."""
        ...

    async def close(self, code: int = 1000) -> None: ...
