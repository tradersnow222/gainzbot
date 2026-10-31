#!/usr/bin/env python3
"""Tests for morning_checkin.py."""

from plan_check import PlanValidator
from record_confirmation import ConfirmationRecorder
from red_flag_check import RedFlagChecker, is_passing_check_in
from morning_checkin import MorningCheckIn


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


PUSH = {"sleep": 8, "soreness": 1, "energy": 5, "stress": 1}
NORMAL = {"sleep": 7, "soreness": 3, "energy": 3, "stress": 3}
EASY = {"sleep": 5, "soreness": 2, "energy": 4, "stress": 1}
AS_OF = "2026-10-28"
HISTORY = [{
    "date": "2026-10-21T00:00:00Z",
    "confirmed": True,
    "changes": {"load": 100},
}]


def check(entry, confirmed_changes=None, as_of=AS_OF, planned_load=200, baseline_load=50):
    """Caller planned and baseline values are intentionally not the real baseline."""
    return MorningCheckIn().check_in(
        entry,
        planned_load=planned_load,
        baseline_load=baseline_load,
        confirmed_changes=HISTORY if confirmed_changes is None else confirmed_changes,
        as_of=as_of,
    )


def week():
    return [
        {"date": "2026-10-26", "load": 100},
        {"date": "2026-10-27", "load": 100},
        {"date": "2026-10-28", "load": 100},
        {"date": "2026-10-29", "load": 100},
    ]


class TestDayType:
    def test_a_fresh_morning_is_a_push_inside_the_cap(self):
        result = check(PUSH)
        assert result["day"] == "push"
        assert result["applied"] is False
        assert result["proposal"]["changes"]["load"] == 110
        checked = PlanValidator().validate_training_load_increase(100, 110)
        assert checked.valid

    def test_an_ordinary_morning_keeps_the_load(self):
        result = check(NORMAL)
        assert result["day"] == "normal"
        assert result["proposal"]["changes"]["load"] == 100

    def test_a_short_night_makes_an_easy_day(self):
        result = check(EASY)
        assert result["day"] == "easy"
        assert result["proposal"]["changes"]["load"] == 90

    def test_high_soreness_makes_an_easy_day(self):
        entry = {"sleep": 8, "soreness": 5, "energy": 5, "stress": 1}
        result = check(entry)
        assert result["day"] == "easy"
        assert result["proposal"]["changes"]["load"] <= 100

    def test_a_push_after_a_rewrite_to_110_does_not_propose_121(self):
        rewritten = MorningCheckIn().rewrite_week(week(), "2026-10-27")
        later = [
            item for item in rewritten["proposal"]["changes"]["sessions"]
            if item["date"] > "2026-10-27"
        ]
        assert later
        assert all(item["load"] == 110 for item in later)
        history = [{
            "date": "2026-10-28T00:00:00Z",
            "confirmed": True,
            "changes": {"load": 110},
        }]
        push = check(
            PUSH,
            confirmed_changes=history,
            as_of="2026-10-28T12:00:00Z",
            planned_load=110,
            baseline_load=100,
        )
        assert push["proposal"]["changes"]["load"] == 110
        assert push["proposal"]["changes"]["load"] != 121

    def test_missing_fields_change_nothing(self):
        result = MorningCheckIn().check_in({"sleep": 8}, 100)
        assert result["ok"] is False
        assert result["proposal"] is None
        assert result["applied"] is False

    def test_a_score_outside_1_to_5_is_refused(self):
        entry = {"sleep": 8, "soreness": 9, "energy": 5, "stress": 1}
        result = check(entry)
        assert result["ok"] is False
        assert result["applied"] is False


class TestMissedSession:
    def test_a_missed_session_rewrites_later_days_inside_the_cap(self):
        result = MorningCheckIn().rewrite_week(week(), "2026-10-27")
        assert result["applied"] is False
        sessions = result["proposal"]["changes"]["sessions"]
        by_date = {item["date"]: item for item in sessions}
        assert by_date["2026-10-27"]["missed"] is True
        assert by_date["2026-10-27"]["load"] == 0
        assert by_date["2026-10-26"]["load"] == 100
        assert by_date["2026-10-28"]["load"] == 110
        assert by_date["2026-10-29"]["load"] == 110
        assert result["proposal"]["changes"]["left_out"] == 80
        for item in sessions:
            if not item["missed"]:
                assert item["load"] <= 110

    def test_a_small_miss_still_fits_in_the_week(self):
        sessions = [
            {"date": "2026-10-27", "load": 10},
            {"date": "2026-10-28", "load": 100},
        ]
        result = MorningCheckIn().rewrite_week(sessions, "2026-10-27")
        updated = result["proposal"]["changes"]["sessions"]
        assert updated[1]["load"] == 110
        assert result["proposal"]["changes"]["left_out"] == 0

    def test_an_unknown_session_is_not_rewritten(self):
        result = MorningCheckIn().rewrite_week(week(), "2026-10-30")
        assert result["ok"] is False
        assert result["proposal"] is None


class TestConfirmation:
    def test_check_in_apply_without_confirmation_does_nothing(self):
        proposal = check(PUSH)["proposal"]
        applied = MorningCheckIn().apply(proposal, None)
        assert applied["applied"] is False
        assert applied["changes"] == {}
        assert "record_confirmation" in applied["message"]

    def test_matching_confirmation_applies_the_day(self):
        proposal = check(PUSH)["proposal"]
        applied = MorningCheckIn().apply(proposal, confirm(proposal))
        assert applied["applied"] is True
        assert applied["changes"]["load"] == 110
        assert applied["changes"]["day"] == "push"

    def test_week_rewrite_needs_confirmation(self):
        proposal = MorningCheckIn().rewrite_week(week(), "2026-10-27")["proposal"]
        refused = MorningCheckIn().apply(proposal, None)
        assert refused["applied"] is False
        applied = MorningCheckIn().apply(proposal, confirm(proposal))
        assert applied["applied"] is True
        assert applied["changes"]["left_out"] == 80

    def test_a_different_proposal_is_not_covered(self):
        proposal = check(PUSH)["proposal"]
        record = confirm(proposal)
        edited = {
            "summary": proposal["summary"],
            "changes": {"day": "push", "load": 140},
            "needs_confirmation": True,
        }
        applied = MorningCheckIn().apply(edited, record)
        assert applied["applied"] is False
