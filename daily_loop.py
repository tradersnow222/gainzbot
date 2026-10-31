#!/usr/bin/env python3
"""Bot-led day. The user answers in a word or a number. They do not start the chat."""

from datetime import date, timedelta
import re

from morning_checkin import MorningCheckIn


_MORNING = (
    "Morning. Sleep hours and soreness (fine, sore, or very sore)? "
    "Minutes today, and weight if you track it."
)
_SECOND = "One more: soreness or sleep, in a word or a number."
_EVENING = "Did you do it? easy, right, or hard. What did you eat?"
_NUDGE = "Missed today. I'll pick it up in the morning."


def _fold(reply):
    if not isinstance(reply, str):
        return ""
    return " ".join(reply.lower().replace("'", "").split())


def parse_morning(reply):
    """Sleep, soreness, minutes, and an optional weight from a short reply."""
    text = _fold(reply)
    parsed = {}
    if "bad sleep" in text or "slept bad" in text:
        parsed["sleep"] = 4
    if "very sore" in text:
        parsed["soreness"] = 5
    elif re.search(r"\bsore\b", text):
        parsed["soreness"] = 4
    elif re.search(r"\bfine\b", text):
        parsed["soreness"] = 2
    if re.search(r"\bgood\b", text):
        parsed["energy"] = 5
    elif re.search(r"\blow\b", text):
        parsed["energy"] = 2
    elif re.search(r"\bok\b", text):
        parsed["energy"] = 3
    numbers = []
    for raw in re.findall(r"\d+(?:\.\d+)?", text):
        value = float(raw)
        numbers.append(int(value) if value == int(value) else value)
    if "sleep" not in parsed:
        for index, number in enumerate(numbers):
            if 0 <= number <= 14:
                parsed["sleep"] = number
                numbers = numbers[:index] + numbers[index + 1:]
                break
    weight = re.search(r"(\d+(?:\.\d+)?)\s*kg\b", text)
    if weight:
        parsed["weight_kg"] = float(weight.group(1))
    minutes = re.search(r"(\d+)\s*min\b", text)
    if minutes:
        parsed["minutes"] = int(minutes.group(1))
    else:
        for number in numbers:
            if number >= 15:
                parsed["minutes"] = int(number)
                break
    return parsed


def parse_evening(reply):
    text = _fold(reply)
    did_it = bool(re.search(r"\b(?:yes|yep|yeah|did)\b", text)) and not re.search(r"\bno\b", text)
    if re.search(r"\bno\b", text):
        did_it = False
    felt = None
    for word in ("easy", "right", "hard"):
        if re.search(rf"\b{word}\b", text):
            felt = word
            break
    ate = text
    for word in ("yes", "yep", "yeah", "did", "no", "easy", "right", "hard"):
        ate = re.sub(rf"\b{word}\b", " ", ate)
    ate = " ".join(ate.split())
    return {"did_it": did_it, "felt": felt, "ate": ate}


class DailyLoop:
    """Morning, workout, evening, and a weekly review inside the load cap."""

    def __init__(self, load=80, minutes=45, calories=None, confirmed_at="2026-10-19T07:00:00Z", goal="hold"):
        self.load = load
        self.minutes = minutes
        self.calories = calories
        self.goal = goal
        self.confirmed_at = confirmed_at
        self.history = [{
            "date": confirmed_at,
            "confirmed": True,
            "changes": {"load": load},
        }]
        self.phase = {}
        self.notes = {}
        self.nudges = {}
        self.felt_easy = 0
        self.workouts = {}

    def open_morning(self, day):
        """The bot opens. The user does not send a command first."""
        self.phase[day] = "morning"
        self.notes[day] = {}
        return _MORNING

    def open_evening(self, day):
        self.phase[day] = "evening"
        return _EVENING

    def nudge(self, day):
        """One gentle nudge for a missed day. A second call says nothing."""
        if self.nudges.get(day, 0) >= 1:
            return None
        self.nudges[day] = 1
        return _NUDGE

    def hear(self, day, reply):
        phase = self.phase.get(day)
        if phase == "morning":
            parsed = parse_morning(reply)
            self.notes[day].update(parsed)
            if self._needs_more(day):
                self.phase[day] = "morning2"
                return _SECOND
            return self._workout(day)
        if phase == "morning2":
            self.notes[day].update(parse_morning(reply))
            return self._workout(day)
        if phase == "evening":
            return self._evening(day, reply)
        return "I'll pick it up in the morning."

    def _needs_more(self, day):
        notes = self.notes.get(day, {})
        return "sleep" not in notes or "soreness" not in notes

    def _scores(self, day):
        notes = self.notes.get(day, {})
        return {
            "sleep": notes.get("sleep", 7),
            "soreness": notes.get("soreness", 2),
            "energy": notes.get("energy", 3),
            "stress": notes.get("stress", 2),
        }

    def _workout(self, day):
        scores = self._scores(day)
        as_of = f"{day}T12:00:00Z"
        checked = MorningCheckIn().check_in(
            scores,
            confirmed_changes=self.history,
            as_of=as_of,
        )
        day_name = checked.get("day") or "normal"
        changes = (checked.get("proposal") or {}).get("changes") or {}
        load = changes.get("load", self.load)
        available = self.notes[day].get("minutes", self.minutes)
        if day_name == "easy":
            session_minutes = max(15, int(round(available * 0.7)))
            lead = "Easy day."
        else:
            session_minutes = available
            lead = f"Today is a {day_name} day."
        food = f"{self.calories} kcal" if self.calories is not None else self.goal
        text = f"{lead} {session_minutes} min, load {load}. Food: {food}."
        row = {
            "day": day_name,
            "minutes": session_minutes,
            "load": load,
            "food": food,
            "text": text,
        }
        self.workouts[day] = row
        self.phase[day] = "workout"
        return text

    def _evening(self, day, reply):
        parsed = parse_evening(reply)
        self.notes[day].update(parsed)
        if parsed.get("felt") == "easy":
            self.felt_easy += 1
        self.phase[day] = "done"
        if parsed.get("did_it"):
            return "Logged. See you in the morning."
        return "Logged the miss. See you in the morning."

    def weekly(self, as_of):
        """A short review. A raise waits for 7 times 24 hours and stays inside 10 percent."""
        food = f"{self.calories} kcal" if self.calories is not None else self.goal
        if self.felt_easy < 1:
            return {
                "load": self.load,
                "changed": False,
                "food": food,
                "text": f"Load stays {self.load}. Food: {food}.",
            }
        checked = MorningCheckIn().check_in(
            {"sleep": 8, "soreness": 1, "energy": 5, "stress": 1},
            confirmed_changes=self.history,
            as_of=as_of,
        )
        changes = (checked.get("proposal") or {}).get("changes") or {}
        proposed = changes.get("load", self.load)
        changed = proposed != self.load
        if changed:
            text = (
                f"Week felt easy. Load {self.load} to {proposed}, "
                f"inside the 10 percent cap. Food: {food}."
            )
        else:
            text = f"Load stays {self.load} until the confirmed load is 7 times 24 hours old. Food: {food}."
        return {
            "load": proposed,
            "changed": changed,
            "food": food,
            "text": text,
        }


def simulate_happy_week():
    """Seven bot-led days. The user only answers the questions."""
    loop = DailyLoop(load=80, minutes=45, calories=2200, confirmed_at="2026-10-19T07:00:00Z")
    start = date(2026, 10, 26)
    mornings = (
        "8 fine 45",
        "8 very sore 30",
        "bad sleep fine 40",
        "8 fine 45",
        "8 fine 45",
        "8 fine 45",
        "8 fine 45",
    )
    rows = []
    for offset, morning in enumerate(mornings):
        day = (start + timedelta(days=offset)).isoformat()
        opened = loop.open_morning(day)
        workout = loop.hear(day, morning)
        evening = loop.open_evening(day)
        closed = loop.hear(day, "yes easy chicken")
        rows.append({
            "day": day,
            "opened": opened,
            "morning_reply": morning,
            "workout": loop.workouts[day],
            "workout_text": workout,
            "evening": evening,
            "closed": closed,
        })
    review = loop.weekly("2026-11-02T07:00:00Z")
    return {"rows": rows, "review": review, "replies": mornings}
