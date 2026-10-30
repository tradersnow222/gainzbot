#!/usr/bin/env python3
"""
Morning check-in for sleep, soreness, energy, and stress.

The day is push, normal, or easy. The session scales inside the 10 percent
load cap. A missed session rewrites the rest of the week without breaking
that cap. Nothing is applied until record_confirmation covers that proposal.
"""

from datetime import date, datetime
from typing import Dict, List, Optional
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guardrails.validate import InputValidator, ValidationError
from plan_check import PlanValidator
from record_confirmation import ConfirmationRecorder


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


class MorningCheckIn:
    """Sets the day and proposes a load that stays inside the cap."""

    def check_in(self, entry, planned_load, baseline_load=None) -> Dict:
        parsed = self._entry(entry)
        if not parsed["ok"]:
            return parsed
        try:
            planned = InputValidator.parse_number(planned_load, "planned_load")
        except ValidationError as exc:
            return self._bad(str(exc))
        baseline = planned
        if baseline_load is not None:
            try:
                baseline = InputValidator.parse_number(baseline_load, "baseline_load")
            except ValidationError as exc:
                return self._bad(str(exc))
        if baseline <= 0:
            return self._bad("Training load needs a positive baseline before it can change.")

        day_name = self._day_name(parsed)
        factor = {"push": 1.10, "normal": 1.0, "easy": 0.90}[day_name]
        cap = baseline * (1 + PlanValidator.MAX_TRAINING_LOAD_INCREASE_PERCENT / 100)
        scaled = min(planned * factor, cap)
        load = _whole(scaled)
        proposal = {
            "summary": f"Today is a {day_name} day.",
            "changes": {"day": day_name, "load": load},
            "needs_confirmation": True,
        }
        return {
            "ok": True,
            "day": day_name,
            "applied": False,
            "proposal": proposal,
            "message": f"Today is a {day_name} day. Nothing is applied until it is confirmed.",
        }

    def rewrite_week(self, sessions, missed_date) -> Dict:
        rows = self._sessions(sessions)
        if isinstance(rows, dict):
            return rows
        missed = _parse_day(missed_date)
        if missed is None:
            return self._bad("The missed session needs a real date.")
        matched = [row for row in rows if row["date"] == missed]
        if len(matched) != 1:
            return self._bad("That session is not in this week.")
        missed_row = matched[0]
        later = [row for row in rows if row["date"] > missed]
        rooms = [
            row["load"] * (PlanValidator.MAX_TRAINING_LOAD_INCREASE_PERCENT / 100)
            for row in later
        ]
        assigned = self._spread(missed_row["load"], rooms)
        updated = []
        for row in rows:
            if row["date"] == missed:
                updated.append({
                    "date": row["date"].isoformat(),
                    "load": 0,
                    "missed": True,
                })
                continue
            if row["date"] < missed:
                updated.append({
                    "date": row["date"].isoformat(),
                    "load": _whole(row["load"]),
                    "missed": False,
                })
                continue
            index = later.index(row)
            updated.append({
                "date": row["date"].isoformat(),
                "load": _whole(row["load"] + assigned[index]),
                "missed": False,
            })
        left_out = _whole(missed_row["load"] - sum(assigned))
        proposal = {
            "summary": "The rest of the week is rewritten so it still holds.",
            "changes": {"sessions": updated, "left_out": left_out},
            "needs_confirmation": True,
        }
        message = "The rest of the week stays within 10 percent of each day's plan. Nothing is applied until it is confirmed."
        if left_out > 0:
            message = "Some of the missed load did not fit under the 10 percent cap. " + message
        return {
            "ok": True,
            "applied": False,
            "proposal": proposal,
            "message": message,
        }

    def apply(self, proposal, confirmation=None) -> Dict:
        if not isinstance(proposal, dict) or "changes" not in proposal:
            return {
                "applied": False,
                "changes": {},
                "message": "This proposal needs record_confirmation before it applies.",
            }
        if not ConfirmationRecorder().covers(confirmation, proposal):
            return {
                "applied": False,
                "changes": {},
                "message": "This proposal needs record_confirmation before it applies.",
            }
        return {
            "applied": True,
            "changes": proposal["changes"],
            "message": "Confirmed. This proposal can be applied.",
        }

    def _day_name(self, parsed) -> str:
        sleep = parsed["sleep"]
        soreness = parsed["soreness"]
        energy = parsed["energy"]
        stress = parsed["stress"]
        easy = sleep < 6 or soreness >= 4 or energy <= 2 or stress >= 4
        if easy:
            return "easy"
        if sleep >= 7 and soreness <= 2 and energy >= 4 and stress <= 2:
            return "push"
        return "normal"

    def _entry(self, entry) -> Dict:
        if not isinstance(entry, dict):
            return self._bad("The check-in has to include sleep, soreness, energy, and stress.")
        try:
            sleep = InputValidator.parse_number(entry["sleep"], "sleep", allow_zero=True)
            soreness = InputValidator.parse_number(entry["soreness"], "soreness")
            energy = InputValidator.parse_number(entry["energy"], "energy")
            stress = InputValidator.parse_number(entry["stress"], "stress")
        except (KeyError, ValidationError) as exc:
            if isinstance(exc, KeyError):
                return self._bad("The check-in has to include sleep, soreness, energy, and stress.")
            return self._bad(str(exc))
        if sleep > 14:
            return self._bad("Sleep hours have to be between 0 and 14.")
        for name, value in (("soreness", soreness), ("energy", energy), ("stress", stress)):
            if value < 1 or value > 5:
                return self._bad(f"{name.capitalize()} has to be from 1 to 5.")
        return {"ok": True, "sleep": sleep, "soreness": soreness, "energy": energy, "stress": stress}

    def _sessions(self, sessions):
        if not isinstance(sessions, list) or not sessions:
            return self._bad("The week needs its sessions.")
        rows = []
        seen = set()
        for item in sessions:
            if not isinstance(item, dict):
                return self._bad("Each session needs a date and a load.")
            day = _parse_day(item.get("date"))
            if day is None:
                return self._bad("Each session needs a real date.")
            if day in seen:
                return self._bad("Each session date has to be unique.")
            seen.add(day)
            try:
                load = InputValidator.parse_number(item.get("load"), "load")
            except ValidationError as exc:
                return self._bad(str(exc))
            rows.append({"date": day, "load": load})
        return rows

    def _spread(self, total: float, rooms: List[float]) -> List[float]:
        assigned = [0.0 for _ in rooms]
        left = total
        guard = 0
        while left > 1e-9 and guard < 20:
            guard += 1
            open_slots = [i for i, room in enumerate(rooms) if room - assigned[i] > 1e-9]
            if not open_slots:
                break
            share = left / len(open_slots)
            moved = 0.0
            for index in open_slots:
                space = rooms[index] - assigned[index]
                take = min(space, share)
                assigned[index] += take
                moved += take
            left -= moved
            if moved <= 1e-9:
                break
        return assigned

    def _bad(self, message: str) -> Dict:
        return {
            "ok": False,
            "day": None,
            "applied": False,
            "proposal": None,
            "message": message,
        }
