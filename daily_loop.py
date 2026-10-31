#!/usr/bin/env python3
"""Bot-led day. The user answers in a word or a number. They do not start the chat."""

from datetime import date, timedelta
import json
import os
import re

from morning_checkin import MorningCheckIn
from red_flag_check import RedFlagChecker, clear_safety_no, is_passing_check_in
from readiness_screen import ReadinessScreen, passing_readiness
from safety_labels import hard_stop, hard_stop_message, label_action
from signals import read_gap_reply


_SYMPTOM = "Morning. Any chest pain, trouble breathing, dizziness or new pain? no / yes"
_MORNING = "Hours of sleep, and soreness from 1 to 5?"
_SECOND = "One more: soreness or sleep, in a word or a number."
_EVENING = "Did you do it? easy, right, or hard. What did you eat?"
_NUDGE = "Missed today. I'll pick it up in the morning."


def _data_file_message():
    """The unreadable-key line, when a saved pause would otherwise hide it."""
    from seal_secret import DATA_FILE_MESSAGE, _key_path, _read_installed

    path = _key_path()
    if os.path.isfile(path) and _read_installed(path) is None:
        return DATA_FILE_MESSAGE
    return None


def _onboarding_hold():
    """The onboarding symptom hold, when one still blocks today."""
    from onboarding import active_hold_message

    return active_hold_message()


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
    for name in ("soreness", "energy", "stress"):
        if name in parsed:
            continue
        for index, number in enumerate(numbers):
            if 1 <= number <= 5:
                parsed[name] = number
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


_WEEKDAYS = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
)
_LEADING_NO = re.compile(r"^\s*(no|nope)\b\s*[,.]?\s*", re.IGNORECASE)
_LEADING_NUMBER = re.compile(r"(\d+)\s*[,.]?\s*")
_SKIP_SPORTS = {"general training", "lifting", "gym", "weights", "none", "no"}
# A leftover remark is kept only when every token is on this list.
# A symptom, a hedge, or any other word re-asks. It does not send a session.
_REMARK_WORDS = frozenset({
    "yep", "yeah", "yes", "yup", "ok", "okay",
    "thanks", "thank", "hi", "hello", "hey",
    "going", "doing", "gonna", "plan", "plans", "planned",
    "parkrun", "run", "running", "race", "racing",
    "at", "am", "pm", "today", "tomorrow", "tonight",
    "morning", "afternoon", "evening",
    "breakfast", "lunch", "dinner", "snack", "food", "eat", "eating", "ate",
    "meal", "coffee", "tea", "eggs", "toast", "oats", "oatmeal", "yogurt",
    "chicken", "rice", "salad", "protein", "shake", "banana", "apple",
    "milk", "water", "juice",
    "a", "an", "the", "to", "for", "my", "i", "im", "on", "in", "and",
    "then", "of", "with", "some", "it", "just", "after", "before", "this",
})


def _weekday_name(day):
    return _WEEKDAYS[date.fromisoformat(str(day)[:10]).weekday()]


def _split_scored_no(reply):
    """A leading no plus at least two scores, then a leftover remark.

    'no, 7, 2, 4, 2' has no leftover, so it stays on the clear-no path and
    energy and stress still parse. 'no, 7, 2. yep doing parkrun at 9' keeps
    the scores in the prefix and the remark as the note.
    """
    if not isinstance(reply, str):
        return None
    text = reply.strip()
    opened = _LEADING_NO.match(text)
    if not opened:
        return None
    rest = text[opened.end():]
    numbers = []
    while True:
        found = _LEADING_NUMBER.match(rest)
        if not found:
            break
        numbers.append(found.group(1))
        rest = rest[found.end():]
    if len(numbers) < 2:
        return None
    note = rest.strip(" \t.,;")
    if not note:
        return None
    prefix = f"{opened.group(1).lower()}, " + ", ".join(numbers)
    return prefix, note


_BARE_YES = frozenset({"yes", "yep", "yeah", "yup", "ok", "okay"})


def _leading_symptom_no(reply):
    """An explicit no or nope at the start of the symptom answer."""
    if not isinstance(reply, str):
        return False
    return re.match(r"\s*(?:no|nope)\b", reply, flags=re.IGNORECASE) is not None


def _bare_symptom_no(reply):
    """'No.' and 'no' are the same answer. Trailing punctuation does not count."""
    if not isinstance(reply, str):
        return False
    text = _fold(reply).strip(" .,!?;:\"'`")
    return text in {"no", "nope"}


def _remark_allowed(note):
    """True when the leftover is only an allowlisted plan, time, food, or greeting.

    The whole remark has to match. A question mark, a symptom, or any other
    word does not. Numbers are only clock pieces, up to 59. A remark that is
    only yes or yep is not a note. Those words can still sit inside a longer
    allowlisted remark.
    """
    if not isinstance(note, str) or not note.strip():
        return False
    if "?" in note or "？" in note:
        return False
    text = note.strip().lower().replace("'", "").replace("\u2019", "")
    text = re.sub(r"\b\d{1,2}:\d{2}\b", " ", text)
    tokens = re.findall(r"[a-z]+|\d+", text)
    if not tokens:
        return False
    words = []
    for token in tokens:
        if token.isdigit():
            if int(token) > 59:
                return False
            continue
        if token not in _REMARK_WORDS:
            return False
        words.append(token)
    if words and all(token in _BARE_YES for token in words):
        return False
    return True


def _safety_line(reply):
    """Hard-stop copy plus the checker's own line when it has one. Negation is ignored."""
    from record_confirmation import reply_pause

    message = hard_stop_message()
    paused = reply_pause(reply) if isinstance(reply, str) else None
    extra = getattr(paused, "message", None) if paused is not None else None
    if isinstance(extra, str) and extra.strip() and extra not in message:
        message = f"{message} {extra.strip()}"
    if "doctor" not in message.lower():
        message = (
            message
            + " Rest today. Come back tomorrow, or after you see a doctor."
        )
    return message


def _label_hold_text(reply, labels):
    """A red flag uses the emergency line. A second unclear uses the rest line."""
    from safety_labels import validate_labels

    parsed, reason = validate_labels(labels) if labels is not None else (None, "missing")
    flag = parsed["red_flag"] if reason is None else "none"
    if flag in {"chest_pain", "cardiac_symptoms", "breathing_difficulty", "fainting"}:
        return _safety_line(reply)
    return "Rest today. Come back tomorrow, or after you see a doctor."


_EVENING_FOOD = frozenset({
    "ate", "oats", "oatmeal", "breakfast", "lunch", "dinner", "coffee", "tea",
    "salad", "chicken", "rice", "eggs", "toast", "yogurt", "banana", "apple",
    "milk", "water", "juice", "protein", "shake", "snack", "food", "meal",
})
_EVENING_DID = frozenset({
    "yes", "yep", "yeah", "yup", "no", "nope", "did", "didnt",
})
_EVENING_WORDS = _EVENING_FOOD | _EVENING_DID | frozenset({
    "not", "it", "easy", "right", "hard", "the", "a", "workout", "and",
})


def _evening_exact(reply):
    """The whole reply is a did or didn't answer and food tokens. Nothing else.

    'no idea what I ate' is the closed food-unknown token. Extra words need labels.
    """
    text = _fold(reply)
    if not text:
        return False
    scan = text
    if _food_unknown(text):
        scan = _FOOD_DOUBT.sub(" ", text)
        scan = re.sub(r"\bwhat i ate\b", " ", scan)
    words = re.findall(r"[a-z0-9]+", scan)
    if not words or any(word not in _EVENING_WORDS and not word.isdigit() for word in words):
        return False
    did = any(word in _EVENING_DID for word in words)
    food = any(word in _EVENING_FOOD for word in words) or _food_unknown(text)
    return did or food


def _evening_explicit(reply):
    """Kept for callers that only need the old word check. The engine uses _evening_exact."""
    return _evening_exact(reply)


def _score_exact(reply):
    """Numbers and the short check-in words only. Extra words need labels."""
    if not isinstance(reply, str) or not reply.strip():
        return False
    tokens = re.findall(r"[a-z]+|\d+(?:\.\d+)?", reply.lower().replace("'", ""))
    if not tokens:
        return False
    for token in tokens:
        if re.fullmatch(r"\d+(?:\.\d+)?", token):
            continue
        if token not in _CHECKIN_WORDS:
            return False
    return True


def _remark_pause(note):
    """scan_text and reply_pause on the remark alone. A leading no is not in it."""
    from record_confirmation import reply_pause

    if not isinstance(note, str) or not note.strip():
        return None
    paused = reply_pause(note)
    scanned = RedFlagChecker().scan_text(note)
    real = [
        flag for flag in (scanned.flags_detected or [])
        if flag != "needs_clarification"
    ]
    if not real:
        return None
    if paused is not None:
        return _pause_text(paused)
    if scanned.pause_plan:
        return _pause_text(scanned)
    return None


def _shown_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value == int(value):
        return str(int(value))
    return str(value)


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
    "sport_day",
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

    def __init__(self, load=80, minutes=45, calories=None, confirmed_at=None, goal="hold", signals=None, outreach=None, history=None, profile=None, week_path=None, log_path=None):
        self.load = load
        self.minutes = minutes
        self.calories = calories
        self.goal = goal
        self.confirmed_at = confirmed_at
        self.signals = signals
        self.outreach = outreach
        self.profile = profile
        self.week_path = week_path
        self.log_path = log_path
        self.history = list(history) if history else []
        self.phase = {}
        self.notes = {}
        self.nudges = {}
        self.felt_easy = 0
        self.workouts = {}
        self.questions = {}
        self.pending = {}
        self.hold_text = {}

    def open_morning(self, day):
        """The bot opens with the symptom line. Wearables skip only the other questions.

        A pause or an onboarding hold already in force for today stays. Opening
        the morning again does not clear it or start a session.
        """
        held = _onboarding_hold()
        if held:
            return held
        if self.phase.get(day) == "paused":
            blocked = _data_file_message()
            if blocked:
                return blocked
            return self.hold_text.get(day) or self._saved_pause(day) or _SYMPTOM
        saved = self._saved_pause(day)
        if saved:
            self.phase[day] = "paused"
            self.hold_text[day] = saved
            blocked = _data_file_message()
            if blocked:
                return blocked
            return saved
        pending = self._pending(day)
        if pending:
            return self._pending_open(day, pending)
        self.notes[day] = {}
        self.phase[day] = "symptom"
        if self._rest_day(day):
            self.questions[day] = 0
            return _SYMPTOM
        extra = self._other_questions(day)
        if extra:
            return f"{_SYMPTOM} {extra}"
        return _SYMPTOM

    def _has_session(self, day):
        """A rest day or a sport day with no session gets the symptom line only."""
        profile = self.profile if isinstance(self.profile, dict) else None
        if not profile:
            return True
        days = profile.get("days")
        if not isinstance(days, list) or not days:
            return True
        return day in {str(item) for item in days}

    def _rest_day(self, day):
        """A confirmed week with no session that date is a rest day.

        With no confirmed week, the profile's day list decides. A missing
        list still counts as a session, so an unplanned loop can name a day.
        """
        if self._confirmed_week() is not None:
            return self._confirmed_session(day) is None
        return not self._has_session(day)

    def _food_text(self):
        if self.calories is not None:
            shown = _shown_number(self.calories)
            if shown is not None:
                return f"{shown} kcal"
        week = self._confirmed_week()
        plan = week.get("plan") if isinstance(week, dict) else None
        nutrition = plan.get("nutrition") if isinstance(plan, dict) else None
        calories = nutrition.get("calories") if isinstance(nutrition, dict) else None
        shown = _shown_number(calories)
        if shown is not None:
            return f"{shown} kcal"
        return self.goal

    def _scheduled_sport(self, day):
        """The sport name when that sport is on today's weekday."""
        profile = self.profile if isinstance(self.profile, dict) else None
        if not profile:
            return None
        sport = profile.get("sport")
        if not isinstance(sport, str):
            return None
        name = " ".join(sport.split())
        if not name or name.lower() in _SKIP_SPORTS:
            return None
        sport_day = profile.get("sport_day")
        if not isinstance(sport_day, str) or not sport_day.strip():
            return None
        if sport_day.strip().lower()[:3] != _weekday_name(day).lower()[:3]:
            return None
        return name

    def _next_session(self, day):
        week = self._confirmed_week()
        if not week:
            return None
        later = []
        for row in week.get("sessions") or []:
            if isinstance(row, dict) and str(row.get("date") or "") > str(day):
                later.append(row)
        if not later:
            return None
        later.sort(key=lambda row: str(row.get("date")))
        return later[0]

    def _annotate(self, day, text):
        as_of = f"{day}T12:00:00Z"
        if self.signals is not None and "resting_hr" in self.signals.abnormal(as_of):
            text += " If you feel unwell, check with a doctor."
        if self.signals is not None and self.signals.connected():
            note = self.signals.plan_note(f"{day}T08:00:00Z")
            if self.outreach is not None:
                self.outreach.scheduled(day, note)
            if note and note != "Today is on plan.":
                text = f"{note} {text}"
        return text

    def _rest_line(self, day, food):
        sport = self._scheduled_sport(day)
        if sport:
            line = f"Rest day. Enjoy {sport}, keep it conversational."
        else:
            line = "Rest day."
        text = f"{line} Food: {food}."
        nxt = self._next_session(day)
        if nxt:
            name = nxt.get("name") or "Session"
            when = _weekday_name(nxt.get("date"))
            text += f" Next: {name} on {when}."
        return text

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
        held = _onboarding_hold()
        if held:
            return held
        self.phase[day] = "evening"
        return _EVENING

    def nudge(self, day):
        """One gentle nudge for a missed day. A second call says nothing."""
        held = _onboarding_hold()
        if held:
            return held
        if self.nudges.get(day, 0) >= 1:
            return None
        self.nudges[day] = 1
        return _NUDGE

    def hear(self, day, reply, labels=None):
        held = _onboarding_hold()
        if held:
            return held
        if self.phase.get(day) == "paused" or self._saved_pause(day):
            blocked = _data_file_message()
            if blocked:
                return blocked
        if hard_stop(reply):
            self.notes.setdefault(day, {})["reply"] = reply
            return self._remember_pause(day, _safety_line(reply))
        pending_reply = self._gate_pending(day, reply, labels)
        if pending_reply is not None:
            return pending_reply
        gated = self._labels_before_workout(day, reply, labels)
        if gated is not None:
            return gated
        phase = self.phase.get(day)
        if phase == "symptom":
            self.notes.setdefault(day, {})["reply"] = reply
            if symptom_is_clear(reply):
                return self._after_symptom(day, reply)
            split = _split_scored_no(reply)
            if split:
                prefix, note = split
                return self._labeled_note(day, prefix, note, labels)
            return self._free_text_hold(day, reply, labels)
        if phase == "signals":
            pending = self.pending.get(day, {"gaps": [], "personal": []})
            notes = self.notes.setdefault(day, {})
            notes["reply"] = (notes.get("reply") or "") + " " + reply
            notes.update(read_gap_reply(pending["gaps"], reply))
            self._use_hr_answer(day, f"{day}T08:00:00Z")
            for key in pending["personal"]:
                self.signals.settle(key)
            self._seed(day, f"{day}T08:00:00Z")
            return self._workout(day)
        if phase == "morning2":
            notes = self.notes.setdefault(day, {})
            notes["reply"] = (notes.get("reply") or "") + " " + reply
            notes.update(parse_morning(reply))
            return self._workout(day)
        if phase == "evening":
            return self._evening(day, reply, labels)
        return "I'll pick it up in the morning."

    def _unclear_path(self):
        week = self._week_file()
        return os.path.join(os.path.dirname(os.path.abspath(week)), "daily_unclear.json")

    def _unclear_count(self, day):
        path = self._unclear_path()
        if not os.path.isfile(path):
            return 0
        try:
            with open(path, encoding="utf-8") as handle:
                loaded = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return 0
        if not isinstance(loaded, dict):
            return 0
        value = loaded.get(str(day))
        if isinstance(value, int) and value >= 0:
            return value
        return 0

    def _set_unclear(self, day, count):
        path = self._unclear_path()
        loaded = {}
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as handle:
                    found = json.load(handle)
                if isinstance(found, dict):
                    loaded = found
            except (OSError, json.JSONDecodeError):
                loaded = {}
        loaded[str(day)] = count
        temporary = path + ".tmp"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(loaded, handle)
                handle.write("\n")
            os.replace(temporary, path)
        except OSError:
            return False
        return True

    def _free_text_hold(self, day, reply, labels):
        """A remark with no scores needs labels. One miss re-asks. The next holds."""
        action = label_action(labels, self._unclear_count(day))
        if action == "hold":
            return self._remember_pause(day, _label_hold_text(reply, labels))
        if action == "clear_age":
            self._write_pending(day, "age_check")
            self.phase[day] = "symptom"
            return "How old are you? Please type the number."
        if action == "follow_up":
            self._set_unclear(day, self._unclear_count(day) + 1)
            self._open_follow_up(day, reply, labels)
            self.phase[day] = "symptom"
            return _SYMPTOM
        if action == "swap":
            self._remember_old_injury(day, reply)
            return self._after_symptom(day, reply)
        if action == "note" and isinstance(reply, str):
            self.notes.setdefault(day, {})["note"] = reply.strip()
        if action in {"note", "pass"} and _leading_symptom_no(reply):
            self.notes.setdefault(day, {})["symptom_cleared"] = True
            return self._after_symptom(day, reply)
        self.phase[day] = "symptom"
        if action in {"note", "pass"}:
            return "Still need a clear no or yes on the symptom line."
        return _SYMPTOM

    def _labeled_note(self, day, prefix, note, labels):
        """A leftover remark. note_ok stores it. Anything else does not send the day."""
        action = label_action(labels, self._unclear_count(day))
        if action == "hold":
            return self._remember_pause(day, _label_hold_text(note, labels))
        if action == "clear_age":
            self._write_pending(day, "age_check")
            self.phase[day] = "symptom"
            return "How old are you? Please type the number."
        if action == "follow_up":
            self._set_unclear(day, self._unclear_count(day) + 1)
            self._open_follow_up(day, note, labels)
            self.phase[day] = "symptom"
            return _SYMPTOM
        words = re.findall(r"[a-z]+", _fold(note))
        if words and all(word in _BARE_YES for word in words):
            self.phase[day] = "symptom"
            return _SYMPTOM
        if action == "note":
            self.notes.setdefault(day, {})["note"] = note
            return self._after_symptom(day, prefix)
        if action == "swap":
            self.notes.setdefault(day, {})["injury"] = note
            self._remember_old_injury(day, note)
            return self._after_symptom(day, prefix)
        if action == "pass":
            return self._after_symptom(day, prefix)
        self.phase[day] = "symptom"
        return _SYMPTOM

    def _symptom_hold(self, reply):
        """A real symptom in the whole message. A missing checklist does not hold."""
        checker = RedFlagChecker()
        scanned = checker.scan_check_in({"notes": reply if isinstance(reply, str) else ""})
        real = [
            flag for flag in (scanned.flags_detected or [])
            if flag != "needs_clarification"
        ]
        if not real:
            return None
        paused = self._text_pause(reply)
        if paused:
            return paused
        if scanned.pause_plan:
            return _pause_text(scanned)
        return None

    def _unclear_symptom(self, day, reply):
        """Not a clear no. scan_check_in runs, then one gentle re-ask. No workout."""
        held = self._symptom_hold(reply)
        if held:
            return self._remember_pause(day, held)
        self.phase[day] = "symptom"
        return _SYMPTOM

    def _pause_file(self):
        """The pause sits beside the week file so a new DailyLoop can load it."""
        week = self._week_file()
        return os.path.join(os.path.dirname(os.path.abspath(week)), "daily_pause.json")

    def _saved_pause(self, day):
        path = self._pause_file()
        if not path or not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as handle:
                loaded = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(loaded, dict):
            return None
        text = loaded.get(str(day))
        if isinstance(text, str) and text.strip():
            return text
        return None

    def _write_pause(self, day, text):
        path = self._pause_file()
        loaded = {}
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as handle:
                    found = json.load(handle)
                if isinstance(found, dict):
                    loaded = found
            except (OSError, json.JSONDecodeError):
                loaded = {}
        loaded[str(day)] = text
        temporary = path + ".tmp"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(loaded, handle)
                handle.write("\n")
            os.replace(temporary, path)
        except OSError:
            return False
        return True

    def _remember_pause(self, day, text):
        """Keep the pause. A later open_morning, even on a new object, returns it."""
        self.phase[day] = "paused"
        self.hold_text[day] = text
        self._write_pause(day, text)
        self._write_pending(day, "hold", message=text)
        return text

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
            self.notes.setdefault(day, {}).update(parse_morning(reply))
            notes = self.notes.setdefault(day, {})
            if self._needs_more(day):
                if (
                    _bare_symptom_no(reply)
                    or self._rest_day(day)
                    or notes.get("symptom_cleared")
                ):
                    self._fill_defaults(day, as_of)
                else:
                    self.phase[day] = "morning2"
                    return _SECOND
            return self._workout(day)
        self.notes.setdefault(day, {}).update(read_gap_reply(pending["gaps"], reply))
        self._use_hr_answer(day, as_of)
        abnormal = set(self.signals.abnormal(as_of)) if self.signals is not None else set()
        unanswered = [
            gap for gap in pending["gaps"]
            if self._gap_open(day, gap) and gap not in abnormal
        ]
        personal = list(pending["personal"])
        if personal and not _bare_symptom_no(reply) and _fold(reply) != "none":
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
        notes = self.notes.setdefault(day, {})
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

    def _fill_defaults(self, day, as_of):
        """Wearable sleep when it is fresh, otherwise sleep 7 and soreness 2."""
        self._seed(day, as_of)
        notes = self.notes.setdefault(day, {})
        if "sleep" not in notes:
            notes["sleep"] = 7
        if "soreness" not in notes:
            notes["soreness"] = 2

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

    def _all_no_check(self, reply):
        checker = RedFlagChecker()
        answers = {aliases[0]: "no" for _flag, aliases in checker.CHECKLIST_GROUPS}
        return checker.scan_check_in({"symptom_checklist": answers, "notes": reply})

    def _checklist(self, reply):
        """Fill all-no here. scan_check_in does not treat a bare no as the list.

        A bare no or nope, plus scores, is the short morning line. 'none'
        still counts only after the full list was shown, except when this
        caller already decided the short line was clear.
        """
        if clear_safety_no(reply) or symptom_is_clear(reply) or _split_scored_no(reply):
            return self._all_no_check(reply)
        return RedFlagChecker().scan_check_in({"notes": reply})

    def _before_training(self, day):
        notes = self.notes.get(day, {})
        reply = notes.get("reply") or ""
        if notes.get("symptom_cleared"):
            result = self._all_no_check(reply)
        else:
            result = self._checklist(reply)
        if not is_passing_check_in(result):
            text = _pause_text(result)
            from seal_secret import DATA_FILE_MESSAGE

            if DATA_FILE_MESSAGE in text:
                return DATA_FILE_MESSAGE
            return self._remember_pause(day, text)
        if not isinstance(self.profile, dict):
            return self._remember_pause(day, "Readiness has to pass before training.")
        screen = ReadinessScreen().screen_intake(_readiness_intake(self.profile))
        if not passing_readiness(screen):
            for reason in screen.reasons or []:
                if isinstance(reason, str) and "can't be read" in reason:
                    return reason
                if isinstance(reason, str) and reason.startswith("Unknown key:"):
                    return self._remember_pause(day, reason)
            return self._remember_pause(day, "Readiness has to pass before training.")
        return None

    def _week_file(self):
        if self.week_path:
            return self.week_path
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "week.json")

    def _confirmed_week(self):
        """The saved week, or None when the file is missing or not confirmed."""
        path = self._week_file()
        if not path or not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as handle:
                loaded = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(loaded, dict):
            return None
        confirmation = loaded.get("confirmation")
        sessions = loaded.get("sessions")
        if not isinstance(confirmation, dict) or not confirmation.get("record_id"):
            return None
        if not isinstance(sessions, list):
            return None
        return loaded

    def _confirmed_session(self, day):
        loaded = self._confirmed_week()
        if loaded is None:
            return None
        for row in loaded["sessions"]:
            if isinstance(row, dict) and str(row.get("date")) == str(day):
                return row
        return None

    def _workout(self, day):
        pending = self._pending(day)
        if isinstance(pending, dict):
            if pending.get("kind") == "age_check":
                return "How old are you? Please type the number."
            if pending.get("kind") == "hold":
                text = pending.get("message") or self._saved_pause(day)
                if isinstance(text, str) and text.strip():
                    return text
                return "Rest today. Come back tomorrow, or after you see a doctor."
            return self._phase_prompt(self.phase.get(day))
        blocked = self._before_training(day)
        if blocked:
            return blocked
        scores = self._scores(day)
        as_of = f"{day}T12:00:00Z"
        note = self.notes.get(day, {}).get("note")
        checked = MorningCheckIn().check_in(
            scores,
            confirmed_changes=self.history,
            as_of=as_of,
            log_path=self.log_path,
            note=note if isinstance(note, str) and note.strip() else None,
        )
        day_name = checked.get("day") or "normal"
        changes = (checked.get("proposal") or {}).get("changes") or {}
        session = self._confirmed_session(day)
        needs_yes = False
        name = None
        exercises = None
        if session:
            name = session.get("name") or "Session"
            exercises = session.get("exercises") if isinstance(session.get("exercises"), list) else []
            available = session.get("minutes", self.notes.setdefault(day, {}).get("minutes", self.minutes))
            session_load = session.get("load", self.load)
            proposed = changes.get("load")
            load = session_load
            if isinstance(proposed, (int, float)) and isinstance(session_load, (int, float)):
                if proposed > session_load:
                    needs_yes = True
                    load = proposed
                elif proposed < session_load:
                    load = proposed
            if day_name == "easy":
                session_minutes = max(15, int(round(available * 0.7)))
                lead = f"Easy day. {name}."
            else:
                session_minutes = available
                lead = f"{name}."
            exercises = self._with_old_injury(day, exercises)
            names = []
            for item in exercises:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    names.append(item["name"])
                elif isinstance(item, str) and item:
                    names.append(item)
            shown = ", ".join(names)
            text = f"{lead} {shown}. {session_minutes} min."
            if needs_yes:
                text += " Yes to raise the load."
            week = self._confirmed_week()
            dates = [
                str(row.get("date"))
                for row in (week or {}).get("sessions", [])
                if isinstance(row, dict) and row.get("date")
            ]
            first = min(dates) if dates else None
            if session.get("experience") == "intermediate" and str(day) == first:
                text += " Pick a weight you can lift 10 times with 2 reps left."
        elif self._rest_day(day):
            food = self._food_text()
            text = self._annotate(day, self._rest_line(day, food))
            self.workouts[day] = {
                "day": "rest",
                "food": food,
                "text": text,
                "needs_yes": False,
            }
            self.phase[day] = "workout"
            return text
        else:
            load = changes.get("load", self.load)
            available = self.notes.setdefault(day, {}).get("minutes", self.minutes)
            if day_name == "easy":
                session_minutes = max(15, int(round(available * 0.7)))
                lead = "Easy day."
            else:
                session_minutes = available
                lead = f"Today is a {day_name} day."
            text = f"{lead} {session_minutes} min."
        food = self._food_text()
        text = self._annotate(day, f"{text} Food: {food}.")
        row = {
            "day": name or day_name,
            "minutes": session_minutes,
            "load": load,
            "food": food,
            "text": text,
            "needs_yes": needs_yes,
        }
        if name:
            row["name"] = name
            row["exercises"] = exercises
        self.workouts[day] = row
        self.phase[day] = "workout"
        return text

    def _safety_directory(self):
        return os.path.dirname(os.path.abspath(self._pause_file()))

    def _pending(self, day):
        from safety_pending import read_pending

        return read_pending(self._safety_directory(), day, "daily")

    def _write_pending(self, day, kind, **extra):
        from safety_pending import write_pending

        return write_pending(self._safety_directory(), kind, day, "daily", **extra)

    def _clear_pending(self):
        from safety_pending import clear_pending

        return clear_pending(self._safety_directory(), "daily")

    def _remember_old_injury(self, day, text):
        if isinstance(text, str) and text.strip():
            self.notes.setdefault(day, {})["old_injury"] = text

    def _open_follow_up(self, day, reply, labels):
        """Missing or invalid labels are not cleared by an Old/Recent tap."""
        from onboarding import _follow_up_cause

        text = reply if isinstance(reply, str) else ""
        self._write_pending(day, "follow_up", cause=_follow_up_cause(labels), text=text)

    def _bare_number(self, reply, labels):
        from safety_pending import typed_age

        return labels is None and typed_age(reply) is not None

    def _pending_open(self, day, pending):
        """Opening the morning does not prescribe over a pending record."""
        kind = pending.get("kind")
        if kind == "hold":
            self.phase[day] = "paused"
            text = pending.get("message") or self._saved_pause(day)
            if not isinstance(text, str) or not text.strip():
                text = "Rest today. Come back tomorrow, or after you see a doctor."
            self.hold_text[day] = text
            return text
        if kind == "age_check":
            return "How old are you? Please type the number."
        return self._phase_prompt(self.phase.get(day) or "symptom")

    def _gate_pending(self, day, reply, labels):
        """Structured input only. Anything else does not prescribe or log."""
        from safety_pending import resolves_follow_up, typed_age

        pending = self._pending(day)
        if not isinstance(pending, dict):
            return None
        kind = pending.get("kind")
        if kind == "hold":
            self.phase[day] = "paused"
            text = pending.get("message") or self._saved_pause(day) or self.hold_text.get(day)
            if not isinstance(text, str) or not text.strip():
                text = "Rest today. Come back tomorrow, or after you see a doctor."
            return text
        if kind == "age_check":
            number = typed_age(reply) if labels is None else None
            if number is None or number < 13 or number > 100:
                return "How old are you? Please type the number."
            if number < 18:
                return self._remember_pause(
                    day, "Rest today. Come back tomorrow, or after you see a doctor."
                )
            self._clear_pending()
            return self._phase_prompt(self.phase.get(day))
        if kind == "follow_up":
            button = None
            if labels is None:
                from onboarding import _injury_button

                button = _injury_button(reply)
            injury_unclear = pending.get("cause") == "injury_unclear"
            if self._bare_number(reply, labels):
                return self._phase_prompt(self.phase.get(day))
            if resolves_follow_up(
                labels, button=button, injury_unclear=injury_unclear
            ):
                saved = pending.get("text") if isinstance(pending.get("text"), str) else ""
                self._clear_pending()
                self._set_unclear(day, 0)
                return self._resolve_follow_up(day, reply, labels, button, saved)
            return self._remember_pause(
                day, "Rest today. Come back tomorrow, or after you see a doctor."
            )
        return self._remember_pause(
            day, "Rest today. Come back tomorrow, or after you see a doctor."
        )

    def _resolve_follow_up(self, day, reply, labels, button, saved=""):
        """Store the structured answer. This turn does not prescribe or log."""
        area = saved if isinstance(saved, str) and saved.strip() else reply
        if button == "current":
            return self._remember_pause(
                day, "Rest today. Come back tomorrow, or after you see a doctor."
            )
        if button == "old":
            self._remember_old_injury(day, area)
            return self._phase_prompt(self.phase.get(day))
        action = label_action(labels, 0)
        if action == "clear_age":
            self._write_pending(day, "age_check")
            return "How old are you? Please type the number."
        if action == "hold":
            return self._remember_pause(day, _label_hold_text(reply, labels))
        if action == "swap":
            self._remember_old_injury(day, area or reply)
            return self._phase_prompt(self.phase.get(day))
        return self._phase_prompt(self.phase.get(day))

    def _with_old_injury(self, day, exercises):
        """injury=old swaps the lifts that load the area named in the reply."""
        text = (self.notes.get(day) or {}).get("old_injury")
        if not isinstance(text, str) or not text.strip():
            return exercises
        from plan_builder import _blocks_exercise, _injury_replacements

        kept = []
        for item in exercises:
            name = item.get("name") if isinstance(item, dict) else item
            if isinstance(name, str) and _blocks_exercise(name, text):
                continue
            kept.append(item)
        for extra in _injury_replacements(text):
            already = False
            for item in kept:
                current = item.get("name") if isinstance(item, dict) else item
                if current == extra:
                    already = True
                    break
            if not already:
                kept.append({"name": extra, "sets": 3, "reps": "8-12"})
        return kept

    def _labels_before_workout(self, day, reply, labels):
        """Label action before any workout. Free text in later phases needs labels."""
        phase = self.phase.get(day)
        if labels is not None:
            action = label_action(labels, self._unclear_count(day))
            if action == "hold":
                return self._remember_pause(day, _label_hold_text(reply, labels))
            if action == "clear_age":
                self._write_pending(day, "age_check")
                return "How old are you? Please type the number."
            if action == "swap":
                self._remember_old_injury(day, reply)
            if action not in {"note", "pass", "swap"}:
                count = self._unclear_count(day)
                if count >= 1:
                    return self._remember_pause(
                        day, "Rest today. Come back tomorrow, or after you see a doctor."
                    )
                self._set_unclear(day, count + 1)
                self._open_follow_up(day, reply, labels)
                return self._phase_prompt(phase)
        elif self._bare_number(reply, labels) and phase not in {"morning2", "signals"}:
            return self._phase_prompt(phase)
        elif (
            phase in {"morning2", "signals"}
            and not _score_exact(reply)
            and not self._bare_number(reply, labels)
        ):
            count = self._unclear_count(day)
            if count >= 1:
                return self._remember_pause(
                    day, "Rest today. Come back tomorrow, or after you see a doctor."
                )
            self._set_unclear(day, count + 1)
            self._open_follow_up(day, reply, None)
            return self._phase_prompt(phase)
        elif phase == "evening" and not _evening_exact(reply):
            count = self._unclear_count(day)
            if count >= 1:
                return self._remember_pause(
                    day, "Rest today. Come back tomorrow, or after you see a doctor."
                )
            self._set_unclear(day, count + 1)
            self._open_follow_up(day, reply, None)
            self.phase[day] = "evening"
            return _EVENING
        elif phase == "symptom" and labels is None and not symptom_is_clear(reply) and not _split_scored_no(reply):
            count = self._unclear_count(day)
            if count >= 1:
                return self._remember_pause(
                    day, "Rest today. Come back tomorrow, or after you see a doctor."
                )
            self._set_unclear(day, count + 1)
            self._open_follow_up(day, reply, None)
            self.phase[day] = "symptom"
            return _SYMPTOM
        return None

    def _phase_prompt(self, phase):
        if phase == "evening":
            return _EVENING
        if phase == "morning2":
            return _SECOND
        return _SYMPTOM

    def _evening(self, day, reply, labels=None):
        if labels is not None:
            action = label_action(labels, self._unclear_count(day))
            if action == "hold":
                return self._remember_pause(day, _label_hold_text(reply, labels))
            if action == "clear_age":
                self._write_pending(day, "age_check")
                return "How old are you? Please type the number."
            if action == "swap":
                self._remember_old_injury(day, reply)
            if action not in {"note", "pass", "swap"}:
                self._set_unclear(day, self._unclear_count(day) + 1)
                self._open_follow_up(day, reply, labels)
                self.phase[day] = "evening"
                return _EVENING
        elif not _evening_exact(reply):
            self.phase[day] = "evening"
            return _EVENING
        notes = self.notes.setdefault(day, {})
        parsed = parse_evening(reply)
        if parsed.get("ate") == "" and notes.get("ate"):
            parsed = {key: value for key, value in parsed.items() if key != "ate"}
        notes.update(parsed)
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
        held = _onboarding_hold()
        if held:
            return {"load": self.load, "changed": False, "food": food, "text": held}
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
