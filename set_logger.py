#!/usr/bin/env python3
"""
Log each set and suggest the next one.

The baseline is the last confirmed load from the shared history reader.
Nothing moves up when that load is missing or younger than 7 times 24 hours
in UTC. A rise is at most 10 percent of that confirmed load, and apply does
nothing until record_confirmation covers that exact proposal.
"""

from datetime import date, datetime
from typing import Dict, List, Optional
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from confirmed_change import confirmed_baseline
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


class SetLogger:
    """Stores sets and keeps the next suggestion inside the load cap."""

    def __init__(self):
        self.sets: List[Dict] = []
        self.working: Dict[str, Dict] = {}

    def log_set(self, exercise, weight, reps, day) -> Dict:
        name = self._name(exercise)
        if not name:
            return self._no("Name the exercise.")
        when = _parse_day(day)
        if when is None:
            return self._no("The set needs a real date.")
        try:
            lifted = InputValidator.parse_number(weight, "weight")
            count = InputValidator.parse_number(reps, "reps")
        except ValidationError as exc:
            return self._no(str(exc))
        entry = {
            "exercise": name,
            "weight": lifted,
            "reps": count,
            "date": when,
        }
        self.sets.append(entry)
        stored = dict(entry)
        stored["date"] = when.isoformat()
        stored["weight"] = _whole(lifted)
        stored["reps"] = _whole(count)
        return {
            "ok": True,
            "stored": True,
            "applied": False,
            "message": "Set stored. The working weight is unchanged.",
            "entry": stored,
        }

    def suggest_next(self, exercise, confirmed_changes=None, as_of=None) -> Dict:
        name = self._name(exercise)
        if not name:
            return self._no("Name the exercise.")
        done = [item for item in self.sets if item["exercise"] == name]
        if not done and name not in self.working:
            return self._no("Log a set first.")
        last_weight, last_reps = self._last(name, done)
        baseline = confirmed_baseline(confirmed_changes, "load", as_of)
        if baseline is None:
            weight = last_weight
        else:
            cap = baseline * (1 + PlanValidator.MAX_TRAINING_LOAD_INCREASE_PERCENT / 100)
            if last_reps >= 8 and last_weight < cap:
                weight = min(last_weight * 1.10, cap)
            else:
                weight = min(last_weight, cap)
        suggestion = {
            "exercise": name,
            "weight": _whole(weight),
            "reps": _whole(last_reps),
        }
        proposal = None
        message = "Next set stays at this weight."
        if baseline is not None and suggestion["weight"] > baseline:
            check = PlanValidator().validate_training_load_increase(baseline, suggestion["weight"])
            if not check.valid:
                suggestion["weight"] = _whole(baseline)
            else:
                proposal = {
                    "summary": f"Next {name} set is {suggestion['weight']} for {suggestion['reps']} reps.",
                    "changes": dict(suggestion),
                    "needs_confirmation": True,
                }
                message = "The next set stays within 10 percent. Nothing is applied until it is confirmed."
        return {
            "ok": True,
            "applied": False,
            "suggestion": suggestion,
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
        changes = proposal["changes"]
        name = self._name(changes.get("exercise"))
        if not name:
            return {
                "applied": False,
                "changes": {},
                "message": "This proposal needs record_confirmation before it applies.",
            }
        try:
            weight = InputValidator.parse_number(changes.get("weight"), "weight")
            reps = InputValidator.parse_number(changes.get("reps"), "reps")
        except ValidationError:
            return {
                "applied": False,
                "changes": {},
                "message": "This proposal needs record_confirmation before it applies.",
            }
        self.working[name] = {"weight": weight, "reps": reps}
        return {
            "applied": True,
            "changes": {"exercise": name, "weight": _whole(weight), "reps": _whole(reps)},
            "message": "Confirmed. This working weight can be applied.",
        }

    def _last(self, name, done):
        if done:
            last = done[-1]
            return last["weight"], last["reps"]
        working = self.working[name]
        return working["weight"], working["reps"]

    def _name(self, exercise) -> Optional[str]:
        if not isinstance(exercise, str):
            return None
        text = " ".join(exercise.split())
        return text or None

    def _no(self, message: str) -> Dict:
        return {
            "ok": False,
            "stored": False,
            "applied": False,
            "suggestion": None,
            "proposal": None,
            "message": message,
        }
