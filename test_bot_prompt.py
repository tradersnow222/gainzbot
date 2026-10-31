#!/usr/bin/env python3
"""Locks the bot prompt, the quickstart, and the template package."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROMPT = (ROOT / "BOT_PROMPT.md").read_text(encoding="utf-8")
QUICKSTART = (ROOT / "QUICKSTART.md").read_text(encoding="utf-8")
TEMPLATE = json.loads((ROOT / "template" / "template.json").read_text(encoding="utf-8"))
GETTING_STARTED = (ROOT / "template" / "getting-started.md").read_text(encoding="utf-8")
PROFILE = (ROOT / "template" / "profile.md").read_text(encoding="utf-8")


def test_the_template_names_gainzbot():
    assert TEMPLATE["name"] == "Gainzbot"
    assert isinstance(TEMPLATE["description"], str) and TEMPLATE["description"]
    assert TEMPLATE["instructions_file"] == "BOT_PROMPT.md"
    assert TEMPLATE["getting_started"] == "getting-started.md"
    assert TEMPLATE["memory"] == "profile.md"
    assert len(TEMPLATE["starter_prompts"]) >= 3
    assert "plan_check" in TEMPLATE["skills"]
    assert "record_confirmation" in TEMPLATE["skills"]
    assert "one question at a time" in GETTING_STARTED.lower()
    assert "any sport" in GETTING_STARTED.lower()
    assert "Sport:" in PROFILE


def test_the_prompt_says_when_to_call_each_script():
    assert "one question at a time" in PROMPT.lower()
    assert "what to do today" in PROMPT.lower()
    for name in (
        "red_flag_check.scan_check_in",
        "readiness_screen.ReadinessScreen.screen_intake",
        "plan_check.PlanValidator.validate_plan",
        "record_confirmation.ConfirmationRecorder.record",
        "dashboard.Dashboard.build",
        "morning_checkin.check_in",
        "photo_food_log.store_estimate",
        "photo_food_log.log_line",
        "photo_food_log.left_today",
        "set_logger.log_set",
        "set_logger.suggest_next",
        "set_logger.apply",
        "wearable_import.parse_apple_health",
        "wearable_import.store_summary",
        "wearable_import.fetch_garmin",
        "trend_review.review",
        "trend_review.apply",
    ):
        assert name in PROMPT
    assert "7 times 24 hours" in PROMPT
    assert "cut or lose" in PROMPT.lower()
    assert "one log is not enough" in PROMPT.lower()


def test_the_prompt_keeps_the_safety_order_and_the_horizons():
    safety = PROMPT.lower().split("## safety order", 1)[1].split("## ", 1)[0]
    red = safety.index("red_flag_check.scan_check_in")
    ready = safety.index("readiness_screen.readinessscreen.screen_intake")
    plan = safety.index("plan_check.planvalidator.validate_plan")
    yes = safety.index("record_confirmation.confirmationrecorder.record")
    assert red < ready < plan < yes
    assert "never raise a load or a calorie target without a recorded yes" in PROMPT.lower()
    assert "lifestyle and any sport" in PROMPT.lower()
    progress = PROMPT.lower()
    assert "daily, weekly, monthly, and yearly from logged progress" in progress


def test_the_quickstart_reaches_a_confirmed_plan():
    assert "under 5 minutes" in QUICKSTART.lower()
    assert "grok bot" in QUICKSTART.lower()
    assert "bot_prompt.md" in QUICKSTART.lower()
    start = QUICKSTART.index("```python\n") + len("```python\n")
    end = QUICKSTART.index("```", start)
    block = QUICKSTART[start:end]
    namespace = {}
    exec(block, namespace, namespace)
    assert namespace["record"].confirmed is True


def test_the_docs_do_not_call_the_checks_tamper_proof():
    texts = (PROMPT, QUICKSTART, GETTING_STARTED, PROFILE, json.dumps(TEMPLATE))
    for text in texts:
        assert "tamper-proof" not in text.lower()
        assert "tamper proof" not in text.lower()
        assert "\u2014" not in text
    assert "signing key is in the public repo" in PROMPT
    assert "caller-supplied string" in PROMPT
