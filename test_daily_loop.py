#!/usr/bin/env python3
"""A bot-led week. The user only answers the questions."""

from daily_loop import DailyLoop, simulate_happy_week
from routines import change_loop_time, start_daily_loop


def test_one_yes_starts_the_daily_loop_at_default_times():
    started = start_daily_loop("yes")
    assert started["ok"] is True
    assert started["enabled"] == ["daily_checkin", "evening_followup", "weekly_review"]
    assert started["times"]["daily_checkin"] == "07:00"
    assert started["times"]["evening_followup"] == "20:00"
    assert started["times"]["weekly_review"] == "Sun 18:00"
    assert "monthly" not in started["enabled"]
    assert start_daily_loop("yes, but later")["ok"] is False
    changed = change_loop_time("morning 6:30", started["times"])
    assert changed["daily_checkin"] == "06:30"
    assert changed["evening_followup"] == "20:00"
    assert changed["weekly_review"] == "Sun 18:00"
    evening = change_loop_time("evening 9pm", changed)
    assert evening["evening_followup"] == "21:00"
    weekly = change_loop_time("weekly sunday 9am", evening)
    assert weekly["weekly_review"] == "Sunday 09:00"
    assert change_loop_time("morning 25:99", weekly)["daily_checkin"] == "06:30"
    assert change_loop_time("morning 6:30 unless I'm busy", weekly)["daily_checkin"] == "06:30"


def test_a_missed_day_gets_one_nudge_then_the_next_morning():
    loop = DailyLoop()
    nudge = loop.nudge("2026-10-27")
    assert nudge == "Missed today. I'll pick it up in the morning."
    assert loop.nudge("2026-10-27") is None
    morning = loop.open_morning("2026-10-28")
    assert morning.startswith("Morning.")
    assert "missed" not in morning.lower()
    assert "command" not in morning.lower()


def test_seven_days_of_short_answers_adapt_the_plan():
    week = simulate_happy_week()
    rows = week["rows"]
    assert len(rows) == 7
    for row in rows:
        assert row["opened"].startswith("Morning.")
        assert len(row["morning_reply"].split()) <= 4
        assert len("yes easy chicken".split()) <= 4
        assert row["evening"].startswith("Did you do it?")
        assert "command" not in row["opened"].lower()
    normal = rows[0]["workout"]
    sore = rows[1]["workout"]
    sleepy = rows[2]["workout"]
    assert normal["day"] != "easy"
    assert normal["minutes"] == 45
    assert sore["day"] == "easy"
    assert sore["minutes"] < normal["minutes"]
    assert sore["load"] < normal["load"]
    assert "easy day" in sore["text"].lower()
    assert sleepy["day"] == "easy"
    assert sleepy["minutes"] < normal["minutes"]
    assert sleepy["load"] < normal["load"]
    assert "bad sleep" in rows[2]["morning_reply"]
    assert normal["food"] == sore["food"] == "2200 kcal"
    review = week["review"]
    assert review["changed"] is True
    assert review["load"] == 88
    assert review["load"] <= 80 * 1.10
    assert review["food"] == "2200 kcal"
    assert "10 percent" in review["text"]


def test_progress_waits_until_the_load_is_seven_days_old():
    loop = DailyLoop(load=80, minutes=45, confirmed_at="2026-10-25T12:00:00Z")
    day = "2026-10-26"
    loop.open_morning(day)
    loop.hear(day, "8 fine 45")
    loop.open_evening(day)
    loop.hear(day, "yes easy oats")
    review = loop.weekly("2026-10-26T20:00:00Z")
    assert review["changed"] is False
    assert review["load"] == 80
