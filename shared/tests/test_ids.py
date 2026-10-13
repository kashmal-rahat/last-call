"""Generated identifiers always pass the patterns every API boundary validates against."""

from datetime import datetime
from zoneinfo import ZoneInfo

from lastcall_shared import ids


def test_generated_ids_match_their_patterns():
    inspection_id = ids.new_inspection_id(datetime(2026, 10, 13, 14, 25, 1, tzinfo=ZoneInfo("Asia/Karachi")))
    assert ids.INSPECTION_ID.match(inspection_id)
    assert ids.CALL_ID.match(ids.new_call_id())
    batch_id = ids.make_batch_id(inspection_id, "banana_top_left_2", "johar_town")
    assert ids.BATCH_ID.match(batch_id)


def test_patterns_reject_lookalikes():
    assert not ids.INSPECTION_ID.match("insp_../../etc")
    assert not ids.ITEM_KEY.match("Banana")
    assert not ids.CALL_ID.match("call_" + "z" * 32)
    assert not ids.BATCH_ID.match("insp_1__banana")
    assert ids.E164.match("+923001234567") and not ids.E164.match("03001234567")
