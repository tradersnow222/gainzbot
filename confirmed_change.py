#!/usr/bin/env python3
"""
Read the last confirmed load or calorie change.

Fail closed. A missing history, a history that is not a list, an unreadable
date, a date with no clock time, or a wrong key means no load or calorie
change. Dates are compared in UTC. Seven days means seven times 24 hours, so
6 days and 22.5 hours is not enough. A calendar date is not midnight UTC.
Caller baselines and planned values are not read here.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guardrails.validate import InputValidator, ValidationError


KINDS = ("load", "calories")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


class ConfirmedChange:
    """One read of the confirmed history. ok is false when the history cannot be trusted."""

    def __init__(self, ok: bool, value: Optional[float], at: Optional[datetime], reason: str):
        self.ok = ok
        self.value = value
        self.at = at
        self.reason = reason


def confirmed_history(logs, user):
    """The confirmed_changes list, or None when that key is absent."""
    if isinstance(logs, dict) and "confirmed_changes" in logs:
        return logs.get("confirmed_changes")
    if isinstance(user, dict) and "confirmed_changes" in user:
        return user.get("confirmed_changes")
    return None


def parse_utc(value) -> Optional[datetime]:
    """Parse a UTC time. A date with no clock time is rejected, not read as midnight."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, date) or not isinstance(value, str):
        return None
    text = value.strip()
    if _DATE.fullmatch(text) or not _STAMP.fullmatch(text):
        return None
    iso = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def last_confirmed_change(history, kind: str, as_of) -> ConfirmedChange:
    """Pull the latest confirmed load or calorie value and its UTC time."""
    when = parse_utc(as_of)
    if kind not in KINDS or when is None:
        return ConfirmedChange(False, None, None, "unreadable")
    if history is None:
        return ConfirmedChange(False, None, None, "no history")
    if not isinstance(history, list):
        return ConfirmedChange(False, None, None, "not a list")

    latest_value = None
    latest_at = None
    saw_confirmed = False
    for item in history:
        if not isinstance(item, dict):
            return ConfirmedChange(False, None, None, "bad row")
        changes = item.get("changes")
        if not isinstance(changes, dict) or not changes:
            return ConfirmedChange(False, None, None, "wrong key")
        if any(key not in KINDS for key in changes):
            return ConfirmedChange(False, None, None, "wrong key")
        stamp = parse_utc(item.get("date"))
        if stamp is None:
            return ConfirmedChange(False, None, None, "unreadable date")
        if item.get("confirmed") is not True:
            continue
        if kind not in changes:
            continue
        try:
            value = InputValidator.parse_number(changes[kind], kind)
        except ValidationError:
            return ConfirmedChange(False, None, None, "bad value")
        saw_confirmed = True
        if latest_at is None or stamp > latest_at:
            latest_at = stamp
            latest_value = value
    if not saw_confirmed:
        return ConfirmedChange(True, None, None, "nothing confirmed")
    return ConfirmedChange(True, latest_value, latest_at, "ok")


def seven_days_old(changed_at: datetime, as_of) -> bool:
    """True only when the change is at least 7 times 24 hours old, in UTC."""
    when = parse_utc(as_of)
    if when is None or changed_at is None or changed_at.tzinfo is None:
        return False
    return (when - changed_at) >= timedelta(days=7)


def confirmed_baseline(history, kind: str, as_of) -> Optional[float]:
    """The value a new change may move from, or None when no change is allowed."""
    found = last_confirmed_change(history, kind, as_of)
    if not found.ok or found.value is None or found.at is None:
        return None
    if not seven_days_old(found.at, as_of):
        return None
    return found.value
