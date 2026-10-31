#!/usr/bin/env python3
"""Bot-led day. The user answers in a word or a number. They do not start the chat."""

from datetime import date, timedelta
import re

from morning_checkin import MorningCheckIn
from red_flag_check import RedFlagChecker, is_passing_check_in
from readiness_screen import ReadinessScreen, passing_readiness
from signals import read_gap_reply


_SYMPTOM = "Morning. Any chest pain, dizziness or new pain? no / yes"
_MORNING = (
    "Sleep hours and soreness (fine, sore, or very sore)? "
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


def _pause_text(result):
    parts = [result.message]
    for line in result.recommendations or []:
        if line not in parts:
            parts.append(line)
    return " ".join(parts)


_CHECKIN_WORDS = {
    "no", "none", "nope", "fine", "sore", "very", "bad", "sleep", "slept",
    "min", "kg", "good", "low", "ok", "okay",
}


def symptom_is_clear(reply):
    """A leading no, plus only the short check-in words and numbers.

    'no' and 'no 8 45' are clear. Anything else, including another script,
    emoji, parentheses, 'but', or 'idea', is not.
    """
    if not isinstance(reply, str) or not reply.strip():
        return False
    if "?" in reply or "？" in reply:
        return False
    for char in reply:
        if char.isspace() or char.isdigit() or ("a" <= char.lower() <= "z"):
            continue
        if char in ".,!;:'\"-":
            continue
        return False
    tokens = re.findall(r"[a-z]+|\d+(?:\.\d+)?", reply.lower().replace("'", ""))
    if not tokens or tokens[0] not in {"no", "none", "nope"}:
        return False
    for token in tokens:
        if re.fullmatch(r"\d+(?:\.\d+)?", token):
            continue
        if token not in _CHECKIN_WORDS:
            return False
    return True


def _ate_text(text):
    for word in ("yes", "yep", "yeah", "did", "didnt", "no", "not", "nt", "easy", "right", "hard", "ate"):
        text = re.sub(rf"\b{word}\b", " ", text)
    text = " ".join(text.split())
    if text in {"not", "nt", "didnt"}:
        return ""
    return text


_FOOD_DOUBT = re.compile(r"\b(?:no idea|dont know|not sure|no clue|idk)\b")


def _food_unknown(text):
    """True when the reply says they do not know what they ate."""
    return _FOOD_DOUBT.search(text) is not None and re.search(r"\bwhat i ate\b", text) is not None


def parse_evening(reply):
    """Workout words and food are separate. 'ate' starts the food.

    'no idea what I ate' leaves the food unknown. A reply that only names
    food leaves the workout unknown instead of calling it a miss.
    """
    text = _fold(reply)
    unknown_food = _food_unknown(text)
    scan = text
    if unknown_food:
        scan = _FOOD_DOUBT.sub(" ", text)
        scan = re.sub(r"\bwhat i ate\b", " ", scan)
    workout = scan
    food = None
    ate_at = re.search(r"\bate\b", scan)
    if ate_at:
        workout = scan[:ate_at.start()]
        food = scan[ate_at.end():]
    elif "," in scan:
        workout, food = scan.split(",", 1)
    if re.search(r"\bdid\s+not\b", workout) or re.search(r"\bdidnt\b", workout):
        did_it = False
    elif re.search(r"\bno\b", workout):
        did_it = False
    elif re.search(r"\b(?:yes|yep|yeah|did)\b", workout):
        did_it = True
    elif (food is not None and _ate_text(food).strip()) or unknown_food:
        did_it = None
    else:
        did_it = False
    felt = None
    for word in ("easy", "right", "hard"):
        if re.search(rf"\b{word}\b", workout):
            felt = word
            break
    ate = None if unknown_food else _ate_text(food if food is not None else text)
    return {"did_it": did_it, "felt": felt, "ate": ate}


# Plan fields on the profile from onboarding._profile. Readiness does not screen them.
_PLAN_PROFILE_KEYS = {
    "days",
    "minutes",
    "equipment",
    "experience",
    "sport",
    "injuries",
    "goal",
}


def _readiness_intake(profile):
    """Readiness fields from a readiness intake or from onboarding._profile."""
    if not isinstance(profile, dict):
        return profile
    return {
        key: value
        for key, value in profile.items()
        if key not in _PLAN_PROFILE_KEYS
    }


class DailyLoop:
    """Morning, workout, evening, and a weekly review inside the load cap.

    profile can be a readiness intake, or the profile onboarding._profile
    returns. Plan keys on that profile (days, minutes, equipment, experience,
    sport, injuries, goal) are accepted. Session length and the food goal
    still come from the minutes and goal arguments.
    """

    def __init__(self, load=80, minutes=45, calories=None, confirmed_at=None, goal="hold", signals=None, outreach=None, history=None, profile=None):
        self.load = load
        self.minutes = minutes
        self.calories = calories
        self.goal = goal
        self.confirmed_at = confirmed_at
        self.signals = signals
        self.outreach = outreach
        self.profile = profile
        self.history = list(history) if history else []
        self.phase = {}
        self.notes = {}
        self.nudges = {}
        self.felt_easy = 0
        self.workouts = {}
        self.questions = {}
        self.pending = {}

    def open_morning(self, day):
        """The bot opens with the symptom line. Wearables skip only the other questions."""
        self.notes[day] = {}
        self.phase[day] = "symptom"
        extra = self._other_questions(day)
        if extra:
            return f"{_SYMPTOM} {extra}"
        return _SYMPTOM

    def _other_questions(self, day):
        if self.signals is None or not self.signals.connected():
            self.questions[day] = 1
            return _MORNING
        as_of = f"{day}T08:00:00Z"
        gaps = self.signals.gaps(as_of)
        personal = self.signals.personal_questions()
        self.pending[day] = {"gaps": list(gaps), "personal": [key for key, _text in personal]}
        self.questions[day] = len(gaps) + len(personal)
        if not gaps and not personal:
            return ""
        asked = [self.signals.gap_question(gap) for gap in gaps]
        asked.extend(text for _key, text in personal)
        return " ".join(asked)

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
        if phase == "symptom":
            self.notes.setdefault(day, {})["reply"] = reply
            if symptom_is_clear(reply):
                return self._after_symptom(day, reply)
            return self._unclear_symptom(day, reply)
        if phase == "signals":
            pending = self.pending.get(day, {"gaps": [], "personal": []})
            self.notes[day]["reply"] = (self.notes[day].get("reply") or "") + " " + reply
            paused = self._text_pause(reply)
            if paused:
                self.phase[day] = "paused"
                return paused
            self.notes[day].update(read_gap_reply(pending["gaps"], reply))
            self._use_hr_answer(day, f"{day}T08:00:00Z")
            for key in pending["personal"]:
                self.signals.settle(key)
            self._seed(day, f"{day}T08:00:00Z")
            return self._workout(day)
        if phase == "morning2":
            self.notes[day]["reply"] = (self.notes[day].get("reply") or "") + " " + reply
            paused = self._text_pause(reply)
            if paused:
                self.phase[day] = "paused"
                return paused
            self.notes[day].update(parse_morning(reply))
            return self._workout(day)
        if phase == "evening":
            return self._evening(day, reply)
        return "I'll pick it up in the morning."

    def _unclear_symptom(self, day, reply):
        """Not a clear no. scan_check_in runs, then one gentle re-ask. No workout."""
        checker = RedFlagChecker()
        scanned = checker.scan_check_in({"notes": reply if isinstance(reply, str) else ""})
        real = [
            flag for flag in (scanned.flags_detected or [])
            if flag != "needs_clarification"
        ]
        paused = self._text_pause(reply)
        if paused and real:
            self.phase[day] = "paused"
            return paused
        if scanned.pause_plan and real:
            self.phase[day] = "paused"
            return _pause_text(scanned)
        self.phase[day] = "symptom"
        return _SYMPTOM

    def _text_pause(self, reply):
        scanned = RedFlagChecker().scan_text(reply if isinstance(reply, str) else "")
        if scanned.pause_plan:
            return _pause_text(scanned)
        return None

    def _gap_open(self, day, gap):
        notes = self.notes.get(day, {})
        if gap == "weight":
            return "weight_kg" not in notes
        return gap not in notes

    def _after_symptom(self, day, reply):
        as_of = f"{day}T08:00:00Z"
        pending = self.pending.get(day)
        if pending is None:
            self.notes[day].update(parse_morning(reply))
            if self._needs_more(day):
                self.phase[day] = "morning2"
                return _SECOND
            return self._workout(day)
        self.notes[day].update(read_gap_reply(pending["gaps"], reply))
        self._use_hr_answer(day, as_of)
        abnormal = set(self.signals.abnormal(as_of)) if self.signals is not None else set()
        unanswered = [
            gap for gap in pending["gaps"]
            if self._gap_open(day, gap) and gap not in abnormal
        ]
        personal = list(pending["personal"])
        if personal and _fold(reply) not in {"no", "none", "nope"}:
            for key in personal:
                self.signals.settle(key)
            personal = []
        if unanswered or personal:
            self.phase[day] = "signals"
            self.pending[day] = {"gaps": unanswered, "personal": personal}
            asked = [self.signals.gap_question(gap) for gap in unanswered]
            asked.extend(text for key, text in self.signals.personal_questions() if key in personal)
            return " ".join(asked)
        self._seed(day, as_of)
        return self._workout(day)

    def _use_hr_answer(self, day, as_of):
        """The resting heart rate they just gave is the one the day uses."""
        if self.signals is None:
            return
        value = self.notes.get(day, {}).get("resting_hr")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        self.signals.record("resting_hr", as_of, value)

    def _seed(self, day, as_of):
        book = self.signals
        if book is None:
            return
        notes = self.notes[day]
        if "sleep" not in notes:
            sleep = book.fresh_value("sleep", as_of)
            if sleep is not None:
                notes["sleep"] = sleep
        if book.hrv_down(as_of) and "stress" not in notes:
            notes["stress"] = 4
        if book.abnormal(as_of):
            notes["stress"] = 4
            if "sleep" in book.abnormal(as_of) and "sleep" not in notes:
                notes["sleep"] = book.readings["sleep"].get("value")

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

    def _checklist(self, reply):
        checker = RedFlagChecker()
        if symptom_is_clear(reply):
            answers = {aliases[0]: "no" for _flag, aliases in checker.CHECKLIST_GROUPS}
            return checker.scan_check_in({"symptom_checklist": answers, "notes": reply})
        return checker.scan_check_in({"notes": reply})

    def _before_training(self, day):
        reply = self.notes.get(day, {}).get("reply") or ""
        result = self._checklist(reply)
        if not is_passing_check_in(result):
            self.phase[day] = "paused"
            return _pause_text(result)
        if not isinstance(self.profile, dict):
            self.phase[day] = "paused"
            return "Readiness has to pass before training."
        screen = ReadinessScreen().screen_intake(_readiness_intake(self.profile))
        if not passing_readiness(screen):
            self.phase[day] = "paused"
            for reason in screen.reasons or []:
                if isinstance(reason, str) and reason.startswith("Unknown key:"):
                    return reason
            return "Readiness has to pass before training."
        return None

    def _workout(self, day):
        blocked = self._before_training(day)
        if blocked:
            return blocked
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
        if self.signals is not None and "resting_hr" in self.signals.abnormal(as_of):
            text += " If you feel unwell, check with a doctor."
        if self.signals is not None and self.signals.connected():
            note = self.signals.plan_note(f"{day}T08:00:00Z")
            if self.outreach is not None:
                self.outreach.scheduled(day, note)
            if note and note != "Today is on plan.":
                text = f"{note} {text}"
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
        paused = self._text_pause(reply)
        if paused:
            self.phase[day] = "paused"
            return paused
        parsed = parse_evening(reply)
        if parsed.get("ate") == "" and self.notes[day].get("ate"):
            parsed = {key: value for key, value in parsed.items() if key != "ate"}
        self.notes[day].update(parsed)
        if parsed.get("did_it") is None:
            self.phase[day] = "evening"
            return "Did you do the workout?"
        if parsed.get("felt") == "easy":
            self.felt_easy += 1
        self.phase[day] = "done"
        if parsed["did_it"]:
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
            confirmed_changes=_sealed_changes(self.history),
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


def _sealed_changes(history):
    """Rows whose confirmation seal covers the stored proposal. Anything else is ignored."""
    from log_store import _trusted_change

    sealed = []
    if not isinstance(history, list):
        return sealed
    for row in history:
        if not isinstance(row, dict):
            continue
        changes = row.get("changes")
        if not isinstance(changes, dict):
            continue
        trusted = _trusted_change(row, changes)
        if trusted:
            sealed.append(trusted)
    return sealed


def adult_profile():
    """A caller-supplied adult. The loop does not invent one."""
    return {
        "age": 30,
        "sex": "male",
        "weight_kg": 80,
        "height_cm": 180,
        "par_q": {flag: False for flag in ReadinessScreen.PAR_Q_RED_FLAGS},
        "pregnant": False,
        "medical_conditions": [],
        "medical_clearance": False,
    }


def simulate_happy_week(history=None):
    """Seven bot-led days. The user only answers the questions."""
    loop = DailyLoop(
        load=80,
        minutes=45,
        calories=2200,
        history=history,
        profile=adult_profile(),
    )
    start = date(2026, 10, 26)
    mornings = (
        "no 8 fine 45",
        "no 8 very sore 30",
        "no bad sleep fine 40",
        "no 8 fine 45",
        "no 8 fine 45",
        "no 8 fine 45",
        "no 8 fine 45",
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
