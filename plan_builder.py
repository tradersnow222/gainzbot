#!/usr/bin/env python3
"""
Build the first week of sessions from a profile.

The week uses the days, minutes, equipment, experience, sport, and
injuries they gave. It does not raise the load. It is saved only after
plan_check passes and record_confirmation covers that same plan.
"""

from datetime import date, datetime, timedelta, timezone
import copy
import json
import math
import os
import re
import unicodedata

from guardrails.validate import InputValidator, ValidationError
from plan_check import PlanValidator
from readiness_screen import (
    ReadinessScreen,
    passing_readiness,
    screening_seal_matches,
    subject_hash,
)
from record_confirmation import ConfirmationRecord, ConfirmationRecorder, covers_first_plan


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
_LOG_KINDS = (
    "meals",
    "sets",
    "checkins",
    "weights",
    "confirmations",
    "used_records",
    "sessions",
)
_DOSE = {
    "beginner": (3, "8-12", "90 sec", "Leave 3 reps in reserve"),
    "intermediate": (4, "6-10", "2 min", "Leave 2 reps in reserve"),
    "advanced": (5, "4-8", "3 min", "Leave 1 rep in reserve"),
}
_MAX_EXERCISES = 8
_MAX_SETS = 6
_MAX_REPS = 20
_SECONDS_PER_REP = 4
# Generous load ceilings, as a multiple of body weight.
# A normal lifter stays inside these. An absurd load still refuses.
_LOAD_MULTIPLE = {
    "beginner": 2.5,
    "intermediate": 3.5,
    "advanced": 5.0,
}
_ABSOLUTE_LOAD_CAP = 300.0
_FALLBACK_LOAD_CAP = 100.0
_EXERCISE_KEYS = {"name", "sets", "reps", "rest", "effort", "load_kg"}
_GYM = {
    "Full body": ("Back squat", "Bench press", "Barbell row", "Romanian deadlift", "Plank", "Farmer carry"),
    "Full body A": ("Back squat", "Bench press", "Barbell row", "Romanian deadlift", "Plank", "Farmer carry"),
    "Full body B": ("Front squat", "Overhead press", "Pull-up", "Hip thrust", "Dead bug", "Carry"),
    "Full body C": ("Leg press", "Incline bench", "Seated cable row", "Walking lunge", "Back extension", "Side plank"),
    "Upper": ("Bench press", "Barbell row", "Overhead press", "Lat pulldown", "Curl", "Face pull"),
    "Lower": ("Back squat", "Romanian deadlift", "Leg press", "Walking lunge", "Calf raise", "Plank"),
    "Push": ("Bench press", "Overhead press", "Incline bench", "Dip", "Lateral raise", "Triceps press"),
    "Pull": ("Barbell row", "Pull-up", "Seated cable row", "Face pull", "Curl", "Rear delt raise"),
    "Legs": ("Back squat", "Romanian deadlift", "Leg press", "Walking lunge", "Calf raise", "Plank"),
}
_SAFE = ("Glute bridge", "Dead bug", "Bird dog", "Carry", "Side plank", "Calf raise")
_SPORT_MOVE = (
    ("run", "Easy run"),
    ("cycl", "Easy spin"),
    ("bike", "Easy spin"),
    ("swim", "Easy swim"),
)


def _confirm_changes(plan):
    """Load and calories in the shape the confirmed-history reader stores."""
    if not isinstance(plan, dict):
        return {}
    changes = {}
    training = plan.get("training")
    if isinstance(training, dict) and training.get("current_load") not in (None, ""):
        changes["load"] = training["current_load"]
    nutrition = plan.get("nutrition")
    if isinstance(nutrition, dict) and nutrition.get("calories") not in (None, ""):
        changes["calories"] = nutrition["calories"]
    return changes


def week_to_confirm(plan, sessions):
    """The object record_confirmation has to cover: the plan and the sessions."""
    body = {"plan": plan, "sessions": sessions}
    changes = _confirm_changes(plan)
    if changes:
        body["changes"] = changes
    return body


def _split_name(count, index):
    if count <= 1:
        return "Full body"
    if count == 2:
        return ("Full body A", "Full body B")[index]
    if count == 3:
        return ("Full body A", "Full body B", "Full body C")[index]
    if count == 4:
        return ("Upper", "Lower", "Upper", "Lower")[index]
    return ("Push", "Pull", "Legs")[index % 3]


def _gear(equipment):
    text = equipment if isinstance(equipment, str) else " ".join(equipment)
    text = text.lower()
    gym_words = ("gym", "barbell", "rack", "cable", "machine", "full")
    if any(word in text for word in gym_words):
        return "gym"
    if "dumbbell" in text or "kettlebell" in text:
        return "dumbbell"
    return "bodyweight"


def _bodyweight_name(name):
    table = {
        "Back squat": "Squat",
        "Front squat": "Split squat",
        "Leg press": "Squat",
        "Bench press": "Push-up",
        "Incline bench": "Push-up",
        "Overhead press": "Pike push-up",
        "Barbell row": "Inverted row",
        "Seated cable row": "Inverted row",
        "Lat pulldown": "Inverted row",
        "Pull-up": "Inverted row",
        "Romanian deadlift": "Hip hinge",
        "Walking lunge": "Reverse lunge",
        "Hip thrust": "Glute bridge",
        "Dip": "Bench dip",
        "Curl": "Towel curl",
        "Face pull": "Band pull-apart",
        "Rear delt raise": "Band pull-apart",
        "Lateral raise": "Arm circle",
        "Triceps press": "Bench dip",
        "Back extension": "Bird dog",
        "Calf raise": "Calf raise",
        "Farmer carry": "Carry",
        "Carry": "Carry",
        "Plank": "Plank",
        "Side plank": "Side plank",
        "Dead bug": "Dead bug",
    }
    return table.get(name, name)


def _dumbbell_name(name):
    swapped = (
        name.replace("Barbell ", "Dumbbell ")
        .replace("Back squat", "Goblet squat")
        .replace("Front squat", "Goblet squat")
        .replace("Leg press", "Split squat")
        .replace("Pull-up", "Dumbbell row")
        .replace("Lat pulldown", "Dumbbell row")
        .replace("Seated cable row", "Dumbbell row")
        .replace("Incline bench", "Dumbbell bench")
        .replace("Bench press", "Dumbbell bench")
        .replace("Overhead press", "Dumbbell shoulder press")
    )
    return swapped


def _blocked_parts(injuries):
    text = injuries.lower()
    if text.strip() in _NO_INJURY:
        return ()
    parts = []
    if "knee" in text:
        parts.extend(("squat", "lunge", "leg press"))
    if "shoulder" in text:
        parts.extend(("overhead", "bench", "push-up", "pike", "dip", "press"))
    if "back" in text:
        parts.extend(("deadlift", "row", "extension"))
    if "wrist" in text:
        parts.extend(("push-up", "bench", "dip"))
    return tuple(parts)


def _sport_exercise(sport):
    text = sport.lower()
    for key, name in _SPORT_MOVE:
        if key in text:
            return {
                "name": name,
                "sets": 1,
                "reps": "10 min",
                "rest": "0 sec",
                "effort": "Easy, conversational",
            }
    return None


def _rest_minutes(rest):
    if not isinstance(rest, str):
        return None
    text = rest.strip().lower()
    match = re.match(r"^(\d+(?:\.\d+)?)\s*(sec|min)$", text)
    if match is None:
        return None
    number = float(match.group(1))
    if match.group(2) == "sec":
        return number / 60.0
    return number


def _is_duration(exercise):
    reps = exercise.get("reps")
    return isinstance(reps, str) and reps.strip().lower().endswith("min")


def _whole_number(value):
    """A real int. Bools, floats, and numeric strings are not counts."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _duration_minutes(reps):
    if not isinstance(reps, str):
        return None
    match = re.fullmatch(r"(\d+)\s*min", reps.strip().lower())
    if match is None:
        return None
    return int(match.group(1))


def _high_reps(reps):
    """A whole rep count, or the high end of a low-high range."""
    counted = _whole_number(reps)
    if counted is not None:
        return counted
    if not isinstance(reps, str):
        return None
    match = re.fullmatch(r"(\d+)-(\d+)", reps.strip())
    if match is None:
        return None
    low = int(match.group(1))
    high = int(match.group(2))
    if low < 1 or high < low:
        return None
    return high


def _fold_cue(value):
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFKC", value)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    return text.lower()


def _to_failure(exercise):
    folded = _fold_cue(exercise.get("reps")) + " " + _fold_cue(exercise.get("effort"))
    if "fail" in folded or "max effort" in folded:
        return True
    return re.search(r"rpe\s*10", folded) is not None


def _finite_load(value):
    if isinstance(value, bool) or isinstance(value, str):
        return None
    if isinstance(value, int):
        return float(value)
    if isinstance(value, float) and math.isfinite(value):
        return value
    return None


def _load_cap(user):
    """Body weight times the profile experience, with a fixed cap when weight is missing.

    Experience comes from the profile, not from session rows. The result also
    stays at or under 300 kg.
    """
    experience = "beginner"
    weight = None
    if isinstance(user, dict):
        name = user.get("experience")
        if isinstance(name, str) and name.strip().lower() in _LOAD_MULTIPLE:
            experience = name.strip().lower()
        weight = _finite_load(user.get("weight_kg"))
    if weight is None or weight <= 0:
        cap = _FALLBACK_LOAD_CAP
    else:
        cap = weight * _LOAD_MULTIPLE[experience]
    return min(cap, _ABSOLUTE_LOAD_CAP)


def _block_minutes(exercise):
    sets = _whole_number(exercise.get("sets"))
    if sets is None:
        return None
    duration = _duration_minutes(exercise.get("reps"))
    if duration is not None:
        return duration if sets == 1 else None
    reps = _high_reps(exercise.get("reps"))
    rest = _rest_minutes(exercise.get("rest"))
    if reps is None or rest is None or sets < 1:
        return None
    work = sets * reps * _SECONDS_PER_REP / 60.0
    if sets <= 1:
        return work
    return work + (sets - 1) * rest


def session_volume(exercises):
    """Minutes of work and rest in one session's exercises."""
    total = 0.0
    for exercise in exercises:
        block = _block_minutes(exercise)
        if block is None:
            return None
        total += block
    return total


def _fit_minutes(chosen, minutes):
    """Drop or shorten work until it fits in the minutes they asked for."""
    while len(chosen) > 1 and session_volume(chosen) > minutes:
        if _is_duration(chosen[-1]) and len(chosen) > 1:
            chosen.pop(-2 if len(chosen) > 2 else 0)
        else:
            chosen.pop()
    while chosen and session_volume(chosen) > minutes:
        shrunk = False
        for row in chosen:
            if not _is_duration(row) and row["sets"] > 1:
                row["sets"] -= 1
                shrunk = True
                break
        if not shrunk:
            chosen.pop()
    return chosen


def _exercise_problem(sessions, user=None):
    """A reason the exercises are outside the bounds, or None."""
    cap = _load_cap(user)
    for row in sessions:
        if not isinstance(row, dict):
            return "Each session needs its exercises."
        exercises = row.get("exercises")
        if not isinstance(exercises, list) or not exercises:
            return "Each session needs its exercises."
        if len(exercises) > _MAX_EXERCISES:
            return "That session has too many exercises."
        for exercise in exercises:
            if not isinstance(exercise, dict):
                return "Each exercise has to be an object."
            if any(key not in _EXERCISE_KEYS for key in exercise):
                return "That exercise has a field the week does not use."
            name = exercise.get("name")
            if not isinstance(name, str) or not name.strip():
                return "Each exercise needs a name."
            if _to_failure(exercise):
                return "Training to failure is outside the bounds."
            sets = _whole_number(exercise.get("sets"))
            if sets is None:
                return "Sets have to be a whole number."
            if sets < 1 or sets > _MAX_SETS:
                return "That many sets is outside the bounds."
            if _duration_minutes(exercise.get("reps")) is None:
                reps = _high_reps(exercise.get("reps"))
                if reps is None:
                    return "Reps have to be a whole number."
                if reps < 1 or reps > _MAX_REPS:
                    return "Those reps are outside the bounds."
            if _rest_minutes(exercise.get("rest")) is None:
                return "Each exercise needs a rest."
            if "load_kg" in exercise:
                load_kg = _finite_load(exercise.get("load_kg"))
                if load_kg is None or load_kg <= 0:
                    return "load_kg has to be a finite number."
                if load_kg > cap + 1e-9:
                    return "That load_kg is outside the bounds."
            if _block_minutes(exercise) is None:
                return "Those exercises could not be checked."
        try:
            minutes = float(row.get("minutes"))
        except (TypeError, ValueError):
            return "Each session needs its minutes."
        if isinstance(minutes, float) and not math.isfinite(minutes):
            return "Each session needs its minutes."
        volume = session_volume(exercises)
        if volume is None or volume > minutes + 1e-6:
            return "The exercises do not fit in the session minutes."
    return None


def _exercises(equipment, experience, minutes, sport, injuries, index, day_count):
    """Deterministic sets, reps, rest, and an effort cue for one session."""
    label = _split_name(day_count, index)
    gear = _gear(equipment)
    source = _GYM.get(label, _GYM["Full body"])
    if gear == "dumbbell":
        names = [_dumbbell_name(name) for name in source]
    elif gear == "bodyweight":
        names = [_bodyweight_name(name) for name in source]
    else:
        names = list(source)
    blocked = _blocked_parts(injuries)
    kept = []
    for name in names + list(_SAFE):
        if any(part in name.lower() for part in blocked):
            continue
        if name not in kept:
            kept.append(name)
    if minutes <= 30:
        count = 3
    elif minutes <= 45:
        count = 4
    elif minutes <= 60:
        count = 5
    else:
        count = 6
    sets, reps, rest, effort = _DOSE[experience]
    chosen = []
    for name in kept[:count]:
        chosen.append({
            "name": name,
            "sets": sets,
            "reps": reps,
            "rest": rest,
            "effort": effort,
        })
    sport_row = _sport_exercise(sport)
    if sport_row is not None:
        chosen.append(sport_row)
    chosen = _fit_minutes(chosen, minutes)
    return label, chosen


def _blank_log():
    return {kind: [] for kind in _LOG_KINDS}


def _confirmation_ids(raw):
    if not raw:
        return set()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return set()
    if not isinstance(data, dict):
        return set()
    found = set()
    for row in data.get("confirmations") or []:
        if isinstance(row, dict) and isinstance(row.get("record_id"), str):
            found.add(row["record_id"])
    return found


def _week_landed(folder, new_ids):
    if not new_ids or not folder or not os.path.isdir(folder):
        return False
    for name in os.listdir(folder):
        if not name.endswith(".json") or name == "log.json":
            continue
        path = os.path.join(folder, name)
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        confirmation = data.get("confirmation")
        if isinstance(confirmation, dict) and confirmation.get("record_id") in new_ids:
            return True
    return False


_LOG_ROW_TYPES = ("sets", "weights", "meals", "checkins", "confirmations")


def _row_list(data, key):
    if not isinstance(data, dict):
        return []
    value = data.get(key)
    return list(value) if isinstance(value, list) else []


def _row_counts(rows):
    counts = {}
    for item in rows:
        try:
            token = json.dumps(item, sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError):
            token = repr(item)
        counts[token] = counts.get(token, 0) + 1
    return counts


def _counts_cover(backup_rows, live_rows):
    live_counts = _row_counts(live_rows)
    backup_counts = _row_counts(backup_rows)
    for token, count in live_counts.items():
        if backup_counts.get(token, 0) < count:
            return False
    return True


def _backup_can_replace(backup_bytes, live_bytes):
    """Replace only when the backup is a strict superset of every record type.

    sets, weights, meals, check-ins, and confirmations each have to cover the
    live rows, and the backup has to hold at least one extra row. An empty or
    unparseable backup never replaces the live log. A missing or unparseable
    live log is treated as empty, so a parseable backup can restore it.
    """
    if not backup_bytes:
        return False
    try:
        backup = json.loads(backup_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return False
    if not isinstance(backup, dict):
        return False
    live = {}
    if live_bytes:
        try:
            parsed = json.loads(live_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            parsed = None
        if isinstance(parsed, dict):
            live = parsed
    backup_total = 0
    live_total = 0
    for key in _LOG_ROW_TYPES:
        backup_rows = _row_list(backup, key)
        live_rows = _row_list(live, key)
        if not _counts_cover(backup_rows, live_rows):
            return False
        backup_total += len(backup_rows)
        live_total += len(live_rows)
    return backup_total > live_total


def _log_bytes_valid(raw):
    """True when these bytes are a log this builder can keep."""
    if not raw:
        return False
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return False
    if not isinstance(data, dict):
        return False
    for key, value in data.items():
        if key not in _LOG_KINDS or not isinstance(value, list):
            return False
        if any(not isinstance(item, dict) for item in value):
            return False
    return True


def _reconcile_backup(log_path):
    """Recover a crashed log only after the recovered bytes validate.

    A plain read never removes log.json.bak. The backup is removed only
    after those bytes have been validated and written over the live log.
    """
    backup_path = log_path + ".bak"
    if not os.path.exists(backup_path):
        return
    try:
        backup_bytes = _read_bytes(backup_path)
        live_bytes = _read_bytes(log_path) if os.path.exists(log_path) else b""
    except OSError:
        return
    new_ids = _confirmation_ids(live_bytes) - _confirmation_ids(backup_bytes)
    landed = _week_landed(os.path.dirname(log_path), new_ids)
    try:
        if landed or backup_bytes == live_bytes:
            return
        if not _backup_can_replace(backup_bytes, live_bytes):
            return
        if not _log_bytes_valid(backup_bytes):
            return
        _write_bytes(log_path, backup_bytes)
        written = _read_bytes(log_path)
        if written == backup_bytes and _log_bytes_valid(written) and os.path.exists(backup_path):
            os.remove(backup_path)
    except OSError:
        return


def _drop_backup(backup_path):
    """A finished save leaves no log.json.bak behind from an earlier crash."""
    if not backup_path or not os.path.exists(backup_path):
        return
    try:
        os.remove(backup_path)
    except OSError:
        return


def _read_log(path):
    """The user log beside the week file. A bad file is refused, not rebuilt."""
    _reconcile_backup(path)
    if not os.path.exists(path):
        return _blank_log()
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    cleaned = _blank_log()
    for key, value in data.items():
        if key not in _LOG_KINDS or not isinstance(value, list):
            return None
        if any(not isinstance(item, dict) for item in value):
            return None
        cleaned[key] = value
    return cleaned


def _write_bytes(path, raw):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_json(path, payload):
    _write_bytes(path, (json.dumps(payload) + "\n").encode("utf-8"))


def _read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


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
        if isinstance(user, dict):
            user["experience"] = experience
        allowed, answers = self._authorize(user, profile, readiness_result, self._no)
        if allowed is not None:
            return allowed
        structured = len(days) * minutes / 60.0
        if structured + sport_hours > PlanValidator.MAX_WEEKLY_TRAINING_HOURS:
            return self._no("That week is over the 20 hour training cap.")
        load = 80 if experience == "beginner" else 100
        if load is None or load <= 0:
            return self._no("A baseline load is required.")
        goal = self._goal(profile.get("goal"))
        if isinstance(goal, dict):
            return goal
        note = None
        if injuries.strip().lower() not in _NO_INJURY:
            note = "Do not add load."
        shown_minutes = minutes if minutes != int(minutes) else int(minutes)
        sessions = []
        for index, day in enumerate(days):
            label, exercises = _exercises(
                equipment, experience, minutes, sport, injuries, index, len(days),
            )
            row = {
                "date": day.isoformat(),
                "name": label,
                "load": load,
                "minutes": shown_minutes,
                "equipment": equipment,
                "sport": sport,
                "experience": experience,
                "exercises": exercises,
            }
            if not exercises:
                return self._no("The exercises do not fit in the session minutes.")
            if note:
                row["note"] = note
            sessions.append(row)
        problem = _exercise_problem(sessions, user if isinstance(user, dict) else None)
        if problem:
            return self._no(problem)
        training = {
            "previous_load": load,
            "current_load": load,
            "weeks_since_deload": 0,
            "structured_hours": structured,
            "sport_hours": sport_hours,
        }
        plan = {"training": training}
        if user:
            plan["user"] = user
        if (
            isinstance(user, dict)
            and goal in {"cut", "lose", "gain"}
            and user.get("age") is not None
            and user["age"] >= PlanValidator.ADULT_AGE
        ):
            targets = self._nutrition(user, goal)
            if isinstance(targets, dict):
                return targets
            nutrition, goals = targets
            plan["nutrition"] = nutrition
            plan["goals"] = goals
        if answers is not None:
            plan["par_q"] = self._with_source(answers, user)
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
        age_gate, _answers = self._authorize(plan.get("user"), plan, readiness_result, self._saved_no)
        if age_gate is not None:
            return age_gate
        source_error = self._par_q_source_error(plan, self._saved_no)
        if source_error is not None:
            return source_error
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
        week = week_to_confirm(plan, sessions)
        covered = isinstance(confirmation, ConfirmationRecord) and (
            ConfirmationRecorder().covers(confirmation, week)
            or covers_first_plan(confirmation, week)
        )
        if not covered:
            return self._saved_no("This week needs record_confirmation before it is saved.")
        problem = _exercise_problem(sessions, plan.get("user") if isinstance(plan.get("user"), dict) else None)
        if problem:
            return self._saved_no(problem)
        target = os.fspath(path)
        log_path = os.path.join(os.path.dirname(target), "log.json")
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
        log_existed = os.path.exists(log_path)
        loaded_log = _read_log(log_path)
        if loaded_log is None:
            return self._saved_no("The log could not be read.")
        stamp = confirmation.timestamp if confirmation.timestamp else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        on_file = existing.get("confirmation") if isinstance(existing.get("confirmation"), dict) else {}
        on_id = on_file.get("record_id") if isinstance(on_file.get("record_id"), str) else ""
        on_at = on_file.get("saved_at") if isinstance(on_file.get("saved_at"), str) else ""
        already = any(
            isinstance(row, dict) and row.get("record_id") == confirmation.record_id
            for row in loaded_log["confirmations"]
        )
        if already and on_id and on_id != confirmation.record_id:
            return self._saved_no("An older yes does not replace the saved week.")
        if on_at and stamp < on_at:
            return self._saved_no("An older yes does not replace the saved week.")
        if already and os.path.exists(target) and (on_id == confirmation.record_id or not on_id):
            _drop_backup(log_path + ".bak")
            return {
                "ok": True,
                "saved": True,
                "applied": False,
                "message": "Week saved.",
                "path": target,
                "log_path": log_path,
            }
        if already and not os.path.exists(target):
            newer = any(
                isinstance(row, dict)
                and row.get("record_id") != confirmation.record_id
                and isinstance(row.get("date"), str)
                and row["date"] > stamp
                for row in loaded_log["confirmations"]
            )
            if newer:
                return self._saved_no("An older yes does not replace the saved week.")
            existing = {
                "plan": plan,
                "sessions": sessions,
                "confirmation": {
                    "record_id": confirmation.record_id,
                    "plan_hash": confirmation.plan_hash,
                    "saved_at": stamp,
                },
            }
            try:
                _write_json(target, existing)
            except OSError:
                return self._saved_no("The week could not be saved.")
            _drop_backup(log_path + ".bak")
            return {
                "ok": True,
                "saved": True,
                "applied": False,
                "message": "Week saved.",
                "path": target,
                "log_path": log_path,
            }
        existing["plan"] = plan
        existing["sessions"] = sessions
        existing["confirmation"] = {
            "record_id": confirmation.record_id,
            "plan_hash": confirmation.plan_hash,
            "saved_at": stamp,
        }
        proposal = week_to_confirm(plan, sessions)
        loaded_log["confirmations"].append({
            "record_id": confirmation.record_id,
            "plan_hash": confirmation.plan_hash,
            "quoted_words": confirmation.quoted_words,
            "speaker": confirmation.speaker,
            "date": stamp,
            "timestamp": confirmation.timestamp,
            "issuer_seal": confirmation.issuer_seal,
            "confirmed": True,
            "message": confirmation.message,
        })
        for key in ("load", "calories"):
            if key not in proposal.get("changes", {}):
                continue
            loaded_log["confirmations"].append({
                "date": stamp,
                "timestamp": confirmation.timestamp,
                "issuer_seal": confirmation.issuer_seal,
                "confirmed": True,
                "changes": {key: proposal["changes"][key]},
                "proposal": proposal,
                "record_id": confirmation.record_id,
                "plan_hash": confirmation.plan_hash,
                "quoted_words": confirmation.quoted_words,
                "speaker": confirmation.speaker,
            })
        original_bytes = b""
        backup_path = log_path + ".bak"
        try:
            if log_existed:
                original_bytes = _read_bytes(log_path)
            _write_bytes(backup_path, original_bytes)
        except OSError:
            return self._saved_no("The log could not be saved.")
        try:
            _write_json(log_path, loaded_log)
        except OSError:
            self._restore_log(log_path, original_bytes, log_existed, backup_path)
            return self._saved_no("The log could not be saved.")
        try:
            _write_json(target, existing)
        except OSError:
            restored = self._restore_log(log_path, original_bytes, log_existed, backup_path)
            if not restored:
                restored = self._restore_log(log_path, None, log_existed, backup_path)
            week_tmp = target + ".tmp"
            if os.path.exists(week_tmp):
                try:
                    os.remove(week_tmp)
                except OSError:
                    pass
            if os.path.exists(backup_path) and restored:
                try:
                    os.remove(backup_path)
                except OSError:
                    pass
            return self._saved_no("The week could not be saved.")
        _drop_backup(backup_path)
        return {
            "ok": True,
            "saved": True,
            "applied": False,
            "message": "Week saved.",
            "path": target,
            "log_path": log_path,
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

    def _restore_log(self, log_path, original_bytes, log_existed, backup_path):
        """Put the log back from the backup before a failure is reported.

        The backup is renamed over the log. That still works when a fresh
        write of the old bytes fails, which is the case that used to leave
        the new rows in place.
        """
        for _attempt in range(3):
            try:
                if not log_existed:
                    if os.path.exists(log_path):
                        os.remove(log_path)
                    temporary = log_path + ".tmp"
                    if os.path.exists(temporary):
                        os.remove(temporary)
                    if not os.path.exists(log_path):
                        return True
                    continue
                if backup_path and os.path.exists(backup_path):
                    os.replace(backup_path, log_path)
                    if original_bytes is None or _read_bytes(log_path) == original_bytes:
                        return True
                raw = original_bytes
                if raw is None and backup_path and os.path.exists(backup_path):
                    raw = _read_bytes(backup_path)
                if raw is None:
                    return False
                _write_bytes(log_path, raw)
                if _read_bytes(log_path) == raw:
                    return True
            except OSError:
                continue
        return False

    def _goal(self, value):
        if value in (None, ""):
            return None
        if not isinstance(value, str):
            return self._no("The goal has to be cut, lose, gain, or hold.")
        text = value.strip().lower()
        if text not in {"cut", "lose", "gain", "hold"}:
            return self._no("The goal has to be cut, lose, gain, or hold.")
        return text

    def _nutrition(self, user, goal):
        """A first calorie and protein target that stays on the safe side of plan_check."""
        try:
            sex = InputValidator.parse_sex(user["sex"], "sex").value
            weight = InputValidator.parse_number(user["weight_kg"], "weight_kg")
            height = InputValidator.parse_number(user["height_cm"], "height_cm")
            age = int(user["age"])
        except ValidationError as exc:
            return self._no(str(exc))
        bmr = PlanValidator.estimate_bmr(weight, sex, age, height)
        floor = PlanValidator.CALORIE_FLOOR_MEN if sex == "M" else PlanValidator.CALORIE_FLOOR_WOMEN
        calories = max(floor, math.ceil(bmr - 1e-9))
        if goal == "gain":
            calories = max(calories, math.ceil(bmr - 1e-9) + 200)
        low = math.ceil(weight * PlanValidator.MIN_PROTEIN_G_PER_KG - 1e-9)
        high = math.floor(weight * PlanValidator.MAX_PROTEIN_G_PER_KG + 1e-9)
        protein = int(round(weight * 1.8))
        protein = min(max(protein, low), max(high, low))
        rate = round(weight * 0.005, 2)
        cap = round(weight * (PlanValidator.MAX_WEIGHT_LOSS_PERCENT / 100), 2)
        if rate < 0.01:
            rate = 0.01
        if cap >= 0.01 and rate > cap:
            rate = cap
        if goal == "gain":
            rate = -rate
        return (
            {"calories": int(calories), "protein_g": int(protein)},
            {"goal": goal, "weight_loss_kg_per_week": rate},
        )

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

    def _authorize(self, user, par_source, readiness_result, no):
        """Age or a passing screen, and a complete PAR-Q or that same screen."""
        if readiness_result is not None and not screening_seal_matches(readiness_result):
            return no("This readiness screen was not issued by readiness_screen."), None
        age = None
        if isinstance(user, dict) and user.get("age") not in (None, ""):
            try:
                age = InputValidator.parse_number(user["age"], "age")
            except ValidationError as exc:
                return no(str(exc)), None
        if age is not None and age < PlanValidator.ADULT_AGE:
            return no("There is no training plan for anyone under 18."), None
        if age is None and not self._readiness_passes(readiness_result):
            return no(
                "An age or a passing readiness screen is required before this week is built. "
                "A missing baseline does not get a plan."
            ), None
        if age is not None and age < PlanValidator.ADULT_AGE and not self._readiness_passes(readiness_result):
            return no("A passing readiness screen is required before this week is built."), None
        status, answers = self._par_q_answers(par_source)
        if status != "clear" and not self._readiness_passes(readiness_result):
            if status == "yes" and answers:
                result = ReadinessScreen().check_par_q(answers)
                text = " ".join(result.reasons) if result.reasons else "A PAR-Q yes blocks this week."
                return no(text), None
            return no(
                "A skipped or partial PAR-Q needs a passing readiness screen before this week is built."
            ), None
        needs_screen = (
            age is None
            or (age is not None and age < PlanValidator.ADULT_AGE)
            or status != "clear"
        )
        if needs_screen:
            mismatch = self._different_person(readiness_result, user, no)
            if mismatch is not None:
                return mismatch, None
        return None, answers

    def _has_body_details(self, user):
        if not isinstance(user, dict):
            return False
        return any(user.get(key) not in (None, "") for key in ("sex", "weight_kg", "age", "height_cm"))

    def _different_person(self, result, user, no):
        if not self._has_body_details(user):
            return no("This readiness screen cannot be tied to a person.")
        if getattr(result, "subject_hash", "") != subject_hash(user):
            return no("This readiness screen is for a different person.")
        return None

    def _with_source(self, answers, user):
        stamped = dict(answers)
        stamped["source"] = subject_hash(user if isinstance(user, dict) else {})
        return stamped

    def _par_q_source_error(self, plan, no):
        if not isinstance(plan, dict) or "par_q" not in plan:
            return None
        raw = plan.get("par_q")
        user = plan.get("user")
        if not isinstance(raw, dict) or not self._has_body_details(user):
            return no("This PAR-Q cannot be tied to a person.")
        source = raw.get("source")
        if not isinstance(source, str) or source != subject_hash(user):
            return no("This PAR-Q source does not match the user.")
        return None

    def _par_q_answers(self, source):
        flags = tuple(ReadinessScreen.PAR_Q_RED_FLAGS)
        if not isinstance(source, dict):
            return "missing", None
        raw = {}
        saw = False
        nested = source.get("par_q") if "par_q" in source else None
        if isinstance(nested, dict):
            saw = True
            raw.update(nested)
        elif "par_q" in source and nested is not None:
            return "partial", None
        for key in flags:
            if key in source:
                saw = True
                raw[key] = source[key]
        if not saw:
            return "missing", None
        parsed = {}
        for key, value in raw.items():
            if key == "source":
                continue
            if key not in flags:
                return "partial", None
            if isinstance(value, bool):
                parsed[key] = value
                continue
            try:
                parsed[key] = InputValidator.parse_boolean(value, key)
            except ValidationError:
                return "partial", None
        if any(key not in parsed for key in flags):
            return "partial", parsed or None
        if any(parsed[key] for key in flags):
            return "yes", parsed
        return "clear", parsed

    def _positive_load(self, value):
        try:
            number = InputValidator.parse_number(value, "load", allow_zero=True)
        except ValidationError:
            return None
        if number <= 0:
            return None
        return number

    def _readiness_passes(self, result) -> bool:
        return passing_readiness(result)

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
