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
    assert "never change a load or a calorie target without a recorded yes" in PROMPT.lower()
    assert "never raise a load or a calorie target without a recorded yes" not in PROMPT.lower()
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


def test_a_missing_safety_script_stops_the_plan():
    text = PROMPT.lower()
    assert "if it is missing, say so and skip that step" not in text
    assert "if `red_flag_check`, `readiness_screen`, `plan_check`, or `record_confirmation` is missing or returns an error, stop." in text
    assert "do not plan. do not change anything." in text
    assert "if `morning_checkin`, `set_logger`, or `trend_review` is missing, do not change load or calories." in text
    assert "if some other script is missing, say so and skip that step." in text


def test_age_is_always_asked_and_readiness_runs_before_training():
    started = GETTING_STARTED.lower()
    assert "ask age only if" not in started
    assert "always ask age" in started
    assert "they may skip it" in started
    assert "readiness_screen" in started
    assert "check-in" in started
    today = PROMPT.lower().split("## today", 1)[1].split("## ", 1)[0]
    assert "when age is missing, or the user is under 18" in today
    red = today.index("red_flag_check.scan_check_in")
    ready = today.index("readiness_screen.readinessscreen.screen_intake")
    assert red < ready
    assert ready < today.index("morning_checkin.check_in")
    assert ready < today.index("set_logger.suggest_next")


def test_a_red_flag_passes_on_the_check_recommendation():
    safety = PROMPT.lower().split("## safety order", 1)[1].split("## ", 1)[0]
    assert "pass on that check's own recommendation" in safety
    assert "urgent care" in safety
    assert "emergency services" in safety
    assert "don't train through pain" in safety
    assert "signing key" not in PROMPT.lower()
    assert "caller-supplied" not in PROMPT.lower()


def test_first_run_clones_the_repo_and_uses_that_path():
    assert "https://github.com/tradersnow222/gainzbot" in PROMPT
    assert "https://github.com/tradersnow222/gainzbot" in QUICKSTART
    assert "/workspace/gainzbot" in PROMPT
    assert "/workspace/gainzbot" in QUICKSTART
    import_line = "import red_flag_check, readiness_screen, plan_check, record_confirmation"
    assert import_line in PROMPT
    assert import_line in QUICKSTART
    assert "if the clone or the import fails, stop" in PROMPT.lower()
    assert "--branch v0.1.0" in PROMPT
    assert "--branch v0.1.0" in QUICKSTART
    assert "do not fall back to main" in PROMPT.lower()
    assert "do not fall back to main" in QUICKSTART.lower()
    assert TEMPLATE["release_tag"] == "v0.1.0"
    assert "the second message runs readiness_screen, then check_in, then plan_check, then shows the proposal, then asks for the yes" in PROMPT.lower()
    assert "/workspace/gainzbot/data/used_confirmations.json" in PROMPT
    assert "/workspace/gainzbot/data/log.json" in PROMPT
    assert TEMPLATE["repo_url"] == "https://github.com/tradersnow222/gainzbot"
    assert TEMPLATE["repo_path"] == "/workspace/gainzbot"
    assert TEMPLATE["used_list_path"] == "/workspace/gainzbot/data/used_confirmations.json"
    assert TEMPLATE["log_path"] == "/workspace/gainzbot/data/log.json"
    assert "Log this meal: usual breakfast." in TEMPLATE["starter_prompts"]
    guides = TEMPLATE["guides"]
    for name in (
        "saved-logs.md",
        "first-plan.md",
        "onboarding.md",
        "daily-checkin.md",
        "routines.md",
        "dashboard.md",
        "usual-meals.md",
    ):
        assert name in guides.values()
        assert name in PROMPT
        rel = next(value for value in guides.values() if value == name)
        assert not rel.startswith("/")
        assert ".." not in rel.split("/")
    for skill in TEMPLATE["skills"]:
        rel = TEMPLATE["skill_files"][skill]
        assert not rel.startswith("/")
        assert ".." not in rel.split("/")
        text = (ROOT / "template" / rel).read_text(encoding="utf-8")
        assert "/workspace/gainzbot" in text
        assert skill in text
        assert "\u2014" not in text
    assert "do not ask the profile one question at a time" in PROMPT.lower()
    assert "accept none" in PROMPT.lower() or "accepts none" in PROMPT.lower()
    assert "remember_usual" in PROMPT
    assert "plan_builder.py" in PROMPT
    assert "each is opt-in" in PROMPT.lower()


def test_the_docs_do_not_call_the_checks_tamper_proof():
    texts = (PROMPT, QUICKSTART, GETTING_STARTED, PROFILE, json.dumps(TEMPLATE))
    for text in texts:
        assert "tamper-proof" not in text.lower()
        assert "tamper proof" not in text.lower()
        assert "\u2014" not in text
        assert "signing key" not in text.lower()
