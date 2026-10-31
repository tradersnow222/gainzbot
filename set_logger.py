#!/usr/bin/env python3
"""
Log each set and suggest the next one.

Kilograms on an exercise are not the session load index. The next kilogram
comes from the last logged set for that exercise. It rises by 2.5 kg when
every set on the latest day hit the top of the rep range. Anything past
that step needs a yes. The suggestion text names the same kilogram.
apply does nothing until record_confirmation covers that exact proposal.
"""

from datetime import date, datetime, timezone
from typing import Dict, List, Optional
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from confirmed_change import last_confirmed_change
from guardrails.validate import InputValidator, ValidationError
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
    """Stores sets. The next kilogram moves by 2.5 kg, not by the load index."""

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
        # The confirmation list may include a plan row with no changes field.
        # That read is for the session load index only. It is not a kilogram.
        if confirmed_changes is not None and as_of is not None:
            last_confirmed_change(confirmed_changes, "load", as_of)
        done = [
            item for item in self.sets
            if item["exercise"].casefold() == name.casefold()
        ]
        working = self._working(name)
        if not done and working is None:
            return self._no("Log a set first.")
        last_weight, last_reps, day_sets = self._latest(done, working)
        top = self._rep_top(rep_top)
        hit_top = bool(day_sets) and top is not None and all(
            item["reps"] >= top for item in day_sets
        )
        weight = last_weight + (KG_STEP if hit_top else 0)
        needs_yes = False
        if requested_weight is not None:
            try:
                asked = InputValidator.parse_number(requested_weight, "weight")
            except ValidationError as exc:
                return self._no(str(exc))
            if asked - last_weight > KG_STEP + 1e-9:
                weight = asked
                needs_yes = True
            else:
                weight = asked
        suggestion = {
            "exercise": name,
            "weight": _whole(weight),
            "reps": _whole(last_reps),
        }
        shown = suggestion["weight"]
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

    def _latest(self, done, working):
        if done:
            latest = max(item["date"] for item in done)
            day_sets = [item for item in done if item["date"] == latest]
            last = day_sets[-1]
            return last["weight"], last["reps"], day_sets
        return working["weight"], working["reps"], []

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
