#!/usr/bin/env python3
"""Locks grouped onboarding questions and the profile fields."""

from pathlib import Path

import pytest

from onboarding import GROUPS, HAPPY_PATH, PAR_Q, _profile, messages, question_one, run_chat
from readiness_screen import ReadinessScreen


ROOT = Path(__file__).resolve().parent


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
    from datetime import date

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
        assert state["turns"] <= 5, reply
        assert len(bots) <= 5, reply
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
        assert state["first_checkin"] == first_checkin_day(min(days)), reply
        assert date.fromisoformat(state["first_checkin"]).weekday() == 5, reply
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

    asked, asked_bots = run_chat(list(HAPPY_PATH[:-1]) + ["wait, I'm actually 15"])
    assert asked["confirmed"] is False
    assert asked["answers"]["age"] == "30"
    assert asked["record"] is None
    assert asked_bots[-1] == _AGE_ASK
    state, bots = run_chat(list(HAPPY_PATH[:-1]) + ["wait, I'm actually 15", "15"])
    assert state["confirmed"] is False
    assert state["answers"]["age"] == "15"
    assert state["record"] is None
    text = bots[-1].lower()
    assert "under 18" in text
    assert "training" in text
    assert "calorie" in text
    assert "protein" in text
    assert "one yes confirms the plan" not in text
    later, later_bots = run_chat(list(HAPPY_PATH[:-1]) + ["wait, I'm actually 15", "15", "yes"])
    assert later["confirmed"] is False
    assert later["answers"]["age"] == "15"
    assert later["record"] is None or later["record"].confirmed is False
    assert "training" in later_bots[-1].lower()
    assert "calorie" in later_bots[-1].lower()


_AGE_25 = (
    "hello",
    "hold, male, age 25, 80 kg, 180 cm",
    "ok",
    "all no",
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
    state, bots = run_chat(list(_AGE_25) + [reply])
    assert state["confirmed"] is False, reply
    assert state["answers"]["age"] == "25", reply
    assert state["record"] is None, reply
    assert bots[-1] == _AGE_ASK, reply
    assert "one yes confirms the plan" not in bots[-1].lower(), reply
    later, later_bots = run_chat(list(_AGE_25) + [reply, "yes"])
    assert later["confirmed"] is False, reply
    assert later["answers"]["age"] == "25", reply
    assert later_bots[-1] == _AGE_ASK, reply


@pytest.mark.parametrize("reply", _AGE_HINTS)
def test_readiness_runs_on_the_typed_age_not_the_hint(reply):
    state, bots = run_chat(list(_AGE_25) + [reply, "15"])
    assert state["confirmed"] is False, reply
    assert state["answers"]["age"] == "15", reply
    assert state["record"] is None, reply
    text = bots[-1].lower()
    assert "under 18" in text, reply
    assert "training" in text, reply
    assert "calorie" in text, reply
    assert "protein" in text, reply
    assert "one yes confirms the plan" not in text, reply
    later, later_bots = run_chat(list(_AGE_25) + [reply, "15", "yes"])
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
    assert at_bots[-1] == _AGE_ASK
    typed, typed_bots = run_chat(list(_AGE_25) + ["at 7", "25"])
    assert typed["confirmed"] is False
    assert typed["answers"]["age"] == "25"
    assert "one yes confirms the plan" in typed_bots[-1].lower()
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
    state, bots = run_chat(list(_AGE_25) + ["minor", "26"])
    assert state["confirmed"] is False
    assert state["answers"]["age"] == "26"
    assert "one yes confirms the plan" in bots[-1].lower()
    assert "How old are you?" not in bots[-1]
    done, _bots = run_chat(list(_AGE_25) + ["minor", "26", "yes"])
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
    low, low_bots = run_chat(["hello", "hold, male, age 30, 20 kg, 180 cm"])
    assert low["answers"].get("weight") != "20 kg"
    assert "age" in low["answers"]
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
    done, done_bots = run_chat(["all no", "yes"])
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
    from onboarding import _AGE_ASK

    state, bots = run_chat(list(_AGE_25) + ["sounds maybe"])
    assert state["confirmed"] is False
    assert state["answers"]["age"] == "25"
    assert state["record"] is None
    assert bots[-1] == _AGE_ASK
    assert "one yes confirms the plan" not in bots[-1].lower()
    later, later_bots = run_chat(list(_AGE_25) + ["sounds maybe", "yes"])
    assert later["confirmed"] is False
    assert later["answers"]["age"] == "25"
    assert later_bots[-1] == _AGE_ASK
    refused, refused_bots = run_chat(list(_AGE_25) + ["sounds maybe", "15"])
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
    state, bots = run_chat([
        "running, 4 days, 40 min, dumbbells, beginner, no injuries",
    ])
    assert state["answers"]["sport"] == "running"
    assert state["answers"]["equipment"] == "dumbbells"
    assert "weight" in bots[0].lower()
    assert "par-q" not in bots[0].lower()
    done, later = run_chat([
        "running, 4 days, 40 min, dumbbells, beginner, no injuries",
        "hold, male, age 30, 80 kg, 180 cm",
        "all no",
        "yes",
    ])
    assert done["confirmed"] is True
    assert len(later) <= 5


def test_everything_at_once_skips_questions_already_answered():
    blob = (
        "hold, male, age 30, 80 kg, 180 cm, target 80 kg, "
        "general training, 3 days, 45 min, bodyweight, beginner, no injuries, all no"
    )
    state, bots = run_chat([blob, "yes"])
    assert state["confirmed"] is False
    assert state["answers"]["goal"] == "hold"
    assert state["answers"]["sex"] == "male"
    assert state["answers"]["age"] == "30"
    assert state["answers"]["weight"] == "80 kg"
    assert state["answers"]["height"] == "180 cm"
    assert state["answers"]["sport"] == "general training"
    assert state["answers"]["training_days"] == "3"
    assert all(value is not False for value in state["par_q"].values())
    assert bots[-1].startswith("Still need a yes or no:")
    assert "one yes confirms the plan" not in bots[-1].lower()
    done, later = run_chat([blob, "all no", "yes"])
    assert done["confirmed"] is True
    assert len(done["par_q"]) == len(PAR_Q)
    assert all(value is False for value in done["par_q"].values())
    assert "confirm" in later[-1].lower()


def test_ok_does_not_invent_age_sex_weight_or_height():
    state, bots = run_chat(["hello", "cut", "ok", "ok", "all no", "yes"])
    assert state["confirmed"] is False
    assert state["answers"].get("goal") == "cut"
    for key in ("age", "sex", "weight", "height"):
        assert state["answers"].get(key) in (None, "")
    assert "1780" not in "\n".join(bots)
    assert all("kcal" not in turn.lower() for turn in bots)
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

    body = ["hold, male, age 30, 80 kg, 180 cm", "ok"]
    skipped, skip_bots = run_chat(body + ["skip", "yes"])
    assert skipped["confirmed"] is False
    assert skipped.get("par_q_skipped") is True
    assert skipped["par_q"] == {}
    assert skip_bots[-1].startswith("Still need a yes or no:")
    assert skip_bots[-1].count("\n") == 0
    negated, neg_bots = run_chat(body + ["not all no, chest pain yes", "yes"])
    assert negated["confirmed"] is False
    assert negated["par_q"]["chest_pain_at_rest"] is True
    assert negated["par_q"]["chest_pain_during_activity"] is True
    assert "1780" not in "\n".join(neg_bots)
    mixed, mixed_bots = run_chat(body + ["chest pain yes, rest no"])
    assert mixed["confirmed"] is False
    assert mixed["par_q"]["chest_pain_at_rest"] is False
    assert mixed["par_q"]["chest_pain_during_activity"] is True
    asked = mixed_bots[-1]
    assert asked.startswith("Still need a yes or no:")
    assert asked.count("\n") == 0
    assert "chest pain at rest" not in asked.lower()
    assert "chest pain during activity" not in asked.lower()
    for key, _question in PAR_Q:
        if key.startswith("chest_pain"):
            continue
        assert key.replace("_", " ") in asked
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


def test_all_no_counts_only_when_the_whole_reply_is_that_phrase():
    body = ["hold, male, age 30, 80 kg, 180 cm", "ok"]
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
        assert bots[-2].startswith("Still need a yes or no:"), reply
        assert "\n" not in bots[-2]
        assert bots[-1].startswith("Still need a yes or no:")
    kept = (
        ("medication yes, all no", "currently_taking_medications"),
        ("joint problem yes, all no", "bone_joint_problem_worsened_by_activity"),
        ("supervised only yes, otherwise all no", "doctor_advised_supervised_only"),
    )
    for reply, key in kept:
        state, bots = run_chat(body + [reply, "yes"])
        assert state["confirmed"] is False, reply
        assert state["par_q"].get(key) is True, reply
        assert all(value is not False for value in state["par_q"].values()), reply
        assert bots[-1].startswith("Still need a yes or no:"), reply
        assert "\n" not in bots[-1]
    chest, chest_bots = run_chat(body + ["chest pain yes. all no", "yes"])
    assert chest["confirmed"] is False
    assert chest["par_q"]["chest_pain_at_rest"] is True
    assert chest["par_q"]["chest_pain_during_activity"] is True
    assert all(value is not False for value in chest["par_q"].values())
    assert chest_bots[-1].startswith("Still need a yes or no:")
    assert "\n" not in chest_bots[-1]
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
    )
    for reply in accepted:
        state, _bots = run_chat(body + [reply, "yes"])
        assert state["confirmed"] is True, reply
        assert len(state["par_q"]) == len(PAR_Q)
        assert all(value is False for value in state["par_q"].values())
    longest, asked = run_chat(body + ["chest pain at rest yes, rest no"])
    assert longest["par_q"]["chest_pain_at_rest"] is True
    assert "chest pain at rest" not in asked[-1].lower()


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
