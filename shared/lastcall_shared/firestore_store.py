"""Firestore-backed CallStore implementation using AsyncClient and async transactions (Milestone 2B Step 9)."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from pydantic import AwareDatetime
from google.cloud import firestore
from google.api_core.exceptions import AlreadyExists, NotFound

from lastcall_shared.config import get_settings
from lastcall_shared.models import (
    BatchAttempt,
    BatchRecord,
    CallRecord,
    CallResult,
    DealRecord,
    FreshnessResult,
    NegotiationState,
    OutboxMessage,
    StaffTask,
    TranscriptEntry,
    ProduceProfile,
    LadderResult,
    BuyerHistory,
    CallOutcome,
    ScoutResult,
    Unit,
)


class FirestoreStore:
    """Production and integration Firestore implementation of CallStore."""

    def __init__(
        self,
        client: firestore.AsyncClient | None = None,
        project: str | None = None,
        database: str = "(default)",
        collection_prefix: str = "",
        clock: Any = None,
    ):
        self.project = project or get_settings().GOOGLE_CLOUD_PROJECT
        self.database = database
        self.client = client or firestore.AsyncClient(project=self.project, database=self.database)
        self.collection_prefix = collection_prefix
        self.clock = clock

    def _col(self, name: str):
        return self.client.collection(f"{self.collection_prefix}{name}")

    def _now(self) -> datetime:
        if self.clock:
            dt = self.clock()
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc)

    async def create_call(self, record: CallRecord, batch: BatchRecord) -> None:
        call_ref = self._col("calls").document(record.call_id)
        batch_ref = self._col("batches").document(batch.batch_id)

        call_data = record.model_dump(mode="json")
        # Ensure expire_at is set as a real datetime for Firestore TTL policy
        call_data["expire_at"] = record.expire_at
        await call_ref.set(call_data)

        # Batch write if not exists
        batch_data = batch.model_dump(mode="json")
        try:
            await batch_ref.create(batch_data)
        except AlreadyExists:
            pass

    async def get_call(self, call_id: str) -> CallRecord | None:
        snap = await self._col("calls").document(call_id).get()
        if not snap.exists:
            return None
        return CallRecord.model_validate(snap.to_dict())

    async def get_calls(self, call_ids: list[str]) -> dict[str, CallRecord]:
        if not call_ids:
            return {}
        doc_refs = [self._col("calls").document(c_id) for c_id in call_ids]
        out: dict[str, CallRecord] = {}
        async for snap in self.client.get_all(doc_refs):
            if snap.exists:
                data = snap.to_dict()
                if data:
                    out[snap.id] = CallRecord.model_validate(data)
        return out

    async def create_batch(self, batch: BatchRecord) -> BatchRecord:
        batch_ref = self._col("batches").document(batch.batch_id)
        batch_data = batch.model_dump(mode="json")
        try:
            await batch_ref.create(batch_data)
            return batch
        except AlreadyExists:
            snap = await batch_ref.get()
            return BatchRecord.model_validate(snap.to_dict())

    async def add_batch_attempt(self, batch_id: str, attempt: BatchAttempt) -> None:
        batch_ref = self._col("batches").document(batch_id)
        await batch_ref.update({"attempts": firestore.ArrayUnion([attempt.model_dump(mode="json")])})

    async def advance_batch_step(self, batch_id: str, from_index: int) -> bool:
        batch_ref = self._col("batches").document(batch_id)

        @firestore.async_transactional
        async def _tx(transaction: firestore.AsyncTransaction) -> bool:
            snap = await batch_ref.get(transaction=transaction)
            if not snap.exists:
                return False
            data = snap.to_dict() or {}
            current_idx = int(data.get("step_index", 0))
            if current_idx == from_index:
                transaction.update(batch_ref, {"step_index": current_idx + 1})
                return True
            return False

        tx = self.client.transaction()
        return await _tx(tx)

    async def get_batch(self, batch_id: str) -> BatchRecord | None:
        snap = await self._col("batches").document(batch_id).get()
        if not snap.exists:
            return None
        return BatchRecord.model_validate(snap.to_dict())

    async def get_deal(self, call_id: str) -> DealRecord | None:
        snap = await self._col("deals").document(call_id).get()
        if not snap.exists:
            return None
        return DealRecord.model_validate(snap.to_dict())

    async def start_session(self, call_id: str, nonce: str) -> bool:
        doc_ref = self._col("calls").document(call_id)

        @firestore.async_transactional
        async def _tx(transaction: firestore.AsyncTransaction) -> bool:
            snap = await doc_ref.get(transaction=transaction)
            if not snap.exists:
                return False
            data = snap.to_dict() or {}
            if data.get("status") != "pending" or data.get("session_nonce") != nonce:
                return False
            transaction.update(doc_ref, {"status": "in_progress"})
            return True

        tx = self.client.transaction()
        return await _tx(tx)

    async def save_negotiation(self, call_id: str, state: NegotiationState) -> None:
        doc_ref = self._col("calls").document(call_id)
        await doc_ref.update({"negotiation": state.model_dump(mode="json")})

    async def append_transcript(self, call_id: str, entries: list[TranscriptEntry]) -> None:
        doc_ref = self._col("calls").document(call_id)

        @firestore.async_transactional
        async def _tx(transaction: firestore.AsyncTransaction) -> None:
            snap = await doc_ref.get(transaction=transaction)
            if snap.exists:
                data = snap.to_dict() or {}
                current = data.get("transcript", [])
                new_entries = [e.model_dump(mode="json") for e in entries]
                current.extend(new_entries)
                transaction.update(doc_ref, {"transcript": current})

        tx = self.client.transaction()
        await _tx(tx)

    async def add_flag(self, call_id: str, flag: str) -> None:
        doc_ref = self._col("calls").document(call_id)
        await doc_ref.update({"flags": firestore.ArrayUnion([flag])})

    async def append_live_line(self, call_id: str, line: dict[str, Any]) -> None:
        # Phone demo (Module 9): lines live on the call doc, so they share its 24 h TTL.
        # Each line carries its index "i", so ArrayUnion never merges two lines.
        doc_ref = self._col("calls").document(call_id)
        try:
            await doc_ref.update({"live_lines": firestore.ArrayUnion([dict(line)])})
        except NotFound:
            pass

    async def get_live_lines(self, call_id: str) -> list[dict[str, Any]]:
        snap = await self._col("calls").document(call_id).get(field_paths=["live_lines"])
        if not snap.exists:
            return []
        return list((snap.to_dict() or {}).get("live_lines", []))

    async def lock_batch(self, batch_id: str, call_id: str, until: AwareDatetime) -> bool:
        batch_ref = self._col("batches").document(batch_id)
        now = self._now()

        @firestore.async_transactional
        async def _tx(transaction: firestore.AsyncTransaction) -> bool:
            snap = await batch_ref.get(transaction=transaction)
            if not snap.exists:
                return False
            data = snap.to_dict() or {}

            locked_by = data.get("locked_by_call")
            locked_until_raw = data.get("locked_until")
            locked_until = None
            if locked_until_raw:
                if isinstance(locked_until_raw, str):
                    locked_until = datetime.fromisoformat(locked_until_raw)
                elif isinstance(locked_until_raw, datetime):
                    locked_until = locked_until_raw

            if locked_by and locked_by != call_id:
                if locked_until and locked_until > now:
                    return False

            transaction.update(
                batch_ref,
                {
                    "locked_by_call": call_id,
                    "locked_until": until.isoformat() if until else None,
                    "status": "in_negotiation",
                },
            )
            return True

        tx = self.client.transaction()
        return await _tx(tx)

    async def release_batch(self, batch_id: str, call_id: str) -> None:
        batch_ref = self._col("batches").document(batch_id)

        @firestore.async_transactional
        async def _tx(transaction: firestore.AsyncTransaction) -> None:
            snap = await batch_ref.get(transaction=transaction)
            if not snap.exists:
                return
            data = snap.to_dict() or {}
            if data.get("locked_by_call") == call_id:
                status = data.get("status")
                new_status = status
                if status == "in_negotiation":
                    rem = float(data.get("remaining_quantity", 0.0))
                    total = float(data.get("total_quantity", 0.0))
                    if 0 < rem < total:
                        new_status = "partly_sold"
                    elif rem == 0:
                        new_status = "sold"
                    else:
                        new_status = "finding_buyers"
                transaction.update(
                    batch_ref,
                    {
                        "locked_by_call": None,
                        "locked_until": None,
                        "status": new_status,
                    },
                )

        tx = self.client.transaction()
        await _tx(tx)

    async def save_deal_tx(self, call_id: str, deal: DealRecord, quantity: float) -> tuple[bool, str | None]:
        batch_ref = self._col("batches").document(deal.batch_id)
        deal_ref = self._col("deals").document(call_id)
        now = self._now()

        @firestore.async_transactional
        async def _tx(transaction: firestore.AsyncTransaction) -> tuple[bool, str | None]:
            batch_snap = await batch_ref.get(transaction=transaction)
            if not batch_snap.exists:
                return False, "Batch not found"
            batch_data = batch_snap.to_dict() or {}

            # Lock check
            locked_by = batch_data.get("locked_by_call")
            if locked_by != call_id:
                return False, "Batch is not locked by this call"

            locked_until_raw = batch_data.get("locked_until")
            if locked_until_raw:
                locked_until = (
                    datetime.fromisoformat(locked_until_raw)
                    if isinstance(locked_until_raw, str)
                    else locked_until_raw
                )
                if locked_until <= now:
                    return False, "Batch lock has expired"

            # Idempotency check on existing deal
            deal_snap = await deal_ref.get(transaction=transaction)
            if deal_snap.exists:
                existing = deal_snap.to_dict() or {}
                p_time_raw = existing.get("pickup_time")
                existing_time_str = (
                    p_time_raw if isinstance(p_time_raw, str)
                    else p_time_raw.isoformat() if p_time_raw else None
                )
                deal_time_str = deal.pickup_time.isoformat() if deal.pickup_time else None

                if (
                    existing.get("price_per_unit") == deal.price_per_unit
                    and existing.get("quantity") == deal.quantity
                    and existing_time_str == deal_time_str
                    and existing.get("payment_terms") == deal.payment_terms
                ):
                    return True, None
                return False, "Deal already recorded with different terms"

            rem_qty = float(batch_data.get("remaining_quantity", 0.0))
            if rem_qty < quantity:
                return False, f"Insufficient stock: requested {quantity}, available {rem_qty}"

            # Apply changes
            new_rem = max(0.0, rem_qty - quantity)
            new_status = "sold" if new_rem <= 0 else "partly_sold"

            transaction.set(deal_ref, deal.model_dump(mode="json"))
            transaction.update(
                batch_ref,
                {
                    "remaining_quantity": new_rem,
                    "status": new_status,
                },
            )
            return True, None

        tx = self.client.transaction()
        return await _tx(tx)

    async def add_do_not_call(self, mart_id: str, buyer_id: str) -> None:
        doc_id = f"{mart_id}_{buyer_id}"
        await self._col("do_not_call").document(doc_id).set(
            {
                "mart_id": mart_id,
                "buyer_id": buyer_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    async def is_do_not_call(self, mart_id: str, buyer_id: str) -> bool:
        doc_id = f"{mart_id}_{buyer_id}"
        snap = await self._col("do_not_call").document(doc_id).get()
        return snap.exists

    async def add_outbox(self, msg: OutboxMessage) -> None:
        doc_id = getattr(msg, "outbox_id", None) or uuid.uuid4().hex
        await self._col("outbox").document(doc_id).set(msg.model_dump(mode="json"))

    async def get_outbox(self, call_id: str | None = None) -> list[OutboxMessage]:
        col = self._col("outbox")
        if call_id:
            query = col.where(filter=firestore.FieldFilter("call_id", "==", call_id))
        else:
            query = col
        docs = [d async for d in query.stream()]
        return [OutboxMessage.model_validate(d.to_dict()) for d in docs]

    async def add_staff_task(self, task: StaffTask) -> None:
        doc_id = getattr(task, "task_id", None) or uuid.uuid4().hex
        await self._col("staff_tasks").document(doc_id).set(task.model_dump(mode="json"))

    async def get_staff_tasks(self, call_id: str | None = None) -> list[StaffTask]:
        col = self._col("staff_tasks")
        if call_id:
            query = col.where(filter=firestore.FieldFilter("call_id", "==", call_id))
        else:
            query = col
        docs = [d async for d in query.stream()]
        return [StaffTask.model_validate(d.to_dict()) for d in docs]

    async def finish_call(self, call_id: str, result: CallResult) -> None:
        doc_ref = self._col("calls").document(call_id)
        await doc_ref.update(
            {
                "status": "completed",
                "result": result.model_dump(mode="json"),
            }
        )

    async def incr_daily_sessions(self, date: str, cap: int, amount: int = 1) -> bool:
        doc_ref = self._col("daily_sessions").document(date)

        @firestore.async_transactional
        async def _tx(transaction: firestore.AsyncTransaction) -> bool:
            snap = await doc_ref.get(transaction=transaction)
            current = 0
            if snap.exists:
                current = int((snap.to_dict() or {}).get("count", 0))
            if current + amount > cap:
                return False
            transaction.set(doc_ref, {"count": current + amount}, merge=True)
            return True

        tx = self.client.transaction()
        return await _tx(tx)

    async def save_inspection(self, result: FreshnessResult) -> None:
        batch = self.client.batch()
        insp_ref = self._col("inspections").document(result.inspection_id)
        shelf_ref = self._col("shelves").document(f"{result.mart_id}__{result.shelf_id}")
        batch.set(insp_ref, result.model_dump(mode="json"))
        batch.set(
            shelf_ref,
            {
                "latest_inspection_id": result.inspection_id,
                "updated_at": self._now().isoformat(),
            },
        )
        await batch.commit()

    async def get_inspection(self, inspection_id: str) -> FreshnessResult | None:
        snap = await self._col("inspections").document(inspection_id).get()
        if not snap.exists:
            return None
        return FreshnessResult.model_validate(snap.to_dict())

    async def get_latest_inspection(self, mart_id: str, shelf_id: str) -> FreshnessResult | None:
        snap = await self._col("shelves").document(f"{mart_id}__{shelf_id}").get()
        if not snap.exists:
            return None
        latest_id = (snap.to_dict() or {}).get("latest_inspection_id")
        if not latest_id:
            return None
        return await self.get_inspection(latest_id)

    async def get_profiles(self, keys: list[str]) -> dict[str, ProduceProfile]:
        if not keys:
            return {}
        doc_refs = [self._col("produce_knowledge").document(k) for k in keys]
        out: dict[str, ProduceProfile] = {}
        async for snap in self.client.get_all(doc_refs):
            if snap.exists:
                data = snap.to_dict()
                if data:
                    out[snap.id] = ProduceProfile.model_validate(data)
        return out

    async def create_profile(self, profile: ProduceProfile) -> bool:
        doc_ref = self._col("produce_knowledge").document(profile.key)
        try:
            await doc_ref.create(profile.model_dump(mode="json"))
            return True
        except AlreadyExists:
            return False

    async def set_profile(self, profile: ProduceProfile) -> None:
        doc_ref = self._col("produce_knowledge").document(profile.key)
        await doc_ref.set(profile.model_dump(mode="json"))

    async def delete_profile(self, key: str) -> None:
        doc_ref = self._col("produce_knowledge").document(key)
        await doc_ref.delete()

    async def save_decisions(self, result: LadderResult) -> None:
        doc_ref = self._col("decisions").document(result.inspection_id)
        await doc_ref.set(result.model_dump(mode="json"))

    async def get_decisions(self, inspection_id: str) -> LadderResult | None:
        doc_ref = self._col("decisions").document(inspection_id)
        snap = await doc_ref.get()
        if not snap.exists:
            return None
        data = snap.to_dict()
        return LadderResult.model_validate(data) if data else None

    async def get_reading(self, key: str) -> dict[str, Any] | None:
        doc_ref = self._col("inspector_readings").document(key)
        snap = await doc_ref.get()
        if not snap.exists:
            return None
        return snap.to_dict()

    async def create_reading(self, key: str, data: dict[str, Any]) -> bool:
        doc_ref = self._col("inspector_readings").document(key)
        try:
            await doc_ref.create(data)
            return True
        except AlreadyExists:
            return False

    async def save_scout_result(self, r: ScoutResult) -> None:
        doc_ref = self._col("scout_results").document(r.key)
        data = r.model_dump(mode="json")
        # Store expire_at as a real datetime for Firestore TTL policy
        data["expire_at"] = r.expire_at
        await doc_ref.set(data)

    async def get_scout_result(self, key: str) -> ScoutResult | None:
        doc_ref = self._col("scout_results").document(key)
        snap = await doc_ref.get()
        if not snap.exists:
            return None
        data = snap.to_dict()
        if not data:
            return None
        res = ScoutResult.model_validate(data)
        if self._now() >= res.expire_at:
            return None
        return res

    async def get_buyer_histories(self, mart_id: str, buyer_ids: list[str]) -> dict[str, BuyerHistory]:
        if not buyer_ids:
            return {}
        doc_refs = [self._col("buyers").document(f"{mart_id}__{b_id}") for b_id in buyer_ids]
        out: dict[str, BuyerHistory] = {}
        async for snap in self.client.get_all(doc_refs):
            if snap.exists:
                data = snap.to_dict()
                if data:
                    bh = BuyerHistory.model_validate(data)
                    out[bh.buyer_id] = bh
        return out

    async def record_buyer_call(
        self,
        mart_id: str,
        buyer_id: str,
        place_id: str,
        outcome: CallOutcome,
        at: AwareDatetime,
        price: int | None = None,
        unit: Unit | None = None,
    ) -> None:
        doc_ref = self._col("buyers").document(f"{mart_id}__{buyer_id}")

        @firestore.async_transactional
        async def _tx(transaction: firestore.AsyncTransaction) -> None:
            snap = await doc_ref.get(transaction=transaction)
            is_deal = outcome in ("deal", "partial_deal")
            if snap.exists:
                data = snap.to_dict() or {}
                calls = data.get("calls", 0) + 1
                deals = data.get("deals", 0) + (1 if is_deal else 0)
                updates: dict[str, Any] = {
                    "calls": calls,
                    "deals": deals,
                    "last_called_at": at,
                    "last_outcome": outcome,
                }
                if is_deal:
                    updates["last_deal_at"] = at
                    updates["last_deal_price"] = price
                    updates["last_deal_unit"] = unit
                transaction.update(doc_ref, updates)
            else:
                new_data = {
                    "mart_id": mart_id,
                    "buyer_id": buyer_id,
                    "place_id": place_id,
                    "calls": 1,
                    "deals": 1 if is_deal else 0,
                    "last_called_at": at,
                    "last_outcome": outcome,
                    "last_deal_at": at if is_deal else None,
                    "last_deal_price": price if is_deal else None,
                    "last_deal_unit": unit if is_deal else None,
                }
                transaction.set(doc_ref, new_data)

        tx = self.client.transaction()
        await _tx(tx)

    async def get_do_not_call(self, mart_id: str, keys: list[str]) -> set[str]:
        if not keys:
            return set()
        doc_refs = [self._col("do_not_call").document(f"{mart_id}_{k}") for k in keys]
        out: set[str] = set()
        async for snap in self.client.get_all(doc_refs):
            if snap.exists:
                data = snap.to_dict() or {}
                b_id = data.get("buyer_id")
                if b_id:
                    out.add(b_id)
                else:
                    out.add(snap.id[len(mart_id) + 1:])
        return out

    async def clean_prefix(self) -> None:
        """Deletes all test documents created under collection_prefix."""
        if not self.collection_prefix:
            return
        collections = [
            "calls",
            "batches",
            "deals",
            "do_not_call",
            "outbox",
            "staff_tasks",
            "daily_sessions",
            "inspections",
            "shelves",
            "produce_knowledge",
            "decisions",
            "inspector_readings",
            "scout_results",
            "buyers",
        ]
        for col_name in collections:
            col_ref = self._col(col_name)
            async for doc in col_ref.stream():
                await doc.reference.delete()
