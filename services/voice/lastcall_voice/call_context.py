"""In-process call context registry for tracking active call state."""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal
from pydantic import AwareDatetime
from lastcall_shared.models import NegotiationState
from lastcall_shared.store import CallStore


@dataclass
class CallContext:
    store: CallStore
    call_id: str
    mode: Literal["text", "voice"] = "text"
    closing: bool = False
    outcome_set: bool = False
    outcome: str | None = None
    agreed_price_per_unit: int | None = None
    agreed_quantity: float | None = None
    agreed_quantity_unit: str | None = None
    pickup_time: AwareDatetime | None = None
    callback_at: AwareDatetime | None = None
    buyer_spoke: bool = False
    flags: list[str] = None
    clock: Callable[[], AwareDatetime] | None = None
    negotiation: NegotiationState | None = None
    # Sends an event to whoever plays the buyer (D62): the browser page, or the phone
    # bridge, which forwards WhatsApp messages. None in text mode and the simulator.
    notify: Callable[[dict[str, Any]], Awaitable[None]] | None = None

    def __post_init__(self):
        if self.flags is None:
            self.flags = []


_CONTEXTS: dict[str, CallContext] = {}


def register_context(context: CallContext) -> None:
    _CONTEXTS[context.call_id] = context


def get_context(call_id: str) -> CallContext | None:
    return _CONTEXTS.get(call_id)


def unregister_context(call_id: str) -> None:
    _CONTEXTS.pop(call_id, None)
