#!/usr/bin/env python3
"""
Bring in wearable data by free routes only.

Parse an Apple Health export, or check a screenshot summary the user
already has. Garmin's personal API stays behind a flag and never connects
without a real yes from the user. This script stores readings. It does
not change the plan and it does not set a calorie target.
"""

from datetime import datetime
from typing import Dict, Optional
from xml.etree import ElementTree
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guardrails.validate import InputValidator, ValidationError


GROK_SUMMARY_PROMPT = (
    "Read this wearable summary screenshot. Reply with JSON only. "
    "Use null when a value is not on the screen. Keys: date, steps, "
    "sleep_hours, resting_hr, weight_kg. Do not connect to any account."
)

_LB_PER_KG = 2.2046226218


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

    def parse_apple_health(self, source) -> Dict:
        raw = self._read_source(source)
        if isinstance(raw, dict):
            return raw
        try:
            root = ElementTree.fromstring(raw)
        except ElementTree.ParseError:
            return self._no("That Apple Health export could not be read.")
        weights = []
        steps: Dict[str, float] = {}
        sleep: Dict[str, float] = {}
        workouts = []
        for node in root.iter("Record"):
            kind = node.attrib.get("type", "")
            if kind == "HKQuantityTypeIdentifierBodyMass":
                point = self._weight(node)
                if point:
                    weights.append(point)
            elif kind == "HKQuantityTypeIdentifierStepCount":
                self._add_steps(steps, node)
            elif kind == "HKCategoryTypeIdentifierSleepAnalysis":
                self._add_sleep(sleep, node)
        for node in root.iter("Workout"):
            workout = self._workout(node)
            if workout:
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

    def store_summary(self, reading, user_ok=False) -> Dict:
        """Store a screenshot summary. This does not connect an account."""
        if user_ok is not True:
            return self._no("Nothing is connected without your OK.")
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

    def fetch_garmin(self, user_ok=False, fetcher=None, enabled=False) -> Dict:
        """Optional personal API. Off unless the flag is on and the user agreed."""
        if enabled is not True:
            return self._no("Garmin personal API is off.")
        if user_ok is not True:
            return self._no("Nothing is connected without your OK.")
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
        return {"date": when.date().isoformat(), "kg": _whole(value)}

    def _add_steps(self, steps, node) -> None:
        when = _apple_dt(node.attrib.get("startDate"))
        if when is None:
            return
        try:
            value = InputValidator.parse_number(node.attrib.get("value"), "steps", allow_zero=True)
        except ValidationError:
            return
        day = when.date().isoformat()
        steps[day] = steps.get(day, 0) + value

    def _add_sleep(self, sleep, node) -> None:
        value = node.attrib.get("value") or ""
        if "Asleep" not in value:
            return
        start = _apple_dt(node.attrib.get("startDate"))
        end = _apple_dt(node.attrib.get("endDate"))
        if start is None or end is None or end <= start:
            return
        hours = (end - start).total_seconds() / 3600
        day = start.date().isoformat()
        sleep[day] = sleep.get(day, 0) + hours

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
            workout["minutes"] = _whole(minutes)
        return workout

    def _summary(self, reading) -> Dict:
        if not isinstance(reading, dict):
            return self._no("The summary has to be an object.")
        kept = {}
        try:
            if reading.get("steps") is not None:
                steps = InputValidator.parse_number(reading["steps"], "steps", allow_zero=True)
                kept["steps"] = _whole(steps)
            if reading.get("sleep_hours") is not None:
                hours = InputValidator.parse_number(reading["sleep_hours"], "sleep_hours", allow_zero=True)
                if hours > 14:
                    return self._no("Sleep hours have to be between 0 and 14.")
                kept["sleep_hours"] = _whole(hours)
            if reading.get("resting_hr") is not None:
                heart = InputValidator.parse_number(reading["resting_hr"], "resting_hr")
                if heart < 30 or heart > 220:
                    return self._no("Resting heart rate looks out of range.")
                kept["resting_hr"] = _whole(heart)
            if reading.get("weight_kg") is not None:
                weight = InputValidator.parse_number(reading["weight_kg"], "weight_kg")
                kept["weight_kg"] = _whole(weight)
        except ValidationError as exc:
            return self._no(str(exc))
        if not kept:
            return self._no("The summary has no usable numbers.")
        if isinstance(reading.get("date"), str):
            kept["date"] = reading["date"][:10]
        return {"ok": True, "reading": kept}

    def _no(self, message: str) -> Dict:
        return {
            "ok": False,
            "stored": False,
            "connected": False,
            "applied": False,
            "message": message,
        }
