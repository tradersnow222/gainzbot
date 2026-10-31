#!/usr/bin/env python3
"""One dated pending safety record.

A follow_up, an age_check, or a hold is written beside the caller's other
data files. It blocks every prescribe and confirm path until a structured
input resolves it. A date before the caller's today does not block. A bad
file stays active as a hold.
"""

import json
import os
import re
from datetime import date


KINDS = ("follow_up", "age_check", "hold")
SLOTS = ("onboarding", "daily")


def pending_path(directory, slot):
    """The record for this slot. Onboarding and the day each keep their own."""
    if slot not in SLOTS:
        raise ValueError(slot)
    return os.path.join(directory, f"safety_pending_{slot}.json")


def _as_date(value):
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError("date")


def read_pending(directory, today, slot):
    """The active record, or None when it is missing or already a past date.

    An unreadable file, a future date, or a record that is not one of the
    three kinds stays active as a hold. A date before the caller's today
    has expired.
    """
    path = pending_path(directory, slot)
    try:
        today_day = _as_date(today)
    except ValueError:
        today_day = date.today()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"kind": "hold", "date": today_day.isoformat(), "unreadable": True}
    if not isinstance(loaded, dict):
        return {"kind": "hold", "date": today_day.isoformat(), "unreadable": True}
    kind = loaded.get("kind")
    stored = loaded.get("date")
    if kind not in KINDS or not isinstance(stored, str):
        return {"kind": "hold", "date": today_day.isoformat(), "unreadable": True}
    try:
        stored_day = date.fromisoformat(stored)
    except ValueError:
        return {"kind": "hold", "date": today_day.isoformat(), "unreadable": True}
    if stored_day < today_day:
        return None
    if stored_day > today_day:
        return {"kind": "hold", "date": today_day.isoformat(), "future": True}
    return loaded


def write_pending(directory, kind, today, slot, **extra):
    """Replace the record. One kind is pending at a time."""
    if kind not in KINDS:
        raise ValueError(kind)
    try:
        stored = _as_date(today).isoformat()
    except ValueError:
        return False
    payload = {"kind": kind, "date": stored}
    for key, value in extra.items():
        if key not in {"kind", "date"}:
            payload[key] = value
    path = pending_path(directory, slot)
    temporary = path + ".tmp"
    try:
        os.makedirs(directory, exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
            handle.write("\n")
        os.replace(temporary, path)
    except OSError:
        return False
    return True


def clear_pending(directory, slot):
    """Remove the record. A missing file is already clear."""
    path = pending_path(directory, slot)
    if not os.path.isfile(path):
        return False
    try:
        os.remove(path)
    except OSError:
        return False
    return True


def resolves_follow_up(labels, button=None, injury_unclear=False):
    """True for a valid red_flag, minor, or old/current injury label.

    An Old/Recent tap resolves only an injury=unclear follow-up. A pass, a
    note, a missing label, or an invalid label does not resolve it.
    """
    if labels is None and injury_unclear and button in {"old", "current"}:
        return True
    if labels is None:
        return False
    from safety_labels import validate_labels

    parsed, reason = validate_labels(labels)
    if reason is not None:
        return False
    if parsed["red_flag"] != "none":
        return True
    if parsed["minor_signal"] is True:
        return True
    if parsed["injury"] in {"old", "current"}:
        return True
    return False


def typed_age(reply):
    """The int submit_age accepts. A sentence, a word, or a bool is not an age."""
    if isinstance(reply, bool):
        return None
    if isinstance(reply, int):
        return reply
    if isinstance(reply, str) and re.fullmatch(r"[0-9]{1,3}", reply.strip()):
        return int(reply.strip())
    return None
