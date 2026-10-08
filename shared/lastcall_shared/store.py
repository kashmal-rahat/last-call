"""Store layer protocol and thread-safe in-memory store for Last Call."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Protocol
from pydantic import AwareDatetime

from lastcall_shared.models import (
    BatchRecord,
    CallRecord,
    CallResult,
    DealRecord,
    NegotiationState,
    OutboxMessage,
    StaffTask,
    TranscriptEntry,
)


class CallStore(Protocol):
    """Protocol for call and deal storage."""

    async def create_call(self, record: CallRecord, batch: BatchRecord) -> None: ...
    async def get_call(self, call_id: str) -> CallRecord | None: ...
    async def get_batch(self, batch_id: str) -> BatchRecord | None: ...
    async def get_deal(self, call_id: str) -> DealRecord | None: ...
    async def start_session(self, call_id: str, nonce: str) -> bool: ...
    async def save_negotiation(self, call_id: str, state: NegotiationState) -> None: ...
    async def append_transcript(self, call_id: str, entries: list[TranscriptEntry]) -> None: ...
    async def add_flag(self, call_id: str, flag: str) -> None: ...
    async def lock_batch(self, batch_id: str, call_id: str, until: AwareDatetime) -> bool: ...
    async def release_batch(self, batch_id: str, call_id: str) -> None: ...
    async def save_deal_tx(self, call_id: str, deal: DealRecord, quantity: float) -> tuple[bool, str | None]: ...
    async def add_do_not_call(self, mart_id: str, buyer_id: str) -> None: ...
    async def is_do_not_call(self, mart_id: str, buyer_id: str) -> bool: ...
    async def add_outbox(self, msg: OutboxMessage) -> None: ...
    async def get_outbox(self, call_id: str | None = None) -> list[OutboxMessage]: ...
    async def add_staff_task(self, task: StaffTask) -> None: ...
    async def get_staff_tasks(self, call_id: str | None = None) -> list[StaffTask]: ...
    async def finish_call(self, call_id: str, result: CallResult) -> None: ...
    async def incr_daily_sessions(self, date: str, cap: int) -> bool: ...


class InMemoryStore:
    """Thread-safe and async-safe in-memory store implementation."""

    def __init__(self, clock: Any = None):
        self._lock = asyncio.Lock()
        self.clock = clock
        self.calls: dict[str, CallRecord] = {}
        self.batches: dict[str, BatchRecord] = {}
        self.deals: dict[str, DealRecord] = {}
        self.do_not_call: set[tuple[str, str]] = set()  # (mart_id, buyer_id)
        self.outbox: list[OutboxMessage] = []
        self.staff_tasks: list[StaffTask] = []
        self.daily_sessions: dict[str, int] = {}  # date_str -> count

    def _now(self) -> datetime:
        if self.clock:
            dt = self.clock()
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc)

    async def create_call(self, record: CallRecord, batch: BatchRecord) -> None:
        async with self._lock:
            self.calls[record.call_id] = record
            if batch.batch_id not in self.batches:
                self.batches[batch.batch_id] = batch

    async def get_call(self, call_id: str) -> CallRecord | None:
        async with self._lock:
            return self.calls.get(call_id)

    async def get_batch(self, batch_id: str) -> BatchRecord | None:
        async with self._lock:
            return self.batches.get(batch_id)

    async def get_deal(self, call_id: str) -> DealRecord | None:
        async with self._lock:
            return self.deals.get(call_id)

    async def start_session(self, call_id: str, nonce: str) -> bool:
        async with self._lock:
            call = self.calls.get(call_id)
            if not call:
                return False
            if call.status != "pending":
                return False
            if call.session_nonce != nonce:
                return False
            call.status = "in_progress"
            return True

    async def save_negotiation(self, call_id: str, state: NegotiationState) -> None:
        async with self._lock:
            call = self.calls.get(call_id)
            if call:
                call.negotiation = state

    async def append_transcript(self, call_id: str, entries: list[TranscriptEntry]) -> None:
        async with self._lock:
            call = self.calls.get(call_id)
            if call:
                call.transcript.extend(entries)

    async def add_flag(self, call_id: str, flag: str) -> None:
        async with self._lock:
            call = self.calls.get(call_id)
            if call and flag not in call.flags:
                call.flags.append(flag)

    async def lock_batch(self, batch_id: str, call_id: str, until: AwareDatetime) -> bool:
        async with self._lock:
            batch = self.batches.get(batch_id)
            if not batch:
                return False

            now = self._now()
            # Check existing lock and lazy expiry
            if batch.locked_by_call and batch.locked_by_call != call_id:
                if batch.locked_until and batch.locked_until > now:
                    # Locked by another active call
                    return False

            # Lock is either free, owned by this call, or expired
            batch.locked_by_call = call_id
            batch.locked_until = until
            batch.status = "in_negotiation"
            return True

    async def release_batch(self, batch_id: str, call_id: str) -> None:
        async with self._lock:
            batch = self.batches.get(batch_id)
            if batch and batch.locked_by_call == call_id:
                batch.locked_by_call = None
                batch.locked_until = None
                if batch.status == "in_negotiation":
                    batch.status = "finding_buyers"

    async def save_deal_tx(self, call_id: str, deal: DealRecord, quantity: float) -> tuple[bool, str | None]:
        async with self._lock:
            batch = self.batches.get(deal.batch_id)
            if not batch:
                return False, "Batch not found"

            # Check lock ownership
            now = self._now()
            if batch.locked_by_call != call_id:
                return False, "Batch is not locked by this call"
            if batch.locked_until and batch.locked_until <= now:
                return False, "Batch lock has expired"

            # Idempotency check on existing deal
            existing = self.deals.get(call_id)
            if existing:
                if (
                    existing.price_per_unit == deal.price_per_unit
                    and existing.quantity == deal.quantity
                    and existing.pickup_time == deal.pickup_time
                    and existing.payment_terms == deal.payment_terms
                ):
                    return True, None
                return False, "Deal already recorded with different terms"

            # Check quantity
            if batch.remaining_quantity < quantity:
                return False, f"Insufficient stock: requested {quantity}, available {batch.remaining_quantity}"

            # Apply all-or-nothing changes
            self.deals[call_id] = deal
            batch.remaining_quantity -= quantity
            if batch.remaining_quantity <= 0:
                batch.remaining_quantity = 0.0
                batch.status = "sold"
            else:
                batch.status = "partly_sold"

            return True, None

    async def add_do_not_call(self, mart_id: str, buyer_id: str) -> None:
        async with self._lock:
            self.do_not_call.add((mart_id, buyer_id))

    async def is_do_not_call(self, mart_id: str, buyer_id: str) -> bool:
        async with self._lock:
            return (mart_id, buyer_id) in self.do_not_call

    async def add_outbox(self, msg: OutboxMessage) -> None:
        async with self._lock:
            self.outbox.append(msg)

    async def get_outbox(self, call_id: str | None = None) -> list[OutboxMessage]:
        async with self._lock:
            if call_id:
                return [m for m in self.outbox if m.call_id == call_id]
            return list(self.outbox)

    async def add_staff_task(self, task: StaffTask) -> None:
        async with self._lock:
            self.staff_tasks.append(task)

    async def get_staff_tasks(self, call_id: str | None = None) -> list[StaffTask]:
        async with self._lock:
            if call_id:
                return [t for t in self.staff_tasks if t.call_id == call_id]
            return list(self.staff_tasks)

    async def finish_call(self, call_id: str, result: CallResult) -> None:
        async with self._lock:
            call = self.calls.get(call_id)
            if not call:
                raise ValueError(f"Call {call_id} not found")
            call.result = result
            call.status = "completed"

    async def incr_daily_sessions(self, date: str, cap: int) -> bool:
        async with self._lock:
            current = self.daily_sessions.get(date, 0)
            if current >= cap:
                return False
            self.daily_sessions[date] = current + 1
            return True
