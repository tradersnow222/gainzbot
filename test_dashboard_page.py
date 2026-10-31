#!/usr/bin/env python3
"""Locks the dashboard Page layout."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent
PAGE = (ROOT / "template" / "dashboard.md").read_text(encoding="utf-8")


def test_the_page_is_charts_first():
    lowered = PAGE.lower()
    assert "dashboard.py" in lowered
    assert "dashboard.dashboard.build" in lowered
    assert "applied" in lowered and "false" in lowered
    weight = lowered.index("weight chart")
    calories = lowered.index("calories and protein")
    checklist = lowered.index("today's checklist")
    assert weight < calories < checklist
    assert lowered.index("charts first") < weight
    for window in ("7", "28", "90", "365"):
        assert window in PAGE
    assert "not enough data yet" in lowered
    assert "one log is not enough" in lowered
    assert "\u2014" not in PAGE
    skill = (ROOT / "template" / "skills" / "dashboard.md").read_text(encoding="utf-8")
    prompt = (ROOT / "BOT_PROMPT.md").read_text(encoding="utf-8")
    call = "dashboard.Dashboard.build_saved"
    for text in (PAGE, skill, prompt):
        assert call in text
        assert "Dashboard.build" not in text.replace(call, "")
