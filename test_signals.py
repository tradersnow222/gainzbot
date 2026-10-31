#!/usr/bin/env python3
"""Connected signals skip the morning question. Proactive notes stay capped."""

from pathlib import Path

from daily_loop import DailyLoop
from onboarding import GROUPS, run_chat
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


def _loop(book):
    return DailyLoop(
        load=80,
        minutes=45,
        calories=2200,
        confirmed_at="2026-10-19T07:00:00Z",
        signals=book,
    )


def test_full_wearable_data_asks_zero_morning_questions():
    assert format_sleep(5 + 40 / 60) == "5h 40m"
    loop = _loop(_book())
    text = loop.open_morning(DAY)
    assert loop.questions[DAY] == 0
    assert NOTE in text
    assert "?" not in text
    assert loop.workouts[DAY]["day"] == "easy"
    assert loop.workouts[DAY]["load"] == 72
    assert "easy day" in text.lower()


def test_partial_data_asks_only_the_missing_signal():
    loop = _loop(_book(weight=False))
    text = loop.open_morning(DAY)
    assert loop.questions[DAY] == 1
    assert text == "Weight?"
    assert "sleep" not in text.lower()
    workout = loop.hear(DAY, "80")
    assert loop.notes[DAY]["weight_kg"] == 80
    assert loop.phase[DAY] == "workout"
    assert "load" in workout.lower()


def test_a_stale_source_falls_back_to_one_question():
    loop = _loop(_book(sleep_at="2026-10-25T02:00:00Z"))
    text = loop.open_morning(DAY)
    assert loop.questions[DAY] == 1
    assert text == "Sleep last night?"
    workout = loop.hear(DAY, "5")
    assert loop.notes[DAY]["sleep"] == 5
    assert loop.phase[DAY] == "workout"
    assert "load" in workout.lower()


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
    assert "How is the knee today?" in text
    assert "Game day?" in text
    assert "sleep" not in text.lower()
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
    assert outreach.accept(day, "yes") is False
    assert result["held"][0]["applied"] is False
    alone = outreach.fire("2026-10-27", plateau=True)
    proposal = alone["delivered"][0]
    assert proposal["kind"] == "plateau"
    assert proposal["needs_yes"] is True
    assert proposal["applied"] is False
    assert outreach.accept("2026-10-27", "yes") is True
    assert proposal["applied"] is True
    assert outreach.accept("2026-10-27", "yes, but later") is False


def test_intake_asks_once_what_they_track_with():
    training = next(group for group in GROUPS if group["id"] == "training")
    assert "sources" in training["asks"]
    assert "what do you track with" in training["text"].lower()
    state, _bots = run_chat(["hello", "ok", "ok"])
    assert state["answers"]["sources"] == "none"
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
