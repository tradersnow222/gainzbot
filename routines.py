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
_TIME = re.compile(
    r"\d|morning|evening|afternoon|night|\bam\b|\bpm\b|"
    r"sunday|monday|tuesday|wednesday|thursday|friday|saturday|"
    r"daily|weekly|monthly|yearly"
)
_REFUSE = re.compile(r"\bno\b|\bnot\b|\bdon'?t\b|\blater\b|\bmaybe\b|\bsure\b|\bwhatever\b")


def _opted_in(choice, reply, item):
    """A clear yes, or the routine and a time they already picked."""
    if not isinstance(reply, str):
        return False
    text = " ".join(reply.lower().split())
    if text in _YES:
        return True
    if _REFUSE.search(text):
        return False
    title = item["title"].lower()
    named = title in text or choice.replace("_", " ") in text
    names_another = any(
        other["title"].lower() in text
        for other in OFFERS
        if other["id"] != choice
    )
    if names_another and not named:
        return False
    return named or _TIME.search(text) is not None


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
