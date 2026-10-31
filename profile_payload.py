#!/usr/bin/env python3
"""Validate a host profile payload. The sentence is not read here."""

import math
from datetime import date


_GOALS = {"cut", "lose", "gain", "hold"}
_SEX = {"female", "male"}
_EQUIPMENT = {"full gym", "bodyweight", "dumbbells", "barbell", "none"}
_LEVELS = {"beginner", "intermediate", "advanced"}
_TRACKERS = {
    "apple_health",
    "garmin",
    "oura",
    "whoop",
    "fitbit",
    "smart_scale",
    "food_app",
    "none",
}
_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}
_FIELDS = {
    "name",
    "sex",
    "food_style",
    "goal",
    "weight_kg",
    "target_kg",
    "height_cm",
    "age",
    "days",
    "minutes",
    "equipment",
    "level",
    "sport",
    "trackers",
    "event",
}


def _text(value, limit=80):
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text or len(text) > limit:
        return None
    return text


def _whole(value, low, high):
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < low or value > high:
        return None
    return value


def _kg(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 30 or number > 300:
        return None
    if number == int(number):
        return f"{int(number)} kg"
    return f"{number:g} kg"


def _height(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 50 or number > 280:
        return None
    if number == int(number):
        return f"{int(number)} cm"
    return f"{number:g} cm"


def _days(value):
    if not isinstance(value, list) or not value:
        return None
    indexes = []
    for item in value:
        if not isinstance(item, str):
            return None
        index = _WEEKDAYS.get(item.strip().lower())
        if index is None:
            return None
        if index not in indexes:
            indexes.append(index)
    return indexes or None


def _trackers(value):
    if isinstance(value, str) and value.strip().lower() == "none":
        return "none"
    if not isinstance(value, list) or not value:
        return None
    found = []
    for item in value:
        if not isinstance(item, str):
            return None
        key = item.strip().lower()
        if key not in _TRACKERS:
            return None
        if key not in found:
            found.append(key)
    real = [key for key in found if key != "none"]
    if real:
        return real
    if "none" in found:
        return "none"
    return None


def _event(value):
    if not isinstance(value, dict):
        return None
    if any(key not in {"name", "month", "date"} for key in value):
        return None
    name = _text(value.get("name"), 80)
    if name is None:
        return None
    cleaned = {"name": name}
    if "month" in value:
        month = value.get("month")
        if isinstance(month, bool) or not isinstance(month, int) or not 1 <= month <= 12:
            return None
        cleaned["month"] = month
    if "date" in value:
        raw = value.get("date")
        if not isinstance(raw, str):
            return None
        try:
            date.fromisoformat(raw.strip())
        except ValueError:
            return None
        cleaned["date"] = raw.strip()
    if "month" not in cleaned and "date" not in cleaned:
        return None
    return cleaned


def accept_profile(payload):
    """Valid fields in onboarding shapes, plus keys that were dropped.

    Unknown keys are dropped. One bad value drops that field only.
    day_indexes is a list of weekday numbers. The caller turns them into dates.
    """
    if not isinstance(payload, dict):
        return {}, ["profile"]
    fields = {}
    rejected = []
    for key in payload:
        if key not in _FIELDS:
            rejected.append(key)
    goal = payload.get("goal")
    if "goal" in payload:
        text = goal.strip().lower() if isinstance(goal, str) else ""
        if text in _GOALS:
            fields["goal"] = text
        else:
            rejected.append("goal")
    if "sex" in payload:
        text = payload.get("sex")
        text = text.strip().lower() if isinstance(text, str) else ""
        if text in _SEX:
            fields["sex"] = text
        else:
            rejected.append("sex")
    if "name" in payload:
        text = _text(payload.get("name"), 40)
        if text is None:
            rejected.append("name")
        else:
            fields["name"] = text
    if "food_style" in payload:
        text = _text(payload.get("food_style"), 80)
        if text is None:
            rejected.append("food_style")
        else:
            fields["food_style"] = text
    if "sport" in payload:
        text = _text(payload.get("sport"), 80)
        if text is None:
            rejected.append("sport")
        else:
            fields["sport"] = text
    if "weight_kg" in payload:
        text = _kg(payload.get("weight_kg"))
        if text is None:
            rejected.append("weight_kg")
        else:
            fields["weight"] = text
    if "target_kg" in payload:
        text = _kg(payload.get("target_kg"))
        if text is None:
            rejected.append("target_kg")
        else:
            fields["target"] = text
    if "height_cm" in payload:
        text = _height(payload.get("height_cm"))
        if text is None:
            rejected.append("height_cm")
        else:
            fields["height"] = text
    if "age" in payload:
        number = _whole(payload.get("age"), 13, 100)
        if number is None:
            rejected.append("age")
        else:
            fields["age"] = str(number)
    if "minutes" in payload:
        number = _whole(payload.get("minutes"), 10, 180)
        if number is None:
            rejected.append("minutes")
        else:
            fields["minutes"] = str(number)
    if "equipment" in payload:
        text = payload.get("equipment")
        text = text.strip().lower() if isinstance(text, str) else ""
        if text in _EQUIPMENT:
            fields["equipment"] = text
        else:
            rejected.append("equipment")
    if "level" in payload:
        text = payload.get("level")
        text = text.strip().lower() if isinstance(text, str) else ""
        if text in _LEVELS:
            fields["experience"] = text
        else:
            rejected.append("level")
    if "days" in payload:
        indexes = _days(payload.get("days"))
        if indexes is None:
            rejected.append("days")
        else:
            fields["day_indexes"] = indexes
    if "trackers" in payload:
        sources = _trackers(payload.get("trackers"))
        if sources is None:
            rejected.append("trackers")
        else:
            fields["sources"] = sources
    if "event" in payload:
        event = _event(payload.get("event"))
        if event is None:
            rejected.append("event")
        else:
            fields["event"] = event
    return fields, rejected
