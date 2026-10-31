#!/usr/bin/env python3
"""Locks grouped onboarding questions and the profile fields."""

from pathlib import Path

from onboarding import GROUPS, HAPPY_PATH, PAR_Q, messages, question_one, run_chat
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
        "ok",
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
    assert state["confirmed"] is True
    assert len(bots) == 2
    assert "par-q" not in bots[0].lower()
    assert "one yes confirms the plan" in bots[0].lower()
