#!/usr/bin/env python3
"""Per-user signal book and proactive outreach.

A connected source covers a signal only after a reading arrives. Declaring a
watch during intake does not invent data and does not count as connected.
"""

from datetime import datetime, timedelta, timezone
import re


FRESH_HOURS = 24

SOURCE_SIGNALS = {
    "apple_health": ("sleep", "resting_hr", "hrv", "steps", "weight", "workouts"),
    "garmin": ("sleep", "resting_hr", "hrv", "steps", "workouts"),
    "oura": ("sleep", "resting_hr", "hrv"),
    "whoop": ("sleep", "resting_hr", "hrv", "workouts"),
    "fitbit": ("sleep", "resting_hr", "steps", "weight"),
    "smart_scale": ("weight",),
    "food_app": ("nutrition",),
    "none": (),
}

_SIGNAL_ORDER = ("sleep", "resting_hr", "hrv", "steps", "weight", "workouts", "nutrition")

_GAP_QUESTION = {
    "sleep": "Sleep last night?",
    "resting_hr": "Resting heart rate?",
    "hrv": "HRV?",
    "steps": "Steps?",
    "weight": "Weight?",
    "workouts": "Did you train?",
    "nutrition": "What did you eat?",
}

_SOURCE_ALIASES = {
    "apple health": "apple_health",
    "apple watch": "apple_health",
    "apple_health": "apple_health",
    "garmin": "garmin",
    "oura": "oura",
    "whoop": "whoop",
    "fitbit": "fitbit",
    "smart scale": "smart_scale",
    "smart_scale": "smart_scale",
    "scale": "smart_scale",
    "food app": "food_app",
    "food_app": "food_app",
    "none": "none",
}


def source_key(name):
    text = " ".join(str(name).strip().lower().replace("-", " ").replace("_", " ").split())
    if text in _SOURCE_ALIASES:
        return _SOURCE_ALIASES[text]
    underscored = text.replace(" ", "_")
    return _SOURCE_ALIASES.get(underscored)


def format_sleep(hours):
    minutes = int(round(float(hours) * 60))
    hour_part, minute_part = divmod(minutes, 60)
    if minute_part == 0:
        return f"{hour_part}h"
    return f"{hour_part}h {minute_part}m"


def _clock(stamp):
    if not isinstance(stamp, str) or not stamp.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(stamp[:-1]).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return parsed


def read_gap_reply(gaps, reply):
    """One short answer for the signals that were actually asked."""
    text = " ".join(str(reply or "").lower().replace("'", "").split())
    numbers = []
    for raw in re.findall(r"\d+(?:\.\d+)?", text):
        value = float(raw)
        numbers.append(int(value) if value == int(value) else value)
    parsed = {}
    numeric = [name for name in gaps if name in {"sleep", "resting_hr", "hrv", "steps", "weight"}]
    if numeric == ["weight"] and numbers:
        parsed["weight_kg"] = float(numbers[0])
        return parsed
    if numeric == ["sleep"] and numbers:
        parsed["sleep"] = numbers[0]
        return parsed
    if "sleep" in gaps:
        for index, number in enumerate(numbers):
            if 0 <= number <= 14:
                parsed["sleep"] = number
                numbers = numbers[:index] + numbers[index + 1:]
                break
    if "weight" in gaps and numbers:
        parsed["weight_kg"] = float(numbers[0])
        numbers = numbers[1:]
    if "resting_hr" in gaps and numbers:
        parsed["resting_hr"] = numbers[0]
        numbers = numbers[1:]
    if "hrv" in gaps and numbers:
        parsed["hrv"] = numbers[0]
        numbers = numbers[1:]
    if "steps" in gaps and numbers:
        parsed["steps"] = numbers[0]
    return parsed


class SignalBook:
    """Which signals a connected source covers, and how fresh each reading is."""

    def __init__(self):
        self.sources = []
        self.declared = []
        self.readings = {}
        self.facts = {}
        self.settled = set()

    def declare(self, *sources):
        """What they said they track with. This does not connect anything."""
        for source in sources:
            key = source_key(source)
            if key is None or key in self.declared:
                continue
            self.declared.append(key)

    def connect(self, *sources):
        """Mark a source connected. This does not invent a reading."""
        for source in sources:
            key = source_key(source)
            if key is None or key == "none" or key in self.sources:
                continue
            self.sources.append(key)

    def connected(self):
        return bool(self.sources)

    def record(self, signal, at, value=None, down=False):
        self.readings[signal] = {"at": at, "value": value, "down": bool(down)}

    def _recent(self, signal, as_of):
        reading = self.readings.get(signal)
        if not reading:
            return False
        now = _clock(as_of)
        then = _clock(reading.get("at"))
        if now is None or then is None or then > now:
            return False
        return (now - then) < timedelta(hours=FRESH_HOURS)

    def fresh(self, signal, as_of):
        """A reading is fresh only with a real in-range value under about 24 hours."""
        if not self._recent(signal, as_of):
            return False
        value = self.readings[signal].get("value")
        if value is None:
            return False
        if signal == "sleep":
            try:
                number = float(value)
            except (TypeError, ValueError):
                return False
            if number < 4 or number > 24:
                return False
        if signal == "resting_hr":
            try:
                number = float(value)
            except (TypeError, ValueError):
                return False
            if number > 120:
                return False
        return True

    def abnormal(self, as_of):
        """Out-of-range values still on the clock. They are asked, and the day is lighter."""
        found = []
        if self._recent("sleep", as_of):
            value = self.readings["sleep"].get("value")
            if value is not None:
                try:
                    if float(value) < 4:
                        found.append("sleep")
                except (TypeError, ValueError):
                    pass
        if self._recent("resting_hr", as_of):
            value = self.readings["resting_hr"].get("value")
            if value is not None:
                try:
                    if float(value) > 120:
                        found.append("resting_hr")
                except (TypeError, ValueError):
                    pass
        return found

    def fresh_value(self, signal, as_of):
        if not self.fresh(signal, as_of):
            return None
        return self.readings[signal].get("value")

    def hrv_down(self, as_of):
        reading = self.readings.get("hrv")
        return bool(reading and reading.get("down") and self.fresh("hrv", as_of))

    def covered(self):
        names = []
        for signal in _SIGNAL_ORDER:
            if any(signal in SOURCE_SIGNALS.get(source, ()) for source in self.sources):
                names.append(signal)
        return names

    def gaps(self, as_of):
        return [signal for signal in self.covered() if not self.fresh(signal, as_of)]

    def gap_question(self, signal):
        return _GAP_QUESTION[signal]

    def set_situation(self, injury=None, sport_in_season=False, travel=False, shift=False):
        if injury:
            self.facts["injury"] = injury
        if sport_in_season:
            self.facts["sport"] = True
        if travel:
            self.facts["travel"] = True
        if shift:
            self.facts["shift"] = True

    def personal_questions(self):
        questions = []
        injury = self.facts.get("injury")
        if injury and "injury" not in self.settled:
            questions.append(("injury", f"How is the {injury} today?"))
        if self.facts.get("sport") and "sport" not in self.settled:
            questions.append(("sport", "Game day?"))
        if self.facts.get("shift") and "shift" not in self.settled:
            questions.append(("shift", "Shift today?"))
        if self.facts.get("travel") and "travel" not in self.settled:
            questions.append(("travel", "Travel day?"))
        return questions

    def settle(self, key):
        self.settled.add(key)

    def plan_note(self, as_of):
        parts = []
        lighter = False
        sleep = self.fresh_value("sleep", as_of)
        if sleep is not None:
            parts.append(f"Sleep {format_sleep(sleep)}")
            if sleep < 6:
                lighter = True
        if self.hrv_down(as_of):
            parts.append("HRV down")
            lighter = True
        if not parts:
            return "Today is on plan."
        if not lighter:
            return f"{parts[0]}. Today is on plan."
        if len(parts) == 1:
            joined = parts[0]
        elif len(parts) == 2:
            joined = f"{parts[0]} and {parts[1]}"
        else:
            joined = ", ".join(parts[:-1]) + f" and {parts[-1]}"
        return f"{joined}, so today is lighter."


class Outreach:
    """Proactive notes, capped, on top of the scheduled check-ins."""

    CAP = 2

    def __init__(self):
        self._proactive = {}
        self._held = {}
        self._scheduled = {}

    def proactive_count(self, day):
        return len(self._proactive.get(self._day(day), []))

    def scheduled(self, day, text):
        day = self._day(day)
        self._scheduled.setdefault(day, []).append(text)
        return {"text": text, "counts": False, "scheduled": True}

    def _day(self, day):
        return str(day or "").strip().lower()

    def fire(self, day, poor_recovery=False, missed=False, plateau=False, taper=False, streak=False, pr=False, plan=None, check_in=None, readiness=None):
        queue = []
        if poor_recovery:
            queue.append(self._item(
                "poor_recovery",
                "Poor recovery, so today is lighter.",
                needs_yes=False,
            ))
        if missed:
            queue.append(self._item(
                "missed",
                "Missed session. The week is reshuffled inside the cap.",
                needs_yes=False,
            ))
        if plateau:
            item = self._item(
                "plateau",
                "Plateau. Changing calories needs one word yes.",
                needs_yes=True,
            )
            item["plan"] = plan
            item["check_in"] = check_in
            item["readiness"] = readiness
            item["hash"] = None
            if plan is not None:
                from record_confirmation import hash_plan
                item["hash"] = hash_plan(plan)
            queue.append(item)
        if taper:
            queue.append(self._item(
                "taper",
                "Game day, so the week tapers inside the cap.",
                needs_yes=False,
            ))
        if streak:
            queue.append(self._item("streak", "Streak noted.", needs_yes=False))
        if pr:
            queue.append(self._item("pr", "PR noted.", needs_yes=False))
        day = self._day(day)
        delivered = []
        held = list(self._held.get(day, []))
        for item in queue:
            if self.proactive_count(day) >= self.CAP:
                held.append(item)
                continue
            self._proactive.setdefault(day, []).append(item)
            delivered.append(item)
        self._held[day] = held
        return {
            "delivered": delivered,
            "held": held,
            "proactive_count": self.proactive_count(day),
        }

    def accept(self, day, reply, proposal_hash=None):
        """Apply one delivered proposal after plan_check. The hash has to match."""
        from plan_check import PlanValidator
        from record_confirmation import is_clear_yes

        day = self._day(day)
        if not isinstance(proposal_hash, str) or not proposal_hash:
            return False
        if not is_clear_yes(reply):
            return False
        changed = False
        for item in self._proactive.get(day, []):
            if not item["needs_yes"] or item["applied"]:
                continue
            if item.get("hash") != proposal_hash or not isinstance(item.get("plan"), dict):
                continue
            checked = PlanValidator().validate_plan(
                item.get("plan"),
                check_in_result=item.get("check_in"),
                readiness_result=item.get("readiness"),
            )
            if not checked.valid:
                continue
            item["applied"] = True
            changed = True
        return changed

    def _item(self, kind, text, needs_yes):
        return {
            "kind": kind,
            "text": text,
            "needs_yes": needs_yes,
            "applied": not needs_yes,
            "proactive": True,
        }
