#!/usr/bin/env python3
"""Tests for trend_review.py."""

from datetime import date, datetime, timedelta, timezone

import pytest

from confirmed_change import parse_utc
from plan_check import PlanValidator
from record_confirmation import ConfirmationRecorder
from red_flag_check import RedFlagChecker, is_passing_check_in
from trend_review import NOT_ENOUGH, TrendReview, hash_plan


def passing_check_in():
    checker = RedFlagChecker()
    answers = {aliases[0]: "no" for _flag, aliases in checker.CHECKLIST_GROUPS}
    result = checker.scan_check_in({
        "symptom_checklist": answers,
        "notes": "Easy lift, slept fine.",
    })
    assert is_passing_check_in(result)
    return result


def recorded(proposal, reply="yes", speaker="user"):
    return ConfirmationRecorder().record(proposal, reply, speaker, passing_check_in())


def days(start, count):
    origin = date.fromisoformat(start)
    return [origin + timedelta(days=offset) for offset in range(count)]


def confirmation(proposal, reply="yes", speaker="user", confirmed=True):
    return {
        "confirmed": confirmed,
        "plan_hash": hash_plan(proposal),
        "quoted_words": reply,
        "speaker": speaker,
    }


def prior(kind, value, as_of, days_ago=7, confirmed=True, change_key=None):
    day = date.fromisoformat(str(as_of)[:10]) - timedelta(days=days_ago)
    return [{
        "date": day.isoformat() + "T00:00:00Z",
        "confirmed": confirmed,
        "changes": {(change_key or kind): value},
    }]


class TestWindowsAndData:
    def test_bad_window_changes_nothing(self):
        result = TrendReview().review([], user={"sex": "M", "age": 30}, window_days=10)
        assert result["proposals"] == []
        assert result["applied"] is False
        assert "7" in result["message"] and "365" in result["message"]

    def test_empty_log_says_not_enough_data(self):
        result = TrendReview().review({}, {"sex": "F", "age": 30, "weight_kg": 60}, 28)
        assert result["message"] == NOT_ENOUGH
        assert result["proposals"] == []
        assert result["applied"] is False

    def test_sparse_log_says_not_enough_data(self):
        result = TrendReview().review(
            {"weights": [
                {"date": "2026-10-01", "kg": 80},
                {"date": "2026-10-02", "kg": 80},
            ]},
            {"sex": "M", "age": 30, "weight_kg": 80},
            28,
            "2026-10-28",
        )
        assert result["message"] == NOT_ENOUGH
        assert result["proposals"] == []

    @pytest.mark.parametrize("window", [7, 28, 90, 365])
    def test_each_window_is_accepted(self, window):
        result = TrendReview().review({}, window_days=window)
        assert result["applied"] is False
        assert result["message"] == NOT_ENOUGH


class TestSafetyCaps:
    def _adult(self):
        return {"sex": "M", "age": 34, "weight_kg": 80}

    def test_losing_too_fast_raises_calories_by_at_most_200(self):
        dates = days("2026-10-22", 7)
        weights = []
        intake = []
        for index, day in enumerate(dates):
            weights.append({"date": day.isoformat(), "kg": 80 - (index * 0.25)})
            intake.append({"date": day.isoformat(), "calories": 2200, "protein_g": 144})
        result = TrendReview().review(
            {
                "weights": weights,
                "intake": intake,
                "confirmed_changes": prior("calories", 2200, dates[-1].isoformat()),
            },
            self._adult(),
            7,
            dates[-1].isoformat(),
        )
        calorie_changes = [
            item["changes"]["calories"]
            for item in result["proposals"]
            if "calories" in item["changes"]
        ]
        assert calorie_changes
        assert calorie_changes[0] >= PlanValidator.CALORIE_FLOOR_MEN
        assert calorie_changes[0] - 2200 <= PlanValidator.MAX_CALORIE_CHANGE_PER_WEEK
        assert calorie_changes[0] > 2200
        assert result["applied"] is False

    def test_stall_lowers_calories_without_passing_the_floor(self):
        dates = days("2026-10-01", 28)
        weights = [{"date": dates[0].isoformat(), "kg": 80}, {"date": dates[-1].isoformat(), "kg": 80.1}]
        intake = [
            {"date": day.isoformat(), "calories": 1600, "protein_g": 144}
            for day in dates
        ]
        user = self._adult()
        user["goal"] = "cut"
        result = TrendReview().review(
            {
                "weights": weights,
                "intake": intake,
                "confirmed_changes": prior("calories", 1600, dates[-1].isoformat()),
            },
            user,
            28,
            dates[-1].isoformat(),
        )
        calories = next(
            item["changes"]["calories"]
            for item in result["proposals"]
            if "calories" in item["changes"]
        )
        assert PlanValidator.CALORIE_FLOOR_MEN <= calories < 1600
        assert 1600 - calories <= 200

    def test_woman_stall_does_not_go_under_1200(self):
        dates = days("2026-10-01", 28)
        weights = [{"date": dates[0].isoformat(), "kg": 60}, {"date": dates[-1].isoformat(), "kg": 60}]
        intake = [{"date": day.isoformat(), "calories": 1250, "protein_g": 110} for day in dates]
        result = TrendReview().review(
            {
                "weights": weights,
                "intake": intake,
                "confirmed_changes": prior("calories", 1250, dates[-1].isoformat()),
            },
            {"sex": "F", "age": 40, "weight_kg": 60, "goal": "cut"},
            28,
            dates[-1].isoformat(),
        )
        calories = [
            item["changes"]["calories"]
            for item in result["proposals"]
            if "calories" in item["changes"]
        ]
        assert calories
        assert calories[0] >= PlanValidator.CALORIE_FLOOR_WOMEN
        assert 1250 - calories[0] <= 200

    def test_low_protein_is_brought_up_into_range(self):
        dates = days("2026-10-22", 7)
        intake = [
            {"date": day.isoformat(), "calories": 2200, "protein_g": 80}
            for day in dates
        ]
        weights = [
            {"date": dates[0].isoformat(), "kg": 80},
            {"date": dates[-1].isoformat(), "kg": 79.6},
        ]
        result = TrendReview().review(
            {"weights": weights, "intake": intake},
            self._adult(),
            7,
            dates[-1].isoformat(),
        )
        protein = next(
            item["changes"]["protein_g"]
            for item in result["proposals"]
            if "protein_g" in item["changes"]
        )
        assert protein == 128

    def test_high_protein_is_brought_down(self):
        dates = days("2026-10-22", 7)
        intake = [
            {"date": day.isoformat(), "calories": 2500, "protein_g": 220}
            for day in dates
        ]
        weights = [
            {"date": dates[0].isoformat(), "kg": 80},
            {"date": dates[-1].isoformat(), "kg": 80.1},
        ]
        result = TrendReview().review(
            {"intake": intake, "weights": weights},
            self._adult(),
            7,
            dates[-1].isoformat(),
        )
        protein = next(
            item["changes"]["protein_g"]
            for item in result["proposals"]
            if "protein_g" in item["changes"]
        )
        assert protein == 176

    def test_missed_sessions_do_not_raise_the_load(self):
        dates = days("2026-10-01", 8)
        sessions = []
        loads = []
        for index, day in enumerate(dates):
            sessions.append({
                "date": day.isoformat(),
                "planned": True,
                "completed": index < 2,
            })
            loads.append({"date": day.isoformat(), "load": 100})
        result = TrendReview().review(
            {
                "sessions": sessions,
                "loads": loads,
                "confirmed_changes": prior("load", 100, dates[-1].isoformat()),
            },
            self._adult(),
            28,
            dates[-1].isoformat(),
        )
        load_changes = [
            item for item in result["proposals"] if "load" in item["changes"]
        ]
        assert load_changes
        assert load_changes[0]["changes"]["load"] <= 100
        assert "missed" in load_changes[0]["summary"].lower()

    def test_steady_sessions_rise_by_at_most_10_percent(self):
        dates = days("2026-10-22", 7)
        sessions = [{"date": day.isoformat(), "planned": True, "completed": True} for day in dates]
        loads = [{"date": day.isoformat(), "load": 100} for day in dates]
        result = TrendReview().review(
            {
                "sessions": sessions,
                "loads": loads,
                "confirmed_changes": prior("load", 100, dates[-1].isoformat()),
            },
            self._adult(),
            7,
            dates[-1].isoformat(),
        )
        load = next(item["changes"]["load"] for item in result["proposals"] if "load" in item["changes"])
        assert load <= 110
        assert load > 100

    def test_long_stretch_without_a_lighter_week_proposes_a_deload(self):
        start = date(2026, 8, 1)
        loads = []
        sessions = []
        for offset in range(50):
            day = (start + timedelta(days=offset)).isoformat()
            sessions.append({"date": day, "planned": True, "completed": True})
            if offset % 7 == 0:
                loads.append({"date": day, "load": 100})
        as_of = (start + timedelta(days=49)).isoformat()
        result = TrendReview().review(
            {
                "loads": loads,
                "sessions": sessions,
                "confirmed_changes": prior("load", 100, as_of),
            },
            self._adult(),
            90,
            as_of,
        )
        load = next(item["changes"]["load"] for item in result["proposals"] if "load" in item["changes"])
        assert load == 90
        assert "deload" in next(
            item["summary"] for item in result["proposals"] if "load" in item["changes"]
        ).lower()

    def test_under_18_gets_no_calorie_target(self):
        dates = days("2026-10-01", 28)
        weights = [{"date": dates[0].isoformat(), "kg": 55}, {"date": dates[-1].isoformat(), "kg": 55}]
        intake = [{"date": day.isoformat(), "calories": 2200, "protein_g": 70} for day in dates]
        result = TrendReview().review(
            {"weights": weights, "intake": intake},
            {"sex": "M", "age": 16, "weight_kg": 55},
            28,
            dates[-1].isoformat(),
        )
        assert result["proposals"] == []
        blob = result["message"].lower()
        assert "18" in blob
        assert "calorie" in blob

    def test_year_window_still_caps_the_calorie_step(self):
        start = date(2025, 10, 30)
        weights = []
        intake = []
        for week in range(40):
            day = start + timedelta(days=week * 7)
            weights.append({"date": day.isoformat(), "kg": 90 - week * 1.2})
            intake.append({"date": day.isoformat(), "calories": 2400, "protein_g": 160})
        result = TrendReview().review(
            {
                "weights": weights,
                "intake": intake,
                "confirmed_changes": prior("calories", 2400, weights[-1]["date"]),
            },
            {"sex": "M", "age": 40, "weight_kg": 90},
            365,
            weights[-1]["date"],
        )
        calories = [
            item["changes"]["calories"]
            for item in result["proposals"]
            if "calories" in item["changes"]
        ]
        assert calories
        assert calories[0] - 2400 <= 200
        assert calories[0] >= 1500

    def test_missing_age_blocks_calorie_and_protein(self):
        dates = days("2026-10-22", 7)
        weights = []
        intake = []
        for index, day in enumerate(dates):
            weights.append({"date": day.isoformat(), "kg": 80 - (index * 0.25)})
            intake.append({"date": day.isoformat(), "calories": 2200, "protein_g": 80})
        result = TrendReview().review(
            {"weights": weights, "intake": intake},
            {"sex": "M", "weight_kg": 80},
            7,
            dates[-1].isoformat(),
        )
        changes = [item["changes"] for item in result["proposals"]]
        assert all("calories" not in item and "protein_g" not in item for item in changes)
        assert "18" not in result["message"]

    def test_missing_age_still_allows_a_load_change(self):
        dates = days("2026-10-22", 7)
        sessions = [{"date": day.isoformat(), "planned": True, "completed": True} for day in dates]
        loads = [{"date": day.isoformat(), "load": 100} for day in dates]
        result = TrendReview().review(
            {
                "sessions": sessions,
                "loads": loads,
                "confirmed_changes": prior("load", 100, dates[-1].isoformat()),
            },
            {"sex": "M", "weight_kg": 80},
            7,
            dates[-1].isoformat(),
        )
        load = next(item["changes"]["load"] for item in result["proposals"] if "load" in item["changes"])
        assert load == 110
        assert all("calories" not in item["changes"] and "protein_g" not in item["changes"] for item in result["proposals"])

    def _steady_load(self, start, count, load):
        dates = days(start, count)
        return dates, {
            "sessions": [{"date": day.isoformat(), "planned": True, "completed": True} for day in dates],
            "loads": [{"date": day.isoformat(), "load": load} for day in dates],
        }

    def test_reviews_a_day_apart_do_not_stack_load(self):
        review = TrendReview()
        dates, logs = self._steady_load("2026-10-16", 7, 100)
        logs["confirmed_changes"] = prior("load", 100, dates[-1].isoformat())
        user = self._adult()
        first = review.review(logs, user, 7, dates[-1].isoformat())
        assert next(item["changes"]["load"] for item in first["proposals"] if "load" in item["changes"]) == 110

        next_day = dates[-1] + timedelta(days=1)
        dates2, logs2 = self._steady_load((next_day - timedelta(days=6)).isoformat(), 7, 110)
        logs2["confirmed_changes"] = [{
            "date": dates[-1].isoformat() + "T00:00:00Z",
            "changes": {"load": 110},
            "confirmed": True,
        }]
        second = review.review(logs2, user, 7, next_day.isoformat())
        proposed = [item["changes"].get("load") for item in second["proposals"]]
        assert 121 not in proposed
        assert all(load is None or load <= 110 for load in proposed)

    def test_load_change_is_allowed_when_the_last_one_is_7_days_old(self):
        day = date(2026, 10, 29)
        dates, logs = self._steady_load((day - timedelta(days=6)).isoformat(), 7, 110)
        logs["confirmed_changes"] = [{
            "date": (day - timedelta(days=7)).isoformat() + "T00:00:00Z",
            "changes": {"load": 110},
            "confirmed": True,
        }]
        result = TrendReview().review(logs, self._adult(), 7, day.isoformat())
        load = next(item["changes"]["load"] for item in result["proposals"] if "load" in item["changes"])
        assert load == 121

    def test_reviews_a_day_apart_do_not_stack_calories(self):
        review = TrendReview()
        user = self._adult()
        first_dates = days("2026-10-16", 7)
        weights = []
        intake = []
        for index, day in enumerate(first_dates):
            weights.append({"date": day.isoformat(), "kg": 80 - (index * 0.25)})
            intake.append({"date": day.isoformat(), "calories": 2200, "protein_g": 144})
        first = review.review(
            {
                "weights": weights,
                "intake": intake,
                "confirmed_changes": prior("calories", 2200, first_dates[-1].isoformat()),
            },
            user,
            7,
            first_dates[-1].isoformat(),
        )
        calories = next(item["changes"]["calories"] for item in first["proposals"] if "calories" in item["changes"])
        assert calories == 2400

        next_day = first_dates[-1] + timedelta(days=1)
        second_dates = days((next_day - timedelta(days=6)).isoformat(), 7)
        weights = []
        intake = []
        for index, day in enumerate(second_dates):
            weights.append({"date": day.isoformat(), "kg": 78.5 - (index * 0.25)})
            intake.append({"date": day.isoformat(), "calories": 2400, "protein_g": 144})
        second = review.review(
            {
                "weights": weights,
                "intake": intake,
                "confirmed_changes": [{
                    "date": first_dates[-1].isoformat() + "T00:00:00Z",
                    "changes": {"calories": 2400},
                    "confirmed": True,
                }],
            },
            user,
            7,
            next_day.isoformat(),
        )
        proposed = [item["changes"].get("calories") for item in second["proposals"]]
        assert 2600 not in proposed
        assert all(value is None for value in proposed)

    def test_calorie_change_is_allowed_when_the_last_one_is_7_days_old(self):
        end = date(2026, 10, 29)
        dates = days((end - timedelta(days=6)).isoformat(), 7)
        weights = []
        intake = []
        for index, day in enumerate(dates):
            weights.append({"date": day.isoformat(), "kg": 78 - (index * 0.25)})
            intake.append({"date": day.isoformat(), "calories": 2400, "protein_g": 144})
        result = TrendReview().review(
            {
                "weights": weights,
                "intake": intake,
                "confirmed_changes": [{
                    "date": (end - timedelta(days=7)).isoformat() + "T00:00:00Z",
                    "changes": {"calories": 2400},
                    "confirmed": True,
                }],
            },
            self._adult(),
            7,
            end.isoformat(),
        )
        calories = next(item["changes"]["calories"] for item in result["proposals"] if "calories" in item["changes"])
        assert calories == 2600
        assert calories - 2400 <= PlanValidator.MAX_CALORIE_CHANGE_PER_WEEK

    def _stall(self, goal):
        dates = days("2026-10-01", 28)
        weights = [{"date": dates[0].isoformat(), "kg": 80}, {"date": dates[-1].isoformat(), "kg": 80}]
        intake = [{"date": day.isoformat(), "calories": 2200, "protein_g": 144} for day in dates]
        user = self._adult()
        if goal is not None:
            user["goal"] = goal
        result = TrendReview().review(
            {
                "weights": weights,
                "intake": intake,
                "confirmed_changes": prior("calories", 2200, dates[-1].isoformat()),
            },
            user,
            28,
            dates[-1].isoformat(),
        )
        return [
            item for item in result["proposals"] if "calories" in item["changes"]
        ]

    def test_stall_on_a_cut_lowers_calories(self):
        proposals = self._stall("cut")
        assert proposals
        assert proposals[0]["changes"]["calories"] < 2200
        assert "lower" in proposals[0]["summary"].lower()

    def test_stall_on_a_gain_raises_calories(self):
        proposals = self._stall("gain")
        assert proposals
        calories = proposals[0]["changes"]["calories"]
        assert 2200 < calories <= 2200 + PlanValidator.MAX_CALORIE_CHANGE_PER_WEEK
        assert "raise" in proposals[0]["summary"].lower()

    def test_stall_on_hold_proposes_nothing(self):
        assert self._stall("hold") == []

    def test_stall_with_no_goal_proposes_nothing(self):
        assert self._stall(None) == []

    def test_stall_on_lose_lowers_calories(self):
        proposals = self._stall("lose")
        assert proposals
        assert proposals[0]["changes"]["calories"] < 2200
        assert "lower" in proposals[0]["summary"].lower()

    def _ready_load(self, as_of="2026-10-28"):
        dates = days("2026-10-22", 7)
        return {
            "sessions": [
                {"date": day.isoformat(), "planned": True, "completed": True}
                for day in dates
            ],
            "loads": [{"date": day.isoformat(), "load": 100} for day in dates],
        }, as_of

    def test_no_history_proposes_no_load_or_calorie_change(self):
        logs, as_of = self._ready_load()
        logs["weights"] = [
            {"date": "2026-10-22", "kg": 80},
            {"date": "2026-10-28", "kg": 80},
        ]
        logs["intake"] = [
            {"date": day, "calories": 2200, "protein_g": 144}
            for day in ("2026-10-22", "2026-10-28")
        ]
        user = self._adult()
        user["goal"] = "cut"
        user["planned_load"] = 100
        user["baseline_load"] = 100
        result = TrendReview().review(logs, user, 7, as_of)
        assert all("load" not in item["changes"] and "calories" not in item["changes"] for item in result["proposals"])

    @pytest.mark.parametrize("stamp", ["10/20/2026", "yesterday", None])
    def test_unreadable_confirmed_date_proposes_no_change(self, stamp):
        logs, as_of = self._ready_load()
        entry = {"confirmed": True, "changes": {"load": 100}}
        if stamp is not None:
            entry["date"] = stamp
        logs["confirmed_changes"] = [entry]
        result = TrendReview().review(logs, self._adult(), 7, as_of)
        assert all("load" not in item["changes"] for item in result["proposals"])

    def test_wrong_key_proposes_no_change(self):
        logs, as_of = self._ready_load()
        logs["confirmed_changes"] = prior("load", 100, as_of, change_key="training_load")
        result = TrendReview().review(logs, self._adult(), 7, as_of)
        assert all("load" not in item["changes"] for item in result["proposals"])

    def test_non_list_history_proposes_no_change(self):
        logs, as_of = self._ready_load()
        logs["confirmed_changes"] = {"date": "2026-10-21T00:00:00Z", "confirmed": True, "changes": {"load": 100}}
        result = TrendReview().review(logs, self._adult(), 7, as_of)
        assert all("load" not in item["changes"] for item in result["proposals"])

    def test_caller_baseline_is_ignored(self):
        logs, as_of = self._ready_load()
        for row in logs["loads"]:
            row["load"] = 40
        logs["confirmed_changes"] = prior("load", 100, as_of)
        user = self._adult()
        user["planned_load"] = 40
        user["baseline_load"] = 40
        result = TrendReview().review(logs, user, 7, as_of)
        load = next(item["changes"]["load"] for item in result["proposals"] if "load" in item["changes"])
        assert load == 110

    def test_nothing_confirmed_does_not_move_the_load_up(self):
        logs, as_of = self._ready_load()
        logs["confirmed_changes"] = prior("load", 100, as_of, confirmed=False)
        user = self._adult()
        user["planned_load"] = 200
        result = TrendReview().review(logs, user, 7, as_of)
        assert all(item["changes"].get("load", 0) <= 100 for item in result["proposals"])
        assert all("load" not in item["changes"] for item in result["proposals"])

    def test_parse_utc_rejects_a_date_with_no_clock_time(self):
        assert parse_utc("2026-10-20") is None
        assert parse_utc(date(2026, 10, 20)) is None
        assert parse_utc(datetime(2026, 10, 20, 23, 30)) is None
        parsed = parse_utc("2026-10-21T06:30:00Z")
        assert parsed is not None
        assert parsed.hour == 6 and parsed.minute == 30

    def test_a_naive_datetime_does_not_look_eight_hours_older(self):
        # 23:30 with no timezone, read as UTC, is 8 hours older than 23:30 PST.
        as_of = "2026-10-27T23:30:00Z"
        dates = days("2026-10-21", 8)
        logs = {
            "sessions": [
                {"date": day.isoformat(), "planned": True, "completed": True}
                for day in dates
            ],
            "loads": [{"date": day.isoformat(), "load": 40} for day in dates],
            "confirmed_changes": [{
                "date": datetime(2026, 10, 20, 23, 30),
                "confirmed": True,
                "changes": {"load": 100},
            }],
        }
        early = TrendReview().review(logs, self._adult(), 7, as_of)
        assert all("load" not in item["changes"] for item in early["proposals"])
        logs["confirmed_changes"][0]["date"] = datetime(2026, 10, 21, 7, 30, tzinfo=timezone.utc)
        still_early = TrendReview().review(logs, self._adult(), 7, as_of)
        assert all("load" not in item["changes"] for item in still_early["proposals"])
        later = TrendReview().review(logs, self._adult(), 7, "2026-10-28T07:30:00Z")
        load = next(item["changes"]["load"] for item in later["proposals"] if "load" in item["changes"])
        assert load == 110

    def test_a_date_only_history_does_not_raise(self):
        # 11:30 PM PT on 2026-10-20 is 2026-10-21T06:30:00Z. Reading the
        # calendar date as midnight UTC would treat that change as about
        # 5 days 18 hours older than it is.
        as_of = "2026-10-27T00:00:00Z"
        dates = days("2026-10-21", 7)
        logs = {
            "sessions": [
                {"date": day.isoformat(), "planned": True, "completed": True}
                for day in dates
            ],
            "loads": [{"date": day.isoformat(), "load": 100} for day in dates],
            "confirmed_changes": [{
                "date": "2026-10-20",
                "confirmed": True,
                "changes": {"load": 100},
            }],
        }
        result = TrendReview().review(logs, self._adult(), 7, as_of)
        assert all("load" not in item["changes"] for item in result["proposals"])

    def test_eleven_thirty_pm_pt_does_not_raise_after_about_five_days(self):
        as_of = "2026-10-27T00:00:00Z"
        dates = days("2026-10-21", 8)
        logs = {
            "sessions": [
                {"date": day.isoformat(), "planned": True, "completed": True}
                for day in dates
            ],
            "loads": [{"date": day.isoformat(), "load": 40} for day in dates],
            "confirmed_changes": [{
                "date": "2026-10-21T06:30:00Z",
                "confirmed": True,
                "changes": {"load": 100},
            }],
        }
        early = TrendReview().review(logs, self._adult(), 7, as_of)
        assert all("load" not in item["changes"] for item in early["proposals"])
        later = TrendReview().review(logs, self._adult(), 7, "2026-10-28T06:30:00Z")
        load = next(item["changes"]["load"] for item in later["proposals"] if "load" in item["changes"])
        assert load == 110

    def test_six_days_and_22_5_hours_does_not_pass(self):
        as_of = "2026-10-29T00:30:00Z"
        dates = days("2026-10-23", 7)
        logs = {
            "sessions": [
                {"date": day.isoformat(), "planned": True, "completed": True}
                for day in dates
            ],
            "loads": [{"date": day.isoformat(), "load": 100} for day in dates],
            "confirmed_changes": [{
                "date": "2026-10-22T02:00:00Z",
                "confirmed": True,
                "changes": {"load": 100},
            }],
        }
        result = TrendReview().review(logs, self._adult(), 7, as_of)
        assert all("load" not in item["changes"] for item in result["proposals"])

    def test_exactly_seven_utc_days_can_rise(self):
        as_of = "2026-10-29T02:00:00Z"
        dates = days("2026-10-23", 7)
        logs = {
            "sessions": [
                {"date": day.isoformat(), "planned": True, "completed": True}
                for day in dates
            ],
            "loads": [{"date": day.isoformat(), "load": 40} for day in dates],
            "confirmed_changes": [{
                "date": "2026-10-22T02:00:00Z",
                "confirmed": True,
                "changes": {"load": 100},
            }],
        }
        result = TrendReview().review(logs, self._adult(), 7, as_of)
        load = next(item["changes"]["load"] for item in result["proposals"] if "load" in item["changes"])
        assert load == 110


class TestConfirmationGate:
    def test_review_does_not_apply(self):
        dates = days("2026-10-22", 7)
        sessions = [{"date": day.isoformat(), "planned": True, "completed": True} for day in dates]
        loads = [{"date": day.isoformat(), "load": 80} for day in dates]
        result = TrendReview().review(
            {
                "sessions": sessions,
                "loads": loads,
                "confirmed_changes": prior("load", 80, dates[-1].isoformat()),
            },
            {"sex": "F", "age": 30, "weight_kg": 60},
            7,
            dates[-1].isoformat(),
        )
        assert result["applied"] is False
        assert result["proposals"]
        assert all(item["needs_confirmation"] for item in result["proposals"])

    def test_apply_without_confirmation_does_nothing(self):
        proposal = {"summary": "Raise the load.", "changes": {"load": 110}, "needs_confirmation": True}
        applied = TrendReview().apply(proposal, None)
        assert applied["applied"] is False
        assert applied["changes"] == {}
        assert "record_confirmation" in applied["message"]

    def test_vague_confirmation_does_not_apply(self):
        proposal = {"summary": "Raise the load.", "changes": {"load": 110}}
        applied = TrendReview().apply(proposal, recorded(proposal, "sure I guess"))
        assert applied["applied"] is False

    def test_a_lookalike_dict_does_not_apply(self):
        proposal = {"summary": "Raise the load.", "changes": {"load": 110}}
        applied = TrendReview().apply(proposal, confirmation(proposal, "yes"))
        assert applied["applied"] is False

    def test_matching_confirmation_applies(self):
        proposal = {"summary": "Raise the load.", "changes": {"load": 110}}
        applied = TrendReview().apply(proposal, recorded(proposal, "Yes, I confirm."))
        assert applied["applied"] is True
        assert applied["changes"] == {"load": 110}

    def test_edited_proposal_needs_a_new_confirmation(self):
        proposal = {"summary": "Raise the load.", "changes": {"load": 110}}
        record = recorded(proposal, "yes")
        edited = {"summary": "Raise the load.", "changes": {"load": 140}}
        applied = TrendReview().apply(edited, record)
        assert applied["applied"] is False

    def test_non_user_confirmation_does_not_apply(self):
        proposal = {"summary": "Raise the load.", "changes": {"load": 110}}
        applied = TrendReview().apply(proposal, recorded(proposal, "yes", speaker="coach"))
        assert applied["applied"] is False
