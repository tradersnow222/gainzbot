#!/usr/bin/env python3
"""Opt-in reminder routines. One yes does not turn the others on."""

import re
import unicodedata


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


_YES_PREFIXES = (
    "yes i confirm this plan",
    "yes i confirm this change",
    "yes i confirm",
    "i confirm this plan",
    "i confirm this change",
    "i confirm",
    "sounds good",
    "lock it in",
    "lets go",
    "ok fine",
    "confirmed",
    "confirm",
    "yeah",
    "yep",
    "okay",
    "yes",
    "ok",
    "do it",
)
_SCHEDULE_CLAUSE = re.compile(
    r"^(?P<off>no\s+)?"
    r"(?P<slot>check\sin|follow\sup|morning|evening|weekly|review)"
    r"(?:\s+(?P<day>sunday|monday|tuesday|wednesday|thursday|friday|saturday))?"
    r"(?:\s+one)?"
    r"(?:"
    r"\s+(?P<hm>\d{1,2}:\d{2})(?:\s*(?P<hmampm>am|pm))?"
    r"|\s+(?P<h>\d{1,2})\s*(?P<hampm>am|pm)"
    r")?"
)
_SLOT_IDS = {
    "morning": "daily_checkin",
    "check in": "daily_checkin",
    "evening": "evening_followup",
    "follow up": "evening_followup",
    "weekly": "weekly_review",
    "review": "weekly_review",
}


def _schedule_text(reply):
    """Fold a reply for a schedule yes. Other scripts and other emoji refuse."""
    from record_confirmation import _ALLOWED_EMOJI, _SKIN_TONE, _VARIATION, _has_format_character

    if not isinstance(reply, str) or not reply.strip():
        return None
    if "?" in reply or "？" in reply or "</3" in reply or _has_format_character(reply):
        return None
    folded = _VARIATION.sub("", _SKIN_TONE.sub("", reply.lower()))
    folded = folded.replace("'", "").replace("’", "").replace("-", " ")
    kept = []
    for char in folded:
        if char in _ALLOWED_EMOJI or char.isspace():
            kept.append(" ")
            continue
        if char.isdigit() or char == ":" or ("a" <= char <= "z"):
            kept.append(char)
            continue
        if ord(char) < 128 and unicodedata.category(char).startswith("P"):
            kept.append(" ")
            continue
        return None
    return " ".join("".join(kept).split())


def _split_yes(text):
    for prefix in _YES_PREFIXES:
        if text == prefix:
            return ""
        if text.startswith(prefix + " "):
            return text[len(prefix) + 1:]
    return None


def _clause_clock(match):
    """A clock from one clause. None means no clock. False means a bad clock."""
    if match.group("hm"):
        hour_text, minute_text = match.group("hm").split(":")
        hour, minute = int(hour_text), int(minute_text)
        marker = match.group("hmampm")
    elif match.group("h"):
        hour, minute = int(match.group("h")), 0
        marker = match.group("hampm")
    else:
        return None
    if minute > 59:
        return False
    if marker in {"am", "pm"}:
        if not 1 <= hour <= 12:
            return False
        if marker == "pm" and hour != 12:
            hour += 12
        if marker == "am" and hour == 12:
            hour = 0
    elif hour > 23:
        return False
    return f"{hour:02d}:{minute:02d}"


def plan_schedule(reply):
    """A yes followed only by routine-schedule edits, or None.

    The plan itself is unchanged. Morning, evening, and weekly times can move,
    and one of those three can be turned off. Any other word refuses.
    """
    from record_confirmation import reply_pause

    if reply_pause(reply) is not None:
        return None
    text = _schedule_text(reply)
    if text is None:
        return None
    rest = _split_yes(text)
    if rest is None or not rest:
        return None
    enabled = set(LOOP_IDS)
    times = dict(DEFAULT_LOOP_TIMES)
    changed = False
    while rest:
        rest = re.sub(r"^(?:but|and)\s+", "", rest).strip()
        if not rest:
            break
        match = _SCHEDULE_CLAUSE.match(rest)
        if match is None:
            return None
        slot = _SLOT_IDS[match.group("slot")]
        clock = _clause_clock(match)
        if clock is False or (match.group("off") and clock):
            return None
        if match.group("off"):
            enabled.discard(slot)
            changed = True
        elif clock:
            if slot == "weekly_review":
                day = match.group("day")
                prefix = day.title() if day else "Sun"
                times[slot] = f"{prefix} {clock}"
            else:
                times[slot] = clock
            changed = True
        else:
            return None
        rest = rest[match.end():].strip()
    if not changed or not enabled:
        return None
    return {
        "enabled": [slot for slot in LOOP_IDS if slot in enabled],
        "times": times,
    }


def routine_cron(clock):
    """A local wall-clock time as five-field cron. The hour is not converted to UTC.

    6:30 AM daily is `30 6 * * *` before and after a daylight saving change.
    The check that those local hours stay put uses the platform time zone
    database. If that database is missing, do not invent a UTC hour.
    """
    if not isinstance(clock, str):
        return None
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", clock.strip())
    if match is None:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return f"{minute} {hour} * * *"


def first_checkin_day(week_start):
    """The Saturday on or before a Monday start. That is the first check-in."""
    from datetime import date, timedelta

    origin = date.fromisoformat(week_start) if isinstance(week_start, str) else week_start
    back = (origin.weekday() - 5) % 7
    return (origin - timedelta(days=back)).isoformat()


def start_daily_loop(reply):
    """The plan yes starts morning, evening, and weekly. One reply can change a time."""
    from record_confirmation import is_clear_yes

    planned = plan_schedule(reply)
    if planned is not None:
        return {
            "ok": True,
            "enabled": planned["enabled"],
            "times": planned["times"],
            "message": (
                "Morning check-in, evening follow-up, and weekly review follow that reply. "
                "Monthly and yearly stay off."
            ),
        }
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
