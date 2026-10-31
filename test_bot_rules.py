#!/usr/bin/env python3
"""Locks the plain-English coach rules."""

from pathlib import Path


RULES = Path("rules/gainzbot.mdc").read_text(encoding="utf-8")


def test_the_rules_file_has_frontmatter():
    assert RULES.startswith("---\n")
    assert "description:" in RULES.split("---")[1]
    assert "alwaysApply: true" in RULES


def test_rules_guide_and_checks_enforce():
    assert "Rules guide, checks enforce." in RULES


def test_safety_order_is_check_in_then_readiness_then_plan_then_yes():
    names = [
        "red_flag_check.scan_check_in",
        "readiness_screen",
        "plan_check",
        "record_confirmation",
    ]
    positions = [RULES.index(name) for name in names]
    assert positions == sorted(positions)


def test_age_caps_stall_and_privacy_are_stated():
    text = RULES.lower()
    assert "not a doctor" in text
    assert "age is missing" in text
    assert "under 18" in text
    assert "protein target" in text
    assert "7 times 24 hours" in text
    assert "22.5 hours" in text
    assert "cut or lose" in text
    assert "gain means more calories" in text
    assert "hold, or no goal" in text
    assert "do not buy anything" in text
    assert "garmin" in text
    assert "what to do today" in text


def test_the_daily_check_in_is_two_messages():
    from pathlib import Path

    from red_flag_check import RedFlagChecker

    text = RULES.lower()
    assert "two messages" in text
    assert 'accept "none"' in text
    assert "4 scores" in text
    assert "second message asks for the yes" in text
    assert "don't train through pain" in text
    today = RULES.lower().split("## today", 1)[1].split("## ", 1)[0]
    assert today.index("red_flag_check.scan_check_in") < today.index("before readiness")
    guide = Path("template/daily-checkin.md").read_text(encoding="utf-8")
    for label in RedFlagChecker.ITEM_LABELS.values():
        assert label in guide
    lowered = guide.lower()
    assert "accept \"none\"" in lowered
    assert "message 2" in lowered
    assert "4 scores" in lowered
    assert lowered.index("scan_check_in") < lowered.index("readiness_screen")
    assert "\u2014" not in RULES
    assert "\u2014" not in guide


def test_checks_catch_mistakes_and_name_the_public_limits():
    assert "catch mistakes" in RULES.lower()
    assert "signing key is in the public repo" in RULES
    assert "caller-supplied string" in RULES
    assert "tamper-proof" not in RULES.lower()
    assert "tamper proof" not in RULES.lower()
    assert "\u2014" not in RULES
