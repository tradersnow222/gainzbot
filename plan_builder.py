#!/usr/bin/env python3
"""
Build the first week of sessions from a profile.

The week uses the days, minutes, equipment, experience, sport, and
injuries they gave. It does not raise the load. It is saved only after
plan_check passes and record_confirmation covers that same plan.
"""

from datetime import date, timedelta
import copy
import json
import os

from guardrails.validate import InputValidator, ValidationError
from plan_check import PlanValidator
from readiness_screen import ReadinessScreen, ScreeningResult
from record_confirmation import ConfirmationRecord, ConfirmationRecorder


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
_NO_INJURY = {"none", "no", "n/a", "na"}


def week_to_confirm(plan, sessions):
    """The object record_confirmation has to cover: the plan and the sessions."""
    return {"plan": plan, "sessions": sessions}


class PlanBuilder:
    """Proposes a first week and saves it only after a recorded yes."""

    def propose(self, profile, check_in_result, readiness_result=None):
        if not isinstance(profile, dict):
            return self._no("The profile has to be an object.")
        days = self._days(profile)
        if isinstance(days, dict):
            return days
        minutes = self._minutes(profile.get("minutes"))
        if isinstance(minutes, dict):
            return minutes
        equipment = self._equipment(profile.get("equipment"))
        if isinstance(equipment, dict):
            return equipment
        experience = self._experience(profile.get("experience"))
        if isinstance(experience, dict):
            return experience
        sport = self._text(profile.get("sport"), "Name the sport.")
        if isinstance(sport, dict):
            return sport
        injuries = self._text(profile.get("injuries"), "List injuries, or say none.")
        if isinstance(injuries, dict):
            return injuries
        sport_hours = self._sport_hours(profile)
        if isinstance(sport_hours, dict):
            return sport_hours
        user = self._user(profile)
        if isinstance(user, dict) and user.get("ok") is False:
            return user
        age = user["age"] if user else None
        if age is None and not self._readiness_passes(readiness_result):
            return self._no(
                "An age or a passing readiness screen is required before this week is built. "
                "A missing baseline does not get a plan."
            )
        if age is not None and age < PlanValidator.ADULT_AGE and not self._readiness_passes(readiness_result):
            return self._no("A passing readiness screen is required before this week is built.")
        par_q = self._par_q_block(profile)
        if par_q is not None:
            return par_q
        structured = len(days) * minutes / 60.0
        if structured + sport_hours > PlanValidator.MAX_WEEKLY_TRAINING_HOURS:
            return self._no("That week is over the 20 hour training cap.")
        load = 80 if experience == "beginner" else 100
        if load is None or load <= 0:
            return self._no("A baseline load is required.")
        note = None
        if injuries.strip().lower() not in _NO_INJURY:
            note = "Do not add load."
        sessions = []
        for day in days:
            row = {
                "date": day.isoformat(),
                "load": load,
                "minutes": minutes if minutes != int(minutes) else int(minutes),
                "equipment": equipment,
                "sport": sport,
            }
            if note:
                row["note"] = note
            sessions.append(row)
        training = {
            "previous_load": load,
            "current_load": load,
            "weeks_since_deload": 0,
            "structured_hours": structured,
            "sport_hours": sport_hours,
        }
        plan = {"training": training}
        if user:
            plan = {"user": user, "training": training}
        checked = PlanValidator().validate_plan(
            plan,
            readiness_result=readiness_result,
            check_in_result=check_in_result,
        )
        if not checked.valid:
            return self._no(" ".join(checked.errors))
        return {
            "ok": True,
            "plan": plan,
            "sessions": sessions,
            "confirm": week_to_confirm(plan, sessions),
            "applied": False,
            "message": "The week passed plan_check. It is not saved until record_confirmation covers the plan and the sessions.",
        }

    def save(self, plan, confirmation, path, sessions=None, check_in_result=None, readiness_result=None):
        if path is None or (isinstance(path, str) and not path.strip()):
            return self._saved_no("A path is required.")
        if not isinstance(plan, dict) or not isinstance(plan.get("training"), dict):
            return self._saved_no("This week needs record_confirmation before it is saved.")
        if not isinstance(sessions, list) or not sessions or any(not isinstance(row, dict) for row in sessions):
            return self._saved_no("The week needs its sessions.")
        training = plan["training"]
        hours = self._session_hours(sessions)
        if isinstance(hours, dict):
            return hours
        sport_hours = self._sport_hours_value(training.get("sport_hours", 0))
        if isinstance(sport_hours, dict):
            return sport_hours
        if "previous_load" not in training or training.get("previous_load") in (None, ""):
            return self._saved_no("A baseline load is required.")
        age_gate = self._save_age_gate(plan, readiness_result)
        if age_gate is not None:
            return age_gate
        if self._positive_load(training.get("previous_load")) is None or self._positive_load(training.get("current_load")) is None:
            return self._saved_no("A baseline load is required.")
        if any(self._positive_load(row.get("load")) is None for row in sessions):
            return self._saved_no("A baseline load is required.")
        checked_plan = copy.deepcopy(plan)
        checked_plan["training"]["structured_hours"] = hours
        checked_plan["training"]["sport_hours"] = sport_hours
        checked = PlanValidator().validate_plan(
            checked_plan,
            readiness_result=readiness_result,
            check_in_result=check_in_result,
        )
        if not checked.valid:
            return self._saved_no(" ".join(checked.errors))
        if training.get("current_load") != training.get("previous_load"):
            return self._saved_no("The first week does not raise the load.")
        load = training.get("current_load")
        if any(row.get("load") != load for row in sessions):
            return self._saved_no("The first week does not raise the load.")
        if not isinstance(confirmation, ConfirmationRecord) or not ConfirmationRecorder().covers(
            confirmation, week_to_confirm(plan, sessions)
        ):
            return self._saved_no("This week needs record_confirmation before it is saved.")
        target = os.fspath(path)
        existing = {}
        if os.path.exists(target):
            try:
                with open(target, encoding="utf-8") as handle:
                    loaded = json.load(handle)
            except (OSError, json.JSONDecodeError):
                return self._saved_no("The week file could not be read.")
            if not isinstance(loaded, dict):
                return self._saved_no("The week file could not be read.")
            existing = loaded
        existing["plan"] = plan
        existing["sessions"] = sessions
        try:
            folder = os.path.dirname(target)
            if folder:
                os.makedirs(folder, exist_ok=True)
            temporary = target + ".tmp"
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(existing, handle)
                handle.write("\n")
            os.replace(temporary, target)
        except OSError:
            return self._saved_no("The week could not be saved.")
        return {
            "ok": True,
            "saved": True,
            "applied": False,
            "message": "Week saved.",
            "path": target,
        }

    def _days(self, profile):
        raw = profile.get("days")
        if not isinstance(raw, list) or not raw:
            return self._no("The first week needs its training days.")
        if all(self._iso(item) for item in raw):
            days = []
            seen = set()
            for item in raw:
                day = date.fromisoformat(item.strip())
                if day in seen:
                    return self._no("Each training day has to be unique.")
                seen.add(day)
                days.append(day)
            return days
        indexes = []
        for item in raw:
            if not isinstance(item, str) or item.strip().lower() not in _WEEKDAYS:
                return self._no("Each training day needs a real date (YYYY-MM-DD).")
            indexes.append(_WEEKDAYS[item.strip().lower()])
        if len(indexes) != len(set(indexes)):
            return self._no("Each training day has to be unique.")
        start = profile.get("week_start")
        if not self._iso(start):
            return self._no("The first week needs a start date.")
        origin = date.fromisoformat(start.strip())
        monday = origin - timedelta(days=origin.weekday())
        return [monday + timedelta(days=index) for index in indexes]

    def _iso(self, value):
        if not isinstance(value, str) or len(value.strip()) != 10:
            return False
        try:
            date.fromisoformat(value.strip())
        except ValueError:
            return False
        return True

    def _minutes(self, value):
        try:
            return InputValidator.parse_number(value, "minutes")
        except ValidationError as exc:
            return self._no(str(exc))

    def _session_hours(self, sessions):
        total = 0.0
        for row in sessions:
            if "minutes" not in row:
                return self._saved_no("Each session needs its minutes.")
            try:
                total += InputValidator.parse_number(row["minutes"], "minutes")
            except ValidationError as exc:
                return self._saved_no(str(exc))
        return total / 60.0

    def _sport_hours_value(self, value):
        if value in (None, ""):
            return 0
        try:
            return InputValidator.parse_number(value, "sport_hours", allow_zero=True)
        except ValidationError as exc:
            return self._saved_no(str(exc))

    def _sport_hours(self, profile):
        if "sport_hours" not in profile or profile.get("sport_hours") in (None, ""):
            return 0
        try:
            return InputValidator.parse_number(profile["sport_hours"], "sport_hours", allow_zero=True)
        except ValidationError as exc:
            return self._no(str(exc))

    def _equipment(self, value):
        if isinstance(value, str):
            text = " ".join(value.split())
            if not text:
                return self._no("List the equipment, or say none.")
            return text
        if isinstance(value, list) and value and all(isinstance(item, str) and item.strip() for item in value):
            return [" ".join(item.split()) for item in value]
        return self._no("List the equipment, or say none.")

    def _experience(self, value):
        if not isinstance(value, str):
            return self._no("Experience has to be beginner, intermediate, or advanced.")
        key = value.strip().lower()
        if key not in ("beginner", "intermediate", "advanced"):
            return self._no("Experience has to be beginner, intermediate, or advanced.")
        return key

    def _text(self, value, message):
        if not isinstance(value, str) or not value.strip():
            return self._no(message)
        return " ".join(value.split())

    def _user(self, profile):
        keys = ("sex", "weight_kg", "age", "height_cm")
        present = [key for key in keys if key in profile and profile.get(key) not in (None, "")]
        if not present:
            return None
        if len(present) != len(keys):
            return self._no("Sex, height, weight, and age have to be set together.")
        user = {key: profile[key] for key in keys}
        if "medical_clearance" in profile:
            user["medical_clearance"] = profile["medical_clearance"]
        try:
            age = InputValidator.parse_number(user["age"], "age")
        except ValidationError as exc:
            return self._no(str(exc))
        user["age"] = age
        return user

    def _save_age_gate(self, plan, readiness_result):
        """Same gate as propose: an age on the plan user, or a passing readiness result."""
        user = plan.get("user")
        age = None
        if isinstance(user, dict) and user.get("age") not in (None, ""):
            try:
                age = InputValidator.parse_number(user["age"], "age")
            except ValidationError as exc:
                return self._saved_no(str(exc))
        if age is None and not self._readiness_passes(readiness_result):
            return self._saved_no(
                "An age or a passing readiness screen is required before this week is built. "
                "A missing baseline does not get a plan."
            )
        if age is not None and age < PlanValidator.ADULT_AGE and not self._readiness_passes(readiness_result):
            return self._saved_no("A passing readiness screen is required before this week is built.")
        return None

    def _positive_load(self, value):
        try:
            number = InputValidator.parse_number(value, "load", allow_zero=True)
        except ValidationError:
            return None
        if number <= 0:
            return None
        return number

    def _par_q_block(self, profile):
        """A PAR-Q yes blocks the week in code. Missing answers are left to the caller."""
        flags = ReadinessScreen.PAR_Q_RED_FLAGS
        raw = profile.get("par_q")
        if raw is None:
            present = {key: profile[key] for key in flags if key in profile}
            if not present:
                return None
            raw = present
        result = ReadinessScreen().check_par_q(raw)
        if not result.blocked:
            return None
        reasons = " ".join(result.reasons) if result.reasons else "A PAR-Q yes blocks this week."
        return self._no(reasons)

    def _readiness_passes(self, result) -> bool:
        if not isinstance(result, ScreeningResult):
            return False
        if result.blocked is not False:
            return False
        clearance = result.clearance
        if hasattr(clearance, "value"):
            clearance = clearance.value
        return isinstance(clearance, str) and clearance.strip().lower() in {"clear", "caution"}

    def _no(self, message):
        return {
            "ok": False,
            "plan": None,
            "sessions": None,
            "applied": False,
            "message": message,
        }

    def _saved_no(self, message):
        return {"ok": False, "saved": False, "applied": False, "message": message}
