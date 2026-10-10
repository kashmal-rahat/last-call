"""Firestore-backed CallStore implementation using AsyncClient and async transactions (Milestone 2B Step 9)."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from pydantic import AwareDatetime
from google.cloud import firestore
from google.api_core.exceptions import AlreadyExists

from lastcall_shared.config import get_settings
from lastcall_shared.models import (
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
        call_data["expire_at"] = record.created_at + timedelta(days=30)
        await call_ref.set(call_data)

        # Batch write if not exists
        batch_data = batch.model_dump(mode="json")
        await batch_ref.set(batch_data, merge=True)

    async def get_call(self, call_id: str) -> CallRecord | None:
        snap = await self._col("calls").document(call_id).get()
        if not snap.exists:
            return None
        return CallRecord.model_validate(snap.to_dict())

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
                new_status = "finding_buyers" if data.get("status") == "in_negotiation" else data.get("status")
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

    async def incr_daily_sessions(self, date: str, cap: int) -> bool:
        doc_ref = self._col("daily_sessions").document(date)

        @firestore.async_transactional
        async def _tx(transaction: firestore.AsyncTransaction) -> bool:
            snap = await doc_ref.get(transaction=transaction)
            current = 0
            if snap.exists:
                current = int((snap.to_dict() or {}).get("count", 0))
            if current >= cap:
                return False
            transaction.set(doc_ref, {"count": current + 1}, merge=True)
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
        ]
        for col_name in collections:
            col_ref = self._col(col_name)
            async for doc in col_ref.stream():
                await doc.reference.delete()
