#!/usr/bin/env python3
"""Locks grouped onboarding questions and the profile fields."""

from pathlib import Path

from onboarding import GROUPS, PAR_Q, messages
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
    keys = [key for key, _question in PAR_Q]
    assert keys == list(ReadinessScreen.PAR_Q_RED_FLAGS)
    par = next(group for group in GROUPS if group["id"] == "par_q")
    assert list(par["asks"]) == keys
    assert "everyone" in par["text"].lower()
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
