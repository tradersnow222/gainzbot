#!/usr/bin/env python3
"""Tests for trend_review.py."""

from datetime import date, timedelta

import pytest

from plan_check import PlanValidator
from trend_review import NOT_ENOUGH, TrendReview, hash_plan


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
            {"weights": weights, "intake": intake},
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
        result = TrendReview().review(
            {"weights": weights, "intake": intake},
            self._adult(),
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
            {"weights": weights, "intake": intake},
            {"sex": "F", "age": 40, "weight_kg": 60},
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
            {"sessions": sessions, "loads": loads},
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
            {"sessions": sessions, "loads": loads},
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
            {"loads": loads, "sessions": sessions},
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
            {"weights": weights, "intake": intake},
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


class TestConfirmationGate:
    def test_review_does_not_apply(self):
        dates = days("2026-10-22", 7)
        sessions = [{"date": day.isoformat(), "planned": True, "completed": True} for day in dates]
        loads = [{"date": day.isoformat(), "load": 80} for day in dates]
        result = TrendReview().review(
            {"sessions": sessions, "loads": loads},
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
        applied = TrendReview().apply(proposal, confirmation(proposal, "sure I guess"))
        assert applied["applied"] is False

    def test_matching_confirmation_applies(self):
        proposal = {"summary": "Raise the load.", "changes": {"load": 110}}
        applied = TrendReview().apply(proposal, confirmation(proposal, "Yes, I confirm."))
        assert applied["applied"] is True
        assert applied["changes"] == {"load": 110}

    def test_edited_proposal_needs_a_new_confirmation(self):
        proposal = {"summary": "Raise the load.", "changes": {"load": 110}}
        record = confirmation(proposal, "yes")
        edited = {"summary": "Raise the load.", "changes": {"load": 140}}
        applied = TrendReview().apply(edited, record)
        assert applied["applied"] is False

    def test_non_user_confirmation_does_not_apply(self):
        proposal = {"summary": "Raise the load.", "changes": {"load": 110}}
        applied = TrendReview().apply(proposal, confirmation(proposal, "yes", speaker="coach"))
        assert applied["applied"] is False
