#!/usr/bin/env python3
"""Tests for the first-week builder."""

import json
from pathlib import Path

from plan_builder import PlanBuilder, week_to_confirm
from record_confirmation import hash_plan
from plan_check import PlanValidator
from readiness_screen import (
    ClearanceLevel,
    ReadinessScreen,
    ScreeningResult,
    passing_readiness,
    screening_seal_matches,
    subject_hash,
)
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
    assert screening_seal_matches(screen)
    refused_tie = builder.save(
        plan, yes, path, sessions, check_in_result=check_in, readiness_result=screen,
    )
    assert refused_tie["saved"] is False
    assert not path.exists()
    assert "tied" in refused_tie["message"].lower()
    nameless = {
        "user": {"medical_clearance": False},
        "training": plan["training"],
    }
    nameless_yes = recorded(week_to_confirm(nameless, sessions))
    still_open = builder.save(
        nameless, nameless_yes, path, sessions, check_in_result=check_in, readiness_result=screen,
    )
    assert still_open["saved"] is False
    assert not path.exists()
    assert "tied" in still_open["message"].lower()


def test_save_refuses_a_week_at_load_0(tmp_path):
    builder = PlanBuilder()
    check_in = passing_check_in()
    plan = {
        "user": {"sex": "M", "weight_kg": 80, "age": 30, "height_cm": 180},
        "par_q": {
            **clear_par_q(),
            "source": subject_hash({"sex": "M", "weight_kg": 80, "age": 30, "height_cm": 180}),
        },
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


def test_par_q_records_its_source_and_save_refuses_a_mismatch(tmp_path):
    builder = PlanBuilder()
    check_in = passing_check_in()
    built = builder.propose(profile(), check_in)
    assert built["ok"] is True
    person = built["plan"]["user"]
    assert built["plan"]["par_q"]["source"] == subject_hash(person)
    assert built["plan"]["par_q"]["chest_pain_at_rest"] is False
    path = tmp_path / "week.json"
    yes = recorded(week_to_confirm(built["plan"], built["sessions"]))
    assert _save(builder, built, yes, path, check_in=check_in)["saved"] is True
    stolen = json.loads(json.dumps(built["plan"]))
    stolen["user"]["age"] = 41
    stolen_yes = recorded(week_to_confirm(stolen, built["sessions"]))
    stolen_path = tmp_path / "stolen.json"
    refused = builder.save(
        stolen, stolen_yes, stolen_path, built["sessions"], check_in_result=check_in,
    )
    assert refused["saved"] is False
    assert not stolen_path.exists()
    assert "source" in refused["message"].lower()
    missing = json.loads(json.dumps(built["plan"]))
    del missing["par_q"]["source"]
    missing_yes = recorded(week_to_confirm(missing, built["sessions"]))
    missing_path = tmp_path / "missing.json"
    no_source = builder.save(
        missing, missing_yes, missing_path, built["sessions"], check_in_result=check_in,
    )
    assert no_source["saved"] is False
    assert not missing_path.exists()
    assert "source" in no_source["message"].lower()


def test_a_readiness_result_built_in_code_does_not_pass(tmp_path):
    user = {"sex": "M", "weight_kg": 80, "age": 30, "height_cm": 180}
    forged = ScreeningResult(
        ClearanceLevel.CLEAR,
        ["No risk factors identified."],
        False,
        ["Safe to proceed with program design."],
        subject_hash(user),
    )
    assert forged.issuer_seal == ""
    assert passing_readiness(forged) is False
    forged.issuer_seal = "deadbeef"
    assert screening_seal_matches(forged) is False
    skipped = profile()
    del skipped["par_q"]
    check_in = passing_check_in()
    refused = PlanBuilder().propose(skipped, check_in, readiness_result=forged)
    assert refused["ok"] is False
    assert refused["plan"] is None
    assert "issued" in refused["message"].lower()
    real = screen_for(user)
    assert passing_readiness(real) is True
    real.blocked = True
    assert screening_seal_matches(real) is False
    real.blocked = False
    assert passing_readiness(real) is True
    rebuilt = ScreeningResult(
        real.clearance,
        list(real.reasons),
        real.blocked,
        list(real.recommendations),
        real.subject_hash,
    )
    assert passing_readiness(rebuilt) is False
    path = tmp_path / "forged.json"
    plan = {
        "user": user,
        "training": {
            "previous_load": 100,
            "current_load": 100,
            "weeks_since_deload": 0,
            "structured_hours": 0.75,
            "sport_hours": 0,
        },
    }
    sessions = [{"date": "2026-10-26", "load": 100, "minutes": 45}]
    yes = recorded(week_to_confirm(plan, sessions))
    saved = PlanBuilder().save(
        plan, yes, path, sessions, check_in_result=check_in, readiness_result=forged,
    )
    assert saved["saved"] is False
    assert not path.exists()


def test_three_gym_days_are_a_deterministic_full_body_split():
    person = profile(
        equipment="full gym",
        experience="intermediate",
        minutes=60,
        sport="lifting",
        injuries="none",
    )
    check_in = passing_check_in()
    first = PlanBuilder().propose(person, check_in)
    second = PlanBuilder().propose(person, check_in)
    assert first["ok"] is True
    assert first["sessions"] == second["sessions"]
    assert [row["name"] for row in first["sessions"]] == [
        "Full body A", "Full body B", "Full body C",
    ]
    for row in first["sessions"]:
        assert row["exercises"]
        for exercise in row["exercises"]:
            assert {"name", "sets", "reps", "rest", "effort"} <= set(exercise)
            assert exercise["sets"] == 4
    names = [item["name"] for item in first["sessions"][0]["exercises"]]
    assert "Back squat" in names
    knee = PlanBuilder().propose(profile(equipment="full gym", injuries="left knee"), check_in)
    assert knee["ok"] is True
    knee_names = [item["name"].lower() for item in knee["sessions"][0]["exercises"]]
    assert not any("squat" in name or "lunge" in name for name in knee_names)


def test_a_swapped_exercise_is_not_the_confirmed_week(tmp_path):
    builder = PlanBuilder()
    check_in = passing_check_in()
    built = builder.propose(profile(equipment="full gym", sport="lifting"), check_in)
    path = tmp_path / "week.json"
    yes = recorded(week_to_confirm(built["plan"], built["sessions"]))
    assert _save(builder, built, yes, path, check_in=check_in)["saved"] is True
    swapped = json.loads(json.dumps(built["sessions"]))
    swapped[0]["exercises"][0]["name"] = "Something else"
    refused = _save(builder, built, yes, path, sessions=swapped, check_in=check_in)
    assert refused["saved"] is False
    stored = json.loads(path.read_text(encoding="utf-8"))["sessions"]
    assert stored[0]["exercises"] == built["sessions"][0]["exercises"]


def test_an_adult_cut_gets_calories_protein_and_the_goal():
    check_in = passing_check_in()
    built = PlanBuilder().propose(profile(goal="cut"), check_in)
    assert built["ok"] is True
    nutrition = built["plan"]["nutrition"]
    user = built["plan"]["user"]
    bmr = PlanValidator.estimate_bmr(user["weight_kg"], "M", int(user["age"]), user["height_cm"])
    assert nutrition["calories"] >= PlanValidator.CALORIE_FLOOR_MEN
    assert nutrition["calories"] >= bmr
    per_kg = nutrition["protein_g"] / user["weight_kg"]
    assert PlanValidator.MIN_PROTEIN_G_PER_KG <= per_kg <= PlanValidator.MAX_PROTEIN_G_PER_KG
    assert built["plan"]["goals"]["goal"] == "cut"
    checked = PlanValidator().validate_plan(built["plan"], check_in_result=check_in)
    assert checked.valid, checked.errors
    woman = PlanBuilder().propose(
        profile(sex="F", weight_kg=60, height_cm=165, goal="lose"),
        check_in,
    )
    assert woman["ok"] is True
    assert woman["plan"]["nutrition"]["calories"] >= PlanValidator.CALORIE_FLOOR_WOMEN
    assert woman["plan"]["goals"]["goal"] == "lose"
    assert PlanValidator().validate_plan(woman["plan"], check_in_result=check_in).valid
    gain = PlanBuilder().propose(profile(goal="gain"), check_in)
    assert gain["ok"] is True
    assert gain["plan"]["nutrition"]["calories"] > built["plan"]["nutrition"]["calories"]
    assert gain["plan"]["goals"]["goal"] == "gain"
    assert PlanValidator().validate_plan(gain["plan"], check_in_result=check_in).valid
    held = PlanBuilder().propose(profile(goal="hold"), check_in)
    assert held["ok"] is True
    assert "nutrition" not in held["plan"]
    young = profile(age=16, goal="cut")
    screened = PlanBuilder().propose(young, check_in, readiness_result=screen_for(young))
    assert screened["ok"] is True
    assert "nutrition" not in screened["plan"]


def test_the_saved_week_starts_the_seven_day_clock(tmp_path):
    from datetime import datetime, timedelta, timezone

    from confirmed_change import confirmed_baseline, confirmed_history, parse_utc
    from log_store import LogStore
    from trend_review import TrendReview

    builder = PlanBuilder()
    check_in = passing_check_in()
    built = builder.propose(profile(goal="cut"), check_in)
    path = tmp_path / "week.json"
    yes = recorded(built["confirm"])
    saved = _save(builder, built, yes, path, check_in=check_in)
    assert saved["saved"] is True
    log = LogStore(tmp_path / "log.json")
    record = next(row for row in log.data["confirmations"] if "changes" not in row)
    assert record["plan_hash"] == yes.plan_hash
    assert record["plan_hash"] == hash_plan(built["confirm"])
    assert record["quoted_words"] == "yes"
    assert record["speaker"] == "user"
    assert record["record_id"] == yes.record_id
    assert record["date"].endswith("Z")
    when = parse_utc(record["date"])
    assert when is not None
    history = confirmed_history(log.as_trend(), built["plan"]["user"])
    later = (when + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    earlier = (when + timedelta(days=7) - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    load = built["plan"]["training"]["current_load"]
    calories = built["plan"]["nutrition"]["calories"]
    assert confirmed_baseline(history, "load", later) == load
    assert confirmed_baseline(history, "load", earlier) is None
    assert confirmed_baseline(history, "calories", later) == calories
    assert confirmed_baseline(history, "calories", earlier) is None

    def stamp(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

    start = stamp(earlier).date() - timedelta(days=6)
    sessions = []
    training = []
    for offset in range(8):
        day = (start + timedelta(days=offset)).isoformat()
        sessions.append({"date": day, "load": load, "planned": True, "completed": True})
        training.append({"date": day, "load": load})
    logs = {
        "confirmed_changes": history,
        "sessions": sessions,
        "training": training,
    }
    user = built["plan"]["user"]
    early = TrendReview().review(logs, user, 7, earlier)
    late = TrendReview().review(logs, user, 7, later)
    early_loads = [item for item in early["proposals"] if "load" in item.get("changes", {})]
    late_loads = [item for item in late["proposals"] if "load" in item.get("changes", {})]
    assert early_loads == []
    assert late_loads
    assert late_loads[0]["changes"]["load"] != load


def test_a_failed_week_write_rolls_the_log_back(tmp_path, monkeypatch):
    import os

    import plan_builder
    from log_store import LogStore

    real = plan_builder._write_json

    def boom(path, payload):
        if os.path.basename(path) == "week.json":
            raise OSError("full")
        real(path, payload)

    monkeypatch.setattr(plan_builder, "_write_json", boom)
    builder = PlanBuilder()
    check_in = passing_check_in()
    built = builder.propose(profile(), check_in)
    path = tmp_path / "week.json"
    yes = recorded(week_to_confirm(built["plan"], built["sessions"]))
    refused = _save(builder, built, yes, path, check_in=check_in)
    assert refused["saved"] is False
    assert not path.exists()
    log_path = tmp_path / "log.json"
    assert not log_path.exists()
    LogStore(log_path).append("meals", {"date": "2026-10-30", "calories": 500, "protein_g": 30})
    refused_again = builder.save(
        built["plan"], yes, path, built["sessions"], check_in_result=check_in,
    )
    assert refused_again["saved"] is False
    assert not path.exists()
    kept = LogStore(log_path)
    assert kept.data["confirmations"] == []
    assert kept.data["meals"][0]["calories"] == 500


def test_the_builder_does_not_use_the_log_store_and_the_guide_has_no_em_dash():
    source = (ROOT / "plan_builder.py").read_text(encoding="utf-8")
    guide = (ROOT / "template" / "first-plan.md").read_text(encoding="utf-8")
    assert "A skipped or partial PAR-Q runs readiness_screen before propose()." in guide
    assert "par_q` records `source` as that person's subject_hash" in guide
    assert "save` refuses a `par_q` whose source does not match the user" in guide
    assert "no body details cannot be tied to a readiness screen" in guide
    assert "readiness result built in code does not pass" in guide
    assert "log_store" not in source
    assert "plan_check" in guide
    assert "record_confirmation" in guide
    assert "\u2014" not in source
    assert "\u2014" not in guide
