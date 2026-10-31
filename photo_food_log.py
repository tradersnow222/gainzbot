#!/usr/bin/env python3
"""
Log food from a photo estimate or a remembered usual meal.

The Grok vision prompt asks for items, calories, and protein. This script
does not call the model. store_estimate logs a meal only after
record_confirmation covers that exact estimate. Each confirmation logs
one meal. The check is the record id, and those ids are saved to a
required path, so a copy or a restart cannot log that same yes again.
If that file is missing after the first log, nothing else is stored.
A new yes can log the meal when the file is still there.
When log_path is set, the meal and that confirmation id are also appended
to the on-disk user log. If that append fails, the meal is not kept and
the confirmation is not used.
A single item over 3000 kcal or over 300 g protein is rejected for a
re-check, and a day stops at 10000 kcal. Missing age and under 18 set no
protein target. usual breakfast needs a confirmation. A total the user
states, calories and protein in their own words, logs with no confirm.
The bot's own estimate still needs one. Logging a meal does not change
the plan.
"""

from datetime import date, datetime, timezone
from typing import Dict, List, Optional
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guardrails.validate import InputValidator, ValidationError
from plan_check import PlanValidator
from record_confirmation import ConfirmationRecord, ConfirmationRecorder

MAX_ITEM_CALORIES = 3000
MAX_ITEM_PROTEIN_G = 300
MAX_DAILY_CALORIES = 10000
_STATED_CALORIES = re.compile(
    r"(?:\b(?:about|around|roughly)\s+)?"
    r"(\d+(?:\.\d+)?)\s*"
    r"(?:kcals?|calories|calorie|cals|cal)\b",
    re.IGNORECASE,
)
_STATED_PROTEIN = re.compile(
    r"(\d+(?:\.\d+)?)\s*g(?:rams)?\s*(?:of\s+)?protein\b"
    r"|\bprotein\s*(?:of\s+)?(\d+(?:\.\d+)?)\s*g(?:rams)?\b",
    re.IGNORECASE,
)


GROK_VISION_PROMPT = (
    "Look at this meal photo. Reply with JSON only, with keys items "
    "(a list of food names), calories (a number), and protein_g (a number). "
    "Estimate the portion you can see. If you cannot tell, use null. "
    "Do not give a daily calorie target."
)


def _parse_day(value) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _whole(value: float):
    if abs(value - round(value)) < 1e-9:
        return int(round(value))
    return round(value, 1)


class FoodLog:
    """Stores meal estimates and remembered usual meals."""

    def __init__(self, used_path=None):
        self.entries: List[Dict] = []
        self.usuals: Dict[str, Dict] = {}
        self.used_ids: List[str] = []
        self._used_error = None
        if used_path is None:
            self.used_path = None
            self._used_error = "A used confirmation list path is required."
            return
        self.used_path = os.fspath(used_path)
        loaded = self._read_used(self.used_path)
        if isinstance(loaded, str):
            self._used_error = loaded
        else:
            self.used_ids = loaded

    def remember_usual(self, name, items, calories, protein_g, confirmation=None) -> Dict:
        key = self._usual_name(name)
        if not key:
            return self._no("Name the usual meal.")
        parsed = self._meal(items, calories, protein_g)
        if not parsed["ok"]:
            return parsed
        meal = parsed["meal"]
        plan = {
            "remember_usual": key,
            "items": list(meal["items"]),
            "calories": meal["calories"],
            "protein_g": meal["protein_g"],
        }
        if not isinstance(confirmation, ConfirmationRecord) or not ConfirmationRecorder().covers(confirmation, plan):
            return self._no("This usual meal needs record_confirmation before it is saved.")
        self.usuals[key] = meal
        return {
            "ok": True,
            "stored": True,
            "applied": False,
            "message": f"Remembered usual {key}.",
            "meal": meal,
        }

    def log_line(self, line, day, confirmation=None, log_path=None) -> Dict:
        """Log one remembered meal from a line such as 'usual breakfast'."""
        name = self._line_usual(line)
        if not name:
            return self._no("Say 'usual breakfast' to log a remembered meal.")
        meal = self.usuals.get(name)
        if not meal:
            return self._no(f"No usual {name} is remembered yet.")
        plan = {
            "usual": name,
            "items": list(meal["items"]),
            "calories": meal["calories"],
            "protein_g": meal["protein_g"],
        }
        error = self._check_used()
        if error:
            return self._no(error)
        if not self._covers_fresh(confirmation, plan):
            if self._already_used(confirmation):
                return self._no("That confirmation was already used for one log.")
            return self._no("This usual meal needs record_confirmation before it is logged.")
        stored = self._store(meal, day, "usual")
        if stored.get("stored"):
            kept = self._keep(stored, confirmation, log_path)
            if not kept["ok"]:
                return kept
        return stored

    def log_stated(self, line, day, log_path=None) -> Dict:
        """Log a calorie and protein total the user stated. No confirm."""
        parsed = self._stated(line)
        if not parsed["ok"]:
            return parsed
        stored = self._store(parsed["meal"], day, "stated")
        if stored.get("stored") and log_path is not None:
            kept = self._append_stated(log_path, stored["entry"])
            if not kept["ok"]:
                self.entries.pop()
                return kept
        return stored

    def store_estimate(self, estimate, day, confirmation=None, log_path=None) -> Dict:
        if not isinstance(estimate, dict):
            return self._no("The photo estimate has to be an object.")
        parsed = self._meal(
            estimate.get("items"),
            estimate.get("calories"),
            estimate.get("protein_g"),
        )
        if not parsed["ok"]:
            return parsed
        error = self._check_used()
        if error:
            return self._no(error)
        if not self._covers_fresh(confirmation, estimate):
            if self._already_used(confirmation):
                return self._no("That confirmation was already used for one log.")
            return self._no("This estimate needs record_confirmation before it is logged.")
        stored = self._store(parsed["meal"], day, "photo")
        if stored.get("stored"):
            kept = self._keep(stored, confirmation, log_path)
            if not kept["ok"]:
                return kept
        return stored

    def left_today(self, day, user=None, targets=None) -> Dict:
        """Calories and protein still left today. No plan change is applied."""
        user = user if isinstance(user, dict) else {}
        when = _parse_day(day)
        if when is None:
            return {
                "ok": False,
                "applied": False,
                "message": "The day needs a real date.",
                "eaten_calories": 0,
                "eaten_protein_g": 0,
                "calories_left": None,
                "protein_left": None,
            }
        eaten_calories = 0.0
        eaten_protein = 0.0
        for entry in self.entries:
            if entry["date"] != when:
                continue
            eaten_calories += entry["calories"]
            eaten_protein += entry["protein_g"]
        calorie_target, calorie_note = self._calorie_target(user, targets)
        protein_target, protein_note = self._protein_target(user, targets)
        notes = [note for note in (calorie_note, protein_note) if note]
        return {
            "ok": True,
            "applied": False,
            "date": when.isoformat(),
            "eaten_calories": _whole(eaten_calories),
            "eaten_protein_g": _whole(eaten_protein),
            "calories_left": None if calorie_target is None else _whole(calorie_target - eaten_calories),
            "protein_left": None if protein_target is None else _whole(protein_target - eaten_protein),
            "message": " ".join(notes) if notes else "Here is what is left today.",
        }

    def _stated(self, line) -> Dict:
        if not isinstance(line, str) or not line.strip():
            return self._no("Say the calories and the protein to log a total.")
        calories = _STATED_CALORIES.search(line)
        protein = _STATED_PROTEIN.search(line)
        if calories is None or protein is None:
            return self._no("Say the calories and the protein to log a total.")
        protein_text = protein.group(1) or protein.group(2)
        try:
            kcal = InputValidator.parse_number(calories.group(1), "calories", allow_zero=True)
            grams = InputValidator.parse_number(protein_text, "protein_g", allow_zero=True)
        except ValidationError as exc:
            return self._no(str(exc))
        if kcal > MAX_ITEM_CALORIES or grams > MAX_ITEM_PROTEIN_G:
            return self._no("That estimate is too high. Re-check it before logging.")
        return {
            "ok": True,
            "meal": {"items": ["stated total"], "calories": kcal, "protein_g": grams},
        }

    def _append_stated(self, log_path, entry) -> Dict:
        from log_store import LogStore

        meal = {
            "date": entry["date"],
            "items": list(entry["items"]),
            "calories": entry["calories"],
            "protein_g": entry["protein_g"],
            "source": "stated",
        }
        saved = LogStore(log_path).append("meals", meal)
        if not saved["ok"]:
            return self._no(saved["message"])
        return {"ok": True}

    def _store(self, meal, day, source: str) -> Dict:
        when = _parse_day(day)
        if when is None:
            return self._no("The day needs a real date.")
        already = sum(entry["calories"] for entry in self.entries if entry["date"] == when)
        if already + meal["calories"] > MAX_DAILY_CALORIES:
            return self._no("That day is over the 10,000 kcal cap.")
        entry = {
            "date": when,
            "items": list(meal["items"]),
            "calories": meal["calories"],
            "protein_g": meal["protein_g"],
            "source": source,
        }
        self.entries.append(entry)
        stored = dict(entry)
        stored["date"] = when.isoformat()
        return {
            "ok": True,
            "stored": True,
            "applied": False,
            "message": "Meal stored. The plan is unchanged.",
            "entry": stored,
        }

    def _meal(self, items, calories, protein_g) -> Dict:
        names = self._items(items)
        if not names:
            return self._no("The meal needs at least one food name.")
        try:
            kcal = InputValidator.parse_number(calories, "calories", allow_zero=True)
            protein = InputValidator.parse_number(protein_g, "protein_g", allow_zero=True)
        except ValidationError as exc:
            return self._no(str(exc))
        if kcal > MAX_ITEM_CALORIES or protein > MAX_ITEM_PROTEIN_G:
            return self._no("That estimate is too high. Re-check it before logging.")
        return {
            "ok": True,
            "meal": {"items": names, "calories": kcal, "protein_g": protein},
        }

    def _items(self, items) -> List[str]:
        if not isinstance(items, list) or not items:
            return []
        names = []
        for item in items:
            if not isinstance(item, str) or not item.strip():
                return []
            names.append(item.strip())
        return names

    def _usual_name(self, name) -> Optional[str]:
        if not isinstance(name, str):
            return None
        text = " ".join(name.lower().split())
        if text.startswith("usual "):
            text = text[6:].strip()
        return text or None

    def _line_usual(self, line) -> Optional[str]:
        if not isinstance(line, str):
            return None
        text = " ".join(line.lower().split())
        if not text.startswith("usual "):
            return None
        return text[6:].strip() or None

    def _age(self, user) -> Optional[float]:
        if "age" not in user:
            return None
        try:
            return InputValidator.parse_number(user["age"], "age")
        except ValidationError:
            return None

    def _sex(self, user) -> Optional[str]:
        if "sex" not in user:
            return None
        try:
            return InputValidator.parse_sex(user["sex"], "sex").value
        except ValidationError:
            return None

    def _calorie_target(self, user, targets):
        age = self._age(user)
        if age is None:
            return None, "No calorie target is set when age is missing."
        if age < PlanValidator.ADULT_AGE:
            return None, "No calorie target is set under 18."
        sex = self._sex(user)
        if sex is None:
            return None, "No calorie target is set when sex is missing."
        if not isinstance(targets, dict) or "calories" not in targets:
            return None, "No calorie target is set."
        try:
            calories = InputValidator.parse_number(targets["calories"], "calories")
        except ValidationError as exc:
            return None, str(exc)
        floor = PlanValidator.CALORIE_FLOOR_MEN if sex == "M" else PlanValidator.CALORIE_FLOOR_WOMEN
        if calories < floor:
            return None, f"Calorie target is below the floor of {floor}."
        return calories, ""

    def _covers_fresh(self, confirmation, plan) -> bool:
        if self._already_used(confirmation):
            return False
        return isinstance(confirmation, ConfirmationRecord) and ConfirmationRecorder().covers(confirmation, plan)

    def _record_id(self, confirmation) -> Optional[str]:
        if not isinstance(confirmation, ConfirmationRecord):
            return None
        record_id = confirmation.record_id
        if not isinstance(record_id, str) or not record_id.strip():
            return None
        return record_id

    def _already_used(self, confirmation) -> bool:
        record_id = self._record_id(confirmation)
        return record_id is not None and record_id in self.used_ids

    def _marker(self, path: str) -> str:
        return path + ".started"

    def _check_used(self) -> Optional[str]:
        if self.used_path is None:
            return "A used confirmation list path is required."
        if self._used_error:
            return self._used_error
        if not os.path.exists(self.used_path) and os.path.exists(self._marker(self.used_path)):
            self._used_error = "The used confirmation list is missing."
            return self._used_error
        return None

    def _keep(self, stored, confirmation, log_path) -> Dict:
        """Remember the yes, and append the meal when a log path is set."""
        if log_path is not None:
            logged = self._append_log(log_path, stored["entry"], confirmation)
            if not logged["ok"]:
                self.entries.pop()
                return self._no(logged["message"])
        saved = self._remember(confirmation)
        if not saved["ok"]:
            self.entries.pop()
            if log_path is not None:
                self._drop_log(log_path)
            return saved
        return stored

    def _append_log(self, log_path, entry, confirmation) -> Dict:
        from log_store import LogStore

        store = LogStore(log_path)
        meal = {
            "date": entry["date"],
            "items": list(entry["items"]),
            "calories": entry["calories"],
            "protein_g": entry["protein_g"],
            "source": entry.get("source"),
        }
        saved = store.append("meals", meal)
        if not saved["ok"]:
            return saved
        record_id = self._record_id(confirmation)
        if record_id is None:
            store.drop_last("meals")
            return self._no("That confirmation has no record id.")
        used = store.append("used_records", {"record_id": record_id})
        if not used["ok"]:
            store.drop_last("meals")
            return used
        noted = store.append("confirmations", {
            "record_id": record_id,
            "kind": "meal",
            "date": entry["date"],
            "plan_hash": confirmation.plan_hash,
            "quoted_words": confirmation.quoted_words,
            "speaker": confirmation.speaker,
            "confirmed": True,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        if not noted["ok"]:
            store.drop_last("used_records")
            store.drop_last("meals")
            return noted
        return {"ok": True}

    def _drop_log(self, log_path) -> None:
        from log_store import LogStore

        store = LogStore(log_path)
        if store.error:
            return
        store.drop_last("confirmations")
        store.drop_last("used_records")
        store.drop_last("meals")

    def _remember(self, confirmation) -> Dict:
        record_id = self._record_id(confirmation)
        if record_id is None:
            return self._no("That confirmation has no record id.")
        if self.used_path is None:
            return self._no("A used confirmation list path is required.")
        self.used_ids.append(record_id)
        try:
            self._write_used(self.used_path, self.used_ids)
            self._write_marker(self.used_path)
        except OSError:
            self.used_ids.pop()
            return self._no("The used confirmation list could not be saved.")
        return {"ok": True}

    def _read_used(self, path):
        if not os.path.exists(path):
            if os.path.exists(self._marker(path)):
                return "The used confirmation list is missing."
            return []
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return "The used confirmation list could not be read."
        if not isinstance(data, list) or any(not isinstance(item, str) or not item for item in data):
            return "The used confirmation list could not be read."
        return data

    def _write_used(self, path, used_ids: List[str]) -> None:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(used_ids, handle)
            handle.write("\n")
        os.replace(temporary, path)

    def _write_marker(self, path: str) -> None:
        marker = self._marker(path)
        if os.path.exists(marker):
            return
        temporary = marker + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write("used\n")
        os.replace(temporary, marker)

    def _protein_target(self, user, targets):
        age = self._age(user)
        if age is None:
            return None, "No protein target is set when age is missing."
        if age < PlanValidator.ADULT_AGE:
            return None, "No protein target is set under 18."
        if "weight_kg" not in user:
            return None, "No protein target is set when weight is missing."
        try:
            weight = InputValidator.parse_number(user["weight_kg"], "weight_kg")
        except ValidationError as exc:
            return None, str(exc)
        if not isinstance(targets, dict) or "protein_g" not in targets:
            return None, "No protein target is set."
        try:
            protein = InputValidator.parse_number(targets["protein_g"], "protein_g")
        except ValidationError as exc:
            return None, str(exc)
        per_kg = protein / weight
        if per_kg < PlanValidator.MIN_PROTEIN_G_PER_KG or per_kg > PlanValidator.MAX_PROTEIN_G_PER_KG:
            return None, "Protein target is outside 1.6 to 2.2 grams per kilogram."
        return protein, ""

    def _no(self, message: str) -> Dict:
        return {"ok": False, "stored": False, "applied": False, "message": message}
