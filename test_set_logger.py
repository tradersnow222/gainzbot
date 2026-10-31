#!/usr/bin/env python3
"""Tests for set_logger.py."""

from datetime import datetime, timedelta, timezone

from confirmed_change import last_confirmed_change
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
    assert "133.1" not in result["message"]
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
    def test_the_next_set_rises_by_2_5_kg_when_every_set_hits_the_top(self):
        log = SetLogger()
        log.log_set("squat", 70, 10, "2026-11-09")
        result = log.suggest_next("squat", history(100), AS_OF, rep_top=10)
        assert result["applied"] is False
        assert result["suggestion"]["weight"] == 72.5
        assert result["suggestion"]["reps"] == 10
        assert result["suggestion"]["weight"] != 77
        assert result["proposal"] is None
        assert result["message"] == "Next set is 72.5 kg."
        assert "stays at this weight" not in result["message"]
        assert "77" not in result["message"]

    def test_sets_on_one_day_do_not_stack_a_second_step(self):
        log = SetLogger()
        prior = history(100)
        log.log_set("squat", 100, 10, "2026-10-30")
        first = log.suggest_next("squat", prior, AS_OF, rep_top=10)
        assert first["suggestion"]["weight"] == 102.5
        assert first["suggestion"]["weight"] != 105
        assert first["proposal"] is None
        log.log_set("squat", 102.5, 10, "2026-10-30")
        second = log.suggest_next("squat", prior, AS_OF, rep_top=10)
        assert second["suggestion"]["weight"] == 102.5
        assert second["suggestion"]["weight"] != 105
        log.log_set("squat", 105, 10, "2026-10-30")
        third = log.suggest_next("squat", prior, AS_OF, rep_top=10)
        assert third["suggestion"]["weight"] == 102.5
        assert third["suggestion"]["weight"] != 105
        assert third["suggestion"]["weight"] != 107.5
        log.log_set("squat", 102.5, 10, "2026-10-31")
        nxt = log.suggest_next("squat", prior, AS_OF, rep_top=10)
        assert nxt["suggestion"]["weight"] == 105
        assert nxt["proposal"] is None

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

    def test_a_kilogram_step_does_not_wait_7_days(self):
        log = SetLogger()
        log.log_set("squat", 70, 10, "2026-10-28")
        young = history(100, hours_ago=(6 * 24) + 22.5)
        early = "2026-10-29T00:30:00Z"
        result = log.suggest_next("squat", young, early, rep_top=10)
        assert result["suggestion"]["weight"] == 72.5
        assert result["suggestion"]["weight"] != 77
        assert result["proposal"] is None
        assert "72.5" in result["message"]

    def test_the_load_index_does_not_clamp_kilograms(self):
        log = SetLogger()
        log.log_set("bench", 70, 8, "2026-11-09")
        stayed = log.suggest_next("bench", history(100), AS_OF, rep_top=10)
        assert stayed["suggestion"]["weight"] == 70
        assert stayed["message"] == "Next set stays at 70 kg."
        assert stayed["proposal"] is None
        heavy = SetLogger()
        heavy.log_set("squat", 150, 8, "2026-10-28")
        early = "2026-10-29T00:30:00Z"
        young = history(100, as_of=early, hours_ago=(6 * 24) + 22.5)
        held = heavy.suggest_next("squat", young, early)
        assert held["suggestion"]["weight"] == 150
        assert held["suggestion"]["weight"] != 100
        assert "150" in held["message"]
        assert held["proposal"] is None

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
        prior = [{
            "date": "2026-10-20",
            "confirmed": True,
            "changes": {"load": 100},
        }]
        result = _logged(150).suggest_next("squat", prior, AS_OF)
        _asks(result)

    def test_a_string_history_asks_instead_of_repeating_150(self):
        result = _logged(150).suggest_next("squat", "confirmed 100", AS_OF)
        _asks(result)

    def test_one_bad_history_row_asks_instead_of_repeating_150(self):
        prior = _confirmed(100) + [{"nope": True}]
        result = _logged(150).suggest_next("squat", prior, AS_OF)
        _asks(result)
        found = last_confirmed_change(prior, "load", AS_OF)
        assert found.ok is False
        assert found.reason == "wrong key"

    def test_a_plan_row_without_changes_fails_closed(self):
        prior = [
            {
                "record_id": "rec-1",
                "plan_hash": "hash",
                "quoted_words": "yes",
                "date": "not-a-date",
                "confirmed": True,
            },
            {
                "date": "2026-10-21T00:00:00Z",
                "confirmed": True,
                "changes": {"load": 100},
            },
        ]
        found = last_confirmed_change(prior, "load", AS_OF)
        assert found.ok is False
        assert found.value is None
        assert found.reason == "plan row"
        log = SetLogger()
        log.log_set("bench", 70, 10, "2026-11-09")
        result = log.suggest_next("bench", prior, AS_OF, rep_top="6-10")
        assert result["suggestion"] is None
        assert result["proposal"] is None
        assert "What load is confirmed?" in result["message"]
        assert "72.5" not in result["message"]
        assert "77" not in result["message"]

    def test_exercise_names_share_one_history_key(self):
        log = SetLogger()
        stored = log.log_set("Squ\u00e1t\u200b", 70, 10, "2026-11-09")
        assert stored["entry"]["exercise"] == "squat"
        again = log.log_set("SQUAT", 70, 10, "2026-11-09")
        assert again["entry"]["exercise"] == "squat"
        result = log.suggest_next("squat", history(100), AS_OF, rep_top=10)
        assert result["suggestion"]["weight"] == 72.5
        assert result["suggestion"]["exercise"] == "squat"
        greek = log.log_set("squ\u03b1t", 70, 10, "2026-11-09")
        assert greek["entry"]["exercise"] == "squat"
        for name in ("bench-press", "benchpress", "bench press", "b\u0435nch-press"):
            saved = log.log_set(name, 70, 10, "2026-11-09")
            assert saved["entry"]["exercise"] == "benchpress", name
        stepped = log.suggest_next("bench press", history(100), AS_OF, rep_top=10)
        assert stepped["suggestion"]["exercise"] == "benchpress"
        assert stepped["suggestion"]["weight"] == 72.5
        for name in ("bench presses", "lunges", "lunge", "pullups", "pull-ups", "pull ups"):
            saved = log.log_set(name, 70, 10, "2026-11-09")
            if "bench" in name:
                assert saved["entry"]["exercise"] == "benchpress", name
            elif "lunge" in name:
                assert saved["entry"]["exercise"] == "lunge", name
            else:
                assert saved["entry"]["exercise"] == "pullup", name
        same = log.suggest_next("pull-ups", history(100), AS_OF, rep_top=10)
        assert same["suggestion"]["exercise"] == "pullup"
        assert same["suggestion"]["weight"] == 72.5

    def test_one_set_short_of_the_top_keeps_the_weight(self):
        log = SetLogger()
        log.log_set("bench", 70, 10, "2026-11-09")
        log.log_set("bench", 70, 8, "2026-11-09")
        result = log.suggest_next("bench", history(100), AS_OF, rep_top="6-10")
        assert result["suggestion"]["weight"] == 70
        assert result["proposal"] is None
        assert "72.5" not in result["message"]
        assert "77" not in result["message"]

    def test_a_jump_past_2_5_kg_needs_a_yes(self):
        log = SetLogger()
        log.log_set("squat", 70, 10, "2026-11-09")
        result = log.suggest_next(
            "squat", history(100), AS_OF, rep_top=10, requested_weight=75,
        )
        assert result["suggestion"]["weight"] == 75
        assert result["proposal"]["needs_confirmation"] is True
        assert "75" in result["message"]
        assert "yes" in result["message"].lower()
        assert "stays at this weight" not in result["message"]
        normal = log.suggest_next("squat", history(100), AS_OF, rep_top=10)
        assert normal["suggestion"]["weight"] == 72.5
        assert normal["proposal"] is None

    def test_a_yes_jump_is_capped_at_10_percent(self):
        log = SetLogger()
        log.log_set("squat", 70, 10, "2026-10-30")
        result = log.suggest_next(
            "squat", history(100), AS_OF, rep_top=10, requested_weight=80,
        )
        assert result["suggestion"]["weight"] == 77
        assert result["suggestion"]["weight"] != 80
        assert result["proposal"]["needs_confirmation"] is True
        assert "77" in result["message"]
        assert "80" not in result["message"]
        assert "yes" in result["message"].lower()

    def test_a_prior_week_baseline_keeps_the_kilograms_inside_10_percent(self):
        log = SetLogger()
        log.log_set("squat", 100, 10, "2026-10-21")
        log.log_set("squat", 133.1, 8, "2026-10-28")
        held = log.suggest_next("squat", as_of=AS_OF, rep_top=10)
        assert held["suggestion"]["weight"] == 100
        assert held["suggestion"]["weight"] != 133.1
        assert "133.1" not in held["message"]
        assert held["proposal"] is None
        raised = log.suggest_next(
            "squat", history(100), AS_OF, rep_top=10, requested_weight=130,
        )
        assert raised["suggestion"]["weight"] == 110
        assert raised["suggestion"]["weight"] != 130
        assert raised["proposal"]["needs_confirmation"] is True
        assert "130" not in raised["message"]
        assert "110" in raised["message"]

    def test_a_short_set_does_not_jump_the_weight(self):
        log = SetLogger()
        log.log_set("bench", 100, 5, "2026-10-30")
        result = log.suggest_next("bench", history(100), AS_OF, rep_top=10)
        assert result["suggestion"]["weight"] == 100
        assert result["proposal"] is None
        assert result["message"] == "Next set stays at 100 kg."

    def test_no_sets_has_no_suggestion(self):
        result = SetLogger().suggest_next("deadlift")
        assert result["ok"] is False
        assert result["suggestion"] is None
        assert result["message"] == "Log a set first."

    def test_suggest_next_reads_the_saved_log(self, tmp_path):
        from log_store import LogStore

        path = tmp_path / "log.json"
        LogStore(path).append("sets", {
            "date": "2026-11-09",
            "exercise": "Bench press",
            "weight": 70,
            "reps": 10,
        })
        result = SetLogger().suggest_next(
            "Bench press", history(100), AS_OF, log_path=path, rep_top=10,
        )
        assert result["ok"] is True
        assert "Log a set first" not in result["message"]
        assert result["suggestion"]["weight"] == 72.5
        assert "72.5" in result["message"]

    def test_another_exercise_keeps_its_own_kilograms(self):
        log = SetLogger()
        log.log_set("squat", 100, 8, "2026-10-30")
        log.log_set("bench", 60, 8, "2026-10-30")
        bench = log.suggest_next("bench", history(60), AS_OF, rep_top=8)
        squat = log.suggest_next("squat", history(100), AS_OF, rep_top=8)
        assert bench["suggestion"]["weight"] == 62.5
        assert squat["suggestion"]["weight"] == 102.5
        assert bench["proposal"] is None
        assert squat["proposal"] is None


class TestConfirmation:
    def test_a_bare_true_does_not_apply(self):
        log = SetLogger()
        log.log_set("squat", 70, 10, "2026-10-30")
        proposal = log.suggest_next(
            "squat", history(100), AS_OF, rep_top=10, requested_weight=75,
        )["proposal"]
        applied = log.apply(proposal, True)
        assert applied["applied"] is False
        assert "record_confirmation" in applied["message"]

    def test_apply_without_confirmation_does_not_move_the_baseline(self):
        log = SetLogger()
        prior = history(100)
        log.log_set("squat", 70, 10, "2026-10-30")
        proposal = log.suggest_next(
            "squat", prior, AS_OF, rep_top=10, requested_weight=75,
        )["proposal"]
        applied = log.apply(proposal, None)
        assert applied["applied"] is False
        assert "record_confirmation" in applied["message"]
        assert "squat" not in log.working
        log.log_set("squat", 72.5, 10, "2026-10-30")
        held = log.suggest_next("squat", prior, AS_OF, rep_top=10)
        assert held["suggestion"]["weight"] == 72.5
        assert held["suggestion"]["weight"] != 75
        assert held["suggestion"]["weight"] != 77.5
        assert held["proposal"] is None

    def test_a_confirmed_jump_becomes_the_new_baseline(self):
        log = SetLogger()
        log.log_set("squat", 70, 10, "2026-10-30")
        step = log.suggest_next("squat", history(100), AS_OF, rep_top=10)
        assert step["suggestion"]["weight"] == 72.5
        assert step["proposal"] is None
        log.log_set("squat", 72.5, 10, "2026-10-31")
        nxt = log.suggest_next("squat", history(100, hours_ago=24), AS_OF, rep_top=10)
        assert nxt["suggestion"]["weight"] == 75
        assert nxt["proposal"] is None
        proposal = log.suggest_next(
            "squat", history(100), AS_OF, rep_top=10, requested_weight=80,
        )["proposal"]
        applied = log.apply(proposal, confirm(proposal))
        assert applied["applied"] is True
        assert applied["changes"]["weight"] == 77
        assert applied["changes"]["weight"] != 80

    def test_an_edited_proposal_does_not_apply(self):
        log = SetLogger()
        log.log_set("squat", 70, 10, "2026-10-30")
        proposal = log.suggest_next(
            "squat", history(100), AS_OF, rep_top=10, requested_weight=75,
        )["proposal"]
        record = confirm(proposal)
        edited = {
            "summary": proposal["summary"],
            "changes": {"exercise": "squat", "weight": 140, "reps": 10},
            "needs_confirmation": True,
        }
        applied = log.apply(edited, record)
        assert applied["applied"] is False
        assert "squat" not in log.working
