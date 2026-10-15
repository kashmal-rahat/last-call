"""In-process call context registry for tracking active call state."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Literal

from pydantic import AwareDatetime

from lastcall_shared.clock import now_pkt
from lastcall_shared.models import CallingHours, NegotiationState
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
    clock: Callable[[], AwareDatetime] | None = None  # the real time: record timestamps
    # The mart's time (D74): pickup and call-back times. None → the same as `clock` (text sessions, the simulator)
    mart_clock: Callable[[], AwareDatetime] | None = None
    negotiation: NegotiationState | None = None
    # Sends an event to whoever plays the buyer (D62): the browser page, or the phone
    # bridge, which forwards WhatsApp messages. None in text mode and the simulator.
    notify: Callable[[dict[str, Any]], Awaitable[None]] | None = None

    def __post_init__(self):
        if self.flags is None:
            self.flags = []

    def now(self) -> datetime:
        """The real time, for record timestamps."""
        return self.clock() if self.clock else now_pkt()

    def mart_now(self) -> datetime:
        """The mart's time, for anything the buyer agrees to: pickup and call-back times (D74)."""
        return self.mart_clock() if self.mart_clock else self.now()

    def retry_after_drop(self, calling_hours: CallingHours) -> datetime:
        """When to call again after a call ended mid-conversation with no outcome: 2 h later in the mart's day,
        moved to the next start of calling hours if that falls outside them."""
        at = self.mart_now() + timedelta(hours=2)
        if at.time() < calling_hours.start:
            return at.replace(hour=calling_hours.start.hour, minute=calling_hours.start.minute, second=0)
        if at.time() > calling_hours.end:
            return (at + timedelta(days=1)).replace(
                hour=calling_hours.start.hour, minute=calling_hours.start.minute, second=0
            )
        return at


_CONTEXTS: dict[str, CallContext] = {}


def register_context(context: CallContext) -> None:
    _CONTEXTS[context.call_id] = context


def get_context(call_id: str) -> CallContext | None:
    return _CONTEXTS.get(call_id)


def unregister_context(call_id: str) -> None:
    _CONTEXTS.pop(call_id, None)
