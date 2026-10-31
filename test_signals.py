#!/usr/bin/env python3
"""Connected signals skip the non-symptom questions. Proactive notes stay capped."""

from pathlib import Path

from daily_loop import DailyLoop, _SYMPTOM, adult_profile
from onboarding import GROUPS, run_chat
from plan_check import PlanValidator
from record_confirmation import hash_plan
from red_flag_check import RedFlagChecker, is_passing_check_in
from signals import Outreach, SignalBook, format_sleep


ROOT = Path(__file__).resolve().parent
DAY = "2026-10-26"
FRESH = "2026-10-26T07:00:00Z"
NOTE = "Sleep 5h 40m and HRV down, so today is lighter."


def _book(sleep_at=FRESH, weight=True, sleep_hours=5 + 40 / 60):
    book = SignalBook()
    book.connect("apple_health", "food_app")
    book.record("sleep", sleep_at, sleep_hours)
    book.record("resting_hr", FRESH, 52)
    book.record("hrv", FRESH, 40, down=True)
    book.record("steps", FRESH, 3000)
    if weight:
        book.record("weight", FRESH, 80)
    book.record("workouts", FRESH, 1)
    book.record("nutrition", FRESH, "logged")
    return book


def _history():
    return [{
        "date": "2026-10-19T07:00:00Z",
        "confirmed": True,
        "changes": {"load": 80},
    }]


def _loop(book):
    return DailyLoop(
        load=80,
        minutes=45,
        calories=2200,
        signals=book,
        history=_history(),
        profile=adult_profile(),
    )


def _check_in():
    checker = RedFlagChecker()
    answers = {aliases[0]: "no" for _flag, aliases in checker.CHECKLIST_GROUPS}
    result = checker.scan_check_in({"symptom_checklist": answers, "notes": "no"})
    assert is_passing_check_in(result)
    return result


def _plan(calories=1880, previous=1780):
    return {
        "user": {
            "sex": "M",
            "weight_kg": 80,
            "age": 30,
            "height_cm": 180,
            "medical_clearance": False,
        },
        "nutrition": {
            "calories": calories,
            "protein_g": 144,
            "previous_calories": previous,
        },
        "goals": {"goal": "hold"},
        "training": {
            "previous_load": 80,
            "current_load": 80,
            "weeks_since_deload": 0,
            "structured_hours": 3,
            "sport_hours": 0,
        },
    }


def test_full_wearable_data_asks_zero_morning_questions():
    assert format_sleep(5 + 40 / 60) == "5h 40m"
    loop = _loop(_book())
    text = loop.open_morning(DAY)
    assert loop.questions[DAY] == 0
    assert text == _SYMPTOM
    assert "?" in text
    assert NOTE not in text
    assert "easy day" not in text.lower()
    assert DAY not in loop.workouts
    workout = loop.hear(DAY, "no")
    assert NOTE in workout
    assert loop.workouts[DAY]["day"] == "easy"
    assert loop.workouts[DAY]["load"] == 72
    assert "easy day" in workout.lower()


def test_partial_data_asks_only_the_missing_signal():
    loop = _loop(_book(weight=False))
    text = loop.open_morning(DAY)
    assert loop.questions[DAY] == 1
    assert text.startswith(_SYMPTOM)
    assert "Weight?" in text
    assert "sleep" not in text.lower()
    assert "easy day" not in text.lower()
    still = loop.hear(DAY, "no")
    assert still == "Weight?"
    workout = loop.hear(DAY, "80")
    assert loop.notes[DAY]["weight_kg"] == 80
    assert loop.phase[DAY] == "workout"
    assert "load" in workout.lower()


def test_a_stale_source_falls_back_to_one_question():
    loop = _loop(_book(sleep_at="2026-10-25T02:00:00Z"))
    text = loop.open_morning(DAY)
    assert loop.questions[DAY] == 1
    assert text.startswith(_SYMPTOM)
    assert "Sleep last night?" in text
    assert "easy day" not in text.lower()
    still = loop.hear(DAY, "no")
    assert still == "Sleep last night?"
    workout = loop.hear(DAY, "5")
    assert loop.notes[DAY]["sleep"] == 5
    assert loop.phase[DAY] == "workout"
    assert "load" in workout.lower()


def test_none_is_not_fresh_and_out_of_range_values_still_ask():
    as_of = f"{DAY}T08:00:00Z"
    empty = SignalBook()
    empty.connect("oura")
    empty.record("sleep", FRESH, None)
    empty.record("resting_hr", FRESH, 55)
    empty.record("hrv", FRESH, 40)
    assert empty.fresh("sleep", as_of) is False
    assert empty.abnormal(as_of) == []
    asked = _loop(empty)
    opening = asked.open_morning(DAY)
    assert "Sleep last night?" in opening
    assert "easy day" not in opening.lower()
    again = asked.hear(DAY, "no")
    assert "Sleep last night?" in again
    assert "easy day" not in again.lower()
    short = SignalBook()
    short.connect("oura")
    short.record("sleep", FRESH, 3.5)
    short.record("resting_hr", FRESH, 55)
    short.record("hrv", FRESH, 50)
    assert short.fresh("sleep", as_of) is False
    assert "sleep" in short.abnormal(as_of)
    light = _loop(short)
    short_open = light.open_morning(DAY)
    assert "Sleep last night?" in short_open
    assert "easy day" not in short_open.lower()
    short_day = light.hear(DAY, "no")
    assert "easy day" in short_day.lower()
    assert light.notes[DAY]["sleep"] == 3.5
    assert light.workouts[DAY]["load"] == 72
    racing = SignalBook()
    racing.connect("oura")
    racing.record("sleep", FRESH, 8)
    racing.record("resting_hr", FRESH, 130)
    racing.record("hrv", FRESH, 50)
    assert racing.fresh("resting_hr", as_of) is False
    assert "resting_hr" in racing.abnormal(as_of)
    heart = _loop(racing)
    heart_open = heart.open_morning(DAY)
    assert "Resting heart rate?" in heart_open
    assert "easy day" not in heart_open.lower()
    heart_day = heart.hear(DAY, "no")
    assert "easy day" in heart_day.lower()
    assert heart.workouts[DAY]["day"] == "easy"


def test_freshness_is_under_about_24_hours_and_a_connection_is_not_assumed():
    book = SignalBook()
    as_of = f"{DAY}T08:00:00Z"
    book.record("sleep", "2026-10-25T09:00:00Z", 7)
    book.connect("oura")
    assert book.fresh("sleep", as_of) is True
    book.record("sleep", "2026-10-25T07:00:00Z", 7)
    assert book.fresh("sleep", as_of) is False
    empty = SignalBook()
    empty.declare("apple_health")
    empty.connect("none")
    assert empty.connected() is False
    assert empty.declared == ["apple_health"]
    morning = DailyLoop(signals=empty).open_morning(DAY)
    assert morning.startswith("Morning.")
    connected = SignalBook()
    connected.connect("apple_health")
    assert "sleep" in connected.gaps(as_of)
    assert connected.fresh_value("sleep", as_of) is None


def test_personal_questions_stop_once_the_answer_is_settled():
    book = _book()
    book.set_situation(injury="knee", sport_in_season=True)
    loop = _loop(book)
    text = loop.open_morning(DAY)
    assert loop.questions[DAY] == 2
    assert text.startswith(_SYMPTOM)
    assert "How is the knee today?" in text
    assert "Game day?" in text
    assert "sleep" not in text.lower()
    assert "easy day" not in text.lower()
    again = loop.hear(DAY, "no")
    assert "How is the knee today?" in again
    assert "injury" not in book.settled
    loop.hear(DAY, "fine")
    assert "injury" in book.settled
    assert "sport" in book.settled
    nxt = "2026-10-27"
    fresh = "2026-10-27T07:00:00Z"
    for signal, reading in list(book.readings.items()):
        book.record(signal, fresh, reading["value"], down=reading["down"])
    later = loop.open_morning(nxt)
    assert loop.questions[nxt] == 0
    assert "knee" not in later.lower()
    assert "game day" not in later.lower()


def test_proactive_triggers_stay_inside_the_message_cap():
    outreach = Outreach()
    day = DAY
    result = outreach.fire(day, poor_recovery=True, missed=True, plateau=True)
    assert [item["kind"] for item in result["delivered"]] == ["poor_recovery", "missed"]
    assert all(item["needs_yes"] is False and item["applied"] is True for item in result["delivered"])
    assert result["proactive_count"] == 2
    assert len(result["held"]) == 1
    assert result["held"][0]["kind"] == "plateau"
    assert result["held"][0]["needs_yes"] is True
    assert result["held"][0]["applied"] is False
    scheduled = outreach.scheduled(day, "Morning plan")
    assert scheduled["counts"] is False
    assert outreach.proactive_count(day) == 2
    plan = _plan()
    digest = hash_plan(plan)
    assert outreach.accept(day, "yes", proposal_hash=digest) is False
    assert result["held"][0]["applied"] is False
    spaced = "  2026-10-27 "
    alone = outreach.fire(spaced, plateau=True, plan=plan, check_in=_check_in())
    proposal = alone["delivered"][0]
    assert proposal["kind"] == "plateau"
    assert proposal["needs_yes"] is True
    assert proposal["applied"] is False
    assert proposal["hash"] == digest
    assert outreach.accept("2026-10-27", "yes") is False
    assert outreach.accept("2026-10-27", "yes", proposal_hash="not-the-proposal") is False
    assert proposal["applied"] is False
    assert outreach.accept(spaced, "yes", proposal_hash=digest) is True
    assert proposal["applied"] is True
    assert outreach.accept("2026-10-27", "yes, but later", proposal_hash=digest) is False
    jump = _plan(calories=2200, previous=1780)
    jump_day = "2026-10-28"
    blocked = outreach.fire(jump_day, plateau=True, plan=jump, check_in=_check_in())
    jumped = blocked["delivered"][0]
    checked = PlanValidator().validate_plan(jump, check_in_result=_check_in())
    assert checked.valid is False
    assert outreach.accept(jump_day, "yes", proposal_hash=jumped["hash"]) is False
    assert jumped["applied"] is False


def test_intake_asks_once_what_they_track_with():
    training = next(group for group in GROUPS if group["id"] == "training")
    assert "sources" in training["asks"]
    assert "what do you track with" in training["text"].lower()
    state, _bots = run_chat(["hello", "skip", "ok"])
    assert state["answers"]["sources"] == "none"
    assert state["answers"].get("age") is None
    assert state["answers"].get("sex") is None
    assert state["answers"].get("weight") is None
    assert state["answers"].get("height") is None
    named, _bots = run_chat(["apple health and a food app"])
    assert named["answers"]["sources"] == ["apple_health", "food_app"]
    for name in (
        "BOT_PROMPT.md",
        "QUICKSTART.md",
        "template/getting-started.md",
        "template/routines.md",
        "template/onboarding.md",
    ):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "never assume a connection" in text.lower()
        assert "\u2014" not in text
    for name in (
        "BOT_PROMPT.md",
        "QUICKSTART.md",
        "template/getting-started.md",
        "template/routines.md",
    ):
        lowered = (ROOT / name).read_text(encoding="utf-8").lower()
        assert "less than about 24 hours" in lowered
        assert "one short question" in lowered
        assert "about two" in lowered
        assert "what they track with" in lowered or "what do you track with" in lowered
