#!/usr/bin/env python3
"""Tests for photo_food_log.py."""

from photo_food_log import GROK_VISION_PROMPT, FoodLog
from plan_check import PlanValidator
from record_confirmation import ConfirmationRecorder
from red_flag_check import RedFlagChecker, is_passing_check_in


ADULT = {"sex": "M", "age": 34, "weight_kg": 80}
TARGETS = {"calories": 2200, "protein_g": 144}


def estimate():
    return {"items": ["rice", "chicken"], "calories": 600, "protein_g": 40}


def passing_check_in():
    checker = RedFlagChecker()
    answers = {aliases[0]: "no" for _flag, aliases in checker.CHECKLIST_GROUPS}
    result = checker.scan_check_in({
        "symptom_checklist": answers,
        "notes": "Easy lift, slept fine.",
    })
    assert is_passing_check_in(result)
    return result


def recorded(plan):
    return ConfirmationRecorder().record(plan, "yes", "user", passing_check_in())


def store(log, meal, day="2026-10-30"):
    return log.store_estimate(meal, day, recorded(meal))


class TestPhotoEstimate:
    def test_prompt_asks_for_items_calories_and_protein(self):
        text = GROK_VISION_PROMPT.lower()
        assert "items" in text
        assert "calories" in text
        assert "protein" in text
        assert "json" in text

    def test_estimate_is_stored(self):
        meal = estimate()
        result = FoodLog().store_estimate(meal, "2026-10-30", recorded(meal))
        assert result["stored"] is True
        assert result["applied"] is False
        assert result["entry"]["calories"] == 600
        assert result["entry"]["items"] == ["rice", "chicken"]

    def test_store_estimate_requires_confirmation_of_that_estimate(self):
        log = FoodLog()
        meal = estimate()
        other = estimate()
        other["calories"] = 700
        missed = log.store_estimate(meal, "2026-10-30")
        bare = log.store_estimate(meal, "2026-10-30", True)
        wrong = log.store_estimate(meal, "2026-10-30", recorded(other))
        assert missed["stored"] is False
        assert bare["stored"] is False
        assert wrong["stored"] is False
        assert "record_confirmation" in missed["message"]
        assert log.entries == []

    def test_a_single_item_over_3000_kcal_is_rejected(self):
        log = FoodLog()
        meal = {"items": ["cake"], "calories": 3001, "protein_g": 10}
        result = log.store_estimate(meal, "2026-10-30", recorded(meal))
        assert result["stored"] is False
        assert "re-check" in result["message"].lower()
        assert log.entries == []

    def test_a_single_item_over_300_g_protein_is_rejected(self):
        log = FoodLog()
        meal = {"items": ["powder"], "calories": 400, "protein_g": 301}
        result = log.store_estimate(meal, "2026-10-30", recorded(meal))
        assert result["stored"] is False
        assert "re-check" in result["message"].lower()
        assert log.entries == []

    def test_the_upper_bound_itself_can_be_logged(self):
        meal = {"items": ["feast"], "calories": 3000, "protein_g": 300}
        result = FoodLog().store_estimate(meal, "2026-10-30", recorded(meal))
        assert result["stored"] is True
        assert result["entry"]["calories"] == 3000
        assert result["entry"]["protein_g"] == 300

    def test_bad_calories_store_nothing(self):
        log = FoodLog()
        result = log.store_estimate(
            {"items": ["rice"], "calories": "lots", "protein_g": 10},
            "2026-10-30",
        )
        assert result["stored"] is False
        assert log.entries == []

    def test_missing_items_store_nothing(self):
        result = FoodLog().store_estimate(
            {"items": [], "calories": 100, "protein_g": 10},
            "2026-10-30",
        )
        assert result["stored"] is False

    def test_bad_day_stores_nothing(self):
        log = FoodLog()
        result = log.store_estimate(estimate(), "yesterday")
        assert result["stored"] is False
        assert log.entries == []


class TestUsualMeals:
    def test_usual_breakfast_logs_in_one_line(self):
        log = FoodLog()
        remembered = log.remember_usual("breakfast", ["oats", "eggs"], 450, 30)
        assert remembered["stored"] is True
        logged = log.log_line("usual breakfast", "2026-10-30")
        assert logged["stored"] is True
        assert logged["entry"]["calories"] == 450
        assert logged["entry"]["protein_g"] == 30
        assert logged["entry"]["source"] == "usual"
        assert logged["applied"] is False

    def test_unknown_usual_does_not_store(self):
        log = FoodLog()
        result = log.log_line("usual breakfast", "2026-10-30")
        assert result["stored"] is False
        assert log.entries == []

    def test_other_lines_are_not_usual_meals(self):
        log = FoodLog()
        log.remember_usual("breakfast", ["oats"], 400, 20)
        result = log.log_line("breakfast please", "2026-10-30")
        assert result["stored"] is False
        assert log.entries == []


class TestLeftToday:
    def test_one_meal_subtracts_from_the_targets(self):
        log = FoodLog()
        store(log, estimate())
        left = log.left_today("2026-10-30", ADULT, TARGETS)
        assert left["eaten_calories"] == 600
        assert left["eaten_protein_g"] == 40
        assert left["calories_left"] == 1600
        assert left["protein_left"] == 104
        assert left["applied"] is False

    def test_meals_on_the_same_day_add_up(self):
        log = FoodLog()
        store(log, estimate())
        log.remember_usual("breakfast", ["oats"], 400, 20)
        log.log_line("usual breakfast", "2026-10-30")
        left = log.left_today("2026-10-30", ADULT, TARGETS)
        assert left["eaten_calories"] == 1000
        assert left["eaten_protein_g"] == 60

    def test_another_day_is_not_counted(self):
        log = FoodLog()
        store(log, estimate(), "2026-10-29")
        left = log.left_today("2026-10-30", ADULT, TARGETS)
        assert left["eaten_calories"] == 0
        assert left["calories_left"] == 2200

    def test_under_18_gets_no_calorie_target(self):
        log = FoodLog()
        store(log, estimate())
        left = log.left_today(
            "2026-10-30",
            {"sex": "M", "age": 16, "weight_kg": 60},
            {"calories": 2200, "protein_g": 110},
        )
        assert left["calories_left"] is None
        assert left["protein_left"] is None
        assert "18" in left["message"]
        assert "protein" in left["message"].lower()

    def test_missing_age_blocks_the_calorie_target(self):
        log = FoodLog()
        store(log, estimate())
        left = log.left_today("2026-10-30", {"sex": "M", "weight_kg": 80}, TARGETS)
        assert left["calories_left"] is None
        assert "age" in left["message"].lower()

    def test_calorie_target_under_the_floor_is_not_used(self):
        log = FoodLog()
        left = log.left_today(
            "2026-10-30",
            ADULT,
            {"calories": PlanValidator.CALORIE_FLOOR_MEN - 1, "protein_g": 144},
        )
        assert left["calories_left"] is None
        assert "floor" in left["message"].lower()

    def test_protein_target_outside_the_range_is_not_used(self):
        log = FoodLog()
        left = log.left_today(
            "2026-10-30",
            ADULT,
            {"calories": 2200, "protein_g": 50},
        )
        assert left["protein_left"] is None
        assert "1.6" in left["message"]
