#!/usr/bin/env python3
"""
Log each set and suggest the next one.

The next kilogram steps by 2.5 kg from the weight the latest day started
with, and only when every set that day hit the top of the rep range. That
is one step per exercise per day. A heavier set logged later the same day
does not earn another step. The result stays within 10 percent of a confirmed
or prior-week kilogram over any 7 days. With nothing confirmed, the load
does not move up. A jump past 2.5 kg needs a yes and is capped at that same
10 percent. The suggestion text names the kilogram. The session load index
is not copied onto the bar. apply does nothing until record_confirmation
covers that exact proposal.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from confirmed_change import last_confirmed_change
from guardrails.validate import InputValidator, ValidationError
from plan_check import PlanValidator
from record_confirmation import ConfirmationRecord, ConfirmationRecorder


KG_STEP = 2.5


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
    """Stores sets. The next kilogram steps by 2.5 kg inside the 10 percent cap."""

    def __init__(self):
        self.sets: List[Dict] = []
        self.working: Dict[str, Dict] = {}

    def log_set(self, exercise, weight, reps, day, log_path=None) -> Dict:
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
        if log_path is not None:
            from log_store import LogStore

            saved = LogStore(log_path).append("sets", stored)
            if not saved["ok"]:
                self.sets.pop()
                return self._no(saved["message"])
        return {
            "ok": True,
            "stored": True,
            "applied": False,
            "message": "Set stored. The working weight is unchanged.",
            "entry": stored,
        }

    def suggest_next(
        self,
        exercise,
        confirmed_changes=None,
        as_of=None,
        log_path=None,
        rep_top=None,
        requested_weight=None,
    ) -> Dict:
        name = self._name(exercise)
        if not name:
            return self._no("Name the exercise.")
        loaded = self._load_saved(log_path)
        if loaded is not None:
            return loaded
        if requested_weight is not None:
            try:
                asked = InputValidator.parse_number(requested_weight, "weight")
            except ValidationError as exc:
                return self._no(str(exc))
        else:
            asked = None
        # A plan confirmation has no changes field. Skip that row. The load
        # value is the session index, not the kilogram on this exercise.
        found = last_confirmed_change(confirmed_changes, "load", as_of)
        done = [
            item for item in self.sets
            if item["exercise"].casefold() == name.casefold()
        ]
        working = self._working(name)
        if not done and working is None:
            return self._no("Log a set first.")
        confirmed = bool(found.ok and found.value is not None)
        ref = self._ref_day(done, as_of)
        prior = self._prior_week_weight(done, ref)
        if not confirmed and prior is None and working is None:
            return {
                "ok": True,
                "applied": False,
                "suggestion": None,
                "proposal": None,
                "message": "No confirmed load can be read. What load is confirmed?",
            }
        baseline = prior if prior is not None else self._opening_weight(done, working)
        top = self._rep_top(rep_top)
        weight, last_reps, last_weight = self._one_step(done, working, top, baseline)
        if not confirmed and working is None:
            if prior is not None and weight > prior:
                weight = prior
            asked = None
        step = self._within_cap(baseline, weight)
        needs_yes = False
        weight = step
        if asked is not None:
            capped = self._within_cap(baseline, asked)
            weight = capped
            if capped > step + 1e-9:
                needs_yes = True
        shown = self._shown(baseline, weight)
        if shown <= _whole(step) + 1e-9:
            needs_yes = False
        suggestion = {
            "exercise": name,
            "weight": shown,
            "reps": _whole(last_reps),
        }
        proposal = None
        if needs_yes:
            proposal = {
                "summary": f"Next {name} set is {shown} kg.",
                "changes": dict(suggestion),
                "needs_confirmation": True,
            }
            message = f"Next set is {shown} kg. Yes to go past the 2.5 kg step."
        elif shown != _whole(last_weight):
            message = f"Next set is {shown} kg."
        else:
            message = f"Next set stays at {shown} kg."
        return {
            "ok": True,
            "applied": False,
            "suggestion": suggestion,
            "proposal": proposal,
            "message": message,
        }

    def apply(self, proposal, confirmation=None, log_path=None) -> Dict:
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
        if log_path is not None:
            from log_store import LogStore

            saved = LogStore(log_path).append("confirmations", {
                "record_id": confirmation.record_id,
                "plan_hash": confirmation.plan_hash,
                "quoted_words": confirmation.quoted_words,
                "speaker": confirmation.speaker,
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "confirmed": True,
                "kind": "set",
            })
            if not saved.get("ok"):
                return {
                    "applied": False,
                    "changes": {},
                    "message": "The confirmed set was not saved.",
                }
        self.working[name] = {"weight": weight, "reps": reps}
        return {
            "applied": True,
            "changes": {"exercise": name, "weight": _whole(weight), "reps": _whole(reps)},
            "message": "Confirmed. This working weight can be applied.",
        }

    def _load_saved(self, log_path):
        """Fill an empty logger from the saved log. Memory already wins."""
        if log_path is None or self.sets:
            return None
        from log_store import LogStore

        store = LogStore(log_path)
        if store.error:
            return self._no(store.error)
        for row in store.data["sets"]:
            entry = self._saved_set(row)
            if entry is not None:
                self.sets.append(entry)
        return None

    def _saved_set(self, row):
        if not isinstance(row, dict):
            return None
        name = self._name(row.get("exercise"))
        when = _parse_day(row.get("date"))
        if not name or when is None:
            return None
        try:
            lifted = InputValidator.parse_number(row.get("weight"), "weight")
            count = InputValidator.parse_number(row.get("reps"), "reps")
        except ValidationError:
            return None
        return {"exercise": name, "weight": lifted, "reps": count, "date": when}

    def _working(self, name):
        for key, value in self.working.items():
            if key.casefold() == name.casefold():
                return value
        return None

    def _ref_day(self, done, as_of):
        ref = max((item["date"] for item in done), default=None)
        clock = _parse_day(as_of)
        if clock is not None and (ref is None or clock > ref):
            return clock
        return ref

    def _prior_week_weight(self, done, ref):
        """Latest kilogram logged at least 7 days before the reference day."""
        if ref is None:
            return None
        cutoff = ref - timedelta(days=7)
        old = [item for item in done if item["date"] <= cutoff]
        if not old:
            return None
        latest = max(item["date"] for item in old)
        return [item for item in old if item["date"] == latest][-1]["weight"]

    def _opening_weight(self, done, working):
        if not done:
            return working["weight"] if working else None
        earliest = min(item["date"] for item in done)
        return [item for item in done if item["date"] == earliest][0]["weight"]

    def _one_step(self, done, working, top, baseline):
        """One 2.5 kg step from the weight the latest day started with.

        That opening weight is the previous day's kilogram. Later sets on
        the same day do not raise it again.
        """
        if not done:
            return working["weight"], working["reps"], working["weight"]
        latest = max(item["date"] for item in done)
        day_sets = [item for item in done if item["date"] == latest]
        first = day_sets[0]["weight"]
        last = day_sets[-1]
        cap = None
        if baseline is not None and baseline > 0:
            cap = baseline * (1 + PlanValidator.MAX_TRAINING_LOAD_INCREASE_PERCENT / 100)
        if cap is not None and first > cap + 1e-9:
            return baseline, last["reps"], last["weight"]
        hit = top is not None and all(item["reps"] >= top for item in day_sets)
        if hit:
            weight = first + KG_STEP
        elif last["weight"] < first:
            weight = last["weight"]
        else:
            weight = first
        return weight, last["reps"], last["weight"]

    def _within_cap(self, baseline, weight):
        if baseline is None or baseline <= 0 or weight <= baseline + 1e-9:
            return weight
        cap = baseline * (1 + PlanValidator.MAX_TRAINING_LOAD_INCREASE_PERCENT / 100)
        if weight > cap:
            weight = cap
        if PlanValidator().validate_training_load_increase(baseline, weight).valid:
            return weight
        snapped = math.floor(cap * 10 + 1e-9) / 10
        if snapped > baseline and PlanValidator().validate_training_load_increase(baseline, snapped).valid:
            return snapped
        return baseline

    def _shown(self, baseline, weight):
        shown = _whole(weight)
        if baseline is None or shown <= baseline:
            return shown
        if PlanValidator().validate_training_load_increase(baseline, shown).valid:
            return shown
        floored = math.floor(weight * 10 + 1e-9) / 10
        if floored > baseline and PlanValidator().validate_training_load_increase(baseline, floored).valid:
            return _whole(floored)
        return _whole(baseline)

    def _rep_top(self, rep_top):
        """The top of a rep range. '6-10' is 10. Missing means no kilogram step."""
        if rep_top is None or isinstance(rep_top, bool):
            return None
        if isinstance(rep_top, str):
            chunk = rep_top.strip().split("-")[-1].strip()
            try:
                value = float(chunk)
            except ValueError:
                return None
            return value if value > 0 else None
        try:
            value = InputValidator.parse_number(rep_top, "reps")
        except ValidationError:
            return None
        return value

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
