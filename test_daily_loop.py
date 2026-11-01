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
    from safety_pending import clear_pending

    clear_pending(loop._safety_directory(), "daily")
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
        "no, but new pain in my knee",
        "no idea",
    )
    for reply in unclear:
        loop = DailyLoop(load=80, minutes=45, profile=adult_profile())
        _reset_daily(loop)
        loop.open_morning(day)
        again = loop.hear(day, reply)
        assert again == _SYMPTOM, reply
        assert loop.phase[day] == "symptom"
        assert day not in loop.workouts
    tight = DailyLoop(load=80, minutes=45, profile=adult_profile())
    tight.open_morning(day)
    tight_text = tight.hear(day, "no no 8 fine 45 (actually chest tight)")
    assert tight.phase[day] == "paused"
    assert "medical emergency" in tight_text.lower()
    bandage = DailyLoop(load=80, minutes=45, profile=adult_profile())
    bandage.open_morning("2026-10-27")
    paused = bandage.hear("2026-10-27", "no \U0001F915")
    assert bandage.phase["2026-10-27"] == "paused"
    assert "2026-10-27" not in bandage.workouts
    assert "head" in paused.lower() or "doctor" in paused.lower()
    for reply in ("no", "no 8 45", "no 8 fine 45"):
        loop = DailyLoop(load=80, minutes=45, profile=adult_profile())
        _reset_daily(loop)
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
    text = loop.hear(saturday, remark, {
        "minor_signal": False,
        "red_flag": "none",
        "injury": "none",
        "note_ok": True,
    })
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
    _clear_day_files(tmp_path)
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
    for day in ("2026-11-02", "2026-10-31"):
        for prefix in ("no 7 2", "no, 7, 2."):
            for remark in remarks:
                _clear_day_files(tmp_path)
                loop = _live_loop(tmp_path)
                loop.open_morning(day)
                text = loop.hear(day, f"{prefix} {remark}")
                assert day not in loop.workouts, (day, prefix, remark, text)
                assert loop.phase[day] != "workout", (day, prefix, remark, text)
                assert "Full body" not in text
                assert not text.startswith("Rest day")
    saturday = "2026-10-31"
    _clear_day_files(tmp_path)
    clear = _live_loop(tmp_path)
    clear.open_morning(saturday)
    text = clear.hear(saturday, "no, 7, 2. yep doing parkrun at 9", {
        "minor_signal": False,
        "red_flag": "none",
        "injury": "none",
        "note_ok": True,
    })
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
    import os

    from daily_loop import _SYMPTOM

    for day in ("2026-11-02", "2026-10-31"):
        for reply in ("no 7 2 yes", "no 7 2 yep", "no, 7, 2. yep", "no, 7, 2. yes"):
            _clear_day_files(tmp_path)
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
    _clear_day_files(tmp_path)
    clear = _live_loop(tmp_path)
    clear.open_morning(saturday)
    text = clear.hear(saturday, "no, 7, 2. yep doing parkrun at 9", {
        "minor_signal": False,
        "red_flag": "none",
        "injury": "none",
        "note_ok": True,
    })
    assert text != _SYMPTOM
    assert clear.phase[saturday] == "workout"
    assert clear.notes[saturday]["note"] == "yep doing parkrun at 9"


def test_an_evening_reply_after_a_saved_pause_does_not_crash(tmp_path):
    monday = "2026-11-02"
    first = _live_loop(tmp_path)
    first.open_morning(monday)
    paused = first.hear(monday, "no 7 2 slurred speech")
    assert first.phase[monday] == "paused"
    second = _live_loop(tmp_path)
    assert monday not in second.notes
    second.open_evening(monday)
    text = second.hear(monday, "yes easy oats")
    assert isinstance(text, str)
    assert text
    assert text == paused
    assert second.notes.get(monday, {}).get("did_it") is not True


def test_a_saved_pause_does_not_hide_an_unreadable_data_file(monkeypatch, tmp_path):
    import os

    from seal_secret import DATA_FILE_MESSAGE

    monday = "2026-11-02"
    first = _live_loop(tmp_path)
    first.open_morning(monday)
    paused = first.hear(monday, "no 7 2 slurred speech")
    assert first.phase[monday] == "paused"
    assert DATA_FILE_MESSAGE not in paused
    path = tmp_path / "seal.key"
    path.write_bytes(b"k" * 32)
    monkeypatch.setattr("seal_secret._key_path", lambda: str(path))
    real_open = open

    def guarded(file, *args, **kwargs):
        target = file if isinstance(file, (str, bytes)) else getattr(file, "name", None)
        if target is not None and os.path.abspath(str(target)) == os.path.abspath(path):
            raise PermissionError("blocked")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", guarded)
    second = _live_loop(tmp_path)
    opened = second.open_morning(monday)
    assert opened == DATA_FILE_MESSAGE
    assert opened != paused
    heard = second.hear(monday, "yes easy oats")
    assert heard == DATA_FILE_MESSAGE


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


def _safety(flag="none", injury="none", minor=False):
    return {
        "minor_signal": minor,
        "red_flag": flag,
        "injury": injury,
        "note_ok": False,
    }


def test_labels_run_before_a_workout_or_an_evening_log(tmp_path):
    monday = "2026-11-02"
    for labels in (
        _safety("palpitations"),
        _safety(injury="current"),
        _safety(minor=True),
    ):
        loop = _live_loop(tmp_path)
        loop.open_morning(monday)
        text = loop.hear(monday, "no sore 7", labels)
        assert monday not in loop.workouts
        if labels["minor_signal"]:
            assert "how old are you" in text.lower()
        else:
            assert loop.phase[monday] == "paused"
            assert "medical emergency" not in text.lower()
        _clear_day_files(tmp_path)
    second = _live_loop(tmp_path)
    second.open_morning(monday)
    second.hear(monday, "no, 7")
    assert second.phase[monday] in {"morning2", "signals", "symptom"}
    held = second.hear(monday, "8 2 tired", _safety("palpitations"))
    assert second.phase[monday] == "paused"
    assert monday not in second.workouts
    assert "medical emergency" not in held.lower()
    _clear_day_files(tmp_path)
    evening = _live_loop(tmp_path)
    evening.open_morning(monday)
    evening.hear(monday, "no 8 fine 45")
    evening.phase[monday] = "evening"
    logged = evening.hear(monday, "did it, heart racing after", _safety("palpitations"))
    assert evening.phase[monday] == "paused"
    assert evening.notes.get(monday, {}).get("did_it") is None
    assert "logged" not in logged.lower()


def _minor_labels():
    return {
        "minor_signal": True,
        "red_flag": "none",
        "injury": "none",
        "note_ok": False,
    }


def _reset_daily(loop):
    """Drop a same-day pause, unclear count, and pending safety record."""
    import os

    from safety_pending import clear_pending

    clear_pending(os.path.dirname(loop._pause_file()), "daily")
    for path in (loop._pause_file(), loop._unclear_path()):
        if os.path.isfile(path):
            os.remove(path)


def _clear_day_files(tmp_path):
    from safety_pending import clear_pending

    clear_pending(str(tmp_path), "daily")
    for name in ("daily_pause.json", "daily_unclear.json"):
        found = tmp_path / name
        if found.exists():
            found.unlink()


def test_an_age_check_blocks_the_workout_until_a_typed_int(tmp_path):
    day = "2026-11-02"
    loop = _live_loop(tmp_path)
    loop.open_morning(day)
    asked = loop.hear(day, "no sore 7", _minor_labels())
    assert "how old are you" in asked.lower()
    assert day not in loop.workouts
    later = loop.hear(day, "no, 7, 2")
    assert "Full body A" not in later
    assert day not in loop.workouts
    _clear_day_files(tmp_path)
    young = _live_loop(tmp_path)
    young.open_morning(day)
    young.hear(day, "no sore 7", _minor_labels())
    blocked = young.hear(day, "17")
    assert "Full body A" not in blocked
    still = young.hear(day, "no")
    assert "Full body A" not in still
    assert day not in young.workouts
    _clear_day_files(tmp_path)
    adult = _live_loop(tmp_path)
    adult.open_morning(day)
    adult.hear(day, "no sore 7", _minor_labels())
    cleared = adult.hear(day, "30")
    assert "Full body A" not in cleared
    assert day not in adult.workouts
    workout = adult.hear(day, "no, 7, 2")
    assert "Full body A" in workout


def test_a_morning_reask_then_no_does_not_prescribe(tmp_path):
    day = "2026-11-02"
    loop = _live_loop(tmp_path)
    loop.open_morning(day)
    first = loop.hear(day, "kinda off today")
    assert "Full body A" not in first
    assert day not in loop.workouts
    second = loop.hear(day, "no")
    assert "Full body A" not in second
    assert day not in loop.workouts
    assert loop.phase[day] == "paused"


def test_an_evening_reask_then_yes_does_not_log(tmp_path):
    day = "2026-11-02"
    loop = _live_loop(tmp_path)
    loop.open_morning(day)
    loop.hear(day, "no, 7, 2")
    loop.open_evening(day)
    first = loop.hear(day, "not sure about the session")
    assert "logged" not in first.lower()
    second = loop.hear(day, "yes")
    assert "logged" not in second.lower()
    assert loop.notes[day].get("did_it") is None
    assert loop.phase[day] == "paused"
    _clear_day_files(tmp_path)
    aged = _live_loop(tmp_path)
    aged.open_morning(day)
    aged.hear(day, "no, 7, 2")
    aged.open_evening(day)
    asked = aged.hear(day, "im still at school", _minor_labels())
    assert "how old are you" in asked.lower()
    stayed = aged.hear(day, "yes")
    assert "logged" not in stayed.lower()
    assert aged.notes[day].get("did_it") is None


def test_an_old_injury_swaps_the_lift_that_day(tmp_path):
    day = "2026-11-02"
    loop = _live_loop(tmp_path)
    loop.open_morning(day)
    text = loop.hear(day, "no, 7, 2. old knee", {
        "minor_signal": False,
        "red_flag": "none",
        "injury": "old",
        "note_ok": False,
    })
    assert "Full body A" in text
    assert "Back squat" not in text
    assert "Box squat to a high box" in text
    assert loop.phase[day] == "workout"


def test_an_old_follow_up_keeps_the_pending_injury_text(tmp_path):
    day = "2026-11-04"
    loop = _live_loop(tmp_path)
    loop.open_morning(day)
    labels = {
        "minor_signal": False,
        "red_flag": "none",
        "injury": "unclear",
        "note_ok": False,
    }
    first = loop.hear(day, "knee is wrecked", labels)
    assert "Full body" not in first
    second = loop.hear(day, "old")
    assert "Full body" not in second
    assert loop.notes[day]["old_injury"] == "knee is wrecked"
    assert loop.phase[day] != "paused"
    third = loop.hear(day, "no, 7, 2")
    assert "Front squat" not in third
    assert "Box squat to a high box" in third
    assert loop.phase[day] == "workout"


def test_a_stray_number_on_day_two_does_not_hold_unless_labels_say_so(tmp_path):
    day = "2026-11-04"
    loop = _live_loop(tmp_path)
    loop.open_morning(day)
    text = loop.hear(day, "25")
    assert loop.phase[day] != "paused"
    assert "Full body" not in text
    clear = loop.hear(day, "no, 7, 2")
    assert "Full body B" in clear
    assert loop.phase[day] == "workout"
    _clear_day_files(tmp_path)
    held = _live_loop(tmp_path)
    held.open_morning(day)
    paused = held.hear(day, "25", {
        "minor_signal": False,
        "red_flag": "chest_pain",
        "injury": "none",
        "note_ok": False,
    })
    assert held.phase[day] == "paused"
    assert "Full body" not in paused


def test_a_future_dated_pending_file_holds_the_earlier_day(tmp_path):
    from safety_pending import write_pending

    day = "2026-11-02"
    assert write_pending(str(tmp_path), "follow_up", "2026-11-06", "daily") is True
    loop = _live_loop(tmp_path)
    loop.open_morning(day)
    text = loop.hear(day, "no, 7, 2")
    assert "Full body A" not in text
    assert loop.phase[day] == "paused"
    assert day not in loop.workouts


def test_a_clear_no_with_ordinary_soreness_logs_the_morning(tmp_path):
    from daily_loop import DailyLoop, _SYMPTOM, adult_profile
    from log_store import LogStore

    day = "2026-10-26"
    path = tmp_path / "log.json"
    loop = DailyLoop(load=80, minutes=45, profile=adult_profile(), log_path=str(path))
    loop.open_morning(day)
    reply = "no, feeling good. Kinda sore from yesterday's walk."
    text = loop.hear(day, reply, {
        "minor_signal": False,
        "red_flag": "none",
        "injury": "none",
        "note_ok": True,
    })
    assert text != _SYMPTOM
    assert "Still need a clear no" not in text
    assert loop.phase[day] == "workout"
    assert day in loop.workouts
    assert loop.notes[day]["note"] == reply
    rows = LogStore(path).data["checkins"]
    assert len(rows) == 1
    assert rows[0]["note"] == reply
    assert rows[0]["sleep"] == 7
    assert rows[0]["soreness"] == 4


def test_a_scored_no_keeps_the_hours_and_soreness(tmp_path):
    from daily_loop import DailyLoop, adult_profile
    from log_store import LogStore

    day = "2026-10-26"
    path = tmp_path / "log.json"
    loop = DailyLoop(load=80, minutes=45, profile=adult_profile(), log_path=str(path))
    loop.open_morning(day)
    reply = "no. slept 3 hours, soreness 5"
    text = loop.hear(day, reply, {
        "minor_signal": False,
        "red_flag": "none",
        "injury": "none",
        "note_ok": True,
    })
    assert loop.phase[day] == "workout"
    assert loop.notes[day]["sleep"] == 3
    assert loop.notes[day]["soreness"] == 5
    assert loop.notes[day]["note"] == reply
    assert "Today is a normal day" not in text
    assert text.startswith("Easy day.")
    rows = LogStore(path).data["checkins"]
    assert len(rows) == 1
    assert rows[0]["sleep"] == 3
    assert rows[0]["soreness"] == 5
    assert rows[0]["note"] == reply


def test_no_with_trailing_punctuation_is_a_bare_no():
    from daily_loop import DailyLoop, adult_profile

    day = "2026-10-26"
    loop = DailyLoop(load=80, minutes=45, profile=adult_profile())
    loop.open_morning(day)
    text = loop.hear(day, "No.")
    assert loop.phase[day] == "workout"
    assert "one more" not in text.lower()
    assert loop.notes[day]["sleep"] == 7
    assert loop.notes[day]["soreness"] == 2
    assert text.startswith("Today is a normal day.")


def test_the_post_workout_card_maps_answers_and_keeps_food_optional(tmp_path):
    import json

    from daily_loop import DailyLoop, adult_profile, map_post_workout, post_workout_card

    card = post_workout_card()
    assert card["widget"] == "question_card"
    assert 1 <= len(card["steps"]) <= 8
    by_id = {step["id"]: step for step in card["steps"]}
    assert list(by_id) == ["did_it", "felt", "enjoyment", "soreness", "energy", "symptoms", "food"]
    assert by_id["did_it"]["options"] == ["yes", "partly", "no"]
    assert by_id["felt"]["options"] == ["easy", "right", "hard"]
    assert by_id["symptoms"]["options"] == [
        "none", "chest pain", "dizziness or fainting", "sharp joint pain", "other",
    ]
    assert by_id["symptoms"]["allowCustom"] is True
    assert by_id["food"]["input"] == "text"
    assert by_id["food"].get("optional") is True

    base = {
        "did_it": "yes",
        "felt": "right",
        "enjoyment": "4",
        "soreness": 3,
        "energy": "5",
        "symptoms": "none",
    }
    mapped = map_post_workout(base)
    assert mapped["fields"]["did_it"] is True
    assert mapped["fields"]["enjoyment"] == 4
    assert mapped["fields"]["soreness"] == 3
    assert mapped["fields"]["energy"] == 5
    assert "ate" not in mapped["fields"]
    assert mapped["labels"]["red_flag"] == "none"
    assert map_post_workout(dict(base, did_it="partly"))["fields"]["did_it"] is True
    assert map_post_workout(dict(base, did_it="no"))["fields"]["did_it"] is False
    assert map_post_workout(dict(base, symptoms="chest pain"))["labels"]["red_flag"] == "chest_pain"
    assert map_post_workout(dict(base, symptoms="dizziness or fainting"))["labels"]["red_flag"] == "fainting"
    assert map_post_workout(dict(base, symptoms="sharp joint pain"))["labels"]["red_flag"] == "sharp_joint_pain"
    assert map_post_workout(dict(base, symptoms="other")) is None
    custom = map_post_workout(dict(base, symptoms="calf cramp"))
    assert custom["labels"] is None
    assert custom["typed"] == "calf cramp"
    noted = map_post_workout(dict(base, symptoms="other", symptoms_note="calf cramp"))
    assert noted["labels"] is None
    assert noted["typed"] == "calf cramp"
    fed = map_post_workout(dict(base, food="chicken"))
    assert fed["labels"] is None
    assert fed["typed"] == "chicken"

    def loop(name):
        folder = tmp_path / name
        folder.mkdir()
        return DailyLoop(
            load=80,
            minutes=45,
            profile=adult_profile(),
            week_path=str(folder / "week.json"),
        )

    day = "2026-10-26"
    done = loop("done")
    done.open_morning(day)
    done.hear(day, "no 8 fine 45")
    opened = done.open_evening(day)
    assert opened.startswith("Did you do it?")
    widget = json.loads(opened.split("\n", 1)[1])
    assert widget["widget"] == "question_card"
    assert widget["steps"] == card["steps"]
    assert done.hear(day, base).startswith("Logged.")
    assert done.notes[day]["did_it"] is True
    assert done.notes[day]["felt"] == "right"
    assert "ate" not in done.notes[day]

    easy = loop("easy")
    easy.open_morning(day)
    easy.hear(day, "no 8 fine 45")
    easy.open_evening(day)
    labeled = {
        "minor_signal": False,
        "red_flag": "none",
        "injury": "none",
        "note_ok": False,
    }
    assert easy.hear(
        day, dict(base, did_it="partly", felt="easy", food="chicken"), labeled,
    ).startswith("Logged.")
    assert easy.notes[day]["did_it"] is True
    assert easy.notes[day]["ate"] == "chicken"
    assert easy.felt_easy == 1

    missed = loop("missed")
    missed.open_morning(day)
    missed.hear(day, "no 8 fine 45")
    missed.open_evening(day)
    assert missed.hear(day, dict(base, did_it="no")).startswith("Logged the miss")
    assert missed.notes[day]["did_it"] is False

    chest = loop("chest")
    chest.open_morning(day)
    chest.hear(day, "no 8 fine 45")
    chest.open_evening(day)
    held = chest.hear(day, dict(base, symptoms="chest pain"))
    assert "medical emergency" in held.lower()
    assert chest.notes[day].get("did_it") is None
    assert chest.phase[day] == "paused"

    food = loop("food")
    food.open_morning(day)
    food.hear(day, "no 8 fine 45")
    food.open_evening(day)
    stopped = food.hear(day, dict(base, food="oats and chest pain"))
    assert "medical emergency" in stopped.lower()
    assert food.notes[day].get("did_it") is None


def test_typed_card_text_without_labels_does_not_log(tmp_path):
    from daily_loop import DailyLoop, adult_profile

    phrases = (
        "my knee swelled up and I can't put weight on it",
        "tight chest",
        "felt like I might pass out",
        "short of breath for an hour after",
        "pasta, also got really lightheaded",
        "pizza. btw im 14",
    )
    base = {
        "did_it": "yes",
        "felt": "right",
        "enjoyment": "4",
        "soreness": 3,
        "energy": "5",
        "symptoms": "none",
    }
    day = "2026-10-26"
    logged = "Logged. See you in the morning."

    def opened(name):
        folder = tmp_path / name
        folder.mkdir()
        loop = DailyLoop(
            load=80,
            minutes=45,
            profile=adult_profile(),
            week_path=str(folder / "week.json"),
        )
        loop.open_morning(day)
        loop.hear(day, "no 8 fine 45")
        loop.open_evening(day)
        return loop

    for index, phrase in enumerate(phrases):
        for slot, payload in (
            ("food", dict(base, food=phrase)),
            ("symptom", dict(base, symptoms=phrase)),
            ("note", dict(base, symptoms="other", symptoms_note=phrase)),
        ):
            loop = opened(f"{index}-{slot}")
            first = loop.hear(day, payload)
            assert first != logged, phrase
            assert logged not in first, phrase
            assert loop.phase[day] != "done", phrase
            assert loop.notes[day].get("did_it") is None, phrase
            second = loop.hear(day, payload)
            assert second != logged, phrase
            assert logged not in second, phrase
            assert loop.phase[day] != "done", phrase
            assert loop.notes[day].get("did_it") is None, phrase


def test_open_morning_stays_under_three_seconds():
    import time

    from daily_loop import DailyLoop, adult_profile

    loop = DailyLoop(load=80, minutes=45, profile=adult_profile())
    started = time.perf_counter()
    loop.open_morning("2026-10-26")
    loop.open_morning("2026-10-27")
    assert time.perf_counter() - started < 3
