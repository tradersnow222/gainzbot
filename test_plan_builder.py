#!/usr/bin/env python3
"""Tests for the first-week builder."""

import json
from pathlib import Path

from plan_builder import PlanBuilder, week_to_confirm
from plan_check import PlanValidator
from readiness_screen import ReadinessScreen
from record_confirmation import ConfirmationRecorder
from red_flag_check import RedFlagChecker, is_passing_check_in


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


def recorded(plan):
    return ConfirmationRecorder().record(plan, "yes", "user", passing_check_in())


def clear_par_q(**overrides):
    answers = {flag: False for flag in ReadinessScreen.PAR_Q_RED_FLAGS}
    answers.update(overrides)
    return answers


def profile(**extra):
    base = {
        "days": ["2026-10-26", "2026-10-28", "2026-10-30"],
        "minutes": 45,
        "equipment": "bodyweight",
        "experience": "beginner",
        "sport": "running",
        "injuries": "none",
        "sex": "M",
        "weight_kg": 80,
        "age": 30,
        "height_cm": 180,
        "par_q": clear_par_q(),
    }
    base.update(extra)
    return base


def screen_for(user, par_q=None, medical_clearance=False):
    intake = {
        "age": user["age"],
        "sex": user["sex"],
        "weight_kg": user["weight_kg"],
        "height_cm": user["height_cm"],
        "par_q": clear_par_q() if par_q is None else par_q,
        "pregnant": False,
        "medical_conditions": [],
        "medical_clearance": medical_clearance,
    }
    if user["age"] < 18:
        intake["parental_consent"] = True
    return ReadinessScreen().screen_intake(intake)


def test_a_beginner_week_passes_and_does_not_raise_the_load():
    built = PlanBuilder().propose(profile(), passing_check_in())
    assert built["ok"] is True
    assert built["applied"] is False
    training = built["plan"]["training"]
    assert training["previous_load"] == 80
    assert training["current_load"] == 80
    assert training["weeks_since_deload"] == 0
    assert training["sport_hours"] == 0
    assert "nutrition" not in built["plan"]
    assert [row["load"] for row in built["sessions"]] == [80, 80, 80]
    assert built["sessions"][0]["equipment"] == "bodyweight"
    assert "note" not in built["sessions"][0]


def test_intermediate_stays_at_100_and_an_injury_does_not_add_load():
    built = PlanBuilder().propose(
        profile(experience="intermediate", injuries="left knee"),
        passing_check_in(),
    )
    assert built["ok"] is True
    assert built["plan"]["training"]["current_load"] == 100
    assert built["plan"]["training"]["previous_load"] == 100
    assert built["sessions"][0]["note"] == "Do not add load."
    assert built["sessions"][0]["load"] == 100


def test_missing_fields_and_a_long_week_are_refused(tmp_path):
    builder = PlanBuilder()
    for broken in (
        profile(sport=""),
        profile(injuries=None),
        profile(equipment=""),
        profile(experience="elite"),
        profile(days=["2026-10-26", "2026-10-26"]),
        profile(days=["Monday", "Wednesday"]),
        profile(minutes=300, days=["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]),
        profile(age=30, sex=None),
    ):
        refused = builder.propose(broken, passing_check_in())
        assert refused["ok"] is False
        assert refused["plan"] is None
        assert refused["sessions"] is None
    path = tmp_path / "week.json"
    assert builder.save(None, None, path)["saved"] is False
    assert not path.exists()


def test_weekday_names_need_a_start_date():
    built = PlanBuilder().propose(
        profile(days=["Monday", "Wednesday"], week_start="2026-10-28"),
        passing_check_in(),
    )
    assert built["ok"] is True
    assert [row["date"] for row in built["sessions"]] == ["2026-10-26", "2026-10-28"]


def _save(builder, built, confirmation, path, sessions=None, check_in=None):
    return builder.save(
        built["plan"],
        confirmation,
        path,
        built["sessions"] if sessions is None else sessions,
        check_in_result=passing_check_in() if check_in is None else check_in,
    )


def test_save_waits_for_a_recorded_yes_and_keeps_other_keys(tmp_path):
    builder = PlanBuilder()
    check_in = passing_check_in()
    built = builder.propose(profile(), check_in)
    path = tmp_path / "week.json"
    path.write_text(json.dumps({"coach": "sam", "plan": {"old": True}}), encoding="utf-8")
    refused = builder.save(built["plan"], None, path, built["sessions"], check_in_result=check_in)
    assert refused["saved"] is False
    assert json.loads(path.read_text(encoding="utf-8"))["plan"] == {"old": True}
    yes = recorded(week_to_confirm(built["plan"], built["sessions"]))
    saved = _save(builder, built, yes, path, check_in=check_in)
    assert saved["saved"] is True
    assert saved["applied"] is False
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["coach"] == "sam"
    assert stored["plan"]["training"]["current_load"] == 80
    raised = [dict(row, load=200) for row in built["sessions"]]
    missed = _save(builder, built, yes, path, sessions=raised, check_in=check_in)
    assert missed["saved"] is False
    assert json.loads(path.read_text(encoding="utf-8"))["sessions"][0]["load"] == 80


def test_a_corrupt_week_file_is_not_overwritten(tmp_path):
    built = PlanBuilder().propose(profile(), passing_check_in())
    path = tmp_path / "week.json"
    path.write_text("{", encoding="utf-8")
    yes = recorded(week_to_confirm(built["plan"], built["sessions"]))
    refused = PlanBuilder().save(
        built["plan"], yes, path, built["sessions"], check_in_result=passing_check_in(),
    )
    assert refused["saved"] is False
    assert path.read_text(encoding="utf-8") == "{"


def test_under_18_needs_a_passing_readiness_screen():
    young = profile(age=16)
    refused = PlanBuilder().propose(young, passing_check_in())
    assert refused["ok"] is False
    assert "readiness" in refused["message"].lower()
    screen = screen_for(young)
    built = PlanBuilder().propose(young, passing_check_in(), readiness_result=screen)
    assert built["ok"] is True
    assert "nutrition" not in built["plan"]
    assert built["plan"]["user"]["age"] == 16
    assert PlanValidator.ADULT_AGE == 18


def test_a_profile_with_no_age_does_not_get_a_week(tmp_path):
    bare = profile()
    for key in ("sex", "weight_kg", "age", "height_cm"):
        del bare[key]
    refused = PlanBuilder().propose(bare, passing_check_in())
    assert refused["ok"] is False
    assert refused["plan"] is None
    assert refused["sessions"] is None
    assert "missing baseline" in refused["message"].lower()
    path = tmp_path / "week.json"
    assert PlanBuilder().save(None, None, path)["saved"] is False
    assert not path.exists()


def test_swapped_sessions_and_an_unchecked_plan_are_not_saved(tmp_path):
    builder = PlanBuilder()
    check_in = passing_check_in()
    built = builder.propose(profile(injuries="left knee"), check_in)
    path = tmp_path / "week.json"
    yes = recorded(week_to_confirm(built["plan"], built["sessions"]))
    assert _save(builder, built, yes, path, check_in=check_in)["saved"] is True
    longer = []
    for index in range(7):
        longer.append({
            "date": f"2026-11-0{index + 1}",
            "load": 80,
            "minutes": 600,
            "equipment": "bodyweight",
            "sport": "running",
            "note": "Do not add load.",
        })
    swapped = _save(builder, built, yes, path, sessions=longer, check_in=check_in)
    assert swapped["saved"] is False
    assert json.loads(path.read_text(encoding="utf-8"))["sessions"][0]["minutes"] == 45
    dropped = [dict(row) for row in built["sessions"]]
    dropped[0].pop("note")
    assert _save(builder, built, yes, path, sessions=dropped, check_in=check_in)["saved"] is False
    assert "note" in json.loads(path.read_text(encoding="utf-8"))["sessions"][0]
    bad_plan = {
        "training": {
            "previous_load": 100,
            "current_load": 200,
            "weeks_since_deload": 0,
            "structured_hours": 1,
            "sport_hours": 0,
        }
    }
    bad_sessions = [{"date": "2026-10-26", "load": 200, "minutes": 45}]
    bad_yes = recorded(week_to_confirm(bad_plan, bad_sessions))
    bad_path = tmp_path / "bad.json"
    refused = builder.save(bad_plan, bad_yes, bad_path, bad_sessions, check_in_result=check_in)
    assert refused["saved"] is False
    assert not bad_path.exists()


def _adult_screen():
    return ReadinessScreen().screen_intake({
        "age": 30,
        "par_q": {flag: False for flag in ReadinessScreen.PAR_Q_RED_FLAGS},
        "pregnant": False,
        "medical_conditions": [],
        "medical_clearance": False,
    })


def test_a_hand_built_plan_with_no_user_is_not_saved(tmp_path):
    builder = PlanBuilder()
    check_in = passing_check_in()
    plan = {
        "training": {
            "previous_load": 100,
            "current_load": 100,
            "weeks_since_deload": 0,
            "structured_hours": 0.75,
            "sport_hours": 0,
        }
    }
    sessions = [{"date": "2026-10-26", "load": 100, "minutes": 45}]
    yes = recorded(week_to_confirm(plan, sessions))
    path = tmp_path / "week.json"
    refused = builder.save(plan, yes, path, sessions, check_in_result=check_in)
    assert refused["saved"] is False
    assert not path.exists()
    assert "missing baseline" in refused["message"].lower()
    screen = _adult_screen()
    assert screen.blocked is False
    allowed = builder.save(
        plan, yes, path, sessions, check_in_result=check_in, readiness_result=screen,
    )
    assert allowed["saved"] is True


def test_save_refuses_a_week_at_load_0(tmp_path):
    builder = PlanBuilder()
    check_in = passing_check_in()
    plan = {
        "user": {"sex": "M", "weight_kg": 80, "age": 30, "height_cm": 180},
        "par_q": clear_par_q(),
        "training": {
            "previous_load": 0,
            "current_load": 0,
            "weeks_since_deload": 0,
            "structured_hours": 0.75,
            "sport_hours": 0,
        },
    }
    sessions = [{"date": "2026-10-26", "load": 0, "minutes": 45}]
    yes = recorded(week_to_confirm(plan, sessions))
    path = tmp_path / "zero.json"
    refused = builder.save(plan, yes, path, sessions, check_in_result=check_in)
    assert refused["saved"] is False
    assert not path.exists()
    assert "baseline" in refused["message"].lower()


def test_an_adult_par_q_yes_is_blocked_in_code():
    yes_flags = {flag: False for flag in ReadinessScreen.PAR_Q_RED_FLAGS}
    yes_flags["chest_pain_at_rest"] = True
    refused = PlanBuilder().propose(profile(par_q=yes_flags), passing_check_in())
    assert refused["ok"] is False
    assert refused["plan"] is None
    assert refused["sessions"] is None
    assert "chest pain" in refused["message"].lower()
    spread = profile()
    spread["chest_pain_during_activity"] = True
    also = PlanBuilder().propose(spread, passing_check_in())
    assert also["ok"] is False
    clear = {flag: False for flag in ReadinessScreen.PAR_Q_RED_FLAGS}
    built = PlanBuilder().propose(profile(par_q=clear), passing_check_in())
    assert built["ok"] is True


def test_a_skipped_or_partial_par_q_needs_readiness(tmp_path):
    builder = PlanBuilder()
    check_in = passing_check_in()
    skipped = profile()
    del skipped["par_q"]
    refused = builder.propose(skipped, check_in)
    assert refused["ok"] is False
    assert refused["plan"] is None
    assert "par-q" in refused["message"].lower()
    assert builder.propose(profile(par_q=None), check_in)["ok"] is False
    partial = builder.propose(profile(par_q={"chest_pain_at_rest": False}), check_in)
    assert partial["ok"] is False
    assert "partial" in partial["message"].lower() or "skipped" in partial["message"].lower()
    screen = screen_for(skipped)
    assert screen.blocked is False
    built = builder.propose(skipped, check_in, readiness_result=screen)
    assert built["ok"] is True
    assert "par_q" not in built["plan"]

    adult = {
        "user": {"sex": "M", "weight_kg": 80, "age": 30, "height_cm": 180},
        "training": {
            "previous_load": 100,
            "current_load": 100,
            "weeks_since_deload": 0,
            "structured_hours": 0.75,
            "sport_hours": 0,
        },
    }
    sessions = [{"date": "2026-10-26", "load": 100, "minutes": 45}]
    yes = recorded(week_to_confirm(adult, sessions))
    path = tmp_path / "adult.json"
    bare = builder.save(adult, yes, path, sessions, check_in_result=check_in)
    assert bare["saved"] is False
    assert not path.exists()
    assert "par-q" in bare["message"].lower()
    other = screen_for({"sex": "F", "weight_kg": 60, "age": 40, "height_cm": 165})
    wrong = builder.save(
        adult, yes, path, sessions, check_in_result=check_in, readiness_result=other,
    )
    assert wrong["saved"] is False
    assert not path.exists()
    assert "different person" in wrong["message"].lower()
    mine = screen_for(adult["user"])
    saved = builder.save(
        adult, yes, path, sessions, check_in_result=check_in, readiness_result=mine,
    )
    assert saved["saved"] is True


def test_a_cleared_par_q_yes_is_allowed(tmp_path):
    flags = clear_par_q(chest_pain_at_rest=True)
    person = profile(par_q=flags)
    screen = screen_for(person, par_q=flags, medical_clearance=True)
    assert screen.blocked is False
    assert screen.clearance.value == "caution"
    check_in = passing_check_in()
    built = PlanBuilder().propose(person, check_in, readiness_result=screen)
    assert built["ok"] is True
    assert built["plan"]["par_q"]["chest_pain_at_rest"] is True
    path = tmp_path / "cleared.json"
    yes = recorded(week_to_confirm(built["plan"], built["sessions"]))
    saved = PlanBuilder().save(
        built["plan"],
        yes,
        path,
        built["sessions"],
        check_in_result=check_in,
        readiness_result=screen,
    )
    assert saved["saved"] is True
    other = screen_for(
        {"sex": "F", "weight_kg": 60, "age": 40, "height_cm": 165},
        par_q=flags,
        medical_clearance=True,
    )
    wrong_path = tmp_path / "other.json"
    wrong = PlanBuilder().save(
        built["plan"],
        yes,
        wrong_path,
        built["sessions"],
        check_in_result=check_in,
        readiness_result=other,
    )
    assert wrong["saved"] is False
    assert not wrong_path.exists()


def test_the_builder_does_not_use_the_log_store_and_the_guide_has_no_em_dash():
    source = (ROOT / "plan_builder.py").read_text(encoding="utf-8")
    guide = (ROOT / "template" / "first-plan.md").read_text(encoding="utf-8")
    assert "A skipped or partial PAR-Q runs readiness_screen before propose()." in guide
    assert "log_store" not in source
    assert "plan_check" in guide
    assert "record_confirmation" in guide
    assert "\u2014" not in source
    assert "\u2014" not in guide
