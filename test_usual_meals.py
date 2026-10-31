#!/usr/bin/env python3
"""Tests for the usual-breakfast starter."""

from pathlib import Path

import pytest

from photo_food_log import FoodLog
from record_confirmation import ConfirmationRecorder
from red_flag_check import RedFlagChecker, is_passing_check_in
from usual_meals import offer, plan_to_confirm, save_usual


ROOT = Path(__file__).resolve().parent


def passing_check_in():
    checker = RedFlagChecker()
    answers = {aliases[0]: "no" for _flag, aliases in checker.CHECKLIST_GROUPS}
    result = checker.scan_check_in({
        "symptom_checklist": answers,
        "notes": "Easy lift, slept fine.",
    })
    assert is_passing_check_in(result)
    return result


def fresh_log():
    raise RuntimeError("fresh_log is provided by the tmp_path fixture")


@pytest.fixture(autouse=True)
def _food_logs_use_tmp(tmp_path, monkeypatch):
    counter = {"n": 0}

    def make():
        counter["n"] += 1
        return FoodLog(str(tmp_path / f"used-{counter['n']}.json"))

    monkeypatch.setattr("test_usual_meals.fresh_log", make)


def test_a_missing_usual_breakfast_is_offered_and_saved_only_after_yes():
    food = fresh_log()
    asked = offer(food, "breakfast")
    assert asked["offer"] is True
    assert "remember_usual" in asked["message"]
    ready = plan_to_confirm(food, "breakfast", ["oats", "eggs"], 450, 30)
    assert ready["ok"] is True
    refused = save_usual(food, "breakfast", ["oats", "eggs"], 450, 30, confirmation=None)
    assert refused["stored"] is False
    assert food.usuals == {}
    vague = ConfirmationRecorder().record(ready["plan"], "sure", "user", passing_check_in())
    assert save_usual(food, "breakfast", ["oats", "eggs"], 450, 30, vague)["stored"] is False
    yes = ConfirmationRecorder().record(ready["plan"], "yes", "user", passing_check_in())
    saved = save_usual(food, "breakfast", ["oats", "eggs"], 450, 30, yes)
    assert saved["stored"] is True
    assert offer(food, "breakfast")["offer"] is False
    assert "breakfast" in food.usuals


def test_a_bad_meal_is_not_saved():
    food = fresh_log()
    refused = save_usual(food, "breakfast", ["oats"], 5000, 10, confirmation=None)
    assert refused["stored"] is False
    assert food.usuals == {}


def test_the_guide_keeps_the_starter_fail_closed():
    guide = (ROOT / "template" / "usual-meals.md").read_text(encoding="utf-8")
    lowered = guide.lower()
    assert "log this meal: usual breakfast." in lowered
    assert "remember_usual" in lowered
    assert "record_confirmation" in lowered
    assert "\u2014" not in guide
