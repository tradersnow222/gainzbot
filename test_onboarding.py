#!/usr/bin/env python3
"""Locks grouped onboarding questions and the profile fields."""

from pathlib import Path

import pytest

from onboarding import GROUPS, HAPPY_PATH, PAR_Q, _profile, messages, question_one, run_chat
from readiness_screen import ReadinessScreen


ROOT = Path(__file__).resolve().parent


def _labels(**overrides):
    payload = {
        "minor_signal": False,
        "red_flag": "none",
        "injury": "none",
        "note_ok": False,
    }
    payload.update(overrides)
    return payload


def _marked(text, **overrides):
    """A free-text reply plus the host labels the engine is allowed to read."""
    return (text, _labels(**overrides))


def test_questions_go_out_in_a_few_groups():
    sent = messages()
    assert 2 <= len(sent) <= 4
    assert len(sent) == len(GROUPS)
    asked = [name for group in GROUPS for name in group["asks"]]
    for name in (
        "name",
        "sex",
        "age",
        "height",
        "weight",
        "training_days",
        "minutes",
        "equipment",
        "experience",
        "injuries",
        "sport",
        "food_style",
        "goal",
    ):
        assert name in asked
    assert len(asked) == len(set(asked))
    ids = [group["id"] for group in GROUPS]
    assert ids == ["goal", "training", "par_q"]
    assert "one word ok" in sent[0].lower()
    keys = [key for key, _question in PAR_Q]
    assert keys == list(ReadinessScreen.PAR_Q_RED_FLAGS)
    par = next(group for group in GROUPS if group["id"] == "par_q")
    assert list(par["asks"]) == keys
    assert "everyone" in par["text"].lower()
    assert "all no" in par["text"].lower()
    joined = "\n".join(sent).lower()
    assert "one question at a time" not in joined or "not one question at a time" in joined


def test_a_skipped_par_q_answer_runs_readiness_before_training():
    sentence = (
        "A skipped or unclear PAR-Q answer runs readiness_screen, the same as a yes. "
        "There is no training until readiness_screen passes."
    )
    par = next(group for group in GROUPS if group["id"] == "par_q")
    guide = (ROOT / "template" / "onboarding.md").read_text(encoding="utf-8")
    started = (ROOT / "template" / "getting-started.md").read_text(encoding="utf-8")
    assert sentence in par["text"]
    assert sentence in "\n".join(messages())
    assert sentence in guide
    assert sentence in started
    order = "Sport and the schedule come before the PAR-Q. The PAR-Q still comes before any plan is built."
    prompt = (ROOT / "BOT_PROMPT.md").read_text(encoding="utf-8")
    assert order in guide
    assert order in started
    assert order in prompt
    assert "plan_builder" not in "\n".join(messages()).lower() or "before any plan" in "\n".join(messages()).lower()


def test_the_profile_and_guides_match():
    profile = (ROOT / "template" / "profile.md").read_text(encoding="utf-8")
    guide = (ROOT / "template" / "onboarding.md").read_text(encoding="utf-8")
    started = (ROOT / "template" / "getting-started.md").read_text(encoding="utf-8")
    assert "Sport:" in profile
    for label in ("Sex:", "Height:", "Weight:", "Training days:", "Minutes:", "Equipment:", "Experience:", "Injuries:", "Food style:"):
        assert label in profile
    assert "chest_pain_at_rest" in guide
    assert "7" in guide
    assert "one question at a time" in started.lower()
    assert "any sport" in started.lower()
    assert "always ask age" in started.lower()
    assert "plan_builder.py" in started
    assert "each is opt-in" in started.lower()
    for text in (profile, guide, started):
        assert "\u2014" not in text
        assert "signing key" not in text.lower()


def test_question_one_comes_before_any_setup():
    assert question_one() == messages()[0]
    first = run_chat(["hello"])[1][0]
    assert first == question_one()
    lowered = first.lower()
    for word in ("clone", "pip", "pytest", "release_check", "install", "git "):
        assert word not in lowered
    for name in ("BOT_PROMPT.md", "QUICKSTART.md", "template/getting-started.md", "template/onboarding.md"):
        text = (ROOT / name).read_text(encoding="utf-8").lower()
        assert "the first reply asks the first intake question right away" in text
        assert "run setup and release_check in the background, or after intake" in text


def test_a_yes_with_only_a_schedule_edit_confirms_in_the_same_turn():
    from datetime import date, timedelta

    import onboarding
    from onboarding import _profile
    from record_confirmation import is_clear_yes, is_plan_yes
    from red_flag_check import RedFlagChecker
    from routines import first_checkin_day

    proposal_bots = None
    cases = (
        ("yes, morning 6:30", "06:30", "20:00", "Sun 18:00", True),
        ("yes morning 6:30am", "06:30", "20:00", "Sun 18:00", True),
        ("yes, evening 9pm", "07:00", "21:00", "Sun 18:00", True),
        ("yes but no evening one", "07:00", None, "Sun 18:00", False),
        ("yes, review sunday 7pm", "07:00", "20:00", "Sunday 19:00", True),
    )
    for reply, morning, evening, weekly, evening_on in cases:
        assert is_clear_yes(reply) is False, reply
        assert is_plan_yes(reply, "shown-hash") is False, reply
        state, bots = run_chat(list(HAPPY_PATH[:-1]) + [reply])
        assert state["confirmed"] is True, reply
        assert state["record"].confirmed is True, reply
        assert state["turns"] <= 6, reply
        assert len(bots) <= 6, reply
        assert state["answers"]["training_days"] == "3", reply
        assert state["times"]["daily_checkin"] == morning, reply
        assert state["times"]["weekly_review"] == weekly, reply
        assert ("evening_followup" in state["routines_on"]) is evening_on, reply
        if evening_on:
            assert state["times"]["evening_followup"] == evening, reply
            assert "evening" in bots[-1].lower(), reply
        else:
            assert "evening" not in bots[-1].lower(), reply
            assert state["routines_on"] == ["daily_checkin", "weekly_review"], reply
        assert "?" not in bots[-1], reply
        assert "confirm" in bots[-1].lower(), reply
        assert bots[-2].lower().count("yes, morning 6:30") == 1, reply
        assert bots[-2].lower().count("one example") == 1, reply
        proposal_bots = bots[-2]
        days = _profile(state)["days"]
        assert state["first_checkin"] == first_checkin_day(min(days), now=onboarding._now()), reply
        assert state["first_checkin"] == min(days), reply
        assert date.fromisoformat(min(days)) >= onboarding._local_today() + timedelta(days=1), reply
    assert proposal_bots.lower().count("yes, morning 6:30") == 1
    chest = "yes, morning 6:30, but my chest hurts"
    scanned = RedFlagChecker().scan_text(chest)
    assert scanned.pause_plan
    refused, refused_bots = run_chat(list(HAPPY_PATH[:-1]) + [chest])
    assert refused["confirmed"] is False
    assert refused["routines_on"] == []
    assert scanned.message in refused_bots[-1]
    assert "medical emergency" in refused_bots[-1].lower()


def test_an_age_correction_under_18_at_confirm_refuses_the_plan():
    from onboarding import _AGE_ASK

    asked, asked_bots = run_chat(list(HAPPY_PATH[:-1]) + [_marked("wait, I'm actually 15", minor_signal=True)])
    assert asked["confirmed"] is False
    assert asked["answers"].get("age") in (None, "")
    assert asked["record"] is None
    assert asked_bots[-1] == _AGE_ASK
    state, bots = run_chat(list(HAPPY_PATH[:-1]) + [_marked("wait, I'm actually 15", minor_signal=True), "15"])
    assert state["confirmed"] is False
    assert state["answers"]["age"] == "15"
    assert state["record"] is None
    text = bots[-1].lower()
    assert "under 18" in text
    assert "training" in text
    assert "calorie" in text
    assert "protein" in text
    assert "one yes confirms the plan" not in text
    later, later_bots = run_chat(list(HAPPY_PATH[:-1]) + [_marked("wait, I'm actually 15", minor_signal=True), "15", "yes"])
    assert later["confirmed"] is False
    assert later["answers"]["age"] == "15"
    assert later["record"] is None or later["record"].confirmed is False
    assert "training" in later_bots[-1].lower()
    assert "calorie" in later_bots[-1].lower()


_AGE_25 = (
    "hello",
    _marked(
        "hold, male, 80 kg, 180 cm, general training, 3 days 45 min, bodyweight, beginner"
    ),
    "25",
    "all_no",
)


_AGE_HINTS = (
    "actually 16",
    "im 17 not 25",
    "yes, im 15",
    "yes but im 15",
    "I'm 15",
    "i am 15",
    "im 15",
    "15",
    "my age is 15",
    "I lied, im 15",
    "wait, 17",
    "yes, morning 6:30, im 15",
    "im 15 at 6:30",
    "im under 18",
    "not 18 yet",
    "turning 18 next month",
    "fifteen",
    "im fifteen",
    "yes im sixteen",
    "seventeen years old",
    "under eighteen",
    "15yo",
    "15歳",
    "minor",
    "i'm a minor",
    "im in 10th grade",
    "yes \U0001F9D2",
    "yes \U0001F476",
    "yes kid",
    "yes im a kid",
    "yes im young",
    "yes, my son",
)


@pytest.mark.parametrize("reply", _AGE_HINTS)
def test_an_age_hint_at_confirm_asks_and_never_confirms(reply):
    from onboarding import _AGE_ASK, _hints_age

    assert _hints_age(reply), reply
    state, bots = run_chat(list(_AGE_25) + [_marked(reply, minor_signal=True)])
    assert state["confirmed"] is False, reply
    assert state["record"] is None, reply
    assert bots[-1] == _AGE_ASK, reply
    assert "one yes confirms the plan" not in bots[-1].lower(), reply
    later, later_bots = run_chat(list(_AGE_25) + [_marked(reply, minor_signal=True), "yes"])
    assert later["confirmed"] is False, reply
    assert later_bots[-1] == _AGE_ASK, reply


@pytest.mark.parametrize("reply", _AGE_HINTS)
def test_readiness_runs_on_the_typed_age_not_the_hint(reply):
    state, bots = run_chat(list(_AGE_25) + [_marked(reply, minor_signal=True), "15"])
    assert state["confirmed"] is False, reply
    assert state["answers"]["age"] == "15", reply
    assert state["record"] is None, reply
    text = bots[-1].lower()
    assert "under 18" in text, reply
    assert "training" in text, reply
    assert "calorie" in text, reply
    assert "protein" in text, reply
    assert "one yes confirms the plan" not in text, reply
    later, later_bots = run_chat(list(_AGE_25) + [_marked(reply, minor_signal=True), "15", "yes"])
    assert later["confirmed"] is False, reply
    assert later["answers"]["age"] == "15", reply
    assert "calorie" in later_bots[-1].lower(), reply
    assert "protein" in later_bots[-1].lower(), reply


def test_a_schedule_clock_is_not_read_as_an_age():
    from onboarding import _AGE_ASK

    morning, morning_bots = run_chat(list(_AGE_25) + ["yes, morning 6:30"])
    assert morning["confirmed"] is True
    assert morning["answers"]["age"] == "25"
    assert morning["times"]["daily_checkin"] == "06:30"
    assert _AGE_ASK not in morning_bots[-1]
    at_seven, at_bots = run_chat(list(_AGE_25) + ["at 7"])
    assert at_seven["confirmed"] is False
    assert at_seven["answers"]["age"] == "25"
    assert at_bots[-1] != _AGE_ASK
    assert "one check on that message" in at_bots[-1].lower()
    typed, typed_bots = run_chat(list(_AGE_25) + ["at 7", "25"])
    assert typed["confirmed"] is False
    assert typed["answers"]["age"] == "25"
    assert typed["phase"] == "symptom"
    assert "one yes confirms the plan" not in typed_bots[-1].lower()
    _drop_hold()
    evening, evening_bots = run_chat(list(_AGE_25) + ["yes, evening 9pm"])
    assert evening["confirmed"] is True
    assert evening["answers"]["age"] == "25"
    assert evening["times"]["evening_followup"] == "21:00"
    assert _AGE_ASK not in evening_bots[-1]
    review, review_bots = run_chat(list(_AGE_25) + ["yes, review sunday 7pm"])
    assert review["confirmed"] is True
    assert review["answers"]["age"] == "25"
    assert "19:00" in review["times"]["weekly_review"]
    assert _AGE_ASK not in review_bots[-1]


def test_a_weight_correction_at_confirm_reproposes():
    from onboarding import _AGE_ASK

    for reply in ("wait my weight is 60 kg", "actually 60 kg"):
        state, bots = run_chat(list(_AGE_25) + [reply])
        assert state["confirmed"] is False, reply
        assert state["answers"]["weight"] == "60 kg", reply
        assert state["answers"]["age"] == "25", reply
        assert "one yes confirms the plan" in bots[-1].lower(), reply
        assert _AGE_ASK not in bots[-1], reply
        done, _bots = run_chat(list(_AGE_25) + [reply, "yes"])
        assert done["confirmed"] is True, reply
        assert _profile(done)["weight_kg"] == 60, reply


def test_a_typed_adult_age_shows_the_plan_again():
    state, bots = run_chat(list(_AGE_25) + [_marked("minor", minor_signal=True), "26"])
    assert state["confirmed"] is False
    assert state["answers"]["age"] == "26"
    assert "one yes confirms the plan" in bots[-1].lower()
    assert "How old are you?" not in bots[-1]
    done, _bots = run_chat(list(_AGE_25) + [_marked("minor", minor_signal=True), "26", "yes"])
    assert done["confirmed"] is True
    assert done["answers"]["age"] == "26"


@pytest.mark.parametrize("reply", [
    "29.9 kg",
    "300.1 kg",
    "actually 29.9 kg",
    "wait my weight is 300.1 kg",
])
def test_an_out_of_range_weight_asks_for_weight_not_age(reply):
    from onboarding import _AGE_ASK, _WEIGHT_ASK

    state, bots = run_chat(list(_AGE_25) + [reply])
    assert state["confirmed"] is False, reply
    assert state["answers"]["weight"] == "80 kg", reply
    assert state["answers"]["age"] == "25", reply
    assert bots[-1] == _WEIGHT_ASK, reply
    assert _AGE_ASK not in bots[-1], reply
    later, later_bots = run_chat(list(_AGE_25) + [reply, "yes"])
    assert later["confirmed"] is False, reply
    assert later["answers"]["age"] == "25", reply
    assert later_bots[-1] == _WEIGHT_ASK, reply
    assert "How old are you?" not in later_bots[-1], reply


def test_a_weight_outside_30_to_300_asks_again():
    from onboarding import _WEIGHT_ASK

    state, bots = run_chat(list(_AGE_25) + ["actually 20 kg"])
    assert state["confirmed"] is False
    assert state["answers"]["weight"] == "80 kg"
    assert state["answers"]["age"] == "25"
    assert bots[-1] == _WEIGHT_ASK
    still, still_bots = run_chat(list(_AGE_25) + ["actually 20 kg", "yes"])
    assert still["confirmed"] is False
    assert still["answers"]["weight"] == "80 kg"
    assert still_bots[-1] == _WEIGHT_ASK
    fixed, fixed_bots = run_chat(list(_AGE_25) + ["actually 20 kg", "60"])
    assert fixed["confirmed"] is False
    assert fixed["answers"]["weight"] == "60 kg"
    assert "one yes confirms the plan" in fixed_bots[-1].lower()
    low, low_bots = run_chat([
        "hello",
        _marked("hold, male, 20 kg, 180 cm"),
    ])
    assert low["answers"].get("weight") != "20 kg"
    assert low["answers"].get("age") in (None, "")
    assert low_bots[-1] == _WEIGHT_ASK
    high, high_bots = run_chat(list(_AGE_25) + ["wait my weight is 301 kg"])
    assert high["answers"]["weight"] == "80 kg"
    assert high["confirmed"] is False
    assert high_bots[-1] == _WEIGHT_ASK


@pytest.mark.parametrize("reply", [
    "im 15 and dizzy",
    "yes, im 15, chest pain",
    "yes \U0001F9D2 my chest hurts",
    "my chest hurts",
    "yes, chest pain",
    "yes \U0001F915 im 15",
])
def test_a_pause_at_confirm_leaves_and_a_later_yes_cannot_confirm(reply):
    from record_confirmation import reply_pause

    state, bots = run_chat(list(_AGE_25) + [reply])
    assert state["confirmed"] is False, reply
    assert state["phase"] != "confirm", reply
    assert state["record"] is None, reply
    assert state["answers"]["age"] == "25", reply
    assert "one yes confirms the plan" not in bots[-1].lower(), reply
    paused = reply_pause(reply)
    if paused is not None:
        assert paused.message in bots[-1], reply
        assert state["phase"] == "symptom", reply
    later, later_bots = run_chat(list(_AGE_25) + [reply, "yes"])
    assert later["confirmed"] is False, reply
    assert later["phase"] != "confirm", reply
    assert later["answers"]["age"] == "25", reply
    assert later["record"] is None or later["record"].confirmed is False, reply
    assert "one yes confirms the plan" not in later_bots[-1].lower(), reply


@pytest.mark.parametrize("replies", [
    ["im 15 and dizzy", "25", "yes"],
    ["yes, im 15, chest pain", "25", "yes"],
    ["yes \U0001F9D2 my chest hurts", "30", "yes"],
    ["my chest hurts", "no", "yes"],
    ["my chest hurts", "nope", "yes"],
    ["my chest hurts", "no, 7, 2", "yes"],
])
def test_a_symptom_ends_onboarding_for_the_day(replies):
    state, bots = run_chat(list(_AGE_25) + replies)
    assert state["confirmed"] is False, replies
    assert state["phase"] == "symptom", replies
    assert state["record"] is None or state["record"].confirmed is False, replies
    for bot in bots[-len(replies):]:
        assert "one yes confirms the plan" not in bot.lower(), replies
    assert "tomorrow" in bots[-len(replies)].lower(), replies
    assert "tomorrow" in bots[-1].lower(), replies


def test_a_minor_age_during_a_symptom_hold_blocks_and_does_not_resume():
    state, bots = run_chat(list(_AGE_25) + ["im 15 and dizzy", "15", "yes"])
    assert state["confirmed"] is False
    assert state["answers"]["age"] == "25"
    assert state["phase"] == "symptom"
    assert "calorie" in bots[-2].lower()
    assert "protein" in bots[-2].lower()
    assert "tomorrow" in bots[-2].lower()
    assert "tomorrow" in bots[-1].lower()
    assert "one yes confirms the plan" not in bots[-1].lower()
    assert "one yes confirms the plan" not in bots[-2].lower()


def test_a_new_conversation_the_same_day_cannot_confirm_over_a_hold():
    import os

    import onboarding

    first, first_bots = run_chat(list(_AGE_25) + ["my chest hurts"])
    assert first["confirmed"] is False
    assert "medical emergency" in first_bots[-1].lower()
    path = onboarding.onboarding_state_path()
    assert os.path.isfile(path)
    second, second_bots = run_chat(list(_AGE_25) + ["yes"])
    assert second["confirmed"] is False
    assert second["phase"] == "symptom"
    assert second["record"] is None or second["record"].confirmed is False
    assert "one yes confirms the plan" not in " ".join(second_bots).lower()
    third, third_bots = run_chat(HAPPY_PATH)
    assert third["confirmed"] is False
    assert third["phase"] == "symptom"
    assert "one yes confirms the plan" not in " ".join(third_bots).lower()
    assert os.path.isfile(path)


def test_the_next_day_starts_at_the_red_flag_check(monkeypatch):
    import os
    from datetime import datetime, timedelta, timezone

    import onboarding

    start = datetime(2026, 10, 31, 16, 0, tzinfo=timezone.utc)
    clock = {"now": start}
    monkeypatch.setattr(onboarding, "_now", lambda: clock["now"])
    monkeypatch.setattr(onboarding, "_default_timezone_name", lambda: "America/Los_Angeles")
    state, bots = run_chat(list(_AGE_25) + ["my chest hurts"])
    assert state["confirmed"] is False
    assert "tomorrow" in bots[-1].lower()
    assert "medical emergency" in bots[-1].lower()
    same, same_bots = run_chat(["yes"])
    assert same["confirmed"] is False
    assert same["phase"] == "symptom"
    assert "tomorrow" in same_bots[-1].lower()
    assert "one yes confirms the plan" not in same_bots[-1].lower()
    clock["now"] = start + timedelta(days=1)
    opened, opened_bots = run_chat(["hello"])
    assert opened["confirmed"] is False
    assert opened["phase"] != "confirm"
    assert opened["par_q"] == {}
    assert opened.get("readiness") is None
    assert "PAR-Q" in opened_bots[0]
    assert "all no" in opened_bots[0].lower()
    assert "one yes confirms the plan" not in opened_bots[0].lower()
    assert "tomorrow" not in opened_bots[0].lower()
    done, done_bots = run_chat(["all_no", "yes"])
    assert done["readiness"] is not None
    assert "one yes confirms the plan" in done_bots[0].lower()
    assert done["confirmed"] is True
    assert os.path.isfile(onboarding.onboarding_state_path())


@pytest.mark.parametrize("raw", [
    "{",
    "[]",
    "null",
    "garbage",
    '{"hold": "nope"}',
    '{"nope": true}',
    '{"timezone": "America/Los_Angeles", "answers": {"timezone": "America/Los_Angeles", "age": "30"}, "checks_again": true, "hold": {"date": "2099-01-01", "message": "later"}}',
])
def test_a_corrupt_or_future_dated_hold_blocks(raw):
    import os

    import onboarding

    path = onboarding.onboarding_state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(raw)
    state, bots = run_chat(HAPPY_PATH)
    assert state["confirmed"] is False
    assert state["phase"] == "symptom"
    assert "one yes confirms the plan" not in " ".join(bots).lower()
    assert os.path.isfile(path)


def test_an_unreadable_hold_blocks(monkeypatch):
    import os

    import onboarding

    path = onboarding.onboarding_state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write('{"hold": {"date": "2026-10-31", "message": "rest"}}\n')
    real_open = open

    def guarded(file, *args, **kwargs):
        target = file if isinstance(file, (str, bytes)) else getattr(file, "name", None)
        mode = args[0] if args else kwargs.get("mode", "r")
        if (
            target is not None
            and os.path.abspath(str(target)) == os.path.abspath(path)
            and "r" in str(mode)
            and "w" not in str(mode)
            and "+" not in str(mode)
        ):
            raise OSError("blocked")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", guarded)
    state, bots = run_chat(HAPPY_PATH)
    assert state["confirmed"] is False
    assert "one yes confirms the plan" not in " ".join(bots).lower()


def test_a_failed_hold_write_returns_an_error_and_does_not_continue(monkeypatch):
    import os

    import onboarding

    real_replace = os.replace

    def blocked(src, dst):
        if str(dst).endswith("onboarding_state.json"):
            raise OSError("blocked")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", blocked)
    state, bots = run_chat(list(_AGE_25) + ["my chest hurts", "yes"])
    assert state["confirmed"] is False
    assert state["phase"] == "symptom"
    assert state["record"] is None or state["record"].confirmed is False
    assert "could not be saved" in bots[-2].lower()
    assert "stop" in bots[-2].lower()
    assert "one yes confirms the plan" not in bots[-2].lower()
    assert "one yes confirms the plan" not in bots[-1].lower()
    assert "onboarding does not continue" in bots[-1].lower()
    again, again_bots = run_chat(HAPPY_PATH)
    assert again["confirmed"] is False
    assert again["phase"] == "symptom"
    assert "one yes confirms the plan" not in " ".join(again_bots).lower()


def test_a_read_only_data_dir_with_an_expired_hold_still_refuses():
    import json
    import os

    import onboarding

    path = onboarding.onboarding_state_path()
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    expired = {
        "hold": {"date": "2000-01-01", "message": "old"},
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(expired, handle)
        handle.write("\n")
    os.chmod(directory, 0o555)
    try:
        state, bots = run_chat(list(_AGE_25) + ["my chest hurts"])
        assert state["confirmed"] is False
        assert "hold could not be saved" in bots[-1].lower()
        kept = json.loads(open(path, encoding="utf-8").read())
        assert kept["hold"]["date"] == "2000-01-01"
        again, again_bots = run_chat(["yes"])
        assert again["confirmed"] is False
        assert again["phase"] == "symptom"
        assert "one yes confirms the plan" not in " ".join(again_bots).lower()
    finally:
        os.chmod(directory, 0o755)


def test_four_fifty_nine_pm_pdt_to_five_pm_stays_held(monkeypatch):
    import json
    import os
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    import onboarding

    # 4:59 PM PDT is still 31 Oct UTC. 5:00 PM PDT is 1 Nov UTC.
    early = datetime(2026, 10, 31, 23, 59, tzinfo=timezone.utc)
    late = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
    pacific = ZoneInfo("America/Los_Angeles")
    assert early.astimezone(pacific).hour == 16
    assert early.astimezone(pacific).minute == 59
    assert late.astimezone(pacific).hour == 17
    assert late.astimezone(pacific).date().isoformat() == "2026-10-31"
    assert late.date().isoformat() == "2026-11-01"
    clock = {"now": early}
    monkeypatch.setattr(onboarding, "_now", lambda: clock["now"])
    monkeypatch.setattr(onboarding, "_default_timezone_name", lambda: "America/Los_Angeles")
    state, bots = run_chat(list(_AGE_25) + ["my chest hurts"])
    assert state["confirmed"] is False
    assert "tomorrow" in bots[-1].lower()
    path = onboarding.onboarding_state_path()
    saved = json.loads(open(path, encoding="utf-8").read())
    assert saved["hold"]["date"] == "2026-10-31"
    assert saved["timezone"] == "America/Los_Angeles"
    assert saved["answers"]["timezone"] == "America/Los_Angeles"
    clock["now"] = late
    later, later_bots = run_chat(HAPPY_PATH)
    assert later["confirmed"] is False
    assert later["phase"] == "symptom"
    assert "one yes confirms the plan" not in " ".join(later_bots).lower()
    assert os.path.isfile(path)
    kept = json.loads(open(path, encoding="utf-8").read())
    assert kept["hold"]["date"] == "2026-10-31"


def test_real_now_with_a_fixed_offset_stays_held_from_459_to_500(monkeypatch, tmp_path):
    import json
    import os
    import time
    from datetime import datetime, timedelta, timezone

    import onboarding

    pdt = timezone(timedelta(hours=-7))
    early = datetime(2026, 10, 31, 16, 59, tzinfo=pdt)
    late = datetime(2026, 10, 31, 17, 0, tzinfo=pdt)
    assert getattr(early.tzinfo, "key", None) is None
    assert early.astimezone(timezone.utc).date().isoformat() == "2026-10-31"
    assert late.astimezone(timezone.utc).date().isoformat() == "2026-11-01"
    monkeypatch.setattr(onboarding, "_LOCALTIME_PATH", str(tmp_path / "no-localtime"))
    monkeypatch.setattr(onboarding, "_TIMEZONE_FILE", str(tmp_path / "no-timezone"))
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "<-07>7"
    time.tzset()

    class _Clock(datetime):
        instant = early

        @classmethod
        def now(cls, tz=None):
            current = cls.instant
            if tz is not None:
                return current.astimezone(tz)
            return cls(
                current.year, current.month, current.day,
                current.hour, current.minute, current.second,
            )

    try:
        monkeypatch.setattr(onboarding, "datetime", _Clock)
        assert onboarding._now().utcoffset() == timedelta(hours=-7)
        assert onboarding._default_timezone_name() == "-07:00"
        assert onboarding._now().astimezone().date().isoformat() == "2026-10-31"
        state, bots = run_chat(list(_AGE_25) + ["my chest hurts"])
        assert state["confirmed"] is False
        assert "tomorrow" in bots[-1].lower()
        saved = json.loads(open(onboarding.onboarding_state_path(), encoding="utf-8").read())
        assert saved["hold"]["date"] == "2026-10-31"
        assert saved["timezone"] == "-07:00"
        assert saved["timezone"] != "UTC"
        _Clock.instant = late
        assert onboarding._now().astimezone().date().isoformat() == "2026-10-31"
        later, later_bots = run_chat(["yes"])
        assert later["confirmed"] is False
        assert later["phase"] == "symptom"
        assert "one yes confirms the plan" not in " ".join(later_bots).lower()
        kept = json.loads(open(onboarding.onboarding_state_path(), encoding="utf-8").read())
        assert kept["hold"]["date"] == "2026-10-31"
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()


def test_clear_hold_needs_the_date_for_a_future_or_corrupt_file():
    import json
    import os

    import onboarding

    path = onboarding.onboarding_state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    future = {
        "timezone": "-07:00",
        "answers": {"age": "30", "timezone": "-07:00"},
        "checks_again": True,
        "hold": {"date": "2099-01-01", "message": "later"},
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(future, handle)
    assert "2099-01-01" in onboarding.clear_hold("2026-10-31")
    assert os.path.isfile(path)
    refused, refused_bots = run_chat(HAPPY_PATH)
    assert refused["confirmed"] is False
    assert "one yes confirms the plan" not in " ".join(refused_bots).lower()
    assert onboarding.clear_hold("clear_hold 2099-01-01") == "The hold is cleared."
    assert not os.path.isfile(path)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("garbage")
    blocked, blocked_bots = run_chat(HAPPY_PATH)
    assert blocked["confirmed"] is False
    assert "one yes confirms the plan" not in " ".join(blocked_bots).lower()
    today = onboarding._local_today().isoformat()
    assert today in onboarding.clear_hold("nope")
    assert os.path.isfile(path)
    assert onboarding.clear_hold(today) == "The hold is cleared."
    assert not os.path.isfile(path)
    done, _done_bots = run_chat(HAPPY_PATH)
    assert done["confirmed"] is True


def test_clear_hold_leaves_a_hold_dated_today():
    import json
    import os

    import onboarding

    run_chat(list(_AGE_25) + ["my chest hurts"])
    path = onboarding.onboarding_state_path()
    saved = json.loads(open(path, encoding="utf-8").read())
    answer = onboarding.clear_hold(saved["hold"]["date"])
    assert "not cleared" in answer.lower()
    assert os.path.isfile(path)
    later, later_bots = run_chat(["yes"])
    assert later["confirmed"] is False
    assert "one yes confirms the plan" not in " ".join(later_bots).lower()


def test_save_refuses_while_a_hold_dated_today_exists(tmp_path):
    from plan_builder import PlanBuilder

    run_chat(list(_AGE_25) + ["my chest hurts"])
    saved = PlanBuilder().save({}, None, tmp_path / "week.json", [])
    assert saved["saved"] is False
    assert "held" in saved["message"].lower()
    assert "not saved" in saved["message"].lower()


def test_an_unknown_confirm_reply_asks_for_age_and_does_not_confirm():
    state, bots = run_chat(list(_AGE_25) + ["sounds maybe"])
    assert state["confirmed"] is False
    assert state["answers"]["age"] == "25"
    assert state["record"] is None
    assert "one check on that message" in bots[-1].lower()
    assert "one yes confirms the plan" not in bots[-1].lower()
    later, later_bots = run_chat(list(_AGE_25) + ["sounds maybe", "yes"])
    assert later["confirmed"] is False
    assert later["phase"] == "symptom"
    assert later["answers"]["age"] == "25"
    assert "one yes confirms the plan" not in later_bots[-1].lower()
    _drop_hold()
    refused, refused_bots = run_chat(
        list(_AGE_25) + [_marked("sounds maybe", minor_signal=True), "15"]
    )
    assert refused["confirmed"] is False
    assert refused["answers"]["age"] == "15"
    assert "under 18" in refused_bots[-1].lower()
    assert "calorie" in refused_bots[-1].lower()


def test_the_onboarding_first_plan_record_saves(tmp_path):
    from onboarding import _check_in, _profile
    from plan_builder import PlanBuilder

    state, _bots = run_chat(HAPPY_PATH)
    assert state["confirmed"] is True
    assert state["record"].confirmed is True
    profile = _profile(state)
    check_in = _check_in(state)
    built = PlanBuilder().propose(
        profile, check_in, readiness_result=state["readiness"],
    )
    assert built["ok"] is True, built.get("message")
    saved = PlanBuilder().save(
        built["plan"],
        state["record"],
        tmp_path / "week.json",
        built["sessions"],
        check_in_result=check_in,
        readiness_result=state["readiness"],
    )
    assert saved["saved"] is True, saved.get("message")
    assert "record_confirmation" not in saved["message"]


def test_make_it_4_days_at_confirm_updates_the_profile_and_reproposes():
    state, bots = run_chat(list(HAPPY_PATH[:-1]) + ["make it 4 days"])
    assert state["confirmed"] is False
    assert state["answers"]["training_days"] == "4"
    assert len(state["answers"]["days"]) == 4
    assert "4 days" in bots[-1]
    assert "one yes confirms the plan" in bots[-1].lower()
    done, _bots = run_chat(list(HAPPY_PATH[:-1]) + ["make it 4 days", "yes"])
    assert done["confirmed"] is True
    assert done["answers"]["training_days"] == "4"
    assert len(done["record"].plan_hash) > 0


def test_happy_path_confirms_in_five_bot_turns_or_fewer():
    state, bots = run_chat(HAPPY_PATH)
    assert state["confirmed"] is True
    assert state["record"].confirmed is True
    assert state["routines_on"] == ["daily_checkin", "evening_followup", "weekly_review"]
    assert state["times"]["daily_checkin"] == "07:00"
    assert state["times"]["evening_followup"] == "20:00"
    assert state["times"]["weekly_review"] == "Sun 18:00"
    assert state["turns"] == len(bots)
    assert len(bots) <= 5
    assert bots[0] == question_one()
    assert sum("one yes confirms the plan" in turn.lower() for turn in bots) == 1
    assert "each is opt-in" in bots[-2].lower()
    assert "?" not in bots[-1]
    assert "confirm" in bots[-1].lower()


def test_answers_in_any_order_are_kept_and_only_the_gap_is_asked():
    training = _marked("running, 4 days, 40 min, dumbbells, beginner")
    state, bots = run_chat([training])
    assert state["answers"]["sport"] == "running"
    assert state["answers"]["equipment"] == "dumbbells"
    assert state["answers"]["injuries"] == "none"
    assert "weight" in bots[0].lower()
    assert "par-q" not in bots[0].lower()
    done, later = run_chat([
        training,
        _marked("hold, male, 80 kg, 180 cm"),
        "30",
        "all_no",
        "yes",
    ])
    assert done["confirmed"] is True
    assert len(later) <= 6


def test_everything_at_once_skips_questions_already_answered():
    blob = _marked(
        "hold, male, 80 kg, 180 cm, target 80 kg, "
        "general training, 3 days, 45 min, bodyweight, beginner"
    )
    asked, asked_bots = run_chat([blob])
    assert asked["answers"].get("age") in (None, "")
    assert asked["answers"]["injuries"] == "none"
    assert asked_bots[-1] == "How old are you? Please type the number."
    state, bots = run_chat([blob, "30", "yes"])
    assert state["confirmed"] is False
    assert state["answers"]["goal"] == "hold"
    assert state["answers"]["sex"] == "male"
    assert state["answers"]["age"] == "30"
    assert state["answers"]["weight"] == "80 kg"
    assert state["answers"]["height"] == "180 cm"
    assert state["answers"]["sport"] == "general training"
    assert state["answers"]["training_days"] == "3"
    assert state["par_q"] == {}
    assert "one yes confirms the plan" not in bots[-1].lower()
    done, later = run_chat([blob, "30", "all_no", "yes"])
    assert done["confirmed"] is True
    assert len(done["par_q"]) == len(PAR_Q)
    assert all(value is False for value in done["par_q"].values())
    assert "confirm" in later[-1].lower()


def test_a_named_injury_stays_and_the_plan_keeps_weight_off_it():
    back_line = "I kept weight off your lower back. Check with your doctor or a physio before loading it."
    ham_line = "I kept weight off your hamstring. Check with your doctor or a physio before loading it."
    back, bots = run_chat([
        _marked("hold, male, 80 kg, 180 cm, lower back pain", injury="unclear"),
        "old",
        "30",
        "ok",
        "all_no",
        "yes",
    ])
    assert back["confirmed"] is True
    assert back["answers"]["injuries"] == "lower back"
    assert "\n".join(bots).count(back_line) == 1
    for row in back["sessions"]:
        names = " ".join(item["name"].lower() for item in row["exercises"])
        assert "romanian" not in names
        assert "deadlift" not in names
        assert "rdl" not in names
        assert "hip hinge" not in names
        assert "nordic" not in names
    ham, ham_bots = run_chat([
        _marked("hold, male, 80 kg, 180 cm, hamstring injury", injury="old"),
        "30",
        "ok",
        "all_no",
        "yes",
    ])
    assert ham["confirmed"] is True
    assert ham["answers"]["injuries"] == "hamstring"
    assert "\n".join(ham_bots).count(ham_line) == 1
    for row in ham["sessions"]:
        names = " ".join(item["name"].lower() for item in row["exercises"])
        assert "romanian" not in names
        assert "deadlift" not in names
        assert "rdl" not in names
        assert "hip hinge" not in names
        assert "nordic" not in names
    for word in ("ok", "fine", "yes"):
        state, _bots = run_chat(["hold, male, 80 kg, 180 cm", "30", word])
        assert state["answers"].get("injuries") in (None, ""), word
        assert state["confirmed"] is False
    for word in ("no", "none", "nope", "no injuries"):
        state, _bots = run_chat(["hold, male, 80 kg, 180 cm", "30", word])
        assert state["answers"]["injuries"] == "none", word


def test_ok_does_not_invent_age_sex_weight_or_height():
    state, bots = run_chat(["hello", "cut", "ok", "ok", "all no", "yes"])
    assert state["confirmed"] is False
    assert state["answers"].get("goal") == "cut"
    for key in ("age", "sex", "weight", "height"):
        assert state["answers"].get(key) in (None, "")
    assert "1780" not in "\n".join(bots)
    assert all("kcal" not in turn.lower() for turn in bots)
    _drop_hold()
    goal_only, _turns = run_chat(["hello", "ok"])
    assert goal_only["confirmed"] is False
    assert goal_only["answers"].get("goal") == "hold"
    for key in ("age", "sex", "weight", "height"):
        assert key not in goal_only["answers"]
    plain, _turns = run_chat(["hello", "ok fine"])
    assert plain["confirmed"] is False
    assert "age" not in plain["answers"]
    confirmed, turns = run_chat(list(HAPPY_PATH[:-1]) + ["ok"])
    assert confirmed["confirmed"] is True
    finer, _turns = run_chat(list(HAPPY_PATH[:-1]) + ["ok fine"])
    assert finer["confirmed"] is True
    assert "confirm" in turns[-1].lower()


def test_par_q_answers_are_kept_and_a_mixed_reply_asks_only_the_gap():
    from onboarding import PAR_Q, _blank, _check_in
    from red_flag_check import is_passing_check_in

    body = [
        _marked("hold, male, 80 kg, 180 cm, general training, 3 days 45 min, bodyweight, beginner"),
        "30",
    ]
    skipped, skip_bots = run_chat(body + ["skip", "yes"])
    assert skipped["confirmed"] is False
    assert skipped.get("par_q_skipped") is True
    assert skipped["par_q"] == {}
    assert skip_bots[-2].startswith("Still need a yes or no:")
    assert skip_bots[-2].count("\n") == 0
    assert "one yes confirms the plan" not in skip_bots[-1].lower()
    mixed, _mixed_bots = run_chat(body + ["joint problem yes, medications no"])
    assert mixed["confirmed"] is False
    assert mixed["par_q"] == {}
    from onboarding import submit_par_q

    reached, _reached_bots = run_chat(body)
    assert reached["asked"] == "par_q"
    choice = {key: False for key, _question in PAR_Q}
    choice["bone_joint_problem_worsened_by_activity"] = True
    choice["currently_taking_medications"] = False
    assert submit_par_q(reached, choice) is True
    assert reached["par_q"]["bone_joint_problem_worsened_by_activity"] is True
    assert reached["par_q"]["currently_taking_medications"] is False
    invented = _blank()
    invented["par_q_reply"] = "all no"
    invented["par_q"] = {key: False for key, _question in PAR_Q}
    sealed = _check_in(invented)
    assert is_passing_check_in(sealed)
    blob = sealed.message + " ".join(sealed.recommendations)
    assert "Easy lift, slept fine." not in blob
    fake = _blank()
    fake["par_q_reply"] = "not all no, chest pain yes"
    fake["par_q"] = {key: False for key, _question in PAR_Q}
    refused = _check_in(fake)
    assert not is_passing_check_in(refused)
    negated, neg_bots = run_chat(body + ["not all no, chest pain yes", "yes"])
    assert negated["confirmed"] is False
    assert negated["phase"] == "symptom"
    assert "medical emergency" in neg_bots[-1].lower()
    assert "one yes confirms the plan" not in neg_bots[-1].lower()


def test_all_no_counts_only_when_the_whole_reply_is_that_phrase():
    body = [
        _marked("hold, male, 80 kg, 180 cm, general training, 3 days 45 min, bodyweight, beginner"),
        "30",
    ]
    unclear = (
        "all no except chest pain",
        "all no except joint problem",
        "all no (I take blood pressure meds)",
        "all no apart from my knee",
        "all no 🫀",
        "all no, well maybe",
        "it isn't all no",
        "not quite all no",
        "far from all no",
        "i take medication, all no",
        "all no?",
        "all no ?",
        "all no??",
        "all no?!",
        "all no..",
        "all no!!",
        "all no . .",
        "no to all?",
        "none?",
        "all no？",
        "all no :(",
        "all no :-(",
        "all no :/",
        "all no :'(",
        "all no :-/",
        "all no :\\",
        "all no :|",
        "all no ;-(",
        "all no :'-(",
    )
    for reply in unclear:
        state, bots = run_chat(body + [reply, "yes"])
        assert state["confirmed"] is False, reply
        assert state["par_q"] == {}, reply
        assert all(value is not False for value in state["par_q"].values())
        if "chest pain" in reply:
            assert state["phase"] == "symptom", reply
            assert "medical emergency" in bots[-1].lower(), reply
            _drop_hold()
            continue
        assert state["par_q"] == {}, reply
        assert "one yes confirms the plan" not in bots[-1].lower(), reply
        _drop_hold()
    kept = (
        "medication yes, all no",
        "joint problem yes, all no",
        "supervised only yes, otherwise all no",
    )
    for reply in kept:
        state, bots = run_chat(body + [reply, "yes"])
        assert state["confirmed"] is False, reply
        assert state["par_q"] == {}, reply
        assert "one yes confirms the plan" not in bots[-1].lower(), reply
        _drop_hold()
    accepted = (
        "all no.",
        "all no!",
        "all no,",
        "  all no  ",
        "all no thanks",
        "all no lol",
        "all no 👍",
        "all no 👍🏻",
        "no to all",
        "none",
        "nope all no",
        "honestly all no",
        "all no :)",
        "all no :-)",
        "all no, parkrun saturdays 30 min",
    )
    for reply in accepted:
        state, _bots = run_chat(body + [reply, "yes"])
        assert state["confirmed"] is False, reply
        assert state["par_q"] == {}, reply
        _drop_hold()
    button, _button_bots = run_chat(body + ["all_no", "yes"])
    assert button["confirmed"] is True
    assert len(button["par_q"]) == len(PAR_Q)
    assert all(value is False for value in button["par_q"].values())
    chest, chest_bots = run_chat(body + ["chest pain yes. all no", "yes"])
    assert chest["confirmed"] is False
    assert chest["phase"] == "symptom"
    assert "medical emergency" in chest_bots[-1].lower()
    assert "one yes confirms the plan" not in chest_bots[-1].lower()


def test_a_confirmed_plan_deletes_the_pending_profile_draft(tmp_path, monkeypatch):
    draft = tmp_path / "pending_profile.json"
    draft.write_text('{"goal": "hold"}\n', encoding="utf-8")
    monkeypatch.setattr("onboarding.pending_profile_path", lambda: str(draft))
    done, _turns = run_chat(HAPPY_PATH)
    assert done["confirmed"] is True
    assert not draft.exists()


def test_a_symptom_leaves_the_pending_profile_draft(tmp_path, monkeypatch):
    draft = tmp_path / "pending_profile.json"
    draft.write_text('{"goal": "hold"}\n', encoding="utf-8")
    monkeypatch.setattr("onboarding.pending_profile_path", lambda: str(draft))
    refused, bots = run_chat(list(HAPPY_PATH[:-1]) + ["yes, morning 6:30, but my chest hurts"])
    assert refused["confirmed"] is False
    assert draft.is_file()
    assert "medical emergency" in bots[-1].lower()
    later, later_bots = run_chat(HAPPY_PATH)
    assert later["confirmed"] is False
    assert "one yes confirms the plan" not in " ".join(later_bots).lower()
    assert draft.is_file()


def test_an_unreadable_seal_key_stops_without_a_crash(monkeypatch, tmp_path):
    import os

    from seal_secret import DATA_FILE_MESSAGE

    path = tmp_path / "seal.key"
    path.write_bytes(b"k" * 32)
    before = path.read_bytes()
    mode = path.stat().st_mode
    monkeypatch.setattr("seal_secret._key_path", lambda: str(path))
    real_open = open

    def guarded(file, *args, **kwargs):
        target = file if isinstance(file, (str, bytes)) else getattr(file, "name", None)
        if target is not None and os.path.abspath(str(target)) == os.path.abspath(path):
            raise PermissionError("blocked")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", guarded)
    state, bots = run_chat(list(HAPPY_PATH))
    assert state["confirmed"] is False
    assert bots[-1] == DATA_FILE_MESSAGE
    assert "stop" in bots[-1].lower()
    assert "data file" in bots[-1].lower()
    assert "check" in bots[-1].lower()
    descriptor = os.open(path, os.O_RDONLY)
    try:
        assert os.read(descriptor, 64) == before
    finally:
        os.close(descriptor)
    assert path.stat().st_mode == mode


def test_direct_confirm_helpers_refuse_outside_run_chat(tmp_path, monkeypatch):
    import json

    import onboarding
    from plan_builder import PlanBuilder
    from record_confirmation import (
        ConfirmationRecorder,
        _mark_first_plan,
        _store_onboarding_record,
        first_plan_seal,
    )
    from red_flag_check import RedFlagChecker
    from routines import start_daily_loop

    week = {
        "plan": {"user": {"age": 30}},
        "sessions": [{"date": "2026-11-02", "name": "Upper"}],
    }
    unmarked = _mark_first_plan(week)
    assert not unmarked.get("first_plan_seal")
    assert _store_onboarding_record(None, week) is False
    checker = RedFlagChecker()
    answers = {aliases[0]: "no" for _flag, aliases in checker.CHECKLIST_GROUPS}
    check_in = checker.scan_check_in({"symptom_checklist": answers, "notes": "all no"})
    sealed = dict(week)
    sealed["first_plan"] = True
    sealed["first_plan_seal"] = first_plan_seal(sealed)
    record = ConfirmationRecorder().record(sealed, "yes, morning 6:15", "user", check_in)
    assert record.confirmed is False
    assert "run_chat" in record.message.lower()
    started = start_daily_loop("yes, morning 6:15")
    assert started["ok"] is False
    assert "run_chat" in started["message"].lower()
    assert start_daily_loop("yes")["ok"] is True
    draft = tmp_path / "pending_profile.json"
    draft.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(onboarding, "pending_profile_path", lambda: str(draft))
    assert onboarding.clear_pending_profile() is False
    assert draft.is_file()
    saved = PlanBuilder().save(
        {"training": {"previous_load": 80, "current_load": 80}},
        record,
        tmp_path / "week.json",
        [{"date": "2026-11-02", "name": "Upper", "load": 80, "minutes": 30}],
    )
    assert saved["saved"] is False
    assert "run_chat" in saved["message"].lower()
    assert not onboarding.confirm_phase_active()
    assert json.loads(draft.read_text(encoding="utf-8")) == {}


def test_the_round3_transcript_asks_age_then_confirms(monkeypatch):
    import json
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

    import onboarding
    from onboarding import _AGE_ASK
    from plan_builder import session_volume
    from record_confirmation import confirmation_seal_matches

    zone = ZoneInfo("America/Los_Angeles")
    pinned = datetime(2026, 10, 31, 12, 0, tzinfo=zone)
    monkeypatch.setattr(onboarding, "_now", lambda: pinned)
    monkeypatch.setattr(onboarding, "_default_timezone_name", lambda: "America/Los_Angeles")
    monkeypatch.setattr(onboarding, "_local_today", lambda name=None: date(2026, 10, 31))
    profile = (
        "lose fat and get stronger. 70 kg now, want 64. 165 cm, 41, female. "
        "beginner, I have dumbbells at home (5 to 20 kg), can do 3 days a week, "
        "30 min, mon wed fri. I also run a parkrun 5k most saturdays. I wear an oura ring"
    )
    replies = [
        "hey! a friend said you could help me get in shape",
        _marked(profile),
        "41",
        "all_no",
        "yes, morning 6:15",
    ]
    state, bots = run_chat(replies)
    assert state["turns"] <= 6
    assert len(bots) <= 6
    assert _AGE_ASK in bots
    assert bots.index(_AGE_ASK) < len(bots) - 1
    assert state["confirmed"] is True
    answers = state["answers"]
    assert answers["goal"] == "cut"
    assert answers["weight"] == "70 kg"
    assert answers["target"] == "64 kg"
    assert answers["height"] == "165 cm"
    assert answers["age"] == "41"
    assert answers["sex"] == "female"
    assert answers["experience"] == "beginner"
    assert answers["equipment"] == "dumbbells"
    assert answers["training_days"] == "3"
    assert answers["minutes"] == "30"
    assert answers["days"] == ["2026-11-02", "2026-11-04", "2026-11-06"]
    assert answers["sport"] == "parkrun"
    assert answers["sport_day"] == "Saturday"
    assert "oura" in answers["sources"]
    assert answers["injuries"] == "none"
    assert len(state["par_q"]) == len(PAR_Q)
    assert all(value is False for value in state["par_q"].values())
    assert state["first_checkin"] == "2026-11-02"
    assert "2026-11-02" in bots[-2]
    assert state["times"]["daily_checkin"] == "06:15"
    nutrition = state["plan"]["nutrition"]
    assert nutrition["calories"] >= 1200
    assert state["record"].confirmed is True
    assert confirmation_seal_matches(state["record"])
    from record_confirmation import onboarding_record_path

    stored = json.loads(open(onboarding_record_path(), encoding="utf-8").read())
    assert stored["first_plan_seal"]
    assert stored["plan_hash"] == state["record"].plan_hash
    week_path = onboarding.onboarding_week_path()
    saved = json.loads(open(week_path, encoding="utf-8").read())
    assert saved["sessions"][0]["date"] == "2026-11-02"
    assert saved["plan"]["nutrition"]["calories"] >= 1200
    for row in state["sessions"]:
        assert row["minutes"] == 30
        assert session_volume(row["exercises"]) <= 30
        assert "DB Romanian deadlift" in [item["name"] for item in row["exercises"]]
        assert all(item.get("reps") != "10 min" for item in row["exercises"])


def test_free_text_never_stores_an_age_and_the_bot_asks():
    from onboarding import _AGE_ASK

    phrases = (
        "im 20% body fat",
        "im 25 percent bodyfat",
        "im 18 months into lifting",
        "im 19 stone",
        "im 21 weeks pregnant",
        "im 32 waist",
        "im 22 bmi",
        "im 40 bench",
        "im 60 squat",
        "im 70 percent sure",
        "i am 100 percent ready",
    )
    for text in phrases:
        _drop_hold()
        state, bots = run_chat([text])
        assert state["answers"].get("age") in (None, ""), text
        assert state["confirmed"] is False, text
        assert bots[-1] != _AGE_ASK, text
        assert "one check on that message" in bots[-1].lower(), text
        later, later_bots = run_chat([text, "all no", "yes"])
        assert later["answers"].get("age") in (None, ""), text
        assert later["confirmed"] is False, text
        assert "one yes confirms the plan" not in "\n".join(later_bots).lower(), text
    _drop_hold()
    listed, listed_bots = run_chat(["hold, female, 165 cm, 41, 70 kg"])
    assert listed["answers"].get("age") in (None, "")
    assert listed_bots[-1] == _AGE_ASK
    typed, typed_bots = run_chat(["hold, female, 165 cm, 70 kg", "41"])
    assert typed["answers"]["age"] == "41"
    assert typed["confirmed"] is False
    assert _AGE_ASK not in typed_bots[-1]
    years, years_bots = run_chat(["hold, female, 165 cm, 70 kg", "41 years old"])
    assert years["answers"].get("age") in (None, "")
    assert years_bots[-1] == _AGE_ASK


def test_a_lower_age_clears_the_stored_adult_and_refuses():
    from onboarding import _AGE_ASK

    steps = (
        ["hold, male, 80 kg, 180 cm, no injuries", "25", _marked("age 15", minor_signal=True)],
        ["hold, male, 80 kg, 180 cm, no injuries", "25", "ok", _marked("age 15", minor_signal=True)],
        ["hold, male, 80 kg, 180 cm, no injuries", "25", "ok", "all no", _marked("age 15", minor_signal=True)],
        ["hold, male, 80 kg, 180 cm, no injuries", "25", "ok", "all no", _marked("wait im actually 15", minor_signal=True)],
        ["hold, male, 80 kg, 180 cm, no injuries", "25", "ok", "all no", _marked("sorry, age 15 not 25", minor_signal=True)],
    )
    for replies in steps:
        state, bots = run_chat(replies)
        assert state["confirmed"] is False, replies
        assert state["answers"].get("age") in (None, ""), replies
        assert bots[-1] == _AGE_ASK, replies
        minor, minor_bots = run_chat(replies + ["15"])
        assert minor["confirmed"] is False, replies
        assert minor["answers"]["age"] == "15", replies
        text = minor_bots[-1].lower()
        assert "under 18" in text, replies
        assert "calorie" in text, replies
        assert "protein" in text, replies
        assert "one yes confirms the plan" not in text, replies
        still, still_bots = run_chat(replies + ["15", "yes"])
        assert still["confirmed"] is False, replies
        assert still["answers"]["age"] == "15", replies
        assert "one yes confirms the plan" not in still_bots[-1].lower(), replies


def test_shoe_size_and_dogs_do_not_block_a_stored_adult_age():
    from onboarding import _AGE_ASK

    for aside in ("size 9 shoes", "2 dogs", "im 6 foot", "im 2 weeks"):
        state, bots = run_chat(list(HAPPY_PATH[:-1]) + [aside])
        assert state["confirmed"] is False, aside
        assert state["phase"] == "confirm", aside
        assert state["answers"]["age"] == "30", aside
        assert bots.count(_AGE_ASK) == 1, aside
        assert bots[-1] != _AGE_ASK, aside
        assert "one yes confirms the plan" in bots[-1].lower(), aside
        done, done_bots = run_chat(list(HAPPY_PATH[:-1]) + [aside, "yes"])
        assert done["confirmed"] is True, aside
        assert done["answers"]["age"] == "30", aside
        assert done_bots.count(_AGE_ASK) == 1, aside


def test_lift_reps_someone_else_and_a_grade_never_become_the_age():
    from onboarding import _AGE_ASK

    samples = (
        "bench 40",
        "male, bench 40",
        "bench 40, male",
        "I can do 20 pushups",
        "20 reps",
        "my dad is 50",
        "my wife is 33",
        "my son is 12",
        "9th grader",
        "10th grade",
        "high school",
        "freshman",
        "sophomore",
        "junior",
        "senior in HS",
        "middle school",
        "I'm a teen",
    )
    for text in samples:
        state, bots = run_chat([text])
        assert state["answers"].get("age") in (None, ""), text
        assert state["confirmed"] is False, text
        assert "one yes confirms the plan" not in "\n".join(bots).lower(), text
    teen, teen_bots = run_chat([_marked("I'm a teen", minor_signal=True)])
    assert teen_bots[-1] == _AGE_ASK
    grown, grown_bots = run_chat([_marked("I'm a teen", minor_signal=True), "19"])
    assert grown["answers"]["age"] == "19"
    assert grown["confirmed"] is False
    assert grown_bots[-1] != _AGE_ASK
    child, child_bots = run_chat([_marked("I'm a teen", minor_signal=True), "16", "yes"])
    assert child["confirmed"] is False
    assert child["answers"]["age"] == "16"
    assert "one yes confirms the plan" not in child_bots[-1].lower()


def test_a_head_emoji_at_confirm_holds_and_a_later_chat_stays_held():
    from onboarding import hold_is_active

    body = [
        "hello",
        "cut, male, 60 kg, 170 cm, no injuries",
        "25",
        "general training, 3 days 45 min, dumbbells, beginner, no injuries, none",
        "all no",
    ]
    for tail in (["\U0001F915", "no", "yes"], ["\U0001F915", "none", "yes"]):
        state, bots = run_chat(body + tail)
        assert state["confirmed"] is False, tail
        assert state["phase"] == "symptom", tail
        assert hold_is_active(), tail
        assert "which area is injured" not in "\n".join(bots).lower(), tail
        assert "one yes confirms the plan" not in bots[-1].lower(), tail
        again, again_bots = run_chat(["hello", "yes"])
        assert again["confirmed"] is False, tail
        assert again["phase"] == "symptom", tail
        assert hold_is_active(), tail
        assert "one yes confirms the plan" not in "\n".join(again_bots).lower(), tail
        import os

        import onboarding

        path = onboarding.onboarding_state_path()
        if os.path.exists(path):
            os.remove(path)
        onboarding._memory_hold = None
    head, head_bots = run_chat(body + ["\U0001F9B5", "my head"])
    assert head["confirmed"] is False
    assert head["phase"] == "symptom"
    assert hold_is_active()
    assert head_bots[-1] != "Which area is injured?"
    assert "which area is injured" not in head_bots[-1].lower()


def test_a_minor_cue_after_the_age_clears_the_adult_age():
    from onboarding import _AGE_ASK

    body = [
        "hello",
        _marked("cut, male, 60 kg, 170 cm, general training, 3 days 45 min, dumbbells, beginner"),
        "25",
        "all_no",
    ]
    cues = (
        "im a minor",
        "im under 18",
        "i'm not 18 yet",
        "im only 16",
        "in high school",
        "9th grade",
        "teen",
        "15",
        "fifteen",
        "16 actually",
        "sixteen lol",
        "im just 17",
        "15 years old",
        "i am fifteen",
        "still in school",
        "my parents signed up for me",
    )
    for cue in cues:
        state, bots = run_chat(body + [_marked(cue, minor_signal=True)])
        assert state["confirmed"] is False, cue
        assert state["answers"].get("age") in (None, ""), cue
        assert bots[-1] == _AGE_ASK, cue
        later, later_bots = run_chat(body + [_marked(cue, minor_signal=True), "yes"])
        assert later["confirmed"] is False, cue
        assert later["answers"].get("age") in (None, ""), cue
        assert "one yes confirms the plan" not in later_bots[-1].lower(), cue
        minor, minor_bots = run_chat(body + [_marked(cue, minor_signal=True), "15"])
        assert minor["confirmed"] is False, cue
        assert minor["answers"]["age"] == "15", cue
        assert "under 18" in minor_bots[-1].lower(), cue
        assert "one yes confirms the plan" not in minor_bots[-1].lower(), cue
    for plain in ("3 days 45 min", "12 reps"):
        kept, kept_bots = run_chat(body + [plain])
        assert kept["answers"]["age"] == "25", plain
        assert kept_bots[-1] != _AGE_ASK, plain
        assert "one yes confirms the plan" in kept_bots[-1].lower(), plain
        done, _done_bots = run_chat(body + [plain, "yes"])
        assert done["confirmed"] is True, plain
        assert done["answers"]["age"] == "25", plain


def _drop_hold():
    import os

    import onboarding

    path = onboarding.onboarding_state_path()
    if os.path.exists(path):
        os.remove(path)
    onboarding._memory_hold = None


def test_an_acute_structural_injury_holds_and_a_later_chat_stays_held():
    from onboarding import hold_is_active

    body = [
        "hello",
        "cut, male, 60 kg, 170 cm, no injuries",
        "25",
        "general training, 3 days 45 min, dumbbells, beginner, no injuries, none",
        "all no",
    ]
    phrases = (
        "sprained ankle today, cant walk, heard a pop",
        "snapped my achilles",
        "achilles snapped yesterday",
        "torn acl yesterday, knee swollen",
        "torn acl today, knee gave out, heard a pop",
        "pulled hamstring today, heard a pop",
        "sprained ankle, its swollen and i cant walk",
        "healed, knee swollen today",
        "healed, sharp pain in knee",
        "tore my acl yesterday",
    )
    for phrase in phrases:
        state, bots = run_chat(body + [_marked(phrase, injury="current"), "yes"])
        assert state["confirmed"] is False, phrase
        assert state["phase"] == "symptom", phrase
        assert hold_is_active(), phrase
        assert "one yes confirms the plan" not in bots[-1].lower(), phrase
        again, again_bots = run_chat(["hello", "yes"])
        assert again["confirmed"] is False, phrase
        assert again["phase"] == "symptom", phrase
        assert hold_is_active(), phrase
        assert "one yes confirms the plan" not in "\n".join(again_bots).lower(), phrase
        _drop_hold()


def test_an_emergency_sign_holds_with_an_emergency_line():
    from record_confirmation import reply_pause
    from onboarding import hold_is_active

    body = [
        "hello",
        "cut, male, 60 kg, 170 cm, no injuries",
        "25",
        "ok",
        "all no",
    ]
    phrases = (
        "loss of bladder or bowel control",
        "numb legs",
        "can't feel my legs",
        "saddle numbness",
        "chest injury",
        "broken rib",
        "broken ribs",
        "hurt my back today, sharp pain",
        "slipped disc, lost bladder control",
        "slipped disc, cant feel my legs",
        "peed myself",
        "wet myself",
        "incontinence",
        "cant control bladder",
        "tingling both legs",
        "cant feel my feet",
        "pain shooting down both legs",
        "cracked rib",
        "bruised ribs",
    )
    for phrase in phrases:
        paused = reply_pause(phrase)
        assert paused is not None, phrase
        blob = (paused.message + " " + " ".join(paused.recommendations)).lower()
        assert "emergency" in blob or "urgent" in blob, phrase
        state, bots = run_chat(body + [phrase])
        assert state["confirmed"] is False, phrase
        assert state["phase"] == "symptom", phrase
        assert hold_is_active(), phrase
        spoken = bots[-1].lower()
        assert "emergency" in spoken or "urgent" in spoken, phrase
        again, again_bots = run_chat(["hello", "yes"])
        assert again["confirmed"] is False, phrase
        assert again["phase"] == "symptom", phrase
        assert hold_is_active(), phrase
        assert "one yes confirms the plan" not in "\n".join(again_bots).lower(), phrase
        _drop_hold()


def test_a_structural_injury_is_stored_and_does_not_hold_the_day():
    from onboarding import hold_is_active

    samples = (
        ("old sprained ankle", "ankle"),
        ("achilles", "achilles"),
        ("torn acl 2 years ago", "knee"),
        ("torn acl 2 years ago, fine now", "knee"),
    )
    for phrase, area in samples:
        state, bots = run_chat([
            _marked(f"hold, male, 80 kg, 180 cm, {phrase}", injury="old"),
            "30",
            "ok",
            "all_no",
            "yes",
        ])
        assert state["answers"]["injuries"] == area, phrase
        assert state["confirmed"] is True, phrase
        assert state["phase"] != "symptom", phrase
        assert hold_is_active() is False, phrase
        for row in state["sessions"]:
            assert row["exercises"], phrase
    for mixed in ("chest pain and torn acl", "im dizzy and i have a torn acl", "healed, but chest pain"):
        held, held_bots = run_chat([
            "hold, male, 80 kg, 180 cm, no injuries",
            "30",
            "ok",
            mixed,
        ])
        assert held["confirmed"] is False, mixed
        assert held["phase"] == "symptom", mixed
        assert hold_is_active(), mixed
        assert "tomorrow" in held_bots[-1].lower(), mixed
        import os

        import onboarding

        path = onboarding.onboarding_state_path()
        if os.path.exists(path):
            os.remove(path)
        onboarding._memory_hold = None


def test_a_decimal_kg_and_a_pound_weight_convert():
    from onboarding import _TARGET_ASK, _WEIGHT_ASK

    kept, _bots = run_chat(["112.1 kg"])
    assert kept["answers"]["weight"] == "112.1 kg"
    both, _both_bots = run_chat(["176 lbs, want 64 kg"])
    assert both["answers"]["weight"] == "79.8 kg"
    assert both["answers"]["target"] == "64 kg"
    heavy, heavy_bots = run_chat(["660 lbs"])
    assert heavy["answers"].get("weight") in (None, "")
    assert heavy_bots[-1] == _WEIGHT_ASK
    bare, bare_bots = run_chat(["want 64"])
    assert bare["answers"].get("target") in (None, "")
    assert bare_bots[-1] == _TARGET_ASK
    named, named_bots = run_chat(["want 64 kg"])
    assert named["answers"].get("weight") in (None, "")
    assert named["answers"]["target"] == "64 kg"
    assert named_bots[-1] == "What's your current weight in kg?"
    assert "looks off" not in named_bots[-1].lower()


def test_a_symptom_at_the_par_q_step_holds_the_day():
    body = ["hold, male, 80 kg, 180 cm, no injuries", "30", "ok"]
    for reply in ("my chest hurts", "i feel faint", "im dizzy"):
        state, bots = run_chat(body + [reply])
        assert state["phase"] == "symptom", reply
        assert state["confirmed"] is False, reply
        assert "tomorrow" in bots[-1].lower(), reply
        if "chest" in reply:
            assert "medical emergency" in bots[-1].lower(), reply
        later, later_bots = run_chat(body + [reply, "all no", "yes"])
        assert later["confirmed"] is False, reply
        assert later["phase"] == "symptom", reply
        assert "one yes confirms the plan" not in later_bots[-1].lower(), reply


def test_a_named_area_wins_and_an_emoji_asks_which_area():
    from onboarding import _INJURY_ASK, _fold, _stated_injury

    assert _stated_injury(_fold("no injuries except my knee")) == "knee"
    assert _stated_injury(_fold("no injuries but my back hurts")) == "back"
    assert _stated_injury(_fold("injuries: none, but shoulder niggle")) == "shoulder"
    assert _stated_injury(_fold("bad knees")) == "knee"
    assert _stated_injury(_fold("herniated disc")) == "back"
    assert _stated_injury(_fold("rotator cuff")) == "shoulder"
    assert _stated_injury(_fold("tennis elbow")) == "elbow"
    assert _stated_injury(_fold("plantar fasciitis")) == "ankle"
    emoji, bots = run_chat(["hold, male, 80 kg, 180 cm", "30", "\U0001F9B5"])
    assert emoji["answers"].get("injuries") in (None, "")
    assert bots[-1] == _INJURY_ASK
    named, _named_bots = run_chat(["hold, male, 80 kg, 180 cm", "30", "\U0001F9B5", "knee"])
    assert named["answers"]["injuries"] == "knee"
    knee, knee_bots = run_chat([
        _marked("hold, male, 80 kg, 180 cm, no injuries except my knee", injury="old"),
        "30",
        "ok",
        "all_no",
        "yes",
    ])
    assert knee["confirmed"] is True
    assert knee["answers"]["injuries"] == "knee"
    assert "I kept weight off your knee." in "\n".join(knee_bots)
    for row in knee["sessions"]:
        names = [item["name"].lower() for item in row["exercises"]]
        assert names
        assert any("box squat" in name or "glute bridge" in name for name in names)
        assert not any("lunge" in name for name in names)


def test_want_days_is_not_a_target_weight():
    from onboarding import _TARGET_ASK, _paired_session_minutes

    state, bots = run_chat(["I want 3 days"])
    assert state["answers"].get("target") in (None, "")
    assert bots[-1] == _TARGET_ASK
    weighed, weighed_bots = run_chat(["70 kg now, I want 3 days"])
    assert weighed["answers"].get("target") in (None, "")
    assert weighed_bots[-1] == _TARGET_ASK
    kept, _bots = run_chat(["70 kg now, want 64. 165 cm, 41, female"])
    assert kept["answers"]["target"] == "64 kg"
    assert kept["answers"].get("age") in (None, "")
    for text in ("want 200", "want 200 with current 70 kg", "i want 3 days"):
        missed, _missed_bots = run_chat([text])
        assert missed["answers"].get("target") in (None, ""), text
    staged, _staged_bots = run_chat(["current 70 kg", "want 200"])
    assert staged["answers"]["weight"] == "70 kg"
    assert staged["answers"].get("target") in (None, "")
    ordered, ordered_bots = run_chat(["current 90 kg, want 200"])
    assert ordered["answers"].get("target") in (None, "")
    assert ordered["answers"]["weight"] == "90 kg"
    assert ordered_bots[-1] == "That target looks far from 90 kg. What goal weight do you want?"
    close, _close_bots = run_chat(["current 90 kg, want 100"])
    assert close["answers"]["target"] == "100 kg"
    pounds, _pounds_bots = run_chat(["current 90 kg, want 200 lb"])
    assert pounds["answers"]["target"] == "90.7 kg"
    high, _high_bots = run_chat(["current 90 kg, want 301"])
    assert high["answers"].get("target") in (None, "")
    assert high["answers"]["weight"] == "90 kg"
    assert _paired_session_minutes("3 days 30 min, parkrun saturdays") == "30"
    assert _paired_session_minutes("parkrun is about 32 min, 3 days 30 min") == "30"
    assert _paired_session_minutes("32 min parkrun, 3 days 45 min") == "45"
    assert _paired_session_minutes("3 days, parkrun is about 32 min") is None


def test_all_no_phrases_need_the_message_to_stay_free_of_symptoms():
    from onboarding import _AGE_ASK, read_par_q

    for phrase in ("all no", "no to all", "none", "all clear"):
        status, parsed = read_par_q(phrase)
        assert status == "all_no"
        assert parsed and all(value is False for value in parsed.values())
        mixed, _parsed = read_par_q(phrase + ", my chest hurts")
        assert mixed != "all_no"
    status, _parsed = read_par_q("no injuries, parkrun is about 32 min. all no")
    assert status == "all_no"
    assert read_par_q("not all no")[0] != "all_no"
    body = [
        _marked("hold, male, 80 kg, 180 cm, general training, 3 days 45 min, bodyweight, beginner"),
        "30",
    ]
    impure = (
        "all no for most",
        "all no to most",
        "most all no",
        "none for most",
        "all no 2 and 5",
        "all no, 3 and 6",
        "all no on 1",
        "all no also",
        "all no my",
        "all no i",
        "all no and",
        "all no ...",
        "all no..",
        "all no!!",
        "all no . .",
    )
    assert read_par_q("all no, parkrun saturdays 30 min")[0] == "all_no"
    for reply in impure:
        assert read_par_q(reply)[0] != "all_no", reply
        state, bots = run_chat(body + [reply, "yes"])
        assert state["confirmed"] is False, reply
        assert "one yes confirms the plan" not in bots[-1].lower(), reply
        assert state["par_q"] == {}, reply
        assert state["answers"].get("age") == "30", reply
        _drop_hold()


def test_a_buckled_acl_on_crutches_holds_and_a_later_chat_stays_held():
    from onboarding import hold_is_active

    state, bots = run_chat([
        "hello",
        _marked("cut, male, 60 kg, 170 cm, torn acl, knee buckled, on crutches", injury="current"),
        "25",
        "general training, 3 days 45 min, dumbbells, beginner, none",
        "all no",
        "yes",
    ])
    assert state["confirmed"] is False
    assert state["phase"] == "symptom"
    assert hold_is_active()
    assert "one yes confirms the plan" not in bots[-1].lower()
    again, again_bots = run_chat(["hello", "yes"])
    assert again["confirmed"] is False
    assert again["phase"] == "symptom"
    assert hold_is_active()
    assert "one yes confirms the plan" not in "\n".join(again_bots).lower()
    _drop_hold()


def test_acute_wording_holds_for_every_named_injury():
    from onboarding import hold_is_active

    body = [
        "hello",
        "cut, male, 60 kg, 170 cm, no injuries",
        "25",
        "general training, 3 days 45 min, dumbbells, beginner, none",
        "all no",
    ]
    marks = (
        "ballooned",
        "puffy",
        "black and blue",
        "buckled",
        "gave way",
        "limping",
        "cant bend it",
        "on crutches",
        "in a cast",
        "heard a crack",
        "excruciating",
        "agony",
        "10/10 pain",
        "still hurts",
        "during my run",
        "hours ago",
        "2 days ago",
        "earlier",
        "this morning",
    )
    bases = ("sprained ankle", "torn acl", "pulled hamstring", "torn rotator cuff")
    phrases = [f"{base}, {mark}" for base in bases for mark in marks]
    phrases.extend((
        "calf tear this morning",
        "groin strain 10/10",
        "heard a pop in my achilles",
    ))
    for phrase in phrases:
        state, bots = run_chat(body + [_marked(phrase, injury="current"), "yes"])
        assert state["confirmed"] is False, phrase
        assert state["phase"] == "symptom", phrase
        assert hold_is_active(), phrase
        assert "one yes confirms the plan" not in bots[-1].lower(), phrase
        again, again_bots = run_chat(["hello", "yes"])
        assert again["confirmed"] is False, phrase
        assert again["phase"] == "symptom", phrase
        assert hold_is_active(), phrase
        assert "one yes confirms the plan" not in "\n".join(again_bots).lower(), phrase
        _drop_hold()


def test_an_untimed_named_injury_asks_then_old_stores_and_recent_holds():
    from onboarding import _INJURY_WHEN, hold_is_active

    for phrase in ("torn acl", "bad knees", "slipped disc", "pulled hamstring", "torn rotator cuff"):
        state, bots = run_chat([_marked(f"hold, male, 80 kg, 180 cm, {phrase}", injury="unclear")])
        assert state["answers"].get("injuries") in (None, ""), phrase
        assert state["phase"] != "symptom", phrase
        assert hold_is_active() is False, phrase
        assert bots[-1] == _INJURY_WHEN, phrase
        _drop_hold()
    stored, stored_bots = run_chat([
        _marked("hold, male, 80 kg, 180 cm, torn acl", injury="unclear"),
        "old",
        "30",
        "ok",
        "all_no",
        "yes",
    ])
    assert stored["answers"]["injuries"] == "knee"
    assert stored["confirmed"] is True
    assert hold_is_active() is False
    assert "I kept weight off your knee." in "\n".join(stored_bots)
    healed, _healed_bots = run_chat([
        _marked("hold, male, 80 kg, 180 cm, slipped disc", injury="unclear"),
        "Old & healed",
        "30",
        "ok",
        "all_no",
        "yes",
    ])
    assert healed["answers"]["injuries"] == "back"
    assert healed["confirmed"] is True
    _drop_hold()
    for answer in ("recent", "still painful", "still hurts", "maybe", "yes"):
        held, held_bots = run_chat([
            _marked("hold, male, 80 kg, 180 cm, torn acl", injury="unclear"),
            answer,
        ])
        assert held["confirmed"] is False, answer
        assert held["phase"] == "symptom", answer
        assert held["answers"].get("injuries") in (None, ""), answer
        assert hold_is_active(), answer
        assert "one yes confirms the plan" not in held_bots[-1].lower(), answer
        _drop_hold()


def test_a_clearly_old_injury_at_confirm_stores_and_reproposes():
    from onboarding import hold_is_active

    state, bots = run_chat(list(_AGE_25) + [_marked("torn acl 2 years ago, fine now", injury="old")])
    assert state["confirmed"] is False
    assert state["phase"] == "confirm"
    assert hold_is_active() is False
    assert state["answers"]["injuries"] == "knee"
    assert state["answers"]["age"] == "25"
    assert bots[-1].startswith("Plan for age 25.")
    assert "I kept weight off your knee." in bots[-1]
    assert "one yes confirms the plan" in bots[-1].lower()
    done, _bots = run_chat(list(_AGE_25) + [_marked("torn acl 2 years ago, fine now", injury="old"), "yes"])
    assert done["confirmed"] is True
    assert done["answers"]["injuries"] == "knee"


def test_only_an_allowlisted_reply_stores_an_injury_as_old():
    from onboarding import _INJURY_WHEN, hold_is_active

    training = "general training, 3 days 45 min, dumbbells, beginner, none"
    blocked = (
        "not healed",
        "hasnt healed",
        "no its not old",
        "old?",
        "its old but it hurts",
        "old but sore",
        "old but acting up",
        "old but tweaked it again",
        "old reinjured last week",
        "mostly healed",
        "almost healed",
    )
    for answer in blocked:
        state, bots = run_chat([
            "hello",
            _marked("cut, male, 60 kg, 170 cm, torn acl", injury="unclear"),
            answer,
            "25",
            training,
            "all no",
            "yes",
        ])
        assert state["confirmed"] is False, answer
        assert "one yes confirms the plan" not in bots[-1].lower(), answer
        _drop_hold()
    one, one_bots = run_chat([
        "hello",
        _marked("cut, male, 60 kg, 170 cm, torn acl, not healed", injury="current"),
        "25",
        training,
        "all no",
        "yes",
    ])
    assert one["confirmed"] is False
    assert one["phase"] == "symptom"
    assert one["answers"].get("injuries") in (None, "")
    assert hold_is_active()
    assert "one yes confirms the plan" not in one_bots[-1].lower()
    _drop_hold()
    for phrase in ("my knee hurts", "knee pain", "back pain", "achilles tendinitis"):
        asked, asked_bots = run_chat([_marked(f"hold, male, 80 kg, 180 cm, {phrase}", injury="unclear")])
        assert asked["answers"].get("injuries") in (None, ""), phrase
        assert asked["phase"] != "symptom", phrase
        assert hold_is_active() is False, phrase
        assert asked_bots[-1] == _INJURY_WHEN, phrase
        _drop_hold()
    stored, stored_bots = run_chat([
        _marked("hold, male, 80 kg, 180 cm, knee pain", injury="unclear"),
        "Old & healed",
        "30",
        "ok",
        "all_no",
        "yes",
    ])
    assert stored["confirmed"] is True
    assert stored["answers"]["injuries"] == "knee"
    assert "I kept weight off your knee." in "\n".join(stored_bots)
    painful, _pain_bots = run_chat([
        _marked("hold, male, 80 kg, 180 cm, my knee hurts", injury="unclear"),
        "it hurts",
    ])
    assert painful["confirmed"] is False
    assert painful["phase"] == "symptom"
    assert painful["answers"].get("injuries") in (None, "")
    assert hold_is_active()
    _drop_hold()


def test_joined_age_cues_and_times_at_confirm():
    from onboarding import _AGE_ASK

    cues = (
        "17yo",
        "15yrs",
        "15y",
        "age15",
        "under eighteen",
        "not an adult",
        "highschooler",
        "my mom said i can",
        "my dad said i can",
        "16 am i allowed",
    )
    for cue in cues:
        state, bots = run_chat(list(_AGE_25) + [_marked(cue, minor_signal=True)])
        assert state["confirmed"] is False, cue
        assert state["answers"].get("age") in (None, ""), cue
        assert bots[-1] == _AGE_ASK, cue
        assert "one yes confirms the plan" not in bots[-1].lower(), cue
    clock, clock_bots = run_chat(list(_AGE_25) + ["6:30"])
    assert clock["confirmed"] is False
    assert clock["phase"] == "confirm"
    assert clock["answers"]["age"] == "25"
    assert clock_bots[-1].startswith("Plan for age 25.")
    assert _AGE_ASK not in clock_bots[-1]
    days, days_bots = run_chat(list(_AGE_25) + ["mon wed fri"])
    assert days["confirmed"] is False
    assert days["phase"] == "confirm"
    assert days["answers"]["age"] == "25"
    assert days_bots[-1].startswith("Plan for age 25.")
    assert _AGE_ASK not in days_bots[-1]
    at_six, at_bots = run_chat(list(_AGE_25) + ["at 6 am"])
    assert at_six["answers"]["age"] == "25"
    assert at_six["confirmed"] is False
    assert at_six["phase"] == "confirm"
    assert at_bots[-1].startswith("Plan for age 25.")
    assert _AGE_ASK not in at_bots[-1]
    yes_at, yes_bots = run_chat(list(_AGE_25) + ["yes at 7"])
    assert yes_at["confirmed"] is False
    assert yes_at["phase"] == "confirm"
    assert yes_at["answers"]["age"] == "25"
    assert yes_bots[-1].startswith("Plan for age 25.")
    assert _AGE_ASK not in yes_bots[-1]
    ten, ten_bots = run_chat(list(_AGE_25) + ["10 am"])
    assert ten["confirmed"] is False
    assert ten["phase"] == "confirm"
    assert ten["answers"]["age"] == "25"
    assert ten_bots[-1].startswith("Plan for age 25.")
    assert _AGE_ASK not in ten_bots[-1]


def test_a_later_weight_is_bounded_against_the_target_and_a_lift_is_not_body_weight():
    from onboarding import _CURRENT_WEIGHT_ASK, _WEIGHT_ASK

    asked, asked_bots = run_chat(["want 64 kg"])
    assert asked["answers"]["target"] == "64 kg"
    assert asked["answers"].get("weight") in (None, "")
    assert asked_bots[-1] == _CURRENT_WEIGHT_ASK
    heavy, heavy_bots = run_chat(["want 64 kg", "200 kg"])
    assert heavy["answers"]["target"] == "64 kg"
    assert heavy["answers"].get("weight") in (None, "")
    assert heavy_bots[-1] == _WEIGHT_ASK
    fit, _fit_bots = run_chat(["want 64 kg", "80 kg"])
    assert fit["answers"]["target"] == "64 kg"
    assert fit["answers"]["weight"] == "80 kg"
    lifted, lifted_bots = run_chat(["bench 100 kg, want 64 kg"])
    assert lifted["answers"].get("weight") in (None, "")
    assert lifted["answers"]["target"] == "64 kg"
    assert lifted_bots[-1] == _CURRENT_WEIGHT_ASK
    assert "looks off" not in lifted_bots[-1].lower()
    kept, kept_bots = run_chat(["80 kg, want 48 kg"])
    assert kept["answers"]["weight"] == "80 kg"
    assert kept["answers"]["target"] == "48 kg"
    assert "far from" not in kept_bots[-1].lower()
    assert "looks off" not in kept_bots[-1].lower()
    far, far_bots = run_chat(["80 kg, want 40 kg"])
    assert far["answers"]["weight"] == "80 kg"
    assert far["answers"].get("target") in (None, "")
    assert far_bots[-1] == "That target looks far from 80 kg. What goal weight do you want?"
    second, second_bots = run_chat(["80 kg, want 40 kg", "30 kg"])
    assert second["answers"]["weight"] == "80 kg"
    assert second["answers"].get("target") in (None, "")
    assert second_bots[-1].startswith("Goal, weight, target")
    assert "far from" not in second_bots[-1].lower()
    third, third_bots = run_chat(["80 kg, want 40 kg", "want 20 kg"])
    assert third["answers"]["weight"] == "80 kg"
    assert third["answers"].get("target") in (None, "")
    assert third_bots[-1].startswith("Goal, weight, target")


_TRAINING = "general training, 3 days 45 min, dumbbells, beginner, none"
_PROFILE = "cut, male, 60 kg, 170 cm, no injuries"


def test_a_red_flag_in_a_pain_phrase_holds_before_old_can_save_it():
    from record_confirmation import reply_pause

    from onboarding import hold_is_active

    flagged = (
        ("back pain shooting down my leg", "blood_clot"),
        ("sharp knee pain", "sharp_joint_pain"),
    )
    acute = (
        "severe back pain",
        "stabbing back pain",
        "sharp back pain",
        "back pain with fever",
        "knee pain, cant straighten it",
    )
    for phrase, flag in flagged:
        paused = reply_pause(phrase)
        assert paused is not None, phrase
        assert flag in paused.flags_detected, phrase
    for phrase in [item[0] for item in flagged] + list(acute):
        flag = "injury"
        for item in flagged:
            if item[0] == phrase:
                flag = item[1]
        state, bots = run_chat([
            "hello",
            _marked(f"cut, male, 60 kg, 170 cm, {phrase}", red_flag=flag),
            "old",
            "25",
            _TRAINING,
            "all no",
            "yes",
        ])
        assert state["confirmed"] is False, phrase
        assert state["phase"] == "symptom", phrase
        assert hold_is_active(), phrase
        assert "one yes confirms the plan" not in "\n".join(bots).lower(), phrase
        again, again_bots = run_chat(["hello", "yes"])
        assert again["confirmed"] is False, phrase
        assert again["phase"] == "symptom", phrase
        assert "one yes confirms the plan" not in "\n".join(again_bots).lower(), phrase
        _drop_hold()


def test_an_age_cue_beside_an_injury_clears_age_before_the_injury_branch():
    from onboarding import _AGE_ASK

    phrases = (
        "back pain, im a minor",
        "knee pain, in high school",
        "achilles tendinitis, im not an adult",
        "torn acl, im 15",
        "im 16, sprained ankle",
        "torn acl, 17yo",
    )
    training = ["hello", _PROFILE, "25"]
    confirm = training + [_TRAINING, "all no"]
    for phrase in phrases:
        at_training, training_bots = run_chat(training + [_marked(phrase, minor_signal=True, injury="unclear")])
        assert at_training["confirmed"] is False, phrase
        assert at_training["answers"].get("age") in (None, ""), phrase
        assert training_bots[-1] == _AGE_ASK, phrase
        assert "one yes confirms the plan" not in training_bots[-1].lower(), phrase
        at_confirm, confirm_bots = run_chat(confirm + [_marked(phrase, minor_signal=True, injury="unclear")])
        assert at_confirm["confirmed"] is False, phrase
        assert at_confirm["answers"].get("age") in (None, ""), phrase
        assert confirm_bots[-1] == _AGE_ASK, phrase
        assert "one yes confirms the plan" not in confirm_bots[-1].lower(), phrase
    later, later_bots = run_chat(confirm + [
        _marked("my knee hurts, im 15", minor_signal=True, injury="unclear"),
        "old",
        "yes",
        "yes",
    ])
    assert later["confirmed"] is False
    assert later["answers"].get("age") != "25"
    assert later_bots[-1] == _AGE_ASK
    assert "one yes confirms the plan" not in later_bots[-1].lower()


def test_a_minor_signal_with_an_injury_keeps_it_and_does_not_confirm_none():
    from onboarding import _AGE_ASK, _INJURY_WHEN, hold_is_active

    training = "general training, 3 days 45 min, dumbbells, beginner, none"
    prefix = [
        "hello",
        "cut, male, 60 kg, 170 cm, no injuries",
        "25",
        training,
        "all no",
    ]
    unclear = prefix + [_marked("my knee hurts, im 15", minor_signal=True, injury="unclear")]
    asked, asked_bots = run_chat(unclear)
    assert asked["confirmed"] is False
    assert asked["answers"].get("age") in (None, "")
    assert asked_bots[-1] == _AGE_ASK
    assert asked.get("pending_injury")
    assert asked["answers"].get("injuries") != "none"
    aged, aged_bots = run_chat(unclear + ["25", "yes"])
    assert aged["confirmed"] is False
    assert aged["answers"].get("injuries") != "none"
    assert aged_bots[-2] == _INJURY_WHEN
    assert "one yes confirms the plan" not in aged_bots[-1].lower()
    _drop_hold()

    current = prefix + [
        _marked("my knee hurts, im 15", minor_signal=True, injury="current"),
        "25",
        "yes",
    ]
    held, held_bots = run_chat(current)
    assert held["confirmed"] is False
    assert held["phase"] == "symptom"
    assert held.get("pending_injury")
    assert held["answers"].get("injuries") != "none"
    assert hold_is_active()
    after = "\n".join(held_bots[len(prefix):]).lower()
    assert "one yes confirms the plan" not in after
    _drop_hold()

    flagged = prefix + [
        _marked("my knee hurts, im 15", minor_signal=True, red_flag="chest_pain", injury="old"),
        "25",
        "yes",
    ]
    stopped, stopped_bots = run_chat(flagged)
    assert stopped["confirmed"] is False
    assert stopped["phase"] == "symptom"
    assert stopped["answers"].get("injuries") != "none"
    after = "\n".join(stopped_bots[len(prefix):]).lower()
    assert "one yes confirms the plan" not in after
    _drop_hold()


def test_a_single_message_past_stores_only_an_exact_allowlist_remainder():
    from onboarding import _INJURY_WHEN, hold_is_active

    phrases = (
        "torn acl, old, flares up sometimes",
        "nowhere near healed",
        "far from healed",
        "barely healed",
        "kind of healed",
        "healed-ish",
        "old, still recovering",
        "old, in rehab",
        "old, had surgery last month",
        "old but unstable",
        "old but gives way",
        "torn acl 4 months ago, still recovering",
        "calf tear last year",
        "slipped disc in 2020",
    )
    for phrase in phrases:
        state, bots = run_chat([_marked(f"hold, male, 80 kg, 180 cm, {phrase}", injury="unclear")])
        assert state["answers"].get("injuries") in (None, ""), phrase
        assert state["phase"] != "symptom", phrase
        assert state["confirmed"] is False, phrase
        assert hold_is_active() is False, phrase
        assert bots[-1] == _INJURY_WHEN, phrase


def test_pain_in_more_areas_asks_old_or_recent_and_confirm_pain_holds_the_day():
    from onboarding import _INJURY_WHEN, hold_is_active

    areas = (
        ("shoulder pain", "shoulder"),
        ("hip pain", "hip"),
        ("ankle pain", "ankle"),
        ("neck pain", "neck"),
        ("wrist pain", "wrist"),
        ("lower back pain", "lower back"),
    )
    for phrase, area in areas:
        asked, asked_bots = run_chat([_marked(f"hold, male, 80 kg, 180 cm, {phrase}", injury="unclear")])
        assert asked["answers"].get("injuries") in (None, ""), phrase
        assert asked["phase"] != "symptom", phrase
        assert hold_is_active() is False, phrase
        assert asked_bots[-1] == _INJURY_WHEN, phrase
        stored, _stored_bots = run_chat([
            _marked(f"hold, male, 80 kg, 180 cm, {phrase}", injury="unclear"),
            "old",
            "30",
            "ok",
            "all_no",
            "yes",
        ])
        assert stored["confirmed"] is True, phrase
        assert stored["answers"]["injuries"] == area, phrase
        _drop_hold()
    for phrase in ("my knee hurts",) + tuple(item[0] for item in areas):
        held, held_bots = run_chat(list(_AGE_25) + [_marked(phrase, injury="current")])
        assert held["confirmed"] is False, phrase
        assert held["phase"] == "symptom", phrase
        assert hold_is_active(), phrase
        assert "one yes confirms the plan" not in held_bots[-1].lower(), phrase
        again, again_bots = run_chat(["hello", "yes"])
        assert again["confirmed"] is False, phrase
        assert again["phase"] == "symptom", phrase
        assert hold_is_active(), phrase
        assert "one yes confirms the plan" not in "\n".join(again_bots).lower(), phrase
        _drop_hold()


def test_an_emoji_on_an_old_answer_asks_again_and_yes_7_pm_stays_on_confirm():
    from onboarding import _AGE_ASK, _INJURY_WHEN, hold_is_active

    state, bots = run_chat([
        _marked("hold, male, 80 kg, 180 cm, torn acl", injury="unclear"),
        "old \U0001F605",
    ])
    assert state["answers"].get("injuries") in (None, "")
    assert state["phase"] == "symptom"
    assert state["confirmed"] is False
    assert hold_is_active() is True
    assert "one yes confirms the plan" not in bots[-1].lower()
    _drop_hold()
    clock, clock_bots = run_chat(list(_AGE_25) + ["yes 7 pm"])
    assert clock["confirmed"] is False
    assert clock["phase"] == "confirm"
    assert clock["answers"]["age"] == "25"
    assert clock_bots[-1].startswith("Plan for age 25.")
    assert _AGE_ASK not in clock_bots[-1]


def test_free_text_does_not_confirm_and_a_sentence_is_not_an_old_injury():
    from onboarding import _INJURY_ASK, _blank, apply_reply, submit_age, _ask_injury_when

    blocked, _bots = run_chat([
        "hello",
        "hold, male, 80 kg, 180 cm, general training, 3 days 45 min, bodyweight, beginner, no injuries",
        30,
        "all no",
        "4 days, my knee is wrecked",
        "yes",
    ])
    assert blocked["confirmed"] is False
    assert blocked["answers"].get("injuries") != "knee"
    _drop_hold()
    area = _blank()
    area["phase"] = "intake"
    area["awaiting"] = "injury"
    area["error"] = _INJURY_ASK
    apply_reply(area, "my knee hurts")
    assert area["answers"].get("injuries") in (None, "")
    assert area["answers"].get("injuries") != "old"
    asked = _blank()
    asked["pending_injury"] = "knee"
    _ask_injury_when(asked, "")
    apply_reply(asked, "old", {"minor_signal": False, "red_flag": "none", "injury": "old", "note_ok": "yes"})
    assert asked["answers"].get("injuries") in (None, "")
    assert "old" != asked["answers"].get("injuries")
    _drop_hold()
    aged = _blank()
    assert submit_age(aged, "25") is True
    assert aged["answers"].get("age") in (None, "")
    assert submit_age(aged, "１５") is True
    assert aged["answers"].get("age") in (None, "")
    assert submit_age(aged, 25) is True
    assert aged["answers"]["age"] == "25"
