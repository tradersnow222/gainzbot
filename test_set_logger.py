#!/usr/bin/env python3
"""Tests for set_logger.py."""

from datetime import datetime, timedelta, timezone

from plan_check import PlanValidator
from record_confirmation import ConfirmationRecorder
from red_flag_check import RedFlagChecker, is_passing_check_in
from set_logger import SetLogger

AS_OF = "2026-10-29T00:00:00Z"


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


def _logged(weight):
    log = SetLogger()
    log.log_set("squat", weight, 8, "2026-10-28")
    return log


def _confirmed(load):
    return [{
        "date": "2026-10-21T00:00:00Z",
        "confirmed": True,
        "changes": {"load": load},
    }]


def _asks(result):
    assert result["suggestion"] is None
    assert result["proposal"] is None
    assert "What load is confirmed?" in result["message"]
    assert "150" not in result["message"]
    assert "stays at this weight" not in result["message"]


def history(load, as_of=AS_OF, hours_ago=7 * 24, confirmed=True):
    when = datetime(2026, 10, 29, tzinfo=timezone.utc) - timedelta(hours=hours_ago)
    if as_of != AS_OF:
        parsed = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        when = parsed - timedelta(hours=hours_ago)
    return [{
        "date": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "confirmed": confirmed,
        "changes": {"load": load},
    }]


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
        result = log.suggest_next("squat", history(100), AS_OF)
        assert result["applied"] is False
        assert result["suggestion"]["weight"] == 110
        assert result["suggestion"]["reps"] == 8
        assert PlanValidator().validate_training_load_increase(100, 110).valid
        assert result["proposal"]["needs_confirmation"] is True

    def test_two_sets_cannot_stack_from_100_to_121(self):
        log = SetLogger()
        prior = history(100)
        log.log_set("squat", 100, 8, "2026-10-30")
        first = log.suggest_next("squat", prior, AS_OF)
        assert first["suggestion"]["weight"] == 110
        log.log_set("squat", 110, 8, "2026-10-30")
        second = log.suggest_next("squat", prior, AS_OF)
        assert second["suggestion"]["weight"] == 110
        assert second["suggestion"]["weight"] != 121
        assert second["suggestion"]["weight"] != 133.1

    def test_logging_100_then_121_then_133_1_with_no_history_asks(self):
        log = SetLogger()
        log.log_set("squat", 100, 8, "2026-10-30")
        log.log_set("squat", 121, 8, "2026-10-30")
        log.log_set("squat", 133.1, 8, "2026-10-30")
        result = log.suggest_next("squat", as_of=AS_OF)
        assert result["suggestion"] is None
        assert result["proposal"] is None
        assert "What load is confirmed?" in result["message"]
        assert "133.1" not in result["message"]
        assert "stays at this weight" not in result["message"]

    def test_a_confirmed_load_under_7_days_does_not_move_up(self):
        log = SetLogger()
        log.log_set("squat", 110, 8, "2026-10-28")
        young = history(110, hours_ago=(6 * 24) + 22.5)
        early = "2026-10-29T00:30:00Z"
        result = log.suggest_next("squat", young, early)
        assert result["suggestion"]["weight"] == 110
        assert result["suggestion"]["weight"] != 121
        assert result["proposal"] is None

    def test_a_log_above_a_young_confirmed_load_stays_at_the_confirmed_value(self):
        log = SetLogger()
        log.log_set("squat", 150, 8, "2026-10-28")
        early = "2026-10-29T00:30:00Z"
        young = history(100, as_of=early, hours_ago=(6 * 24) + 22.5)
        result = log.suggest_next("squat", young, early)
        assert result["suggestion"]["weight"] == 100
        assert result["suggestion"]["weight"] != 150
        assert result["proposal"] is None
        assert "150" not in result["message"]
        assert "stays at this weight" in result["message"]

    def test_a_missing_as_of_asks_instead_of_repeating_150(self):
        result = _logged(150).suggest_next("squat", _confirmed(100))
        _asks(result)

    def test_a_date_only_as_of_asks_instead_of_repeating_150(self):
        result = _logged(150).suggest_next("squat", _confirmed(100), "2026-10-30")
        _asks(result)

    def test_a_us_date_as_of_asks_instead_of_repeating_150(self):
        result = _logged(150).suggest_next("squat", _confirmed(100), "10/30/2026")
        _asks(result)

    def test_a_date_only_history_entry_asks_instead_of_repeating_150(self):
        history = [{
            "date": "2026-10-20",
            "confirmed": True,
            "changes": {"load": 100},
        }]
        result = _logged(150).suggest_next("squat", history, AS_OF)
        _asks(result)

    def test_a_string_history_asks_instead_of_repeating_150(self):
        result = _logged(150).suggest_next("squat", "confirmed 100", AS_OF)
        _asks(result)

    def test_one_bad_history_row_asks_instead_of_repeating_150(self):
        history = _confirmed(100) + [{"nope": True}]
        result = _logged(150).suggest_next("squat", history, AS_OF)
        _asks(result)

    def test_a_short_set_does_not_jump_the_weight(self):
        log = SetLogger()
        log.log_set("bench", 100, 5, "2026-10-30")
        result = log.suggest_next("bench", history(100), AS_OF)
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
        bench = log.suggest_next("bench", history(60), AS_OF)
        squat = log.suggest_next("squat", history(100), AS_OF)
        assert bench["suggestion"]["weight"] == 66
        assert squat["suggestion"]["weight"] == 110


class TestConfirmation:
    def test_a_bare_true_does_not_apply(self):
        log = SetLogger()
        log.log_set("squat", 100, 8, "2026-10-30")
        proposal = log.suggest_next("squat", history(100), AS_OF)["proposal"]
        applied = log.apply(proposal, True)
        assert applied["applied"] is False
        assert "record_confirmation" in applied["message"]

    def test_apply_without_confirmation_does_not_move_the_baseline(self):
        log = SetLogger()
        prior = history(100)
        log.log_set("squat", 100, 8, "2026-10-30")
        proposal = log.suggest_next("squat", prior, AS_OF)["proposal"]
        applied = log.apply(proposal, None)
        assert applied["applied"] is False
        assert "record_confirmation" in applied["message"]
        log.log_set("squat", 110, 8, "2026-10-30")
        held = log.suggest_next("squat", prior, AS_OF)
        assert held["suggestion"]["weight"] == 110
        assert held["suggestion"]["weight"] != 121

    def test_a_confirmed_jump_becomes_the_new_baseline(self):
        log = SetLogger()
        log.log_set("squat", 100, 8, "2026-10-30")
        proposal = log.suggest_next("squat", history(100), AS_OF)["proposal"]
        applied = log.apply(proposal, confirm(proposal))
        assert applied["applied"] is True
        assert applied["changes"]["weight"] == 110
        log.log_set("squat", 110, 8, "2026-10-31")
        too_soon = log.suggest_next("squat", history(110, hours_ago=24), AS_OF)
        assert too_soon["suggestion"]["weight"] == 110
        assert too_soon["suggestion"]["weight"] != 121
        nxt = log.suggest_next("squat", history(110), AS_OF)
        assert nxt["suggestion"]["weight"] == 121
        assert nxt["suggestion"]["weight"] != 133.1
        assert PlanValidator().validate_training_load_increase(110, 121).valid

    def test_an_edited_proposal_does_not_apply(self):
        log = SetLogger()
        log.log_set("squat", 100, 8, "2026-10-30")
        proposal = log.suggest_next("squat", history(100), AS_OF)["proposal"]
        record = confirm(proposal)
        edited = {
            "summary": proposal["summary"],
            "changes": {"exercise": "squat", "weight": 140, "reps": 8},
            "needs_confirmation": True,
        }
        applied = log.apply(edited, record)
        assert applied["applied"] is False
        assert "squat" not in log.working
