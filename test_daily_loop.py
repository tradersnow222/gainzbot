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


def test_the_first_check_in_is_the_saturday_before_a_monday_start():
    from routines import first_checkin_day

    assert first_checkin_day("2026-10-26") == "2026-10-24"
    assert first_checkin_day("2026-10-24") == "2026-10-24"
    assert first_checkin_day("2026-10-31") == "2026-10-31"


def test_a_rest_day_asks_only_the_symptom_line():
    from daily_loop import DailyLoop, _MORNING, _SYMPTOM, adult_profile

    profile = adult_profile()
    profile["days"] = ["2026-10-26", "2026-10-28"]
    rest = DailyLoop(load=80, minutes=45, profile=profile)
    opened = rest.open_morning("2026-10-27")
    assert opened == _SYMPTOM
    assert "sleep" not in opened.lower()
    assert rest.questions["2026-10-27"] == 0
    session = DailyLoop(load=80, minutes=45, profile=profile)
    asked = session.open_morning("2026-10-26")
    assert asked.startswith(_SYMPTOM)
    assert _MORNING in asked
    assert "soreness from 1 to 5" in asked
    assert "energy" not in asked.lower()
    assert "stress" not in asked.lower()


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
    assert opened.startswith("Morning. Any chest pain, trouble breathing, dizziness or new pain? no / yes")
    assert "soreness from 1 to 5" in opened
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
    salad = parse_evening("did not, ate salad")
    assert salad["did_it"] is False
    assert salad["ate"] == "salad"
    logged = DailyLoop(load=80, minutes=45, profile=adult_profile())
    logged.open_morning(day)
    logged.hear(day, "no 8 fine 45")
    logged.open_evening(day)
    logged.hear(day, "did not, ate salad")
    assert logged.notes[day]["did_it"] is False
    assert logged.notes[day]["ate"] == "salad"
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


def test_evening_food_does_not_invent_a_miss():
    from daily_loop import adult_profile, parse_evening

    unknown = parse_evening("yes, no idea what I ate")
    assert unknown["did_it"] is True
    assert unknown["ate"] is None
    bare = parse_evening("ate salad")
    assert bare["ate"] == "salad"
    assert bare["did_it"] is None
    day = "2026-10-26"
    loop = DailyLoop(load=80, minutes=45, profile=adult_profile())
    loop.open_morning(day)
    loop.hear(day, "no 8 fine 45")
    loop.open_evening(day)
    logged = loop.hear(day, "yes, no idea what I ate")
    assert loop.notes[day]["did_it"] is True
    assert loop.notes[day]["ate"] is None
    assert logged.startswith("Logged.")
    assert not logged.startswith("Logged the miss")
    food = DailyLoop(load=80, minutes=45, profile=adult_profile())
    food.open_morning(day)
    food.hear(day, "no 8 fine 45")
    food.open_evening(day)
    asked = food.hear(day, "ate salad")
    assert food.notes[day]["ate"] == "salad"
    assert food.notes[day]["did_it"] is None
    assert asked == "Did you do the workout?"
    assert "\n" not in asked
    assert food.phase[day] == "evening"
    done = food.hear(day, "yes")
    assert done.startswith("Logged.")
    assert food.notes[day]["did_it"] is True
    assert food.notes[day]["ate"] == "salad"
    assert food.phase[day] == "done"


def test_the_onboarding_profile_opens_the_day():
    from onboarding import HAPPY_PATH, _profile, run_chat

    state, _bots = run_chat(HAPPY_PATH)
    profile = _profile(state)
    assert "days" in profile
    day = "2026-10-26"
    loop = DailyLoop(profile=profile)
    opened = loop.open_morning(day)
    assert opened.startswith("Morning.")
    workout = loop.hear(day, "no 8 fine 45")
    assert "Unknown key" not in workout
    assert loop.phase[day] == "workout"
    assert day in loop.workouts
    junk = dict(profile)
    junk["kcal"] = 1
    blocked = DailyLoop(profile=junk)
    blocked.open_morning(day)
    refused = blocked.hear(day, "no 8 fine 45")
    assert "Unknown key: 'kcal'" in refused
    assert blocked.phase[day] == "paused"


def test_a_confirmed_week_returns_that_session_without_a_yes(tmp_path):
    import json

    from daily_loop import DailyLoop, adult_profile

    day = "2026-11-02"
    exercises = [
        {"name": "Bench press", "sets": 4, "reps": "6-10"},
        {"name": "Barbell row", "sets": 4, "reps": "6-10"},
    ]
    week = {
        "plan": {"training": {"current_load": 100, "previous_load": 100}},
        "sessions": [{
            "date": day,
            "name": "Upper",
            "load": 100,
            "minutes": 45,
            "experience": "intermediate",
            "exercises": exercises,
        }],
        "confirmation": {
            "record_id": "rec-1",
            "plan_hash": "abc",
            "saved_at": "2026-10-31T00:00:00Z",
        },
    }
    path = tmp_path / "week.json"
    path.write_text(json.dumps(week), encoding="utf-8")
    loop = DailyLoop(load=80, minutes=45, calories=2200, profile=adult_profile(), week_path=str(path))
    loop.open_morning(day)
    text = loop.hear(day, "no, 7, 2, 4, 2")
    assert loop.phase[day] == "workout"
    assert loop.workouts[day]["name"] == "Upper"
    assert loop.workouts[day]["exercises"] == exercises
    assert loop.workouts[day]["needs_yes"] is False
    assert text.startswith("Upper.")
    assert "Bench press" in text
    assert "Barbell row" in text
    assert "yes" not in text.lower()
    assert "push" not in text.lower()
    assert "Pick a weight you can lift 10 times with 2 reps left." in text
    raised = DailyLoop(
        load=100,
        minutes=45,
        profile=adult_profile(),
        week_path=str(path),
        history=[{
            "date": "2026-10-25T12:00:00Z",
            "confirmed": True,
            "changes": {"load": 100},
        }],
    )
    raised.open_morning(day)
    raised_text = raised.hear(day, "no, 7, 2, 4, 2")
    assert raised.workouts[day]["name"] == "Upper"
    assert raised.workouts[day]["needs_yes"] is True
    assert "yes" in raised_text.lower()
    assert raised.workouts[day]["load"] == 110


def test_a_clear_no_with_sleep_and_soreness_sends_the_session_in_one_turn():
    from daily_loop import DailyLoop, adult_profile
    from red_flag_check import RedFlagChecker, is_passing_check_in

    day = "2026-10-26"
    loop = DailyLoop(load=80, minutes=45, calories=2200, profile=adult_profile())
    loop.open_morning(day)
    text = loop.hear(day, "no, 7, 2")
    assert loop.phase[day] == "workout"
    assert day in loop.workouts
    assert text.startswith("Today is a normal day.")
    assert "45 min" in text
    assert "none" not in text.lower()
    assert "checklist" not in text.lower()
    assert loop.notes[day]["sleep"] == 7
    assert loop.notes[day]["soreness"] == 2
    checked = RedFlagChecker().scan_check_in({"notes": "no, 7, 2"})
    assert is_passing_check_in(checked)
    longer = DailyLoop(load=80, minutes=45, calories=2200, profile=adult_profile())
    longer.open_morning(day)
    longer_text = longer.hear(day, "no, 7, 2, 4, 2")
    assert longer.phase[day] == "workout"
    assert longer.notes[day]["sleep"] == 7
    assert longer.notes[day]["soreness"] == 2
    assert longer.notes[day]["energy"] == 4
    assert longer.notes[day]["stress"] == 2
    assert longer_text.startswith("Today is a push day.")
    assert is_passing_check_in(RedFlagChecker().scan_check_in({"notes": "no, 7, 2, 4, 2"}))


def test_no_but_palpitations_does_not_send_the_session():
    from daily_loop import DailyLoop, adult_profile
    from red_flag_check import RedFlagChecker, clear_safety_no, is_passing_check_in

    reply = "no but I have palpitations"
    assert clear_safety_no(reply) is False
    day = "2026-10-26"
    loop = DailyLoop(load=80, minutes=45, profile=adult_profile())
    loop.open_morning(day)
    text = loop.hear(day, reply)
    assert day not in loop.workouts
    assert loop.phase[day] == "paused"
    assert "medical emergency" in text.lower()
    scanned = RedFlagChecker().scan_check_in({"notes": reply})
    assert scanned.pause_plan
    assert "palpitations" in scanned.flags_detected
    assert not is_passing_check_in(scanned)


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


def test_an_unreadable_seal_key_stops_the_morning(monkeypatch, tmp_path):
    import os

    from daily_loop import adult_profile
    from seal_secret import DATA_FILE_MESSAGE

    path = tmp_path / "seal.key"
    path.write_bytes(b"k" * 32)
    before = path.read_bytes()
    monkeypatch.setattr("seal_secret._key_path", lambda: str(path))
    real_open = open

    def guarded(file, *args, **kwargs):
        target = file if isinstance(file, (str, bytes)) else getattr(file, "name", None)
        if target is not None and os.path.abspath(str(target)) == os.path.abspath(path):
            raise PermissionError("blocked")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", guarded)
    day = "2026-10-26"
    loop = DailyLoop(load=80, minutes=45, profile=adult_profile())
    loop.open_morning(day)
    text = loop.hear(day, "no 8 fine 45")
    assert text == DATA_FILE_MESSAGE
    assert day not in loop.workouts
    descriptor = os.open(path, os.O_RDONLY)
    try:
        assert os.read(descriptor, 64) == before
    finally:
        os.close(descriptor)
