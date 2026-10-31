#!/usr/bin/env python3
"""
Bring in wearable data by free routes only.

Parse an Apple Health export, or check a screenshot summary the user
already has. Each path needs record_confirmation for that source. A bare
true flag does not count. Garmin's personal API stays behind a flag.
Weight outside 25 to 350 kg, and more than 100000 steps in a day, are
rejected. Sleep stops at 24 hours a day. Workout minutes stop at 1440
in a day. A future date is rejected. An Apple Health confirmation covers
that export file only. This script stores readings. It does not change
the plan and it does not set a calorie target.
"""

from datetime import date, datetime, timezone
from typing import Dict, Optional
from xml.etree import ElementTree
import hashlib
import io
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guardrails.validate import InputValidator, ValidationError
from record_confirmation import ConfirmationRecord, ConfirmationRecorder


GROK_SUMMARY_PROMPT = (
    "Read this wearable summary screenshot. Reply with JSON only. "
    "Use null when a value is not on the screen. Keys: date, steps, "
    "sleep_hours, resting_hr, weight_kg. Do not connect to any account."
)

_LB_PER_KG = 2.2046226218
MIN_WEIGHT_KG = 25
MAX_WEIGHT_KG = 350
MAX_STEPS_PER_DAY = 100000
MAX_SLEEP_HOURS_PER_DAY = 24
MAX_WORKOUT_MINUTES_PER_DAY = 24 * 60
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def _source_bytes(source):
    """The export bytes a confirmation is tied to. None when there is no file."""
    if isinstance(source, bytes):
        return source
    if isinstance(source, str) and os.path.isfile(source):
        with open(source, "rb") as handle:
            return handle.read()
    if isinstance(source, str) and source.lstrip().startswith("<"):
        return source.encode("utf-8")
    return None


def apple_health_plan(source) -> Optional[dict]:
    """The confirmation plan for one Apple Health export, not every export."""
    raw = _source_bytes(source)
    if not isinstance(raw, bytes):
        return None
    return {
        "source": "apple_health",
        "export_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _confirmed(confirmation, plan) -> bool:
    return (
        isinstance(confirmation, ConfirmationRecord)
        and ConfirmationRecorder().covers(confirmation, plan)
    )


def _real_day(value) -> Optional[str]:
    """A real calendar day. US dates and words like yesterday fail."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.date().isoformat()
        return value.astimezone(timezone.utc).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        return None
    text = value.strip()
    if _DATE.fullmatch(text):
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            return None
    if not _STAMP.fullmatch(text):
        return None
    iso = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).date().isoformat()


def _apple_dt(value) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _whole(value: float):
    if abs(value - round(value)) < 1e-9:
        return int(round(value))
    return round(value, 1)


class WearableImport:
    """Local import plus an optional Garmin fetch that stays off by default."""

    def parse_apple_health(self, source, confirmation=None) -> Dict:
        plan = apple_health_plan(source)
        if plan is None:
            return self._no("Give an Apple Health export file or its XML.")
        if not _confirmed(confirmation, plan):
            return self._no("This Apple Health export needs record_confirmation before it is read.")
        raw = self._read_source(_source_bytes(source))
        if isinstance(raw, dict):
            return raw
        try:
            root = ElementTree.fromstring(raw)
        except ElementTree.ParseError:
            return self._no("That Apple Health export could not be read.")
        if self._has_future_date(root):
            return self._no("A future date is rejected.")
        weights = []
        steps: Dict[str, float] = {}
        sleep: Dict[str, float] = {}
        workouts = []
        workout_minutes: Dict[str, float] = {}
        for node in root.iter("Record"):
            kind = node.attrib.get("type", "")
            if kind == "HKQuantityTypeIdentifierBodyMass":
                point = self._weight(node)
                if not point:
                    continue
                if point.get("error"):
                    return self._no("Weight has to be between 25 and 350 kg.")
                weights.append(point)
            elif kind == "HKQuantityTypeIdentifierStepCount":
                added = self._add_steps(steps, node)
                if added == "too many":
                    return self._no("Steps over 100,000 in a day are rejected.")
            elif kind == "HKCategoryTypeIdentifierSleepAnalysis":
                added = self._add_sleep(sleep, node)
                if added == "too much":
                    return self._no("Sleep over 24 hours in a day is rejected.")
        for node in root.iter("Workout"):
            workout = self._workout(node)
            if not workout:
                continue
            if workout.get("error"):
                return self._no("Workout minutes over 1,440 in a day are rejected.")
            if "minutes" in workout:
                day = workout["date"]
                total = workout_minutes.get(day, 0) + workout["minutes"]
                if total > MAX_WORKOUT_MINUTES_PER_DAY:
                    return self._no("Workout minutes over 1,440 in a day are rejected.")
                workout_minutes[day] = total
            workouts.append(workout)
        return {
            "ok": True,
            "stored": True,
            "connected": False,
            "applied": False,
            "message": "Apple Health export read on this device. No account was connected.",
            "weights": weights,
            "steps": [{"date": day, "steps": _whole(value)} for day, value in sorted(steps.items())],
            "sleep": [{"date": day, "hours": _whole(value)} for day, value in sorted(sleep.items())],
            "workouts": workouts,
        }

    def store_summary(self, reading, confirmation=None) -> Dict:
        """Store a screenshot summary. This does not connect an account."""
        if not isinstance(reading, dict):
            return self._no("The summary has to be an object.")
        if not _confirmed(confirmation, reading):
            return self._no("This summary needs record_confirmation before it is stored.")
        checked = self._summary(reading)
        if not checked["ok"]:
            return checked
        return {
            "ok": True,
            "stored": True,
            "connected": False,
            "applied": False,
            "message": "Summary stored on this device. No account was connected.",
            "reading": checked["reading"],
        }

    def fetch_garmin(self, confirmation=None, fetcher=None, enabled=False) -> Dict:
        """Optional personal API. Off unless the flag is on and the source is confirmed."""
        if enabled is not True:
            return self._no("Garmin personal API is off.")
        if not _confirmed(confirmation, {"source": "garmin"}):
            return self._no("Garmin needs record_confirmation before anything is connected.")
        if not callable(fetcher):
            return self._no("No request was sent.")
        payload = fetcher()
        checked = self._summary(payload)
        if not checked["ok"]:
            checked["connected"] = False
            return checked
        return {
            "ok": True,
            "stored": True,
            "connected": True,
            "applied": False,
            "message": "Garmin data stored after your OK.",
            "reading": checked["reading"],
        }

    def _read_source(self, source):
        if isinstance(source, bytes):
            if source[:2] == b"PK":
                return self._xml_from_zip(io.BytesIO(source))
            return source
        if isinstance(source, str) and os.path.isfile(source):
            if zipfile.is_zipfile(source):
                return self._xml_from_zip(source)
            with open(source, "rb") as handle:
                return handle.read()
        if isinstance(source, str) and source.lstrip().startswith("<"):
            return source.encode("utf-8")
        return self._no("Give an Apple Health export file or its XML.")

    def _xml_from_zip(self, source):
        try:
            with zipfile.ZipFile(source) as archive:
                names = [name for name in archive.namelist() if name.endswith("export.xml")]
                if not names:
                    return self._no("That zip has no export.xml.")
                return archive.read(names[0])
        except zipfile.BadZipFile:
            return self._no("That Apple Health export could not be read.")

    def _weight(self, node) -> Optional[Dict]:
        when = _apple_dt(node.attrib.get("startDate"))
        if when is None:
            return None
        try:
            value = InputValidator.parse_number(node.attrib.get("value"), "weight")
        except ValidationError:
            return None
        unit = (node.attrib.get("unit") or "").lower()
        if unit in {"lb", "lbs"}:
            value = value / _LB_PER_KG
        elif unit not in {"kg", "kgm"}:
            return None
        if value < MIN_WEIGHT_KG or value > MAX_WEIGHT_KG:
            return {"error": "weight"}
        return {"date": when.date().isoformat(), "kg": _whole(value)}

    def _add_steps(self, steps, node) -> Optional[str]:
        when = _apple_dt(node.attrib.get("startDate"))
        if when is None:
            return None
        try:
            value = InputValidator.parse_number(node.attrib.get("value"), "steps", allow_zero=True)
        except ValidationError:
            return None
        day = when.date().isoformat()
        total = steps.get(day, 0) + value
        if total > MAX_STEPS_PER_DAY:
            return "too many"
        steps[day] = total
        return None

    def _has_future_date(self, root) -> bool:
        today = datetime.now(timezone.utc).date()
        nodes = list(root.iter("Record")) + list(root.iter("Workout"))
        for node in nodes:
            when = _apple_dt(node.attrib.get("startDate"))
            if when is not None and when.date() > today:
                return True
        return False

    def _add_sleep(self, sleep, node) -> Optional[str]:
        value = node.attrib.get("value") or ""
        if "Asleep" not in value:
            return None
        start = _apple_dt(node.attrib.get("startDate"))
        end = _apple_dt(node.attrib.get("endDate"))
        if start is None or end is None or end <= start:
            return None
        hours = (end - start).total_seconds() / 3600
        day = start.date().isoformat()
        total = sleep.get(day, 0) + hours
        if total > MAX_SLEEP_HOURS_PER_DAY:
            return "too much"
        sleep[day] = total
        return None

    def _workout(self, node) -> Optional[Dict]:
        start = _apple_dt(node.attrib.get("startDate"))
        if start is None:
            return None
        activity = node.attrib.get("workoutActivityType", "Workout")
        prefix = "HKWorkoutActivityType"
        if activity.startswith(prefix):
            activity = activity[len(prefix):]
        workout = {"date": start.date().isoformat(), "activity": activity}
        if "duration" in node.attrib:
            try:
                minutes = InputValidator.parse_number(node.attrib.get("duration"), "duration", allow_zero=True)
            except ValidationError:
                return None
            unit = (node.attrib.get("durationUnit") or "min").lower()
            if unit in {"hr", "hour", "hours"}:
                minutes *= 60
            if minutes > MAX_WORKOUT_MINUTES_PER_DAY:
                return {"error": "minutes"}
            workout["minutes"] = _whole(minutes)
        return workout

    def _summary(self, reading) -> Dict:
        if not isinstance(reading, dict):
            return self._no("The summary has to be an object.")
        kept = {}
        try:
            if reading.get("steps") is not None:
                steps = InputValidator.parse_number(reading["steps"], "steps", allow_zero=True)
                if steps > MAX_STEPS_PER_DAY:
                    return self._no("Steps over 100,000 in a day are rejected.")
                kept["steps"] = _whole(steps)
            if reading.get("sleep_hours") is not None:
                hours = InputValidator.parse_number(reading["sleep_hours"], "sleep_hours", allow_zero=True)
                if hours > MAX_SLEEP_HOURS_PER_DAY:
                    return self._no("Sleep over 24 hours in a day is rejected.")
                kept["sleep_hours"] = _whole(hours)
            if reading.get("resting_hr") is not None:
                heart = InputValidator.parse_number(reading["resting_hr"], "resting_hr")
                if heart < 30 or heart > 220:
                    return self._no("Resting heart rate looks out of range.")
                kept["resting_hr"] = _whole(heart)
            if reading.get("weight_kg") is not None:
                weight = InputValidator.parse_number(reading["weight_kg"], "weight_kg")
                if weight < MIN_WEIGHT_KG or weight > MAX_WEIGHT_KG:
                    return self._no("Weight has to be between 25 and 350 kg.")
                kept["weight_kg"] = _whole(weight)
        except ValidationError as exc:
            return self._no(str(exc))
        day = _real_day(reading.get("date"))
        if day is None:
            return self._no("The summary date needs a real date.")
        if date.fromisoformat(day) > datetime.now(timezone.utc).date():
            return self._no("A future date is rejected.")
        if not kept:
            return self._no("The summary has no usable numbers.")
        kept["date"] = day
        return {"ok": True, "reading": kept}

    def _no(self, message: str) -> Dict:
        return {
            "ok": False,
            "stored": False,
            "connected": False,
            "applied": False,
            "message": message,
        }
