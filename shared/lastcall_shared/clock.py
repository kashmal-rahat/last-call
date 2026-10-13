"""Mart time: the Pakistan timezone and the time wording used in prompts, briefs and messages."""

from datetime import datetime
from zoneinfo import ZoneInfo

PKT = ZoneInfo("Asia/Karachi")


def now_pkt() -> datetime:
    return datetime.now(PKT)


def clock_words(dt: datetime) -> str:
    """'6 PM', '6:30 PM'."""
    hour = dt.strftime("%I").lstrip("0")
    minute = dt.strftime("%M")
    return f"{hour}:{minute} {dt.strftime('%p')}" if minute != "00" else f"{hour} {dt.strftime('%p')}"


def time_words(dt: datetime) -> str:
    """'13 October, 6 PM': the date and time the agent says and the brief shows."""
    return f"{dt.strftime('%d %B')}, {clock_words(dt)}"
