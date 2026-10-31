#!/usr/bin/env python3
"""Opt-in reminder routines. One yes does not turn the others on."""

import re


OFFERS = (
    {"id": "daily_checkin", "window_days": None, "title": "Daily check-in"},
    {"id": "evening_followup", "window_days": None, "title": "Evening follow-up"},
    {"id": "weekly_review", "window_days": 7, "title": "Weekly review"},
    {"id": "monthly_review", "window_days": 28, "title": "Monthly review"},
    {"id": "yearly_review", "window_days": 365, "title": "Yearly review"},
)

# The plan yes turns these three on together. Monthly and yearly stay off.
LOOP_IDS = ("daily_checkin", "evening_followup", "weekly_review")
DEFAULT_LOOP_TIMES = {
    "daily_checkin": "07:00",
    "evening_followup": "20:00",
    "weekly_review": "Sun 18:00",
}
_LOOP_SLOT = (
    ("daily_checkin", re.compile(r"\b(?:morning|check-in|checkin)\b")),
    ("evening_followup", re.compile(r"\b(?:evening|follow-up|follow up)\b")),
    ("weekly_review", re.compile(r"\bweekly\b")),
)
_WEEKDAY = re.compile(
    r"\b(sunday|monday|tuesday|wednesday|thursday|friday|saturday)\b"
)

_YES = {"yes", "yes, i confirm."}
_CLOCK = re.compile(
    r"\d|\bam\b|\bpm\b|\bmorning\b|\bevening\b|\bafternoon\b|\bnight\b|"
    r"\bsunday\b|\bmonday\b|\btuesday\b|\bwednesday\b|\bthursday\b|\bfriday\b|\bsaturday\b"
)
_HEDGE = re.compile(
    r"\b(?:no|not|never|stop|later|maybe|sure|whatever|nah|nope|"
    r"don't|dont|won't|wont|can't|cant|think|guess|"
    r"unless|although|though|but|except|if|when|busy)\b"
)
_CLOCK_TIME = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_CLOCK_AMPM = re.compile(r"\b(\d{1,2})\s*(am|pm)\b")
_CLOCK_HOUR = re.compile(r"\b(\d{1,2})\b")


def _real_clock(text):
    """False when a written time cannot exist, such as 25:99."""
    for hour, minute in _CLOCK_TIME.findall(text):
        if int(hour) > 23 or int(minute) > 59:
            return False
    for hour, _marker in _CLOCK_AMPM.findall(text):
        if not 1 <= int(hour) <= 12:
            return False
    for hour in _CLOCK_HOUR.findall(text):
        if int(hour) > 23:
            return False
    return True


def _opted_in(choice, reply, item):
    """A plain yes, or this routine's name together with a real time."""
    if not isinstance(reply, str):
        return False
    text = " ".join(reply.lower().split())
    if text in _YES:
        return True
    if _HEDGE.search(text) or not _real_clock(text):
        return False
    title = item["title"].lower()
    named = title in text or choice.replace("_", " ") in text
    if not named:
        return False
    names_another = any(
        other["title"].lower() in text
        for other in OFFERS
        if other["id"] != choice
    )
    if names_another:
        return False
    return _CLOCK.search(text) is not None


def offer():
    """The four routines. None are on yet."""
    return [dict(item, enabled=False) for item in OFFERS]


def enable(choice, reply):
    known = {item["id"]: item for item in OFFERS}
    if choice not in known:
        return {
            "ok": False,
            "enabled": False,
            "message": "That routine is not one of the four.",
        }
    if not _opted_in(choice, reply, known[choice]):
        return {
            "ok": False,
            "enabled": False,
            "id": choice,
            "message": "That routine stays off until they say yes.",
        }
    return {
        "ok": True,
        "enabled": True,
        "id": choice,
        "window_days": known[choice]["window_days"],
        "message": "That routine is on. The others stay off.",
    }


def _clock_value(text):
    """One real clock, or None. 25:99 is not a time. 6:30 and 8pm are."""
    match = _CLOCK_TIME.search(text)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            return None
        return f"{hour:02d}:{minute:02d}"
    match = _CLOCK_AMPM.search(text)
    if match:
        hour = int(match.group(1))
        if not 1 <= hour <= 12:
            return None
        if match.group(2) == "pm" and hour != 12:
            hour += 12
        if match.group(2) == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:00"
    return None


def start_daily_loop(reply):
    """The plan yes starts morning, evening, and weekly. One reply can change a time later."""
    from record_confirmation import is_clear_yes

    if not is_clear_yes(reply):
        return {
            "ok": False,
            "enabled": [],
            "times": {},
            "message": "The daily loop stays off until they say yes.",
        }
    return {
        "ok": True,
        "enabled": list(LOOP_IDS),
        "times": dict(DEFAULT_LOOP_TIMES),
        "message": (
            "Morning check-in at 07:00, evening follow-up at 20:00, "
            "weekly review Sunday at 18:00. One reply can change a time. "
            "Monthly and yearly stay off."
        ),
    }


def change_loop_time(reply, times):
    """Change a default time in one reply. A bad clock or a hedge leaves the times alone."""
    if not isinstance(reply, str) or not isinstance(times, dict):
        return dict(times or {})
    text = " ".join(reply.lower().split())
    updated = dict(times)
    if _HEDGE.search(text):
        return updated
    clock = _clock_value(text)
    if clock is None:
        return updated
    named = [slot for slot, pattern in _LOOP_SLOT if pattern.search(text)]
    if not named:
        return updated
    day = _WEEKDAY.search(text)
    for slot in named:
        if slot == "weekly_review":
            prefix = day.group(1).title() if day else "Sun"
            updated[slot] = f"{prefix} {clock}"
        else:
            updated[slot] = clock
    return updated
