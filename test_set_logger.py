#!/usr/bin/env python3
"""Tests for set_logger.py."""

from plan_check import PlanValidator
from record_confirmation import ConfirmationRecorder
from red_flag_check import RedFlagChecker, is_passing_check_in
from set_logger import SetLogger


def passing_check_in():
    checker = RedFlagChecker()
    answers = {aliases[0]: "no" for _flag, aliases in checker.CHECKLIST_GROUPS}
    result = checker.scan_check_in({
        "symptom_checklist": answers,
        "notes": "Easy lift, slept fine.",
    })
    assert is_passing_check_in(result)
    return result


def confirm(proposal):
    return ConfirmationRecorder().record(proposal, "yes", "user", passing_check_in())


class TestLogging:
    def test_a_set_is_stored_and_does_not_change_the_working_weight(self):
        result = SetLogger().log_set("squat", 100, 8, "2026-10-30")
        assert result["stored"] is True
        assert result["applied"] is False
        assert result["entry"]["weight"] == 100
        assert result["entry"]["reps"] == 8

    def test_a_bad_set_is_not_stored(self):
        log = SetLogger()
        result = log.log_set("squat", 0, 8, "2026-10-30")
        assert result["stored"] is False
        assert log.sets == []

    def test_a_set_needs_a_real_date(self):
        result = SetLogger().log_set("squat", 100, 8, "tomorrow")
        assert result["stored"] is False


class TestSuggestion:
    def test_the_next_set_rises_by_at_most_10_percent(self):
        log = SetLogger()
        log.log_set("squat", 100, 8, "2026-10-30")
        result = log.suggest_next("squat")
        assert result["applied"] is False
        assert result["suggestion"]["weight"] == 110
        assert result["suggestion"]["reps"] == 8
        assert PlanValidator().validate_training_load_increase(100, 110).valid
        assert result["proposal"]["needs_confirmation"] is True

    def test_two_sets_cannot_stack_from_100_to_121(self):
        log = SetLogger()
        log.log_set("squat", 100, 8, "2026-10-30")
        first = log.suggest_next("squat")
        assert first["suggestion"]["weight"] == 110
        log.log_set("squat", 110, 8, "2026-10-30")
        second = log.suggest_next("squat")
        assert second["suggestion"]["weight"] == 110
        assert second["suggestion"]["weight"] != 121

    def test_a_short_set_does_not_jump_the_weight(self):
        log = SetLogger()
        log.log_set("bench", 100, 5, "2026-10-30")
        result = log.suggest_next("bench")
        assert result["suggestion"]["weight"] == 100
        assert result["proposal"] is None

    def test_no_history_has_no_suggestion(self):
        result = SetLogger().suggest_next("deadlift")
        assert result["ok"] is False
        assert result["suggestion"] is None

    def test_another_exercise_keeps_its_own_baseline(self):
        log = SetLogger()
        log.log_set("squat", 100, 8, "2026-10-30")
        log.log_set("bench", 60, 8, "2026-10-30")
        assert log.suggest_next("bench")["suggestion"]["weight"] == 66


class TestConfirmation:
    def test_apply_without_confirmation_does_not_move_the_baseline(self):
        log = SetLogger()
        log.log_set("squat", 100, 8, "2026-10-30")
        proposal = log.suggest_next("squat")["proposal"]
        applied = log.apply(proposal, None)
        assert applied["applied"] is False
        assert "record_confirmation" in applied["message"]
        log.log_set("squat", 110, 8, "2026-10-30")
        assert log.suggest_next("squat")["suggestion"]["weight"] == 110

    def test_a_confirmed_jump_becomes_the_new_baseline(self):
        log = SetLogger()
        log.log_set("squat", 100, 8, "2026-10-30")
        proposal = log.suggest_next("squat")["proposal"]
        applied = log.apply(proposal, confirm(proposal))
        assert applied["applied"] is True
        assert applied["changes"]["weight"] == 110
        log.log_set("squat", 110, 8, "2026-10-31")
        nxt = log.suggest_next("squat")
        assert nxt["suggestion"]["weight"] == 121
        assert PlanValidator().validate_training_load_increase(110, 121).valid

    def test_an_edited_proposal_does_not_apply(self):
        log = SetLogger()
        log.log_set("squat", 100, 8, "2026-10-30")
        proposal = log.suggest_next("squat")["proposal"]
        record = confirm(proposal)
        edited = {
            "summary": proposal["summary"],
            "changes": {"exercise": "squat", "weight": 140, "reps": 8},
            "needs_confirmation": True,
        }
        applied = log.apply(edited, record)
        assert applied["applied"] is False
        assert "squat" not in log.working
