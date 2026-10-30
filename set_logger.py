#!/usr/bin/env python3
"""
Log each set and suggest the next one.

A suggestion can raise the weight by at most 10 percent over the baseline.
The baseline is the last confirmed working weight, or the first set of the
latest day when nothing is confirmed yet. A jump is not applied until
record_confirmation covers that proposal.
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

    def suggest_next(self, exercise) -> Dict:
        name = self._name(exercise)
        if not name:
            return self._no("Name the exercise.")
        done = [item for item in self.sets if item["exercise"] == name]
        if not done and name not in self.working:
            return self._no("Log a set first.")
        baseline_weight, baseline_reps = self._baseline(name, done)
        cap = baseline_weight * (1 + PlanValidator.MAX_TRAINING_LOAD_INCREASE_PERCENT / 100)
        last = done[-1] if done else {"weight": baseline_weight, "reps": baseline_reps}
        if last["reps"] >= 8 and last["weight"] < cap:
            weight = min(last["weight"] * 1.10, cap)
        else:
            weight = min(last["weight"], cap)
        suggestion = {
            "exercise": name,
            "weight": _whole(weight),
            "reps": _whole(baseline_reps),
        }
        check = PlanValidator().validate_training_load_increase(baseline_weight, suggestion["weight"])
        if not check.valid:
            suggestion["weight"] = _whole(cap)
        proposal = None
        message = "Next set stays at this weight."
        if suggestion["weight"] > baseline_weight:
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

    def _baseline(self, name, done):
        if name in self.working:
            working = self.working[name]
            return working["weight"], working["reps"]
        latest = max(item["date"] for item in done)
        session = [item for item in done if item["date"] == latest]
        first = session[0]
        return first["weight"], first["reps"]

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
