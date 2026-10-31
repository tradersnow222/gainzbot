#!/usr/bin/env python3
"""
Log food from a photo estimate or a remembered usual meal.

The Grok vision prompt asks for items, calories, and protein. This script
does not call the model. store_estimate logs a meal only after
record_confirmation covers that exact estimate. A single item over 3000
kcal or over 300 g protein is rejected for a re-check. Under 18, no
protein target is set. Logging a meal does not change the plan.
"""

from datetime import date, datetime
from typing import Dict, List, Optional
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guardrails.validate import InputValidator, ValidationError
from plan_check import PlanValidator
from record_confirmation import ConfirmationRecord, ConfirmationRecorder

MAX_ITEM_CALORIES = 3000
MAX_ITEM_PROTEIN_G = 300


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

    def __init__(self):
        self.entries: List[Dict] = []
        self.usuals: Dict[str, Dict] = {}

    def remember_usual(self, name, items, calories, protein_g) -> Dict:
        key = self._usual_name(name)
        if not key:
            return self._no("Name the usual meal.")
        parsed = self._meal(items, calories, protein_g)
        if not parsed["ok"]:
            return parsed
        self.usuals[key] = parsed["meal"]
        return {
            "ok": True,
            "stored": True,
            "applied": False,
            "message": f"Remembered usual {key}.",
            "meal": parsed["meal"],
        }

    def log_line(self, line, day) -> Dict:
        """Log one remembered meal from a line such as 'usual breakfast'."""
        name = self._line_usual(line)
        if not name:
            return self._no("Say 'usual breakfast' to log a remembered meal.")
        meal = self.usuals.get(name)
        if not meal:
            return self._no(f"No usual {name} is remembered yet.")
        return self._store(meal, day, "usual")

    def store_estimate(self, estimate, day, confirmation=None) -> Dict:
        if not isinstance(estimate, dict):
            return self._no("The photo estimate has to be an object.")
        parsed = self._meal(
            estimate.get("items"),
            estimate.get("calories"),
            estimate.get("protein_g"),
        )
        if not parsed["ok"]:
            return parsed
        if not isinstance(confirmation, ConfirmationRecord) or not ConfirmationRecorder().covers(confirmation, estimate):
            return self._no("This estimate needs record_confirmation before it is logged.")
        return self._store(parsed["meal"], day, "photo")

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

    def _store(self, meal, day, source: str) -> Dict:
        when = _parse_day(day)
        if when is None:
            return self._no("The day needs a real date.")
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

    def _protein_target(self, user, targets):
        age = self._age(user)
        if age is not None and age < PlanValidator.ADULT_AGE:
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
