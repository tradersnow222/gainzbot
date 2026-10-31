#!/usr/bin/env python3
"""Locks the four opt-in reminder routines."""

from pathlib import Path

from routines import OFFERS, enable, offer


ROOT = Path(__file__).resolve().parent


def test_four_routines_start_off():
    shown = offer()
    assert [item["id"] for item in shown] == [
        "daily_checkin",
        "evening_followup",
        "weekly_review",
        "monthly_review",
        "yearly_review",
    ]
    assert [item["window_days"] for item in OFFERS] == [None, None, 7, 28, 365]
    assert all(item["enabled"] is False for item in shown)


def test_each_routine_is_opt_in():
    refused = enable("weekly_review", "sure")
    assert refused["enabled"] is False
    assert enable("weekly_review", True)["enabled"] is False
    assert enable("all", "yes")["ok"] is False
    turned = enable("weekly_review", "yes")
    assert turned["enabled"] is True
    assert turned["id"] == "weekly_review"
    assert "others stay off" in turned["message"]
    yearly = enable("yearly_review", "Yes, I confirm.")
    assert yearly["enabled"] is True
    assert yearly["window_days"] == 365


def test_a_picked_routine_and_time_is_the_yes():
    picked = enable("weekly_review", "weekly review on Sunday at 8")
    assert picked["enabled"] is True
    assert picked["id"] == "weekly_review"
    assert enable("daily_checkin", "daily check-in at 7")["enabled"] is True
    assert enable("daily_checkin", "daily check-in")["enabled"] is False
    assert enable("monthly_review", "the 1st at 9am")["enabled"] is False
    assert enable("yearly_review", "daily check-in at 8")["enabled"] is False
    assert enable("weekly_review", "maybe Sunday")["enabled"] is False
    assert enable("weekly_review", "stop texting me at night")["enabled"] is False
    assert enable("daily_checkin", "never, 3am is fine lol")["enabled"] is False
    assert enable("weekly_review", "i'll think about it tonight")["enabled"] is False
    assert enable("weekly_review", "sunday unless I'm busy")["enabled"] is False
    assert enable("weekly_review", "weekly review on sunday unless I'm busy")["enabled"] is False
    assert enable("weekly_review", "weekly review at 25:99")["enabled"] is False
    assert enable("daily_checkin", "daily check-in at 25:99")["enabled"] is False


def test_the_guide_lists_each_routine_as_opt_in():
    guide = (ROOT / "template" / "routines.md").read_text(encoding="utf-8")
    lowered = guide.lower()
    assert "each is opt-in" in lowered
    assert "that pick is the yes" in lowered
    assert "daily check-in" in lowered
    assert "evening follow-up" in lowered
    assert "weekly review" in lowered
    assert "monthly review" in lowered
    assert "yearly review" in lowered
    assert "\u2014" not in guide
