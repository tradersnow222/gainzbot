#!/usr/bin/env python3
"""
Morning check-in for sleep, soreness, energy, and stress.

The day is push, normal, or easy. The session scales from the last confirmed
load, inside the 10 percent cap, and only after 7 times 24 hours. A planned
load passed by the caller is ignored. A missed session rebuilds the rest of
the week from that confirmed load, not from the loads the caller sends in.
Nothing is applied until record_confirmation covers that proposal.
"""

from datetime import date, datetime, timezone
from typing import Dict, List, Optional
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from confirmed_change import last_confirmed_change, parse_utc, seven_days_old
from guardrails.validate import InputValidator, ValidationError
from plan_check import PlanValidator
from record_confirmation import ConfirmationRecord, ConfirmationRecorder


def _clock(value):
    """UTC clock for this check. A calendar day starts that day. It is not a history stamp."""
    parsed = parse_utc(value)
    if parsed is not None:
        return parsed
    if isinstance(value, datetime):
        return None
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, str) and len(value.strip()) == 10:
        try:
            day = date.fromisoformat(value.strip())
        except ValueError:
            return None
        return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return None


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

    def check_in(self, entry, planned_load=None, baseline_load=None, confirmed_changes=None, as_of=None) -> Dict:
        """planned_load and baseline_load are ignored. The confirmed history is the baseline."""
        del planned_load, baseline_load
        parsed = self._entry(entry)
        if not parsed["ok"]:
            return parsed
        day_name = self._day_name(parsed)
        load = self._scaled_load(day_name, confirmed_changes, _clock(as_of))
        changes = {"day": day_name}
        if load is not None:
            changes["load"] = load
        proposal = {
            "summary": f"Today is a {day_name} day.",
            "changes": changes,
            "needs_confirmation": True,
        }
        return {
            "ok": True,
            "day": day_name,
            "applied": False,
            "proposal": proposal,
            "message": f"Today is a {day_name} day. Nothing is applied until it is confirmed.",
        }

    def _scaled_load(self, day_name, confirmed_changes, as_of):
        if parse_utc(as_of) is None:
            return None
        found = last_confirmed_change(confirmed_changes, "load", as_of)
        if not found.ok or found.value is None:
            return None
        if not seven_days_old(found.at, as_of):
            return _whole(found.value)
        factor = {"push": 1.10, "normal": 1.0, "easy": 0.90}[day_name]
        cap = found.value * (1 + PlanValidator.MAX_TRAINING_LOAD_INCREASE_PERCENT / 100)
        return _whole(min(found.value * factor, cap))

    def rewrite_week(self, sessions, missed_date, confirmed_changes=None, as_of=None) -> Dict:
        rows = self._sessions(sessions)
        if isinstance(rows, dict):
            return rows
        missed = _parse_day(missed_date)
        if missed is None:
            return self._bad("The missed session needs a real date.")
        matched = [row for row in rows if row["date"] == missed]
        if len(matched) != 1:
            return self._bad("That session is not in this week.")
        clock = _clock(as_of)
        found = last_confirmed_change(confirmed_changes, "load", clock) if clock is not None else None
        if found is None or not found.ok or found.value is None:
            return self._bad("The week is built from the confirmed load.")
        base = found.value
        can_raise = seven_days_old(found.at, clock)
        room = base * (PlanValidator.MAX_TRAINING_LOAD_INCREASE_PERCENT / 100) if can_raise else 0.0
        missed_row = matched[0]
        later = [row for row in rows if row["date"] > missed]
        rooms = [room for _ in later]
        to_place = min(missed_row["load"], base)
        assigned = self._spread(to_place, rooms)
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
                    "load": _whole(base),
                    "missed": False,
                })
                continue
            index = later.index(row)
            updated.append({
                "date": row["date"].isoformat(),
                "load": _whole(base + assigned[index]),
                "missed": False,
            })
        left_out = _whole(to_place - sum(assigned))
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
        if not isinstance(confirmation, ConfirmationRecord) or not ConfirmationRecorder().covers(confirmation, proposal):
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
