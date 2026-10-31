#!/usr/bin/env python3
"""Validate a host profile payload. The sentence is not read here."""

import math
from datetime import date


_GOALS = {"cut", "lose", "gain", "hold"}
_SEX = {"female", "male"}
_EQUIPMENT = {"full gym", "bodyweight", "dumbbells", "barbell", "none"}
_LEVELS = {"beginner", "novice", "intermediate", "advanced"}
_GOAL_MAP = {
    "cut": ("cut", "fat"),
    "lose fat": ("cut", "fat"),
    "lose": ("lose", "fat"),
    "gain": ("gain", "muscle"),
    "build muscle": ("gain", "muscle"),
    "hold": ("hold", None),
    "get stronger": ("hold", "strength"),
    "train for a sport or event": ("hold", "sport"),
    "move without pain": ("hold", "pain"),
}
_VAGUE_GOALS = {"get in shape", "feel better", "not sure"}
_HISTORY = {
    "never",
    "on and off",
    "consistent under 2 years",
    "consistent 2 years or more",
}
_STIFFNESS = {"no", "some stiffness", "desk job", "both"}
_EQUIPMENT_RANK = ("none", "bodyweight", "dumbbells", "barbell", "full gym")
_INJURY_CHOICES = {
    "none": ("none", False),
    "old and healed": ("old", True),
    "old": ("old", True),
    "knee": ("knee", False),
    "back": ("back", False),
    "shoulder": ("shoulder", False),
}
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
    "days_per_week",
    "history",
    "benchmarks",
    "likes",
    "dislikes",
    "safety",
    "stiffness",
    "injuries",
    "medical_clearance",
    "weight",
    "height",
    "tracker",
    "stairs",
    "play",
    "floor",
    "toes",
    "hike",
    "suitcase",
    "jog",
    "pushups",
    "lifts",
}
_MARK_KEYS = (
    "stairs", "play", "floor", "toes", "hike", "suitcase", "jog", "pushups", "lifts",
)
_TRACKER_MAP = {
    "none": "none",
    "scale": "smart_scale",
    "food app": "food_app",
    "watch": "apple_health",
}


def _text(value, limit=80):
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text or len(text) > limit:
        return None
    return text


def _whole(value, low, high):
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
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


def _choice_list(value, limit=8):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value or len(value) > limit:
        return None
    found = []
    for item in value:
        text = _text(item, 40)
        if text is None:
            return None
        if text not in found:
            found.append(text)
    return found or None


def _equipment_value(value):
    if isinstance(value, str):
        text = value.strip().lower()
        return text if text in _EQUIPMENT else None
    if not isinstance(value, list) or not value:
        return None
    picked = []
    for item in value:
        if not isinstance(item, str):
            return None
        text = item.strip().lower()
        if text not in _EQUIPMENT:
            return None
        if text not in picked:
            picked.append(text)
    if not picked:
        return None
    return max(picked, key=lambda item: _EQUIPMENT_RANK.index(item))


def _days_per_week(value):
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"5+", "5 plus"}:
            return "5"
        if text.isdigit() and 2 <= int(text) <= 7:
            return str(int(text))
        return None
    number = _whole(value, 2, 7)
    if number is None:
        return None
    return str(number)


def _benchmarks(value):
    if not isinstance(value, dict) or not value:
        return None
    cleaned = {}
    for key, item in value.items():
        name = _text(key, 40)
        answer = _text(item, 40)
        if name is None or answer is None:
            return None
        cleaned[name.lower()] = answer.lower()
    return cleaned or None


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
        mapped = _GOAL_MAP.get(text)
        if mapped is not None:
            fields["goal"] = mapped[0]
            if mapped[1]:
                fields["focus"] = mapped[1]
            if mapped[1] == "pain":
                fields["extra_mobility"] = True
        elif text in _VAGUE_GOALS:
            fields["goal_vague"] = text
        else:
            rejected.append("goal")
    if "sex" in payload:
        text = payload.get("sex")
        text = text.strip().lower() if isinstance(text, str) else ""
        if text == "skip":
            pass
        elif text in _SEX:
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
    if "weight_kg" in payload or "weight" in payload:
        raw = payload.get("weight_kg") if "weight_kg" in payload else payload.get("weight")
        key = "weight_kg" if "weight_kg" in payload else "weight"
        text = _kg(raw)
        if text is None:
            rejected.append(key)
        else:
            fields["weight"] = text
    if "target_kg" in payload:
        text = _kg(payload.get("target_kg"))
        if text is None:
            rejected.append("target_kg")
        else:
            fields["target"] = text
    if "height_cm" in payload or "height" in payload:
        raw = payload.get("height_cm") if "height_cm" in payload else payload.get("height")
        key = "height_cm" if "height_cm" in payload else "height"
        text = _height(raw)
        if text is None:
            rejected.append(key)
        else:
            fields["height"] = text
    if "age" in payload:
        number = _whole(payload.get("age"), 13, 100)
        if number is None:
            rejected.append("age")
        else:
            fields["age"] = str(number)
    if "minutes" in payload:
        raw = payload.get("minutes")
        if isinstance(raw, str) and raw.strip() in {"60+", "60"}:
            fields["minutes"] = "60"
        else:
            number = _whole(raw, 10, 180)
            if number is None:
                rejected.append("minutes")
            else:
                fields["minutes"] = str(number)
    if "equipment" in payload:
        text = _equipment_value(payload.get("equipment"))
        if text is None:
            rejected.append("equipment")
        else:
            fields["equipment"] = text
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
    if "days_per_week" in payload:
        count = _days_per_week(payload.get("days_per_week"))
        if count is None:
            rejected.append("days_per_week")
        else:
            fields["days_per_week"] = count
    if "history" in payload:
        text = payload.get("history")
        text = text.strip().lower() if isinstance(text, str) else ""
        if text in _HISTORY:
            fields["history"] = text
        else:
            rejected.append("history")
    if "likes" in payload:
        likes = _choice_list(payload.get("likes"))
        if likes is None:
            rejected.append("likes")
        else:
            fields["likes"] = likes
    if "dislikes" in payload:
        dislikes = _choice_list(payload.get("dislikes"))
        if dislikes is None:
            rejected.append("dislikes")
        else:
            fields["dislikes"] = dislikes
    if "safety" in payload:
        text = payload.get("safety")
        text = text.strip().lower() if isinstance(text, str) else ""
        if text in {"yes", "no"}:
            fields["safety"] = text
        else:
            rejected.append("safety")
    if "stiffness" in payload:
        text = payload.get("stiffness")
        text = text.strip().lower() if isinstance(text, str) else ""
        if text in _STIFFNESS:
            fields["stiffness"] = text
            if text != "no":
                fields["extra_mobility"] = True
        else:
            rejected.append("stiffness")
    if "injuries" in payload:
        raw = payload.get("injuries")
        text = raw.strip().lower() if isinstance(raw, str) else ""
        choice = _INJURY_CHOICES.get(text)
        if choice is not None:
            fields["injuries"] = choice[0]
            if choice[1]:
                fields["injury_old"] = True
        else:
            custom = _text(raw, 80)
            if custom is None:
                rejected.append("injuries")
            else:
                fields["injuries"] = custom
    marks = {}
    if "benchmarks" in payload:
        parsed = _benchmarks(payload.get("benchmarks"))
        if parsed is None:
            rejected.append("benchmarks")
        else:
            marks.update(parsed)
    for key in _MARK_KEYS:
        if key not in payload:
            continue
        answer = _text(payload.get(key), 40)
        if answer is None:
            rejected.append(key)
        else:
            marks[key] = answer.lower()
    if marks:
        fields["benchmarks"] = marks
    if "tracker" in payload and "trackers" not in payload:
        text = payload.get("tracker")
        text = text.strip().lower() if isinstance(text, str) else ""
        mapped = _TRACKER_MAP.get(text)
        if mapped is None:
            rejected.append("tracker")
        elif mapped == "none":
            fields["sources"] = "none"
        else:
            fields["sources"] = [mapped]
    if "medical_clearance" in payload:
        raw = payload.get("medical_clearance")
        if isinstance(raw, bool):
            fields["medical_clearance"] = raw
        else:
            text = _text(raw, 200)
            if text is None:
                rejected.append("medical_clearance")
            else:
                fields["medical_clearance"] = text
    return fields, rejected
