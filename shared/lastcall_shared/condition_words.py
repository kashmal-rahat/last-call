"""How the agent says an item's condition on the call: a few everyday Urdu words (D77).

The Inspector's reading (stage and issues) is described in English for the page and WhatsApp; on the phone the agent
says it the way a shopkeeper would, and the photo shows the detail. Spoiled stock (sold only as cattle feed) gets one
plain phrase. Issues that mean pieces were removed (rot, mould, slime, leaking, pest damage) aren't mentioned: staff
take those pieces out before a sale, which the buyer understands.
"""

from lastcall_shared.models import ProduceIssue, ProduceStage

FEED_ONLY = "chaare ke liye, khane ke liye nahi"

_RIPENESS: dict[ProduceStage, str] = {"fresh": "taaza", "ripening": "pakke huay", "overripe": "thoray pakke huay"}
_MARKS: set[ProduceIssue] = {"dark_spots", "browning", "bruising", "soft_spots", "yellowing", "splitting"}
_WILTING: set[ProduceIssue] = {"wilting", "shrivelling"}


def spoken_condition(stage: ProduceStage, issues: list[ProduceIssue]) -> str:
    """'thoray pakke huay aur daaghi', 'taaza, thoray daaghi', 'thoray murjhaye huay'; FEED_ONLY when spoiled."""
    if stage not in _RIPENESS:  # spoiled (feed only) or unsafe (never offered)
        return FEED_ONLY
    marks = any(i in _MARKS for i in issues)
    wilting = any(i in _WILTING for i in issues)
    if stage == "overripe":
        defects = [w for w, present in (("daaghi", marks), ("murjhaye", wilting)) if present]
        if not defects:
            return "thoray pakke huay"
        if len(defects) == 1:
            return f"thoray pakke huay aur {defects[0]}"
        return "thoray pakke huay, daaghi aur murjhaye"
    if wilting:  # fresh or ripe leafy greens: the wilting is what a buyer needs to hear
        return "thoray murjhaye huay"
    if marks:
        return f"{_RIPENESS[stage]}, thoray daaghi"
    return _RIPENESS[stage]
