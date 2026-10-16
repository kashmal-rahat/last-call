"""Mart time: the Pakistan timezone and the time wording used in prompts, briefs and messages.

Two clocks (D74). The **real** time runs the system: tokens, locks, caps, cooldowns and record timestamps. The
**mart's** time is what the mart, the agent and the buyer live in: pickup windows, calling hours, call-backs and
"current time". It is the real time moved by a fixed shift (`clock_offset_s`), set by the page's Time of day
preset when the decision is made (0 for "Now") and copied to the batch and the call. One function adds it.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

PKT = ZoneInfo("Asia/Karachi")

MAX_CLOCK_OFFSET_S = 24 * 3600  # a preset's time is on the same day as the real time, so always within a day


def now_pkt() -> datetime:
    return datetime.now(PKT)


def mart_now(clock_offset_s: float, now: datetime | None = None) -> datetime:
    """The mart's time: `now` (default: the real time in Pakistan) moved by the shift (D74)."""
    return (now if now is not None else now_pkt()) + timedelta(seconds=clock_offset_s)


def clock_words(dt: datetime) -> str:
    """'6 PM', '6:30 PM'."""
    hour = dt.strftime("%I").lstrip("0")
    minute = dt.strftime("%M")
    return f"{hour}:{minute} {dt.strftime('%p')}" if minute != "00" else f"{hour} {dt.strftime('%p')}"


def time_words(dt: datetime) -> str:
    """'13 October, 6 PM': the date and time the agent says and the brief shows."""
    return f"{dt.strftime('%d %B')}, {clock_words(dt)}"


def day_words(dt: datetime, now: datetime) -> str:
    """'today', 'tomorrow' or 'Sat 17 Oct': the day of `dt` seen from `now`, in `dt`'s timezone (the mart's)."""
    today = now.astimezone(dt.tzinfo).date()
    if dt.date() == today:
        return "today"
    if dt.date() == today + timedelta(days=1):
        return "tomorrow"
    return dt.strftime("%a %d %b")


def pickup_by_words(deadline: datetime, now: datetime) -> str:
    """'today, 4:30 PM', 'tomorrow, 12 PM': the pickup deadline as the page, WhatsApp and the agent's brief say it
    (D76; pickup is "by the deadline", with no start time)."""
    return f"{day_words(deadline, now)}, {clock_words(deadline)}"
