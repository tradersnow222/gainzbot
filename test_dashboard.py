#!/usr/bin/env python3
"""Tests for dashboard.py."""

import pytest

from dashboard import DASHBOARD_SPEC, NOT_ENOUGH, Dashboard


ADULT = {"sex": "M", "age": 34, "weight_kg": 80}
TARGETS = {"calories": 2200, "protein_g": 144}


def logs():
    return {
        "weights": [
            {"date": "2026-09-20", "kg": 81},
            {"date": "2026-10-20", "kg": 80.4},
            {"date": "2026-10-28", "kg": 80},
        ],
        "intake": [
            {"date": "2026-10-28", "calories": 2100, "protein_g": 140},
            {"date": "2026-10-28", "calories": 100, "protein_g": 4},
            {"date": "2026-09-01", "calories": 3000, "protein_g": 100},
        ],
        "sessions": [
            {"date": "2026-10-26", "planned": True, "completed": True},
            {"date": "2026-10-27", "planned": True, "completed": True},
            {"date": "2026-10-28", "planned": True, "completed": False},
            {"date": "2026-10-29", "planned": False, "completed": False},
        ],
        "sets": [
            {"date": "2026-10-26", "exercise": "squat", "weight": 100, "reps": 5},
            {"date": "2026-10-28", "exercise": "squat", "weight": 110, "reps": 3},
            {"date": "2026-10-28", "exercise": "bench", "weight": 60, "reps": 8},
        ],
    }


def chart(result, chart_id):
    return next(item for item in result["charts"] if item["id"] == chart_id)


class TestSpec:
    def test_the_spec_is_chart_first(self):
        assert DASHBOARD_SPEC["layout"] == "charts"
        assert DASHBOARD_SPEC["windows"] == [7, 28, 90, 365]
        assert [item["id"] for item in DASHBOARD_SPEC["charts"]] == [
            "weight", "calories", "protein", "adherence", "records",
        ]

    def test_a_bad_window_is_refused(self):
        result = Dashboard().build(logs(), ADULT, window_days=10, as_of="2026-10-28")
        assert result["enough_data"] is False
        assert result["applied"] is False
        assert "7" in result["message"] and "365" in result["message"]
        assert chart(result, "weight")["points"] == []

    def test_empty_logs_say_not_enough_data(self):
        result = Dashboard().build({}, ADULT, 28, "2026-10-28", TARGETS)
        assert result["message"] == NOT_ENOUGH
        assert result["applied"] is False
        assert result["spec"]["layout"] == "charts"
        assert chart(result, "weight")["points"] == []

    @pytest.mark.parametrize("window", [7, 28, 90, 365])
    def test_each_window_is_accepted(self, window):
        result = Dashboard().build(logs(), ADULT, window, "2026-10-28", TARGETS)
        assert result["window_days"] == window
        assert result["applied"] is False
        assert [item["id"] for item in result["charts"]] == [
            "weight", "calories", "protein", "adherence", "records",
        ]


class TestCharts:
    def test_weight_trend_stays_inside_the_window(self):
        result = Dashboard().build(logs(), ADULT, 28, "2026-10-28", TARGETS)
        points = chart(result, "weight")["points"]
        assert points == [
            {"date": "2026-10-20", "kg": 80.4},
            {"date": "2026-10-28", "kg": 80},
        ]
        week = Dashboard().build(logs(), ADULT, 7, "2026-10-28", TARGETS)
        assert chart(week, "weight")["points"] == [{"date": "2026-10-28", "kg": 80}]

    def test_calories_and_protein_are_compared_with_the_target(self):
        result = Dashboard().build(logs(), ADULT, 28, "2026-10-28", TARGETS)
        calories = chart(result, "calories")["points"]
        protein = chart(result, "protein")["points"]
        assert calories == [{"date": "2026-10-28", "eaten": 2200, "target": 2200}]
        assert protein == [{"date": "2026-10-28", "eaten": 144, "target": 144}]

    def test_under_18_has_no_calorie_target(self):
        user = {"sex": "M", "age": 16, "weight_kg": 60}
        result = Dashboard().build(
            logs(), user, 28, "2026-10-28", {"calories": 2200, "protein_g": 110},
        )
        assert chart(result, "calories")["points"][0]["target"] is None
        assert chart(result, "protein")["points"][0]["target"] is None
        assert "18" in result["message"]
        assert "protein" in result["message"].lower()

    def test_missing_age_has_no_calorie_target(self):
        result = Dashboard().build(
            logs(), {"sex": "M", "weight_kg": 80}, 28, "2026-10-28", TARGETS,
        )
        assert chart(result, "calories")["points"][0]["target"] is None
        assert "age" in result["message"].lower()

    def test_a_single_log_is_not_dashboard_ready(self):
        one = {"intake": [{"date": "2026-10-28", "calories": 2000, "protein_g": 140}]}
        result = Dashboard().build(one, ADULT, 28, "2026-10-28", TARGETS)
        assert result["enough_data"] is False
        assert result["message"] == NOT_ENOUGH
        assert "Dashboard ready" not in result["message"]
        two = {
            "intake": [
                {"date": "2026-10-27", "calories": 2000, "protein_g": 140},
                {"date": "2026-10-28", "calories": 2100, "protein_g": 150},
            ],
        }
        ready = Dashboard().build(two, ADULT, 28, "2026-10-28", TARGETS)
        assert ready["message"] == "Dashboard ready."

    def test_a_womens_target_under_1200_is_not_drawn(self):
        user = {"sex": "F", "age": 34, "weight_kg": 60}
        low = Dashboard().build(
            logs(), user, 28, "2026-10-28", {"calories": 1199, "protein_g": 120},
        )
        assert chart(low, "calories")["points"][0]["target"] is None
        assert "1200" in low["message"]
        kept = Dashboard().build(
            logs(), user, 28, "2026-10-28", {"calories": 1200, "protein_g": 120},
        )
        assert chart(kept, "calories")["points"][0]["target"] == 1200

    def test_missing_sex_has_no_calorie_target(self):
        result = Dashboard().build(
            logs(), {"age": 34, "weight_kg": 80}, 28, "2026-10-28", TARGETS,
        )
        assert chart(result, "calories")["points"][0]["target"] is None
        assert "sex" in result["message"].lower()

    def test_a_target_under_the_floor_is_not_drawn(self):
        result = Dashboard().build(
            logs(), ADULT, 28, "2026-10-28", {"calories": 1400, "protein_g": 144},
        )
        assert chart(result, "calories")["points"][0]["target"] is None
        assert "floor" in result["message"].lower()

    def test_a_protein_target_outside_the_range_is_not_drawn(self):
        result = Dashboard().build(
            logs(), ADULT, 28, "2026-10-28", {"calories": 2200, "protein_g": 50},
        )
        assert chart(result, "protein")["points"][0]["target"] is None
        assert "1.6" in result["message"]

    def test_adherence_counts_planned_sessions(self):
        result = Dashboard().build(logs(), ADULT, 28, "2026-10-28", TARGETS)
        adherence = chart(result, "adherence")
        assert adherence["completed"] == 2
        assert adherence["planned"] == 3
        assert adherence["rate"] == round(2 / 3, 2)

    def test_personal_records_keep_the_best_set_in_the_window(self):
        result = Dashboard().build(logs(), ADULT, 28, "2026-10-28", TARGETS)
        rows = chart(result, "records")["rows"]
        assert rows == [
            {"exercise": "bench", "weight": 60, "reps": 8, "date": "2026-10-28"},
            {"exercise": "squat", "weight": 110, "reps": 3, "date": "2026-10-28"},
        ]

    def test_the_builder_does_not_change_the_logs(self):
        source = logs()
        before = repr(source)
        result = Dashboard().build(source, ADULT, 90, "2026-10-28", TARGETS)
        assert result["applied"] is False
        assert repr(source) == before
