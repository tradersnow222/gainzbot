#!/usr/bin/env python3
"""
Review logged weight, intake, training load, and adherence.

Proposals stay inside the safety caps. Nothing is applied until a
record_confirmation covers that exact proposal.

A missing age blocks calorie and protein proposals. Under 18 gets no
calorie targets. A load or calorie change is proposed only from the shared
confirmed-history reader, and only when that change is at least 7 days old
in UTC. With no usable history the review does not move the load or the
calories up. A weight stall follows the goal: cut or lose lowers calories,
gain raises them, and hold or no goal changes nothing.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from confirmed_change import confirmed_baseline, confirmed_history, parse_utc
from guardrails.validate import InputValidator, ValidationError
from plan_check import PlanValidator
from record_confirmation import ConfirmationRecord, ConfirmationRecorder, hash_plan


WINDOWS = (7, 28, 90, 365)
MIN_DAYS = {7: 4, 28: 8, 90: 14, 365: 28}
NOT_ENOUGH = "not enough data yet"


def _parse_date(value) -> Optional[date]:
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


def _window_day(value) -> Optional[date]:
    """A review may end on a calendar day. That day is not a confirmed-change time."""
    if isinstance(value, datetime):
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value.strip()) == 10:
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _number(value) -> Optional[float]:
    try:
        return InputValidator.parse_number(value, "value", allow_zero=True)
    except (ValidationError, TypeError):
        return None


def _whole(value: float) -> float:
    if abs(value - round(value)) < 1e-9:
        return int(round(value))
    return round(value, 1)


class TrendReview:
    """Looks across a window and proposes safe adjustments."""

    def review(self, logs, user=None, window_days=28, as_of=None) -> Dict:
        if window_days not in WINDOWS:
            return self._empty("Use a window of 7, 28, 90, or 365 days.")
        user = user if isinstance(user, dict) else {}
        if as_of is not None:
            as_of_dt = parse_utc(as_of)
            if as_of_dt is None:
                end = _window_day(as_of)
                if end is None:
                    return self._empty("No change proposed.")
                as_of_dt = datetime(end.year, end.month, end.day, tzinfo=timezone.utc)
            else:
                end = as_of_dt.date()
        else:
            as_of_dt = None
            end = None
        rows = self._rows(logs)
        if end is None:
            dates = [row["date"] for row in rows]
            end = max(dates) if dates else None
            if end is not None:
                as_of_dt = datetime(end.year, end.month, end.day, tzinfo=timezone.utc)
        if end is None or as_of_dt is None:
            return self._empty(NOT_ENOUGH)
        start = end - timedelta(days=window_days - 1)
        window_rows = [row for row in rows if start <= row["date"] <= end]
        distinct = {row["date"] for row in window_rows}
        if len(distinct) < MIN_DAYS[window_days]:
            return self._empty(NOT_ENOUGH)

        age = self._age(user)
        sex = self._sex(user)
        weight = self._body_weight(user, window_rows)
        goal = self._goal(user)
        proposals = []
        blocked_calories = False
        # Missing age blocks calorie and protein the same way a missing sex
        # blocks a calorie target. Under 18 is handled below.
        history = confirmed_history(logs, user)
        calorie_baseline = confirmed_baseline(history, "calories", as_of_dt)
        load_baseline = confirmed_baseline(history, "load", as_of_dt)

        if age is None:
            weight_proposal = None
            protein_proposal = None
        else:
            weight_proposal = self._weight_proposal(
                window_rows, weight, sex, age, goal, calorie_baseline,
            )
            if weight_proposal == "minor":
                blocked_calories = True
            elif weight_proposal:
                proposals.append(weight_proposal)

            protein_proposal = self._protein_proposal(window_rows, weight, age)
            if protein_proposal == "minor":
                blocked_calories = True
            elif protein_proposal:
                proposals.append(protein_proposal)

        load_proposal = self._load_proposal(window_rows, end, load_baseline)
        if load_proposal:
            proposals.append(load_proposal)

        if age is not None and age < PlanValidator.ADULT_AGE:
            kept = []
            for proposal in proposals:
                changes = proposal["changes"]
                if "calories" in changes or "protein_g" in changes:
                    blocked_calories = True
                    continue
                kept.append(proposal)
            proposals = kept

        if not proposals and blocked_calories:
            return self._empty("No calorie target is set under 18. No change proposed.")
        if not proposals:
            return self._empty("No change proposed.")
        return {
            "message": "Review ready. Nothing is applied until it is confirmed.",
            "proposals": proposals,
            "applied": False,
            "enough_data": True,
            "window_days": window_days,
        }

    def review_saved(self, path, user=None, window_days=28, as_of=None) -> Dict:
        """Read the on-disk log. A bad file proposes nothing."""
        from log_store import LogStore

        store = LogStore(path)
        logs = store.as_trend()
        if store.error or logs is None:
            return self._empty("No change proposed.")
        return self.review(logs, user, window_days, as_of)

    def apply(self, proposal, confirmation=None, log_path=None, as_of=None) -> Dict:
        """Apply a proposal only when record_confirmation covers that version."""
        if not isinstance(proposal, dict) or "changes" not in proposal:
            return {
                "applied": False,
                "message": "This proposal needs record_confirmation before it applies.",
                "changes": {},
            }
        if not isinstance(confirmation, ConfirmationRecord):
            return {
                "applied": False,
                "message": "This proposal needs record_confirmation before it applies.",
                "changes": {},
            }
        if not ConfirmationRecorder().covers(confirmation, proposal):
            return {
                "applied": False,
                "message": "This proposal needs record_confirmation before it applies.",
                "changes": {},
            }
        changes = dict(proposal.get("changes") or {})
        if log_path is None:
            return {
                "applied": True,
                "message": "Confirmed. This proposal can be applied.",
                "changes": changes,
            }
        from confirmed_change import parse_utc

        when = parse_utc(as_of)
        if when is None:
            return {
                "applied": False,
                "message": "The confirmed change needs a UTC time before it is saved.",
                "changes": {},
            }
        kept = {key: changes[key] for key in ("load", "calories") if key in changes}
        if not kept:
            return {
                "applied": True,
                "message": "Confirmed. This proposal can be applied.",
                "changes": changes,
            }
        from log_store import LogStore

        row = {
            "date": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "confirmed": True,
            "changes": kept,
            "proposal": proposal,
            "record_id": confirmation.record_id,
            "plan_hash": confirmation.plan_hash,
            "quoted_words": confirmation.quoted_words,
            "speaker": confirmation.speaker,
            "timestamp": confirmation.timestamp,
            "issuer_seal": confirmation.issuer_seal,
        }
        saved = LogStore(log_path).append("confirmations", row)
        if not saved.get("ok"):
            return {
                "applied": False,
                "message": "The confirmed change was not saved.",
                "changes": {},
            }
        return {
            "applied": True,
            "message": "Confirmed. This proposal can be applied.",
            "changes": changes,
        }

    def _empty(self, message: str) -> Dict:
        return {
            "message": message,
            "proposals": [],
            "applied": False,
            "enough_data": message != NOT_ENOUGH and "window" not in message.lower(),
            "window_days": None,
        }

    def _rows(self, logs) -> List[Dict]:
        rows = []
        if isinstance(logs, list):
            for item in logs:
                row = self._row_from_mapping(item)
                if row:
                    rows.append(row)
            return rows
        if not isinstance(logs, dict):
            return rows
        buckets = {
            "weight": ("weight", "weights", "weight_log"),
            "intake": ("intake", "intakes", "nutrition"),
            "load": ("load", "loads", "training_load", "training"),
            "session": ("sessions", "adherence", "workouts"),
        }
        for kind, keys in buckets.items():
            for key in keys:
                values = logs.get(key)
                if not isinstance(values, list):
                    continue
                for item in values:
                    row = self._row_from_mapping(item, kind)
                    if row:
                        rows.append(row)
        return rows

    def _row_from_mapping(self, item, kind=None) -> Optional[Dict]:
        if not isinstance(item, dict):
            return None
        day = _parse_date(item.get("date") or item.get("day"))
        if day is None:
            return None
        row = {"date": day}
        weight = item.get("kg", item.get("weight_kg", item.get("weight")))
        calories = item.get("calories", item.get("kcal"))
        protein = item.get("protein_g", item.get("protein"))
        load = item.get("load", item.get("training_load"))
        if weight is not None and kind in (None, "weight"):
            parsed = _number(weight)
            if parsed is not None:
                row["weight"] = parsed
        if calories is not None and kind in (None, "intake"):
            parsed = _number(calories)
            if parsed is not None:
                row["calories"] = parsed
        if protein is not None and kind in (None, "intake"):
            parsed = _number(protein)
            if parsed is not None:
                row["protein"] = parsed
        if load is not None and kind in (None, "load"):
            parsed = _number(load)
            if parsed is not None:
                row["load"] = parsed
        if kind in (None, "session") and (
            "completed" in item or "missed" in item or "planned" in item
        ):
            planned = item.get("planned", True)
            if planned in (False, "no", "false", 0):
                row["planned"] = False
            else:
                row["planned"] = True
            if "missed" in item and item.get("missed") in (True, "yes", "true", 1):
                row["completed"] = False
            else:
                row["completed"] = item.get("completed") in (True, "yes", "true", 1)
        if len(row) == 1:
            return None
        return row

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

    def _body_weight(self, user, rows) -> Optional[float]:
        if "weight_kg" in user:
            parsed = _number(user["weight_kg"])
            if parsed:
                return parsed
        weights = [row["weight"] for row in rows if "weight" in row]
        return weights[-1] if weights else None

    def _series(self, rows, key) -> List[Dict]:
        return sorted(
            (row for row in rows if key in row),
            key=lambda row: row["date"],
        )

    def _proposal(self, summary: str, changes: Dict) -> Dict:
        return {
            "summary": summary,
            "changes": changes,
            "needs_confirmation": True,
        }

    def _floor(self, sex: Optional[str]) -> Optional[int]:
        if sex == "M":
            return PlanValidator.CALORIE_FLOOR_MEN
        if sex == "F":
            return PlanValidator.CALORIE_FLOOR_WOMEN
        return None

    def _goal(self, user) -> Optional[str]:
        raw = user.get("goal")
        if not isinstance(raw, str):
            return None
        text = raw.strip().lower()
        if text in {"cut", "lose"}:
            return "cut"
        if text in {"gain", "hold"}:
            return text
        return None

    def _weight_proposal(self, rows, weight, sex, age, goal, calorie_baseline):
        points = self._series(rows, "weight")
        if len(points) < 2 or not weight:
            return None
        start = points[0]
        end = points[-1]
        span_days = max((end["date"] - start["date"]).days, 1)
        weeks = span_days / 7
        delta = end["weight"] - start["weight"]
        per_week = delta / weeks
        limit = weight * (PlanValidator.MAX_WEIGHT_LOSS_PERCENT / 100)
        floor = self._floor(sex)
        if age is not None and age < PlanValidator.ADULT_AGE:
            if abs(per_week) > limit or (span_days >= 14 and abs(delta) < 0.2):
                return "minor"
            return None
        if floor is None or calorie_baseline is None:
            return None
        current = calorie_baseline

        if per_week < -limit:
            return self._calorie_step(
                current, floor, 200, up=True,
                summary="Weight is coming off faster than 1 percent a week. Raise calories.",
            )
        if per_week > limit:
            return self._calorie_step(
                current, floor, 200, up=False,
                summary="Weight is climbing faster than 1 percent a week. Lower calories.",
            )
        if span_days >= 14 and abs(delta) < 0.2:
            if goal == "cut":
                return self._calorie_step(
                    current, floor, 150, up=False,
                    summary="Weight has stalled. Lower calories a little.",
                )
            if goal == "gain":
                return self._calorie_step(
                    current, floor, 150, up=True,
                    summary="Weight has stalled. Raise calories a little.",
                )
            return None
        return None

    def _calorie_step(self, current, floor, step, up, summary):
        cap = PlanValidator.MAX_CALORIE_CHANGE_PER_WEEK
        step = min(step, cap)
        if up:
            target = current + step
        else:
            target = max(floor, current - step)
            if target >= current:
                return None
        if abs(target - current) > cap:
            return None
        if target < floor and current >= floor:
            return None
        if target < floor:
            target = min(floor, current + cap) if up else floor
            if abs(target - current) > cap or target < floor:
                return None
        return self._proposal(summary, {"calories": _whole(target)})

    def _protein_proposal(self, rows, weight, age):
        if age is None or age < PlanValidator.ADULT_AGE:
            return None
        points = self._series(rows, "protein")
        if len(points) < 2 or not weight:
            return None
        average = sum(row["protein"] for row in points) / len(points)
        per_kg = average / weight
        if per_kg < PlanValidator.MIN_PROTEIN_G_PER_KG:
            target = PlanValidator.MIN_PROTEIN_G_PER_KG * weight
            summary = "Protein is under 1.6 grams per kilogram. Bring it up to that floor."
        elif per_kg > PlanValidator.MAX_PROTEIN_G_PER_KG:
            target = PlanValidator.MAX_PROTEIN_G_PER_KG * weight
            summary = "Protein is over 2.2 grams per kilogram. Bring it down into range."
        else:
            return None
        return self._proposal(summary, {"protein_g": _whole(target)})

    def _load_proposal(self, rows, end, load_baseline):
        if load_baseline is None:
            return None
        loads = self._series(rows, "load")
        sessions = [row for row in rows if "completed" in row and row.get("planned", True)]
        planned = len(sessions)
        completed = sum(1 for row in sessions if row["completed"])
        missed = planned >= 4 and (completed / planned) < 0.75
        current = load_baseline
        days_since_drop = None
        if len(loads) >= 2:
            reference = loads[0]["date"]
            for previous, nxt in zip(loads, loads[1:]):
                if previous["load"] > 0 and nxt["load"] <= previous["load"] * 0.90:
                    reference = nxt["date"]
            days_since_drop = (end - reference).days
        deload_due = days_since_drop is not None and days_since_drop >= 28 and current
        proposal = None
        if deload_due:
            target = _whole(current * 0.90)
            proposal = self._proposal(
                "It has been at least 4 weeks without a lighter week. Drop the load by about 10 percent for a deload.",
                {"load": target},
            )
        elif missed and current is not None:
            proposal = self._proposal(
                "Sessions were missed. Keep the load where it is.",
                {"load": _whole(current)},
            )
        elif (
            current
            and planned >= 4
            and completed / planned >= 0.9
            and days_since_drop is not None
            and days_since_drop < 28
        ):
            target = _whole(current * (1 + PlanValidator.MAX_TRAINING_LOAD_INCREASE_PERCENT / 100))
            proposal = self._proposal(
                "Sessions are on track. The load can rise by about 10 percent.",
                {"load": target},
            )
        return proposal
