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


def test_a_local_6_30_cron_does_not_shift_across_november_daylight_saving():
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from routines import routine_cron

    assert routine_cron("06:30") == "30 6 * * *"
    guide = Path("template/routines.md").read_text(encoding="utf-8")
    assert "30 6 * * *" in guide
    assert "do not convert the hour to utc" in guide.lower()
    assert "zoneinfo" in guide
    try:
        zone = ZoneInfo("America/Los_Angeles")
    except ZoneInfoNotFoundError:
        raise AssertionError(
            "America/Los_Angeles is missing from the platform time zone database. "
            "template/routines.md documents that this check cannot run without it. "
            "Do not treat a UTC hour as the routine time."
        )
    before = datetime(2026, 10, 31, 6, 30, tzinfo=zone)
    after = datetime(2026, 11, 2, 6, 30, tzinfo=zone)
    assert routine_cron(before.strftime("%H:%M")) == "30 6 * * *"
    assert routine_cron(after.strftime("%H:%M")) == "30 6 * * *"
    assert before.astimezone(timezone.utc).hour != after.astimezone(timezone.utc).hour
    assert before.astimezone(timezone.utc).hour == 13
    assert after.astimezone(timezone.utc).hour == 14


def test_the_first_check_in_is_the_plan_start_not_an_earlier_day():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from routines import first_checkin_day

    zone = ZoneInfo("America/Los_Angeles")
    evening = datetime(2026, 10, 31, 18, 0, tzinfo=zone)
    assert first_checkin_day("2026-11-02", now=evening) == "2026-11-02"
    assert first_checkin_day("2026-10-26", now=evening) == "2026-11-01"
    early = datetime(2026, 10, 31, 6, 0, tzinfo=zone)
    assert first_checkin_day("2026-10-31", now=early) == "2026-10-31"
    assert first_checkin_day("2026-10-26", now=early) == "2026-10-31"


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
    pause_day = "2026-10-27"
    opened = loop.open_morning(pause_day)
    assert opened.startswith("Morning. Any chest pain, trouble breathing, dizziness or new pain? no / yes")
    assert "soreness from 1 to 5" in opened
    paused = loop.hear(pause_day, "my chest hurts 8 fine 45")
    assert "doctor" in paused.lower()
    assert "easy day" not in paused.lower()
    assert pause_day not in loop.workouts
    assert loop.phase[pause_day] == "paused"
    clear = DailyLoop(load=80, minutes=45, profile=adult_profile())
    clear.open_morning(day)
    follow = clear.hear(day, "no")
    assert follow != opened
    assert "easy day" not in follow.lower()
    assert "one more" not in follow.lower()
    assert clear.phase[day] == "workout"
    assert clear.notes[day]["sleep"] == 7
    assert clear.notes[day]["soreness"] == 2
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


def test_the_daily_loop_stops_while_onboarding_is_held():
    from daily_loop import DailyLoop
    from onboarding import run_chat

    run_chat([
        "hello",
        "hold, male, age 25, 80 kg, 180 cm, no injuries",
        "25",
        "ok",
        "all no",
        "my chest hurts",
    ])
    loop = DailyLoop()
    morning = loop.open_morning("2026-10-31")
    assert "tomorrow" in morning.lower()
    assert "medical emergency" in morning.lower()
    heard = loop.hear("2026-10-31", "no, 7, 2")
    assert "tomorrow" in heard.lower()
    assert loop.workouts == {}
    evening = loop.open_evening("2026-10-31")
    assert "tomorrow" in evening.lower()
    review = loop.weekly("2026-10-31T18:00:00Z")
    assert review["changed"] is False
    assert "tomorrow" in review["text"].lower()


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
    assert not is_passing_check_in(checked)
    longer = DailyLoop(load=80, minutes=45, calories=2200, profile=adult_profile())
    longer.open_morning(day)
    longer_text = longer.hear(day, "no, 7, 2, 4, 2")
    assert longer.phase[day] == "workout"
    assert longer.notes[day]["sleep"] == 7
    assert longer.notes[day]["soreness"] == 2
    assert longer.notes[day]["energy"] == 4
    assert longer.notes[day]["stress"] == 2
    assert longer_text.startswith("Today is a push day.")
    assert not is_passing_check_in(RedFlagChecker().scan_check_in({"notes": "no, 7, 2, 4, 2"}))
    nope = DailyLoop(load=80, minutes=45, calories=2200, profile=adult_profile())
    nope.open_morning(day)
    nope_text = nope.hear(day, "nope, 7, 2")
    assert nope.phase[day] == "workout"
    assert nope_text.startswith("Today is a normal day.")
    assert nope.notes[day]["sleep"] == 7
    assert nope.notes[day]["soreness"] == 2


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
        "no idea",
    )
    for reply in unclear:
        loop = DailyLoop(load=80, minutes=45, profile=adult_profile())
        loop.open_morning(day)
        again = loop.hear(day, reply)
        assert again == _SYMPTOM, reply
        assert loop.phase[day] == "symptom"
        assert day not in loop.workouts
    bandage = DailyLoop(load=80, minutes=45, profile=adult_profile())
    bandage.open_morning("2026-10-27")
    paused = bandage.hear("2026-10-27", "no \U0001F915")
    assert bandage.phase["2026-10-27"] == "paused"
    assert "2026-10-27" not in bandage.workouts
    assert "head" in paused.lower() or "doctor" in paused.lower()
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


def _live_week(tmp_path):
    """Mon/Wed/Fri sessions and a Saturday parkrun, like the 2026-10-31 live week."""
    import json

    sessions = []
    for day, name, exercise in (
        ("2026-11-02", "Full body A", "Back squat"),
        ("2026-11-04", "Full body B", "Front squat"),
        ("2026-11-06", "Full body C", "Leg press"),
    ):
        sessions.append({
            "date": day,
            "name": name,
            "load": 80,
            "minutes": 30,
            "exercises": [{"name": exercise, "sets": 3, "reps": "8-12"}],
        })
    week = {
        "plan": {"nutrition": {"calories": 1366}},
        "sessions": sessions,
        "confirmation": {
            "record_id": "rec-live",
            "plan_hash": "abc",
            "saved_at": "2026-10-30T00:00:00Z",
        },
    }
    path = tmp_path / "week.json"
    path.write_text(json.dumps(week), encoding="utf-8")
    return path


def _live_loop(tmp_path):
    from daily_loop import DailyLoop, adult_profile

    profile = adult_profile()
    profile["sport"] = "parkrun"
    profile["sport_day"] = "Saturday"
    profile["days"] = ["2026-11-02", "2026-11-04", "2026-11-06"]
    profile["minutes"] = 30
    return DailyLoop(
        load=80,
        minutes=30,
        profile=profile,
        week_path=str(_live_week(tmp_path)),
    )


def test_a_scored_no_with_a_plain_remark_keeps_the_note(tmp_path):
    import re

    from daily_loop import _SECOND, _SYMPTOM

    saturday = "2026-10-31"
    remark = "no, 7, 2. yep doing parkrun at 9"
    loop = _live_loop(tmp_path)
    loop.open_morning(saturday)
    text = loop.hear(saturday, remark)
    assert text != _SYMPTOM
    assert loop.phase[saturday] == "workout"
    assert loop.notes[saturday]["sleep"] == 7
    assert loop.notes[saturday]["soreness"] == 2
    assert loop.notes[saturday]["note"] == "yep doing parkrun at 9"
    assert loop.notes[saturday].get("energy") is None
    assert text.startswith("Rest day. Enjoy parkrun, keep it conversational.")
    assert "1366 kcal" in text
    assert "Full body A" in text
    assert "Monday" in text
    assert "Today is a normal day" not in text
    assert "30 min" not in text
    assert re.search(r"load\s+\d+", text.lower()) is None
    held = _live_loop(tmp_path)
    held.open_morning(saturday)
    paused = held.hear(saturday, "no, 7, 2. my chest hurts")
    assert saturday not in held.workouts
    assert held.phase[saturday] == "paused"
    assert "doctor" in paused.lower() or "emergency" in paused.lower()
    pause_file = tmp_path / "daily_pause.json"
    if pause_file.exists():
        pause_file.unlink()
    ambiguous = _live_loop(tmp_path)
    ambiguous.open_morning(saturday)
    again = ambiguous.hear(saturday, "no, 7, 2. but new pain in my knee")
    assert again == _SYMPTOM
    assert ambiguous.phase[saturday] == "symptom"


def test_a_day_missing_from_the_confirmed_week_is_a_rest_day(tmp_path):
    import re

    from daily_loop import _MORNING, _SECOND, _SYMPTOM

    saturday = "2026-10-31"
    loop = _live_loop(tmp_path)
    opened = loop.open_morning(saturday)
    assert opened == _SYMPTOM
    assert _MORNING not in opened
    assert "soreness" not in opened.lower()
    assert loop.questions[saturday] == 0
    text = loop.hear(saturday, "no, 7, 2")
    assert text.startswith("Rest day. Enjoy parkrun, keep it conversational.")
    assert "1366 kcal" in text
    assert "Next: Full body A on Monday." in text
    assert "Today is a normal day" not in text
    assert "30 min" not in text
    assert re.search(r"load\s+\d+", text.lower()) is None
    assert loop.phase[saturday] == "workout"
    assert loop.workouts[saturday]["day"] == "rest"
    bare = _live_loop(tmp_path)
    bare.open_morning(saturday)
    cleared = bare.hear(saturday, "no")
    assert cleared != _SECOND
    assert "one more" not in cleared.lower()
    assert cleared.startswith("Rest day. Enjoy parkrun, keep it conversational.")
    assert bare.notes[saturday]["sleep"] == 7
    assert bare.notes[saturday]["soreness"] == 2
    assert bare.phase[saturday] == "workout"


def test_monday_still_sends_full_body_a(tmp_path):
    import re

    from daily_loop import _MORNING, _SYMPTOM

    monday = "2026-11-02"
    loop = _live_loop(tmp_path)
    opened = loop.open_morning(monday)
    assert opened.startswith(_SYMPTOM)
    assert _MORNING in opened
    text = loop.hear(monday, "no, 7, 2")
    assert "Full body A" in text
    assert text.startswith("Full body A.")
    assert "Rest day" not in text
    assert "Today is a normal day" not in text
    assert re.search(r"load\s+\d+", text.lower()) is None
    assert loop.phase[monday] == "workout"
    assert loop.workouts[monday]["name"] == "Full body A"
    assert loop.notes[monday]["sleep"] == 7
    assert loop.notes[monday]["soreness"] == 2


def test_a_scored_no_remark_is_scanned_alone_and_allowlisted(tmp_path):
    from daily_loop import _SYMPTOM

    remarks = (
        "slurred speech",
        "face drooping",
        "palpitations",
        "heart racing",
        "coughing blood",
        "wheezing",
        "lightheaded",
        "vomited",
        "vision blurry",
        "tingling arm",
        "cant feel my feet",
        "cracked rib",
        "knee buckled",
        "sprained ankle",
        "fever",
        "covid",
        "pregnant",
        "chestpain",
        "cp",
        "sob",
        "d1zzy",
        "actually yes",
        "not great",
    )
    pause_file = tmp_path / "daily_pause.json"
    for day in ("2026-11-02", "2026-10-31"):
        for prefix in ("no 7 2", "no, 7, 2."):
            for remark in remarks:
                if pause_file.exists():
                    pause_file.unlink()
                loop = _live_loop(tmp_path)
                loop.open_morning(day)
                text = loop.hear(day, f"{prefix} {remark}")
                assert day not in loop.workouts, (day, prefix, remark, text)
                assert loop.phase[day] != "workout", (day, prefix, remark, text)
                assert "Full body" not in text
                assert not text.startswith("Rest day")
    saturday = "2026-10-31"
    if pause_file.exists():
        pause_file.unlink()
    clear = _live_loop(tmp_path)
    clear.open_morning(saturday)
    text = clear.hear(saturday, "no, 7, 2. yep doing parkrun at 9")
    assert text != _SYMPTOM
    assert clear.phase[saturday] == "workout"
    assert clear.notes[saturday]["note"] == "yep doing parkrun at 9"
    assert text.startswith("Rest day. Enjoy parkrun, keep it conversational.")


def test_open_morning_does_not_reset_a_pause_or_a_hold(tmp_path):
    from daily_loop import DailyLoop, adult_profile
    from onboarding import hold_is_active, run_chat

    monday = "2026-11-02"
    loop = _live_loop(tmp_path)
    loop.open_morning(monday)
    paused = loop.hear(monday, "no 7 2 slurred speech")
    assert loop.phase[monday] == "paused"
    assert monday not in loop.workouts
    again = loop.open_morning(monday)
    assert again == paused
    assert loop.phase[monday] == "paused"
    assert monday not in loop.workouts
    assert "slurred" in (loop.notes[monday].get("reply") or "")
    third = loop.open_morning(monday)
    assert third == paused
    assert monday not in loop.workouts
    held_state, held_bots = run_chat(["hello", "my chest hurts"])
    assert held_state["phase"] == "symptom"
    assert hold_is_active()
    fresh = DailyLoop(load=80, minutes=45, profile=adult_profile())
    opened = fresh.open_morning(monday)
    repeated = fresh.open_morning(monday)
    assert opened == repeated
    assert opened == held_bots[-1]
    assert monday not in fresh.phase
    assert monday not in fresh.workouts
    stayed = fresh.hear(monday, "no, 7, 2")
    assert stayed == opened
    assert monday not in fresh.workouts


def test_a_bare_yes_or_yep_remark_is_not_a_note(tmp_path):
    from daily_loop import _SYMPTOM

    for day in ("2026-11-02", "2026-10-31"):
        for reply in ("no 7 2 yes", "no 7 2 yep", "no, 7, 2. yep", "no, 7, 2. yes"):
            loop = _live_loop(tmp_path)
            loop.open_morning(day)
            text = loop.hear(day, reply)
            assert text == _SYMPTOM, (day, reply, text)
            assert loop.phase[day] == "symptom", (day, reply)
            assert day not in loop.workouts, (day, reply)
            assert loop.notes[day].get("note") in (None, ""), (day, reply)
            assert "Full body" not in text
            assert not text.startswith("Rest day")
    saturday = "2026-10-31"
    clear = _live_loop(tmp_path)
    clear.open_morning(saturday)
    text = clear.hear(saturday, "no, 7, 2. yep doing parkrun at 9")
    assert text != _SYMPTOM
    assert clear.phase[saturday] == "workout"
    assert clear.notes[saturday]["note"] == "yep doing parkrun at 9"


def test_a_pause_loads_on_a_new_daily_loop(tmp_path):
    monday = "2026-11-02"
    first = _live_loop(tmp_path)
    first.open_morning(monday)
    paused = first.hear(monday, "no 7 2 slurred speech")
    assert first.phase[monday] == "paused"
    assert monday not in first.workouts
    second = _live_loop(tmp_path)
    opened = second.open_morning(monday)
    assert opened == paused
    assert second.phase[monday] == "paused"
    assert monday not in second.workouts
    stayed = second.hear(monday, "no, 7, 2")
    assert monday not in second.workouts
    assert second.phase[monday] == "paused"
