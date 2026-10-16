"""D77: the agent says an item's condition in a few everyday Urdu words."""

import pytest

from lastcall_shared.condition_words import FEED_ONLY, spoken_condition


@pytest.mark.parametrize(
    "stage,issues,spoken",
    [
        ("overripe", [], "thoray pakke huay"),
        ("overripe", ["dark_spots", "browning"], "thoray pakke huay aur daaghi"),
        ("overripe", ["wilting"], "thoray pakke huay aur murjhaye"),
        ("overripe", ["bruising", "shrivelling"], "thoray pakke huay, daaghi aur murjhaye"),
        ("ripening", ["soft_spots"], "pakke huay, thoray daaghi"),
        ("fresh", ["yellowing"], "taaza, thoray daaghi"),
        ("fresh", ["wilting", "dark_spots"], "thoray murjhaye huay"),  # greens: the wilting is what matters
        ("fresh", [], "taaza"),
        ("ripening", [], "pakke huay"),
        ("overripe", ["rot", "mould"], "thoray pakke huay"),  # removed pieces aren't mentioned
        ("spoiled", ["dark_spots"], FEED_ONLY),
        ("unsafe", [], FEED_ONLY),
    ],
)
def test_spoken_condition(stage, issues, spoken):
    assert spoken_condition(stage, issues) == spoken


def test_every_issue_is_either_said_or_deliberately_left_out():
    """A new Inspector issue must be placed in a group (or added to the left-out list) on purpose."""
    from typing import get_args

    from lastcall_shared import condition_words as cw
    from lastcall_shared.models import ProduceIssue

    left_out = {"leaking", "pest_damage", "rot", "slime", "mould"}
    assert set(get_args(ProduceIssue)) == cw._MARKS | cw._WILTING | left_out
