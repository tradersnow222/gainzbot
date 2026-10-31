#!/usr/bin/env python3
"""A bot-led week. The user only answers the questions."""

from pathlib import Path

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


def sealed_load_history(load, when):
    """One confirmed load row this install actually sealed. Tests only."""
    from record_confirmation import ConfirmationRecorder
    from red_flag_check import RedFlagChecker, is_passing_check_in

    checker = RedFlagChecker()
    answers = {aliases[0]: "no" for _flag, aliases in checker.CHECKLIST_GROUPS}
    check_in = checker.scan_check_in({"symptom_checklist": answers, "notes": "no"})
    if not is_passing_check_in(check_in):
        return []
    plan = {"changes": {"load": load}}
    record = ConfirmationRecorder().record(plan, "yes", "user", check_in)
    if not record.confirmed:
        return []
    return [{
        "date": when,
        "confirmed": True,
        "changes": {"load": load},
        "proposal": plan,
        "record_id": record.record_id,
        "plan_hash": record.plan_hash,
        "quoted_words": record.quoted_words,
        "speaker": record.speaker,
        "timestamp": record.timestamp,
        "issuer_seal": record.issuer_seal,
        "message": record.message,
    }]


def test_seven_days_of_short_answers_adapt_the_plan():
    week = simulate_happy_week(history=sealed_load_history(80, "2026-10-19T07:00:00Z"))
    rows = week["rows"]
    assert len(rows) == 7
    for row in rows:
        assert row["opened"].startswith("Morning.")
        assert len(row["morning_reply"].split()) <= 5
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
    from daily_loop import adult_profile

    loop = DailyLoop(
        load=80,
        minutes=45,
        history=[{
            "date": "2026-10-25T12:00:00Z",
            "confirmed": True,
            "changes": {"load": 80},
        }],
        profile=adult_profile(),
    )
    assert DailyLoop(load=80).history == []
    day = "2026-10-26"
    loop.open_morning(day)
    loop.hear(day, "no 8 fine 45")
    loop.open_evening(day)
    loop.hear(day, "yes easy oats")
    review = loop.weekly("2026-10-26T20:00:00Z")
    assert review["changed"] is False
    assert review["load"] == 80


def test_a_symptom_in_the_morning_pauses_before_the_workout():
    from daily_loop import adult_profile, parse_evening

    loop = DailyLoop(load=80, minutes=45, profile=adult_profile())
    day = "2026-10-26"
    opened = loop.open_morning(day)
    assert opened.startswith("Morning. Any chest pain, dizziness or new pain? no / yes")
    paused = loop.hear(day, "my chest hurts 8 fine 45")
    assert "doctor" in paused.lower()
    assert "easy day" not in paused.lower()
    assert day not in loop.workouts
    assert loop.phase[day] == "paused"
    clear = DailyLoop(load=80, minutes=45, profile=adult_profile())
    clear.open_morning(day)
    follow = clear.hear(day, "no")
    assert follow != opened
    assert "easy day" not in follow.lower()
    assert clear.phase[day] == "morning2"
    assert parse_evening("did not")["did_it"] is False
    assert parse_evening("I did not do it")["did_it"] is False
    assert parse_evening("did")["did_it"] is True
    clear.hear(day, "8 fine")
    clear.open_evening(day)
    missed = clear.hear(day, "did not")
    assert clear.notes[day]["did_it"] is False
    assert clear.notes[day]["ate"] == ""
    assert parse_evening("did not")["ate"] == ""
    for words in ("didn't", "didnt", "did not"):
        parsed = parse_evening(words)
        assert parsed["ate"] == "", words
        assert parsed["did_it"] is False, words
    assert parse_evening("did not chicken")["ate"] == "chicken"
    assert "sealed_load_history" not in Path(__file__).resolve().parent.joinpath("daily_loop.py").read_text(encoding="utf-8")
    assert missed.startswith("Logged the miss")
    evening = DailyLoop(load=80, minutes=45, profile=adult_profile())
    evening.open_morning(day)
    evening.hear(day, "no 8 fine 45")
    evening.open_evening(day)
    flagged = evening.hear(day, "no idea, chest pain")
    assert "doctor" in flagged.lower()
    assert "logged" not in flagged.lower()
    assert evening.phase[day] == "paused"
    assert "did_it" not in evening.notes[day]


def test_a_no_with_anything_else_asks_the_symptom_line_again():
    from daily_loop import _SYMPTOM, adult_profile

    day = "2026-10-26"
    unclear = (
        "no, болит грудь",
        "no no 8 fine 45 (actually chest tight)",
        "no, but new pain in my knee",
        "no 🤕",
        "no idea",
    )
    for reply in unclear:
        loop = DailyLoop(load=80, minutes=45, profile=adult_profile())
        loop.open_morning(day)
        again = loop.hear(day, reply)
        assert again == _SYMPTOM, reply
        assert loop.phase[day] == "symptom"
        assert day not in loop.workouts
    for reply in ("no", "no 8 45", "no 8 fine 45"):
        loop = DailyLoop(load=80, minutes=45, profile=adult_profile())
        loop.open_morning(day)
        text = loop.hear(day, reply)
        assert text != _SYMPTOM, reply
        assert loop.phase[day] != "symptom"
        assert day in loop.workouts or loop.phase[day] == "morning2"


def test_weekly_ignores_an_unsealed_history():
    from daily_loop import adult_profile

    loop = DailyLoop(
        load=80,
        minutes=45,
        history=[{
            "date": "2026-10-19T07:00:00Z",
            "confirmed": True,
            "changes": {"load": 80},
        }],
        profile=adult_profile(),
    )
    day = "2026-10-26"
    loop.open_morning(day)
    loop.hear(day, "no 8 fine 45")
    loop.open_evening(day)
    loop.hear(day, "yes easy oats")
    review = loop.weekly("2026-11-02T07:00:00Z")
    assert review["changed"] is False
    assert review["load"] == 80
