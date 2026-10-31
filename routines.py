#!/usr/bin/env python3
"""Opt-in reminder routines. One yes does not turn the others on."""

import re


OFFERS = (
    {"id": "daily_checkin", "window_days": None, "title": "Daily check-in"},
    {"id": "weekly_review", "window_days": 7, "title": "Weekly review"},
    {"id": "monthly_review", "window_days": 28, "title": "Monthly review"},
    {"id": "yearly_review", "window_days": 365, "title": "Yearly review"},
)

_YES = {"yes", "yes, i confirm."}
_CLOCK = re.compile(
    r"\d|\bam\b|\bpm\b|\bmorning\b|\bevening\b|\bafternoon\b|\bnight\b|"
    r"\bsunday\b|\bmonday\b|\btuesday\b|\bwednesday\b|\bthursday\b|\bfriday\b|\bsaturday\b"
)
_HEDGE = re.compile(
    r"\b(?:no|not|never|stop|later|maybe|sure|whatever|nah|nope|"
    r"don't|dont|won't|wont|can't|cant|think|guess)\b"
)


def _opted_in(choice, reply, item):
    """A plain yes, or this routine's name together with a time."""
    if not isinstance(reply, str):
        return False
    text = " ".join(reply.lower().split())
    if text in _YES:
        return True
    if _HEDGE.search(text):
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
