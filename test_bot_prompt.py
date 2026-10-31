#!/usr/bin/env python3
"""Locks the bot prompt, the quickstart, and the template package."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROMPT = (ROOT / "BOT_PROMPT.md").read_text(encoding="utf-8")
QUICKSTART = (ROOT / "QUICKSTART.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
TEMPLATE = json.loads((ROOT / "template" / "template.json").read_text(encoding="utf-8"))
GETTING_STARTED = (ROOT / "template" / "getting-started.md").read_text(encoding="utf-8")
PROFILE = (ROOT / "template" / "profile.md").read_text(encoding="utf-8")


def test_the_template_names_gainzbot():
    assert TEMPLATE["name"] == "Gainzbot"
    assert isinstance(TEMPLATE["description"], str) and TEMPLATE["description"]
    assert TEMPLATE["instructions_file"] == "BOT_PROMPT.md"
    assert TEMPLATE["getting_started"] == "template/getting-started.md"
    assert TEMPLATE["memory"] == "template/profile.md"
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
    intake = PROMPT.lower().split("## intake", 1)[1].split("## ", 1)[0]
    assert "always ask age" in intake
    assert "grouped messages" in intake
    assert "do not ask the profile one question at a time" in intake
    today = PROMPT.lower().split("## today", 1)[1].split("## ", 1)[0]
    assert "when age is missing, or the user is under 18" in today
    red = today.index("red_flag_check.scan_check_in")
    ready = today.index("readiness_screen.readinessscreen.screen_intake")
    assert red < ready
    assert ready < today.index("morning_checkin.check_in")
    assert ready < today.index("set_logger.suggest_next")


def test_the_safety_section_describes_doctor_clearance():
    safety = PROMPT.lower().split("## safety order", 1)[1].split("## ", 1)[0]
    assert "the plan follows the doctor's clearance" in safety
    assert "do not ask for proof or a document" in safety
    assert "including chest pain" in safety
    assert "my chest hurts right now" in safety
    assert "does not block the account" in safety
    assert "sounds good" in safety
    assert "let's go" in safety
    assert "do it" in safety
    quick = QUICKSTART.lower()
    assert "the plan follows the doctor's clearance" in quick
    assert "do not ask for proof or a document" in quick
    assert "including chest pain" in quick
    assert "does not block the account" in quick


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
    import_line = "import red_flag_check, readiness_screen, plan_check, record_confirmation, release_check"
    assert import_line in PROMPT
    assert import_line in QUICKSTART
    assert "if the clone or the import fails, stop" in PROMPT.lower()
    assert "--branch <release_tag>" in PROMPT
    assert "--branch <release_tag>" in QUICKSTART
    assert "equals v0.1.0" not in PROMPT
    assert "equals v0.1.0" not in QUICKSTART
    assert "must equal v0.1.0" not in README
    assert "v0.1.0" not in PROMPT
    assert "v0.1.0" not in QUICKSTART
    assert "v0.1.0" not in README
    assert "do not fall back to main" in PROMPT.lower()
    assert "do not fall back to main" in QUICKSTART.lower()
    existing = "git -C /workspace/gainzbot describe --tags --exact-match"
    porcelain = "git -C /workspace/gainzbot status --porcelain"
    fetch = "git -C /workspace/gainzbot fetch --depth 1 origin tag <newer-tag>"
    checkout = "git -C /workspace/gainzbot checkout <newer-tag>"
    assert existing in PROMPT
    assert existing in QUICKSTART
    assert existing in README
    for text in (PROMPT, QUICKSTART, README):
        assert porcelain in text
        assert fetch in text
        assert checkout in text
        lowered = text.lower()
        assert "if it isn't a git repo or the tag doesn't match, stop and ask the user" in lowered
        assert "never delete, move or overwrite" in lowered
        assert "any local edits mean stop and ask" in lowered
        assert "never discard them" in lowered
        assert "to upgrade an existing install to a newer tag" in lowered
        if text is not PROMPT:
            assert "it does not prove this is the newest release" in lowered
            assert "clean, self-consistent install" in lowered
        assert "do not delete `/workspace/gainzbot/data/`" in lowered
        assert "git clean -x" in lowered
        assert "v<semver>" in text
        assert "only place the version is set" in lowered
        assert "release_check.py" in text
        assert "equals `release_tag`" in lowered or "equal `release_tag`" in lowered
    assert "every file path in `template/template.json` is relative to the repo root" in QUICKSTART.lower()
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
        rel = f"template/{name}"
        assert rel in guides.values()
        assert name in PROMPT
        assert not rel.startswith("/")
        assert ".." not in rel.split("/")
    for skill in TEMPLATE["skills"]:
        rel = TEMPLATE["skill_files"][skill]
        assert rel.startswith("template/skills/")
        assert not rel.startswith("/")
        assert ".." not in rel.split("/")
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "/workspace/gainzbot" in text
        assert skill in text
        assert "\u2014" not in text
    assert "do not ask the profile one question at a time" in PROMPT.lower()
    assert "accept none" in PROMPT.lower() or "accepts none" in PROMPT.lower()
    assert "remember_usual" in PROMPT
    assert "plan_builder.py" in PROMPT
    assert "each is opt-in" in PROMPT.lower()


def test_template_json_file_paths_are_repo_root_relative():
    paths = [
        TEMPLATE["instructions_file"],
        TEMPLATE["getting_started"],
        TEMPLATE["memory"],
        *TEMPLATE["skill_files"].values(),
        *TEMPLATE["guides"].values(),
    ]
    assert paths[0] == "BOT_PROMPT.md"
    for rel in paths:
        assert not rel.startswith("/")
        assert ".." not in rel.split("/")
        assert rel == "BOT_PROMPT.md" or rel.startswith("template/")
    assert "every file path in `template/template.json` is relative to the repo root" in QUICKSTART.lower()


def test_the_docs_do_not_call_the_checks_tamper_proof():
    texts = (PROMPT, QUICKSTART, GETTING_STARTED, PROFILE, json.dumps(TEMPLATE))
    for text in texts:
        assert "tamper-proof" not in text.lower()
        assert "tamper proof" not in text.lower()
        assert "\u2014" not in text
        assert "signing key" not in text.lower()
