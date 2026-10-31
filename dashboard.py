#!/usr/bin/env python3
"""
Chart data for the dashboard.

The spec is chart-first: weight, calories and protein against the target,
adherence, and personal records. The window is 7, 28, 90, or 365 days.
This builder only reads logs. It does not change the plan.
"""

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guardrails.validate import InputValidator, ValidationError
from plan_check import PlanValidator


WINDOWS = (7, 28, 90, 365)
NOT_ENOUGH = "not enough data yet"

DASHBOARD_SPEC = {
    "layout": "charts",
    "windows": list(WINDOWS),
    "charts": [
        {"id": "weight", "title": "Weight", "kind": "line"},
        {"id": "calories", "title": "Calories vs target", "kind": "bar"},
        {"id": "protein", "title": "Protein vs target", "kind": "bar"},
        {"id": "adherence", "title": "Adherence", "kind": "bar"},
        {"id": "records", "title": "Personal records", "kind": "table"},
    ],
}


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


def _number(value) -> Optional[float]:
    try:
        return InputValidator.parse_number(value, "value", allow_zero=True)
    except (ValidationError, TypeError):
        return None


def _whole(value: float):
    if abs(value - round(value)) < 1e-9:
        return int(round(value))
    return round(value, 1)


class Dashboard:
    """Builds the chart series for one window."""

    def build(self, logs, user=None, window_days=28, as_of=None, targets=None) -> Dict:
        if window_days not in WINDOWS:
            return self._empty("Use a window of 7, 28, 90, or 365 days.", None)
        user = user if isinstance(user, dict) else {}
        rows = self._rows(logs)
        end = _parse_day(as_of) if as_of is not None else None
        if end is None:
            dates = [row["date"] for row in rows]
            end = max(dates) if dates else None
        if end is None:
            return self._empty(NOT_ENOUGH, window_days)
        start = end - timedelta(days=window_days - 1)
        window = [row for row in rows if start <= row["date"] <= end]
        if len(window) < 2:
            return self._empty(NOT_ENOUGH, window_days)

        calorie_target, calorie_note = self._calorie_target(user, targets)
        protein_target, protein_note = self._protein_target(user, targets)
        charts = [
            self._weight_chart(window),
            self._intake_chart("calories", "Calories vs target", window, calorie_target),
            self._intake_chart("protein", "Protein vs target", window, protein_target),
            self._adherence_chart(window),
            self._records_chart(window),
        ]
        notes = [note for note in (calorie_note, protein_note) if note]
        return {
            "applied": False,
            "enough_data": True,
            "window_days": window_days,
            "spec": DASHBOARD_SPEC,
            "charts": charts,
            "message": " ".join(notes) if notes else "Dashboard ready.",
        }

    def build_saved(self, path, user=None, window_days=28, as_of=None, targets=None) -> Dict:
        """Read the on-disk log. A bad file does not become chart data."""
        from log_store import LogStore

        store = LogStore(path)
        if store.error or store.as_dashboard() is None:
            return self._empty(store.error or "The log could not be read.", window_days if window_days in WINDOWS else None)
        return self.build(store.as_dashboard(), user, window_days, as_of, targets)

    def _empty(self, message: str, window_days) -> Dict:
        charts = []
        for chart in DASHBOARD_SPEC["charts"]:
            blank = {"id": chart["id"], "title": chart["title"], "kind": chart["kind"]}
            if chart["id"] == "adherence":
                blank.update({"completed": 0, "planned": 0, "rate": None})
            elif chart["id"] == "records":
                blank["rows"] = []
            else:
                blank["points"] = []
            charts.append(blank)
        return {
            "applied": False,
            "enough_data": False,
            "window_days": window_days,
            "spec": DASHBOARD_SPEC,
            "charts": charts,
            "message": message,
        }

    def _rows(self, logs) -> List[Dict]:
        rows = []
        if not isinstance(logs, dict):
            return rows
        buckets = {
            "weight": ("weights", "weight"),
            "intake": ("intake", "intakes"),
            "session": ("sessions", "adherence"),
            "set": ("sets",),
        }
        for kind, keys in buckets.items():
            for key in keys:
                values = logs.get(key)
                if not isinstance(values, list):
                    continue
                for item in values:
                    row = self._row(item, kind)
                    if row:
                        rows.append(row)
        return rows

    def _row(self, item, kind) -> Optional[Dict]:
        if not isinstance(item, dict):
            return None
        day = _parse_day(item.get("date") or item.get("day"))
        if day is None:
            return None
        row = {"date": day, "kind": kind}
        if kind == "weight":
            weight = _number(item.get("kg", item.get("weight")))
            if weight is None or weight <= 0:
                return None
            row["kg"] = weight
        elif kind == "intake":
            calories = item.get("calories")
            protein = item.get("protein_g", item.get("protein"))
            if calories is not None:
                parsed = _number(calories)
                if parsed is not None:
                    row["calories"] = parsed
            if protein is not None:
                parsed = _number(protein)
                if parsed is not None:
                    row["protein"] = parsed
            if "calories" not in row and "protein" not in row:
                return None
        elif kind == "session":
            row["planned"] = item.get("planned", True) not in (False, "no", "false", 0)
            if item.get("missed") in (True, "yes", "true", 1):
                row["completed"] = False
            else:
                row["completed"] = item.get("completed") in (True, "yes", "true", 1)
        elif kind == "set":
            name = item.get("exercise")
            weight = _number(item.get("weight"))
            reps = _number(item.get("reps"))
            if not isinstance(name, str) or not name.strip() or not weight or not reps:
                return None
            row["exercise"] = " ".join(name.split())
            row["weight"] = weight
            row["reps"] = reps
        return row

    def _weight_chart(self, rows) -> Dict:
        points = []
        seen = {}
        for row in rows:
            if row["kind"] != "weight":
                continue
            seen[row["date"]] = row["kg"]
        for day in sorted(seen):
            points.append({"date": day.isoformat(), "kg": _whole(seen[day])})
        return {"id": "weight", "title": "Weight", "kind": "line", "points": points}

    def _intake_chart(self, key, title, rows, target) -> Dict:
        totals: Dict[date, float] = {}
        source = "calories" if key == "calories" else "protein"
        for row in rows:
            if row["kind"] != "intake" or source not in row:
                continue
            totals[row["date"]] = totals.get(row["date"], 0) + row[source]
        points = []
        for day in sorted(totals):
            points.append({
                "date": day.isoformat(),
                "eaten": _whole(totals[day]),
                "target": None if target is None else _whole(target),
            })
        return {"id": key, "title": title, "kind": "bar", "points": points}

    def _adherence_chart(self, rows) -> Dict:
        sessions = [row for row in rows if row["kind"] == "session" and row.get("planned")]
        planned = len(sessions)
        completed = sum(1 for row in sessions if row["completed"])
        rate = None if planned == 0 else round(completed / planned, 2)
        return {
            "id": "adherence",
            "title": "Adherence",
            "kind": "bar",
            "completed": completed,
            "planned": planned,
            "rate": rate,
        }

    def _records_chart(self, rows) -> Dict:
        best: Dict[str, Dict] = {}
        for row in rows:
            if row["kind"] != "set":
                continue
            current = best.get(row["exercise"])
            better = current is None or row["weight"] > current["weight"] or (
                row["weight"] == current["weight"] and row["reps"] > current["reps"]
            )
            if better:
                best[row["exercise"]] = row
        table = []
        for name in sorted(best):
            row = best[name]
            table.append({
                "exercise": name,
                "weight": _whole(row["weight"]),
                "reps": _whole(row["reps"]),
                "date": row["date"].isoformat(),
            })
        return {"id": "records", "title": "Personal records", "kind": "table", "rows": table}

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
            return None, ""
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
        if age is None:
            return None, "No protein target is set when age is missing."
        if age < PlanValidator.ADULT_AGE:
            return None, "No protein target is set under 18."
        if "weight_kg" not in user or not isinstance(targets, dict) or "protein_g" not in targets:
            return None, ""
        try:
            weight = InputValidator.parse_number(user["weight_kg"], "weight_kg")
            protein = InputValidator.parse_number(targets["protein_g"], "protein_g")
        except ValidationError as exc:
            return None, str(exc)
        per_kg = protein / weight
        if per_kg < PlanValidator.MIN_PROTEIN_G_PER_KG or per_kg > PlanValidator.MAX_PROTEIN_G_PER_KG:
            return None, "Protein target is outside 1.6 to 2.2 grams per kilogram."
        return protein, ""
