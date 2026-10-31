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
            "weight", "calories", "protein", "adherence", "records", "volume",
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
            "weight", "calories", "protein", "adherence", "records", "volume",
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

    def test_missing_age_has_no_protein_target(self):
        result = Dashboard().build(
            logs(), {"sex": "M", "weight_kg": 80}, 28, "2026-10-28", TARGETS,
        )
        assert chart(result, "protein")["points"][0]["target"] is None
        assert chart(result, "calories")["points"][0]["target"] is None
        assert "protein" in result["message"].lower()
        assert "age" in result["message"].lower()

    def test_missing_age_has_no_calorie_target(self):
        result = Dashboard().build(
            logs(), {"sex": "M", "weight_kg": 80}, 28, "2026-10-28", TARGETS,
        )
        assert chart(result, "calories")["points"][0]["target"] is None
        assert "age" in result["message"].lower()

    def test_a_thin_log_still_shows_the_first_day(self):
        week = {
            "plan": {
                "nutrition": {"calories": 2200, "protein_g": 144},
                "goals": {"goal": "cut"},
            },
            "sessions": [
                {
                    "date": "2026-10-28",
                    "name": "Full body A",
                    "exercises": [{"name": "Squat", "sets": 3, "reps": "8-12", "rest": "90 sec", "effort": "Leave 3 reps in reserve"}],
                },
            ],
        }
        result = Dashboard().build({}, ADULT, 28, "2026-10-28", week=week)
        assert result["message"] == NOT_ENOUGH
        assert result["enough_data"] is False
        assert chart(result, "weight")["points"] == []
        day = result["first_day"]
        assert day["today"]["name"] == "Full body A"
        assert day["week"] == week["sessions"]
        assert day["targets"]["calories"] == 2200
        assert day["targets"]["protein_g"] == 144
        assert day["targets"]["goal"] == "cut"
        assert day["next"] == "Log today's session."

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


def test_one_day_of_many_rows_is_not_two_days():
    intake = [
        {"date": "2026-10-28", "calories": 100, "protein_g": 10}
        for _ in range(17)
    ]
    result = Dashboard().build({"intake": intake}, ADULT, 28, "2026-10-28", TARGETS)
    assert result["enough_data"] is False
    assert result["message"] == NOT_ENOUGH
    assert "first_day" in result
    assert "Dashboard ready" not in result["message"]
    two = {
        "intake": intake + [{"date": "2026-10-29", "calories": 100, "protein_g": 10}],
    }
    ready = Dashboard().build(two, ADULT, 28, "2026-10-29", TARGETS)
    assert ready["enough_data"] is True
    assert ready["message"] == "Dashboard ready."


def test_logged_sets_mark_todays_session_done():
    week = {
        "sessions": [
            {
                "date": "2026-10-28",
                "name": "Upper",
                "exercises": [{"name": "Bench press"}, {"name": "Squat"}],
            },
        ],
    }
    partial = {
        "sets": [
            {"date": "2026-10-28", "exercise": "bench press", "weight": 70, "reps": 10},
        ],
    }
    waiting = Dashboard().build(partial, ADULT, 28, "2026-10-28", week=week)
    assert waiting["enough_data"] is False
    assert waiting["first_day"]["next"] == "Log today's session."
    done = {
        "sets": partial["sets"] + [
            {"date": "2026-10-28", "exercise": "SQUAT", "weight": 80, "reps": 8},
        ],
    }
    finished = Dashboard().build(done, ADULT, 28, "2026-10-28", week=week)
    assert finished["first_day"]["next"] != "Log today's session."
    assert finished["first_day"]["next"] == "Log a weight."


def test_weekly_volume_is_sets_times_reps_times_kg():
    result = Dashboard().build(logs(), ADULT, 28, "2026-10-28", TARGETS)
    assert chart(result, "volume")["points"] == [
        {"date": "2026-10-26", "volume": 500},
        {"date": "2026-10-28", "volume": 810},
    ]
    counted = {
        "sets": [
            {"date": "2026-10-27", "exercise": "squat", "weight": 70, "reps": 10, "sets": 3},
            {"date": "2026-10-28", "exercise": "squat", "weight": 70, "reps": 10, "sets": 3},
        ],
    }
    both = Dashboard().build(counted, ADULT, 7, "2026-10-28", TARGETS)
    assert chart(both, "volume")["points"] == [
        {"date": "2026-10-27", "volume": 2100},
        {"date": "2026-10-28", "volume": 2100},
    ]
    empty = Dashboard().build({}, ADULT, 28, "2026-10-28", TARGETS)
    assert chart(empty, "volume")["points"] == []


def test_build_saved_counts_the_confirmed_week(tmp_path):
    import json

    from log_store import LogStore

    log_path = tmp_path / "log.json"
    week = {
        "confirmation": {"record_id": "rec-week"},
        "sessions": [
            {
                "date": "2026-10-28",
                "name": "Upper",
                "exercises": [{"name": "Bench press"}, {"name": "Barbell row"}],
            },
            {
                "date": "2026-10-30",
                "name": "Lower",
                "exercises": [{"name": "Squat"}],
            },
        ],
    }
    (tmp_path / "week.json").write_text(json.dumps(week), encoding="utf-8")
    store = LogStore(log_path)
    store.append("sets", {"date": "2026-10-28", "exercise": "Bench press", "weight": 70, "reps": 10})
    store.append("sets", {"date": "2026-10-28", "exercise": "barbell row", "weight": 60, "reps": 8})
    store.append("weights", {"date": "2026-10-29", "kg": 80})
    built = Dashboard().build_saved(log_path, ADULT, 28, "2026-10-30", TARGETS)
    adherence = chart(built, "adherence")
    assert adherence["planned"] == 2
    assert adherence["completed"] == 1
    assert f"{adherence['completed']} of {adherence['planned']}" != "0 of 0"
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other = other_dir / "log.json"
    LogStore(other).append("sets", {"date": "2026-10-28", "exercise": "Bench press", "weight": 70, "reps": 10})
    LogStore(other).append("weights", {"date": "2026-10-29", "kg": 80})
    missed = Dashboard().build_saved(other, ADULT, 28, "2026-10-30", TARGETS)
    assert chart(missed, "adherence")["planned"] == 0
    assert chart(missed, "adherence")["completed"] == 0
