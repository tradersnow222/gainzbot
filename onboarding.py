#!/usr/bin/env python3
"""Grouped onboarding. A few short messages, then one yes."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import contextvars
import json
import os
import re
import unicodedata

from safety_labels import hard_stop, hard_stop_message, label_action, validate_labels


PAR_Q = (
    ("chest_pain_at_rest", "Do you have chest pain while resting?"),
    ("chest_pain_during_activity", "Do you have chest pain during activity?"),
    ("loss_of_balance_dizziness", "Do you lose balance because of dizziness?"),
    ("loss_of_consciousness", "Have you lost consciousness?"),
    ("bone_joint_problem_worsened_by_activity", "Do you have a bone or joint problem that activity makes worse?"),
    ("currently_taking_medications", "Do you currently take medication for blood pressure or a heart condition?"),
    ("doctor_advised_supervised_only", "Has a doctor said you should only train with supervision?"),
)

# Ok fills preferences only. Age, sex, weight, and height are never invented.
_GOAL_DEFAULTS = {
    "goal": "hold",
    "food_style": "no preference",
}
_TRAINING_DEFAULTS = {
    "sport": "general training",
    "training_days": "3",
    "minutes": "45",
    "equipment": "bodyweight",
    "experience": "beginner",
    "sources": "none",
}
_OPTIONAL = {"name", "food_style", "sources", "target"}
_ACCEPT = {"ok", "okay", "yep", "yeah", "defaults", "default", "sounds good", "do it", "lets go"}
_WEEK_OFFSETS = (0, 2, 4, 5, 1, 3, 6)
_DAY_INDEX = (
    ("monday", 0), ("tuesday", 1), ("wednesday", 2), ("thursday", 3),
    ("friday", 4), ("saturday", 5), ("sunday", 6),
    ("mon", 0), ("tue", 1), ("wed", 2), ("thu", 3), ("fri", 4), ("sat", 5), ("sun", 6),
)
_CONFIRM_PHASE = contextvars.ContextVar("gainzbot_confirm_phase", default=False)
_OUTSIDE_RUN_CHAT = "Stop. This only runs inside onboarding.run_chat."
_SETUP_WORDS = ("clone", "pip", "pytest", "release_check", "install", "git ")

_PASS_LABELS = {
    "minor_signal": False,
    "red_flag": "none",
    "injury": "none",
    "note_ok": False,
}

# The profile line carries host labels. injury=none on that line is the
# structured None tap. "all_no" is the PAR-Q button. The typed token
# "all no" or "all no." is that same button.
HAPPY_PATH = (
    "hello",
    (
        "hold, male, 80 kg, 180 cm, general training, 3 days 45 min, bodyweight, beginner, no injuries",
        _PASS_LABELS,
    ),
    "30",
    "all_no",
    "yes",
)


def _par_q_text():
    lines = [
        "PAR-Q, yes or no. Everyone gets these 7. One word: all no.",
    ]
    for key, question in PAR_Q:
        lines.append(f"- {key}: {question}")
    lines.append(
        "A skipped or unclear PAR-Q answer runs readiness_screen, the same as a yes. "
        "There is no training until readiness_screen passes. "
        "The PAR-Q still comes before any plan is built."
    )
    return "\n".join(lines)


def _injury_and_par_q(state):
    """The injury tap sits on the PAR-Q step. Ok does not ask training again."""
    parts = []
    answers = state.get("answers") if isinstance(state.get("answers"), dict) else {}
    if "injuries" not in answers:
        parts.append(_INJURY_TAP_LINE)
    par_q = _group("par_q")
    if par_q and _missing_keys(state, par_q):
        parts.append(par_q["text"])
    line = _optional_tracker_line(state)
    if line:
        parts.append(line)
        state["tracker_offered"] = True
    if parts:
        return "\n".join(parts)
    return _INJURY_TAP_LINE


GROUPS = (
    {
        "id": "goal",
        "asks": ("goal", "weight", "target", "height", "age", "sex", "name", "food_style"),
        "text": (
            "Goal, weight, target, height, and age? "
            "One word ok uses hold. It does not fill age, sex, weight, or height. "
            "You can skip one. I will not guess a skipped age, sex, or weight. "
            "If you skip the goal, the goal is hold."
        ),
    },
    {
        "id": "training",
        "asks": ("sport", "training_days", "minutes", "equipment", "experience", "injuries", "sources"),
        "text": (
            "Sport, schedule, and equipment? "
            "One word ok uses general training, 3 days, 45 min, bodyweight, beginner. "
            "It does not fill injuries. "
            "Any sport is fine. What do you track with? A watch, a scale, a food app, or none. "
            "I will not assume a connection. Sport and the schedule come before the PAR-Q."
        ),
    },
    {
        "id": "par_q",
        "asks": tuple(key for key, _question in PAR_Q),
        "text": _par_q_text(),
    },
)


def messages():
    """Three or four short intake messages. Not one question at a time."""
    if not (3 <= len(GROUPS) <= 4):
        return []
    return [group["text"] for group in GROUPS]


def question_one():
    """The first thing the bot says. No setup in front of it.

    A symptom hold dated today replaces that question. The bot still
    starts through run_chat, which is the only onboarding entry.
    """
    if hold_is_active():
        state = _state_for_attempt()
        return state.get("error") or state.get("hold_message") or _HOLD_CLOSED
    return GROUPS[0]["text"]


def _fold(reply):
    if not isinstance(reply, str):
        return ""
    text = reply.strip().lower().replace("'", "")
    cleaned = []
    for char in text:
        cleaned.append(char if char.isalnum() or char.isspace() else " ")
    return " ".join("".join(cleaned).split())


_LOCALTIME_PATH = "/etc/localtime"
_TIMEZONE_FILE = "/etc/timezone"
_memory_hold = None


def _now():
    """Aware local time. Tests replace this to pin the clock."""
    return datetime.now().astimezone()


def _zone(name):
    if not isinstance(name, str) or not name.strip():
        return None
    try:
        return ZoneInfo(name.strip())
    except (KeyError, ValueError, OSError):
        return None


def _offset_zone(name):
    """A stored UTC offset such as -07:00. The word UTC is not an offset."""
    if not isinstance(name, str):
        return None
    match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", name.strip())
    if match is None:
        return None
    hours = int(match.group(2))
    minutes = int(match.group(3))
    if hours > 23 or minutes > 59:
        return None
    sign = 1 if match.group(1) == "+" else -1
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def _usable_zone(name):
    return _zone(name) or _offset_zone(name)


def _format_offset(delta):
    if not isinstance(delta, timedelta):
        delta = timedelta(0)
    total = int(delta.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    hours, rem = divmod(total, 3600)
    minutes = rem // 60
    return f"{sign}{hours:02d}:{minutes:02d}"


def _tz_env_name():
    raw = os.environ.get("TZ")
    if not isinstance(raw, str):
        return None
    name = raw.strip()
    if name.startswith(":"):
        name = name[1:].strip()
    if _zone(name) is None:
        return None
    return name


def _localtime_zone_name():
    path = _LOCALTIME_PATH
    try:
        if not os.path.islink(path):
            return None
        target = os.path.realpath(path)
    except OSError:
        return None
    marker = f"{os.sep}zoneinfo{os.sep}"
    index = target.rfind(marker)
    if index == -1:
        return None
    name = target[index + len(marker):].strip()
    if _zone(name) is None:
        return None
    return name


def _timezone_file_name():
    try:
        with open(_TIMEZONE_FILE, encoding="utf-8") as handle:
            line = handle.read().strip().splitlines()
    except OSError:
        return None
    name = line[0].strip() if line else ""
    if _zone(name) is None:
        return None
    return name


def _iana_zone_name():
    """IANA name from TZ, then the localtime symlink, then /etc/timezone."""
    for name in (_tz_env_name(), _localtime_zone_name(), _timezone_file_name()):
        if name:
            return name
    return None


def _default_timezone_name():
    """The profile timezone. An offset when the box has no IANA name.

    datetime.now().astimezone() is a fixed offset and has no zone key.
    That offset is stored as -07:00. It is never the word UTC.
    """
    named = _iana_zone_name()
    if named:
        return named
    now = _now()
    if now.tzinfo is None:
        now = now.astimezone()
    return _format_offset(now.utcoffset())


def _timezone_name(answers=None, saved=None):
    """Name or offset on the profile, then the one stored with the hold, then the box."""
    sources = []
    if isinstance(answers, dict):
        sources.append(answers.get("timezone"))
    if isinstance(saved, dict):
        sources.append(saved.get("timezone"))
        nested = saved.get("answers")
        if isinstance(nested, dict):
            sources.append(nested.get("timezone"))
    for name in sources:
        if _usable_zone(name) is not None:
            return name.strip()
    return _default_timezone_name()


def _local_today(name=None):
    """The user's local calendar date. Not the UTC date."""
    zone = _usable_zone(name) if name else None
    if zone is None:
        named = _iana_zone_name()
        zone = _zone(named) if named else None
    now = _now()
    if now.tzinfo is None:
        now = now.astimezone()
    if zone is None:
        return now.astimezone().date()
    return now.astimezone(zone).date()


def _today():
    return _local_today()


def confirm_phase_active():
    """True only while run_chat is handling a reply in the confirm phase."""
    return _CONFIRM_PHASE.get() is True


def _dates(count, weekdays=None):
    """The next Mon/Wed/Fri, or the named days, on or after tomorrow."""
    count = max(1, min(7, int(count)))
    if not weekdays:
        weekdays = list(_WEEK_OFFSETS[:count])
    else:
        weekdays = list(weekdays)[:count]
    start = _local_today() + timedelta(days=1)
    pending = list(weekdays)
    found = []
    day = start
    for _step in range(28):
        if day.weekday() in pending:
            found.append(day)
            pending = [item for item in pending if item != day.weekday()]
            if not pending:
                break
        day += timedelta(days=1)
    found.sort()
    return [item.isoformat() for item in found]


def _training_weekdays(folded):
    """Named lifting days. A Saturday attached to parkrun is not one of them."""
    text = re.sub(r"\bparkrun\b.{0,48}\b(?:saturdays?|sat)\b", " ", folded)
    text = re.sub(r"\b(?:saturdays?|sat)\b.{0,48}\bparkrun\b", " ", text)
    found = []
    for word, index in _DAY_INDEX:
        if re.search(rf"\b{word}\b", text) and index not in found:
            found.append(index)
    return found


def _without_parkrun_minutes(folded):
    """Drop a parkrun duration. Leave a session length that only sits near parkrun."""
    masked = re.sub(
        r"\bparkrun\b(?:\s+(?:is|about|a|the|my|in|takes|for|around))*"
        r"\s+\d+(?:\.\d+)?\s+min(?:ute)?s?\b",
        " ",
        folded,
    )
    if len(re.findall(r"\b\d+(?:\.\d+)?\s+min(?:ute)?s?\b", masked)) > 1:
        masked = re.sub(r"\b\d+(?:\.\d+)?\s+min(?:ute)?s?\s+parkrun\b", " ", masked)
    return masked


def _paired_session_minutes(reply):
    """Session length next to days per week. A parkrun duration is never it.

    'parkrun is about 32 min' and '32 min parkrun' are the parkrun time, in
    either order. '3 days 30 min, parkrun saturdays' keeps 30.
    """
    if not isinstance(reply, str):
        return None
    found = None
    for piece in re.split(r"[,.!?;]", reply):
        folded = _fold(piece)
        if re.search(r"\b[1-7]\s+days?\b", folded) is None:
            continue
        match = re.search(r"\b(\d{2,3})\s+min(?:ute)?s?\b", _without_parkrun_minutes(folded))
        if match is not None:
            found = match.group(1)
    if found is not None:
        return found
    folded = _fold(reply)
    if re.search(r"\b[1-7]\s+days?\b", folded) is None:
        return None
    match = re.search(r"\b(\d{2,3})\s+min(?:ute)?s?\b", _without_parkrun_minutes(folded))
    if match is None:
        return None
    return match.group(1)


def _school_age_hint(folded):
    """A grade, school, or parent word. It is not a typed age."""
    if re.search(r"\bschool\b", folded):
        return True
    if re.search(r"\b(?:freshman|sophomore|teen|teens|teenage|teenager)\b", folded):
        return True
    if re.search(r"\bjunior(?:\s+high)?\b", folded):
        return True
    if re.search(r"\bhs\b", folded):
        return True
    if re.search(r"\bclass\s+of\b", folded):
        return True
    if re.search(r"\b(?:mom|dad)\s+signed\b", folded):
        return True
    if re.search(r"\b(?:mom|dad)\s+said\b", folded):
        return True
    if re.search(r"\bhighschoolers?\b", folded):
        return True
    if re.search(r"\bparents?\b", folded):
        return True
    if re.search(r"\bguardian\b", folded):
        return True
    if re.search(r"\b\d+(?:st|nd|rd|th)\s+grad(?:e|er)s?\b", folded):
        return True
    if re.search(r"\b(?:grade|grader|grades)\b", folded):
        return True
    return False


def _as_kg(value, unit):
    number = float(value)
    if unit and (unit.startswith("lb") or unit.startswith("pound")):
        number *= 0.45359237
    return number


def _kg_text(number):
    shown = round(float(number) + 1e-9, 1)
    if abs(shown - round(shown)) < 1e-9:
        return str(int(round(shown)))
    return f"{shown:.1f}"


def _without_target_clause(text):
    """'want 64 kg' is a target. It is not the current weight."""
    return re.sub(
        r"\b(?:want|target)\s+\d+(?:\.\d+)?(?:\s*(?:kg|lb|lbs|pounds?))?\b",
        " ",
        text,
    )


_LIFT_LOAD = re.compile(
    r"\b(?:bench(?:\s+press)?|squats?|deadlifts?|press|rows?|curls?|lunges?|"
    r"cleans?|snatch(?:es)?|overhead|incline|pull-?ups?|ohp|rdls?|thrusts?|raises?)"
    r"\s+\d+(?:\.\d+)?\s*(?:kg|lb|lbs|pounds?)\b"
)


def _strip_lift_loads(text):
    """A kilogram after a lift word is the bar, not a body weight."""
    return _LIFT_LOAD.sub(" ", text)


def _current_weight(text):
    """A current body weight in kg or lb. 'ask' means the number is out of range."""
    cleaned = _without_target_clause(text)
    cleaned = _strip_lift_loads(cleaned)
    cleaned = re.sub(
        r"\b\d+(?:\.\d+)?\s+to\s+\d+(?:\.\d+)?\s*(?:kg|lb|lbs|pounds?)\b",
        " ",
        cleaned,
    )
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*(pounds?|lbs|lb|kg)\b", cleaned)
    if match is None:
        return None
    raw = float(match.group(1))
    unit = match.group(2)
    # 660 lb converts to 299.4 kg. This intake still asks, as that figure is out of range.
    if unit != "kg" and raw >= 660:
        return "ask"
    value = _as_kg(raw, unit)
    if not _kg_in_range(value):
        return "ask"
    return _kg_text(value) + " kg"


def _lb_display(text):
    """The user's pound figure, when it is a body weight we can store."""
    if not isinstance(text, str):
        return None
    cleaned = _without_target_clause(text)
    cleaned = _strip_lift_loads(cleaned)
    cleaned = re.sub(
        r"\b\d+(?:\.\d+)?\s+to\s+\d+(?:\.\d+)?\s*(?:kg|lb|lbs|pounds?)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*(pounds?|lbs|lb)\b", cleaned, flags=re.IGNORECASE)
    if match is None:
        return None
    raw = float(match.group(1))
    if raw >= 660:
        return None
    if not _kg_in_range(_as_kg(raw, "lb")):
        return None
    return _kg_text(raw) + " lb"


def _ft_in_display(text):
    """Feet and inches, plus the centimeter value the plan stores."""
    if not isinstance(text, str):
        return None
    raw = text.lower().replace("\u2019", "'").replace("\u2032", "'").replace("\u2033", '"')
    match = re.search(
        r"\b(\d)\s*(?:ft|feet|foot|')\s*(\d{1,2})\s*(?:in(?:ches|ch)?|\"|\u201d)?",
        raw,
    )
    if match is None:
        return None
    feet = int(match.group(1))
    inches = int(match.group(2))
    if feet < 3 or feet > 8 or inches > 11:
        return None
    cm = feet * 30.48 + inches * 2.54
    if cm < 50 or cm > 280:
        return None
    return f"{feet} ft {inches} in", f"{int(round(cm))} cm"


def _remember_unit_echo(state, reply):
    """Remember lb or ft. The shown figure is converted from the stored kg or cm."""
    answers = state.get("answers")
    if not isinstance(answers, dict) or not isinstance(reply, str):
        return
    answers.pop("weight_display", None)
    answers.pop("height_display", None)
    if _lb_display(reply):
        answers["weight_units"] = "lb"
    elif re.search(r"\b\d+(?:\.\d+)?\s*kg\b", _without_target_clause(_fold(reply))):
        answers["weight_units"] = "kg"
    if re.search(r"\b\d{2,3}\s*cm\b", _fold(reply)):
        answers["height_units"] = "cm"
        return
    found = _ft_in_display(reply)
    if found is None:
        return
    _display, canonical = found
    answers["height_units"] = "ft"
    if state.get("skip_body_from_text"):
        return
    if answers.get("height") in (None, ""):
        answers["height"] = canonical


def _weight_kg_in(text):
    cleaned = _strip_lift_loads(text)
    cleaned = re.sub(
        r"\b\d+(?:\.\d+)?\s+to\s+\d+(?:\.\d+)?\s*(?:kg|lb|lbs|pounds?)\b",
        " ",
        cleaned,
    )
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*(kg|lb|lbs|pounds?)\b", cleaned)
    if match is None:
        return None
    return _as_kg(match.group(1), match.group(2))


def _target_from_want(folded):
    """'want N kg' is a target. A bare 'want N' still needs a current weight.

    Pounds are converted to kg. N has to land from 30 to 300 kg. When a
    current weight comes before 'want' or 'target', N also has to sit within
    60 to 140 percent of it. Days, minutes, sets, reps, sessions, or times
    after N are not a target. None means no target was named. 'ask' means
    ask for the target instead of guessing. ('need_weight', 'N kg') means
    the target is stored and the current weight is still missing.
    """
    match = re.search(
        r"\b(?:want|target)\s+(\d+(?:\.\d+)?)(?:\s*(kg|lb|lbs|pounds?))?\b",
        folded,
    )
    if match is None:
        return None
    after = folded[match.end():].strip()
    if re.match(r"(?:days?|mins?|minutes?|sets?|reps?|sessions?|times?)\b", after):
        return "ask"
    unit = match.group(2)
    value = _as_kg(match.group(1), unit)
    if not _kg_in_range(value):
        return "ask"
    shown = _kg_text(value) + " kg"
    current = _weight_kg_in(folded[:match.start()])
    if current is None or current <= 0 or not _kg_in_range(current):
        if unit:
            return ("need_weight", shown)
        return "ask"
    if value < current * 0.6 - 1e-6 or value > current * 1.4 + 1e-6:
        return ("far", _kg_text(current) + " kg")
    return shown


_SAFE_ALL_NO_WORDS = {
    "parkrun", "run", "running", "saturday", "saturdays", "sat",
    "min", "mins", "minute", "minutes", "well", "thanks", "lol", "honestly",
    "ok", "okay",
}


def _safe_all_no(text):
    """An all-no phrase with no symptom or condition word left beside it.

    'all no', 'no to all', 'none', and 'all clear' count, including when the
    same message also gives a profile fact such as no injuries or a parkrun time.
    A symptom, a condition, a hedge, a leftover word, a dotted tail, or a
    negation of the phrase does not. 'all no i', 'all no and', and 'all no ...'
    are not all-no.
    """
    if not isinstance(text, str) or _asks_instead(text) or _ellipsis_tail(text) or _long_punct_tail(text):
        return False
    for char in text:
        if char.isspace() or char.isalnum() or char in "👍":
            continue
        if "\U0001F3FB" <= char <= "\U0001F3FF":
            continue
        if ord(char) < 128 and unicodedata.category(char).startswith("P"):
            continue
        return False
    folded = _fold(text)
    if re.search(r"\b(?:not|isnt|far\s+from|not\s+quite)\b", folded) and re.search(
        r"\b(?:all\s+no|no\s+to\s+all|all\s+clear|none)\b", folded
    ):
        return False
    has = re.search(
        r"\ball\s+no\b|\bno\s+to\s+all\b|\ball\s+clear\b|\bnone\b|\bnope\s+all\s+no\b",
        folded,
    )
    if has is None:
        return False
    rest = folded
    rest = re.sub(r"\bnope\s+all\s+no\b", " ", rest)
    rest = re.sub(r"\bno\s+to\s+all\b", " ", rest)
    rest = re.sub(r"\ball\s+no\b", " ", rest)
    rest = re.sub(r"\ball\s+clear\b", " ", rest)
    rest = re.sub(r"\bnone\b", " ", rest)
    rest = re.sub(r"\bno\s+injur(?:y|ies)\b", " ", rest)
    rest = re.sub(r"\binjur(?:y|ies)\s+none\b", " ", rest)
    rest = re.sub(
        r"\bparkrun\b(?:\s+(?:is|about|on|every|this|saturdays|saturday|sat|"
        r"minutes|minute|mins|min|\d+(?:\.\d+)?))*",
        " ",
        rest,
    )
    leftover = [
        token for token in rest.split()
        if token not in _SAFE_ALL_NO_WORDS and token not in _ALL_NO_FILLERS
    ]
    return not leftover


def _blank():
    return {
        "answers": {},
        "par_q": {},
        "asked": None,
        "phase": "intake",
        "confirmed": False,
        "record": None,
        "routines_on": [],
    }


def _group(group_id):
    for group in GROUPS:
        if group["id"] == group_id:
            return group
    return None


def _missing_keys(state, group):
    if group["id"] == "par_q":
        if all(isinstance(state["par_q"].get(key), bool) for key, _question in PAR_Q):
            return []
        return ["par_q"]
    missing = []
    for key in group["asks"]:
        if key in _OPTIONAL:
            continue
        if state.get("from_profile_payload") and key == "sport":
            continue
        if key not in state["answers"]:
            missing.append(key)
    return missing


def _first_missing(state):
    for group in GROUPS:
        if _missing_keys(state, group):
            return group
    return None


def _fill_group(state, group_id):
    group = _group(group_id)
    if group is None or group_id == "par_q":
        return
    defaults = _GOAL_DEFAULTS if group_id == "goal" else _TRAINING_DEFAULTS
    for key, value in defaults.items():
        if key not in state["answers"]:
            state["answers"][key] = value
    if group_id == "training" and "days" not in state["answers"]:
        state["answers"]["days"] = _dates(state["answers"].get("training_days", "3"))
        state["answers"]["days_named"] = False
    state["answers"]["name"] = state["answers"].get("name", "")


def _parse_sources(answers, folded):
    phrases = (
        ("apple health", "apple_health"),
        ("apple watch", "apple_health"),
        ("garmin", "garmin"),
        ("oura", "oura"),
        ("whoop", "whoop"),
        ("fitbit", "fitbit"),
        ("smart scale", "smart_scale"),
        ("food app", "food_app"),
        ("scale", "smart_scale"),
        ("none", "none"),
    )
    found = []
    for phrase, key in phrases:
        if re.search(rf"\b{re.escape(phrase)}\b", folded) and key not in found:
            found.append(key)
    real = [key for key in found if key != "none"]
    if real:
        answers["sources"] = real
    elif "none" in found:
        answers["sources"] = "none"


def _polarity(clause):
    has_yes = re.search(r"\byes\b", clause) is not None
    has_no = re.search(r"\b(?:no|not|never)\b", clause) is not None
    if has_yes and not has_no:
        return True
    if has_no and not has_yes:
        return False
    if has_yes and has_no:
        yes_at = clause.rfind(" yes")
        no_at = max(clause.rfind(" no"), clause.rfind(" not"), clause.rfind(" never"))
        if yes_at > no_at:
            return True
        if no_at > yes_at:
            return False
    return None


_CLEAN_ALL_NO = {"all no", "no to all", "none", "nope all no"}
_ALL_NO_FILLERS = {"honestly", "thanks", "lol"}
_THUMB = re.compile("👍[\U0001F3FB-\U0001F3FF]?")
# Sad or doubtful faces. A smile such as :) or :-) is not one of these.
_SAD_FACE = re.compile(r"[:;]['’]?-?[(/\\|]")


def _all_no_tokens(text):
    """Words left after punctuation, whitespace, and the small filler list."""
    if not isinstance(text, str):
        return None
    raw = text.strip().lower().replace("'", "").replace("’", "")
    raw = _THUMB.sub(" ", raw)
    raw = raw.replace(":)", " ")
    cleaned = []
    for char in raw:
        if char.isspace():
            cleaned.append(" ")
            continue
        if ord(char) < 128 and unicodedata.category(char).startswith("P"):
            cleaned.append(" ")
            continue
        cleaned.append(char)
    return [token for token in "".join(cleaned).split() if token not in _ALL_NO_FILLERS]


def _all_no_attempt(tokens):
    for index, token in enumerate(tokens):
        if token == "all" and index + 1 < len(tokens) and tokens[index + 1] == "no":
            return True
        if tokens[index:index + 3] == ["no", "to", "all"]:
            return True
        if tokens[index:index + 3] == ["nope", "all", "no"]:
            return True
    if "none" in tokens and tokens != ["none"]:
        return True
    return False


def _asks_instead(text):
    """A question mark or a sad or doubtful face is unclear before punctuation is removed."""
    return "?" in text or "？" in text or _SAD_FACE.search(text) is not None


def _ellipsis_tail(text):
    """A dotted tail such as 'all no ...' is not final punctuation."""
    return "..." in text or "…" in text


def _long_punct_tail(text):
    """'all no..' and 'all no . .' are not a single final . ! or ?.

    A smile such as :) stays. Spaces between the marks still count.
    """
    if not isinstance(text, str):
        return False
    run = 0
    seen = False
    for char in reversed(text.rstrip()):
        if char in ".!?":
            run += 1
            seen = True
            continue
        if char.isspace() and seen:
            continue
        break
    return run >= 2


def bare_all_no(text):
    """True only when the whole reply is an all-no phrase.

    Fillers, a thumb emoji, punctuation, and whitespace may sit beside it.
    A question mark, a full-width question mark, a dotted tail, or a sad or
    doubtful face such as ':(' or ':-(' is unclear even when the words
    underneath are an all-no phrase.
    None means this is not an all-no reply. False means the reply tried to
    say all no and also said something else, so nothing is stored as no.
    """
    if not isinstance(text, str):
        return None
    if _ellipsis_tail(text) or _long_punct_tail(text):
        folded = _fold(text)
        if re.search(r"\ball\s+no\b|\bno\s+to\s+all\b|\ball\s+clear\b|\bnone\b", folded):
            return False
        return None
    if _asks_instead(text):
        asked = _SAD_FACE.sub(" ", text.replace("?", " ").replace("？", " "))
        asked_tokens = _all_no_tokens(asked)
        if asked_tokens is None:
            return None
        asked_phrase = " ".join(asked_tokens)
        if asked_phrase in _CLEAN_ALL_NO or _all_no_attempt(asked_tokens):
            return False
        return None
    tokens = _all_no_tokens(text)
    if tokens is None:
        return None
    phrase = " ".join(tokens)
    if phrase in _CLEAN_ALL_NO:
        return True
    if _all_no_attempt(tokens):
        return False
    return None


def _without_all_no(text):
    """Drop the all-no phrase so it cannot flip an item that was marked yes."""
    if not isinstance(text, str):
        return ""
    raw = re.sub(r"\bnope\s+all\s+no\b", " ", text, flags=re.IGNORECASE)
    raw = re.sub(r"\bno\s+to\s+all\b", " ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\ball\s+no\b", " ", raw, flags=re.IGNORECASE)
    return raw


def read_par_q(text):
    """('all_no', answers), ('unclear', explicit), or ('items', answers).

    Explicit item answers are parsed first. An all-no phrase never supplies
    the answers for an unclear reply.
    """
    if bare_all_no(text) is True or _safe_all_no(text):
        return "all_no", {key: False for key, _question in PAR_Q}
    kind = bare_all_no(text)
    if kind is False:
        return "unclear", _parse_par_q_items(_without_all_no(text))
    return "items", _parse_par_q_items(text)


def parse_par_q(text):
    """Per-item yes or no. An impure 'all no' stores nothing."""
    _status, found = read_par_q(text)
    return found


def _parse_par_q_items(text):
    """Longest phrase wins. A shorter phrase cannot override an explicit yes."""
    if not isinstance(text, str):
        return {}
    raw = text.strip().lower().replace("'", "")
    folded = _fold(text)
    found = {}
    lengths = {}
    if re.search(r"\ball\s+yes\b", folded) and bare_all_no(text) is None:
        if re.fullmatch(r"all\s+yes[\s.!,;:]*", raw):
            return {key: True for key, _question in PAR_Q}
    phrases = (
        ("chest_pain_at_rest", "chest pain while resting"),
        ("chest_pain_at_rest", "resting chest pain"),
        ("chest_pain_at_rest", "chest pain at rest"),
        ("chest_pain_during_activity", "chest pain during activity"),
        ("chest_pain_during_activity", "chest pain during"),
        ("loss_of_balance_dizziness", "lose balance"),
        ("loss_of_balance_dizziness", "dizziness"),
        ("loss_of_balance_dizziness", "dizzy"),
        ("loss_of_balance_dizziness", "balance"),
        ("loss_of_consciousness", "lost consciousness"),
        ("loss_of_consciousness", "loss of consciousness"),
        ("loss_of_consciousness", "consciousness"),
        ("bone_joint_problem_worsened_by_activity", "bone or joint"),
        ("bone_joint_problem_worsened_by_activity", "joint problem"),
        ("bone_joint_problem_worsened_by_activity", "bone joint"),
        ("currently_taking_medications", "medications"),
        ("currently_taking_medications", "medication"),
        ("currently_taking_medications", "medicine"),
        ("doctor_advised_supervised_only", "supervision"),
        ("doctor_advised_supervised_only", "supervised"),
        ("chest_pain_at_rest", "rest"),
    )
    ordered = sorted(phrases, key=lambda item: len(item[1]), reverse=True)

    def apply(key, polarity, length):
        previous = lengths.get(key)
        if previous is None:
            found[key] = polarity
            lengths[key] = length
            return
        if length > previous:
            found[key] = polarity
            lengths[key] = length
            return
        if length < previous:
            return
        if found.get(key) is True and polarity is not True:
            return
        if polarity is True:
            found[key] = True

    clauses = re.split(r"\s*(?:,|\band\b|\bbut\b)\s*", raw)
    for piece in clauses:
        clause = _fold(piece)
        polarity = _polarity(clause)
        if polarity is None:
            continue
        matched_span = False
        for key, phrase in ordered:
            if phrase not in clause:
                continue
            apply(key, polarity, len(phrase))
            matched_span = True
            if phrase != "rest":
                break
        if matched_span:
            continue
        if "chest pain" in clause and not any(
            phrase in clause
            for phrase in ("chest pain at rest", "chest pain while resting", "chest pain during")
        ):
            if "chest_pain_during_activity" not in found:
                apply("chest_pain_during_activity", polarity, len("chest pain"))
            # Shorter than "rest", so a later rest clause can split a generic
            # chest-pain answer. "chest pain at rest" is longer than "rest".
            if "chest_pain_at_rest" not in found:
                apply("chest_pain_at_rest", polarity, len("rest") - 1)
    return found


def _store_par_q(state, parsed, unclear):
    """Keep an item that is already yes. All no cannot flip it."""
    state["par_q_unclear"] = unclear
    for key, value in parsed.items():
        if state["par_q"].get(key) is True and value is not True:
            continue
        state["par_q"][key] = value


def _parse_profile_fields(state, reply):
    """Weight, height, days, and the other profile facts. Not PAR-Q and not injury.

    Those two are a button, a label, or submit_par_q. This function does not read them.
    """
    answers = state["answers"]
    folded = _fold(reply)
    skip_body = state.get("skip_body_from_text") is True
    if re.search(r"\b(?:lose\s+fat|lose\s+weight|fat\s+loss|cut)\b", folded):
        answers["goal"] = "cut"
    else:
        for goal in ("cut", "lose", "gain", "hold"):
            if re.search(rf"\b{goal}\b", folded):
                answers["goal"] = goal
                break
    height = re.search(r"\b(\d{2,3})\s*cm\b", folded)
    if height and not skip_body:
        answers["height"] = height.group(1) + " cm"
    soft = _soft(reply)
    target = _target_from_want(soft)
    need_weight = False
    if isinstance(target, tuple) and target[0] == "need_weight":
        answers["target"] = target[1]
        need_weight = True
    elif isinstance(target, tuple) and target[0] == "far":
        answers.pop("target", None)
        _note_far_target(state, target[1])
    elif target == "ask" and state.get("phase") != "age":
        state["awaiting"] = "target"
        if state.get("error") in (None, ""):
            state["error"] = _TARGET_ASK
    elif target is not None:
        answers["target"] = target
        if state.get("awaiting") == "target":
            state["awaiting"] = None
    weight = None if skip_body else _current_weight(soft)
    if weight == "ask":
        state["error"] = _WEIGHT_ASK
        if target is not None:
            answers.pop("target", None)
            if state.get("awaiting") == "target":
                state["awaiting"] = None
    elif weight is not None and "weight" not in answers:
        stored_target = answers.get("target")
        # A target already checked against this current weight is kept.
        # The current weight is not thrown out because it sits outside the
        # target's own 60 to 140 percent band.
        if _weight_fits_target(stored_target, weight) or _target_near_weight(stored_target, weight):
            answers["weight"] = weight
            need_weight = False
            if state.get("awaiting") == "weight":
                state["awaiting"] = None
                if state.get("error") == _CURRENT_WEIGHT_ASK:
                    state["error"] = None
        else:
            state["awaiting"] = "weight"
            state["error"] = _WEIGHT_ASK
            need_weight = False
    if need_weight and "weight" not in answers and state.get("phase") != "age":
        state["awaiting"] = "weight"
        state["error"] = _CURRENT_WEIGHT_ASK
    if re.search(r"\b(female|woman)\b", folded):
        answers["sex"] = "female"
    elif re.search(r"\b(male|man)\b", folded):
        answers["sex"] = "male"
    named_days = _training_weekdays(folded)
    days = re.search(r"\b([1-7])\s+days?\b", folded)
    if days:
        answers["training_days"] = days.group(1)
        answers["days"] = _dates(days.group(1), named_days or None)
        answers["days_named"] = bool(named_days)
    elif named_days:
        answers["training_days"] = str(len(named_days))
        answers["days"] = _dates(len(named_days), named_days)
        answers["days_named"] = True
    _remember_unit_echo(state, reply)
    minutes = _paired_session_minutes(reply)
    if minutes:
        answers["minutes"] = minutes
    for equipment in ("full gym", "bodyweight", "dumbbells", "barbell", "none"):
        if equipment in folded:
            answers["equipment"] = equipment
            break
    for experience in ("beginner", "intermediate", "advanced"):
        if re.search(rf"\b{experience}\b", folded):
            answers["experience"] = experience
            break
    if re.search(r"\bparkrun\b", folded):
        answers["sport"] = "parkrun"
        if re.search(r"\b(?:saturdays?|sat)\b", folded):
            answers["sport_day"] = "Saturday"
    elif "general training" in folded:
        answers["sport"] = "general training"
    elif re.search(r"\brunning\b", folded):
        answers["sport"] = "running"
    elif re.search(r"\blifting\b", folded):
        answers["sport"] = "lifting"
    _parse_sources(answers, folded)
    named = re.search(r"\bcall me\s+([a-z]+)\b", folded)
    if named:
        answers["name"] = named.group(1)


def _remember_skip(state):
    """A skip is not a guess. Goal falls back to hold. Age, sex, and weight stay blank."""
    asked = state.get("asked")
    if asked == "goal":
        state["answers"]["goal"] = "hold"
        for key in ("age", "sex", "weight", "height", "target"):
            state["answers"].setdefault(key, None)
    elif asked == "training":
        for key in ("sport", "training_days", "minutes", "equipment", "experience", "injuries"):
            state["answers"].setdefault(key, None)
        state["answers"].setdefault("sources", "none")
    elif asked == "par_q":
        state["par_q_skipped"] = True
        for key, _question in PAR_Q:
            state["par_q"].pop(key, None)


_CLOCK = re.compile(
    r"\b\d{1,2}:\d{2}(?:\s*(?:am|pm))?\b"
    r"|\bat\s+(?:[1-9]|1[0-2])(?:\s*(?:am|pm))?\b"
    r"|\b(?:[1-9]|1[0-2])\s*(?:am|pm)\b",
    re.IGNORECASE,
)


def _mask_clocks(reply):
    """Drop a parsed routine time so its digits are not an age hint."""
    if not isinstance(reply, str):
        return ""
    return _CLOCK.sub(lambda match: re.sub(r"\d", " ", match.group(0)), reply)


_AGE_ASK = "How old are you? Please type the number."
_WEIGHT_ASK = "That weight looks off. What's your weight in kg?"
_CURRENT_WEIGHT_ASK = "What's your current weight in kg?"
_TARGET_ASK = "What's your target weight in kg?"


def _far_target_line(current_text):
    """The one warning when a goal weight is far from the current weight."""
    return f"That target looks far from {current_text}. What goal weight do you want?"


def _note_far_target(state, current_text):
    """Say the far-target line once. The next out-of-range answer asks the goal."""
    if state.get("target_far_once"):
        _drop_target_ask_for_goal(state)
        return
    state["target_far_once"] = True
    state["awaiting"] = "target"
    state["error"] = _far_target_line(current_text)


def _drop_target_ask_for_goal(state):
    """Keep the current weight. Stop asking for a target and ask the goal."""
    state["answers"].pop("target", None)
    state["awaiting"] = None
    state.pop("target_far_once", None)
    state["phase"] = "intake"
    state["asked"] = "goal"
    goal = _group("goal")
    state["error"] = goal["text"] if goal else _TARGET_ASK


_INJURY_TAP_LINE = "Injuries: tap None, Old & healed, or Recent or still painful."
_TRACKER_LINE = "Trackers are optional: a watch, a scale, a food app, or none."
_INJURY_WHEN = (
    "Is that an old injury that's healed, or something recent "
    "(last few weeks) or still painful?"
)
_LABEL_FOLLOWUP = (
    "One check on that message. "
    "Tap Old & healed or Recent or still painful, "
    "or say if this is a minor or a red flag. "
    "A second unclear answer pauses today."
)
_REST_LINE = "Rest today. Come back tomorrow, or after you see a doctor."
_HOLD_CLOSED = (
    "Onboarding is held. The hold file is not usable. "
    "Rest today. Come back tomorrow, or after you see a doctor."
)
_HOLD_WRITE_FAILED = (
    "Stop. The onboarding hold could not be saved. Onboarding does not continue."
)
_AGE_EMOJI = "\U0001F9D2\U0001F476\U0001F466\U0001F467"
_NUMBER_WORDS = frozenset({
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty",
    "sixty", "seventy", "eighty", "ninety", "hundred",
    "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth",
    "ninth", "tenth", "eleventh", "twelfth", "thirteenth", "fourteenth",
    "fifteenth", "sixteenth", "seventeenth", "eighteenth", "nineteenth", "twentieth",
})
_AGE_WORDS = frozenset({
    "under", "over", "minor", "grade", "school", "yo", "years", "old", "teen",
    "teens", "teenage", "teenager", "kid", "child", "young", "son", "daughter",
})
_WEIGHT_EDIT = re.compile(
    r"^(?:(?:wait|actually|please|sorry|just)\s+)*"
    r"(?:my\s+)?(?:weight(?:\s+is)?\s+)?(\d+(?:\.\d+)?)\s+kg$"
)
_DAYS_EDIT = re.compile(
    r"^(?:(?:wait|actually|please|sorry|just)\s+)*"
    r"(?:make\s+it\s+|change\s+(?:it\s+)?to\s+)?"
    r"([1-7])\s+days?$"
)
_HEIGHT_EDIT = re.compile(
    r"^(?:(?:wait|actually|please|sorry|just)\s+)*"
    r"(?:my\s+)?height(?:\s+is)?\s+(\d{2,3})\s+cm$"
)


def _soft(reply):
    """Fold a reply but keep a decimal point that sits between digits."""
    if not isinstance(reply, str):
        return ""
    text = reply.strip().lower().replace("'", "").replace("\u2019", "")
    protected = re.sub(r"(?<=\d)\.(?=\d)", "\x00", text)
    cleaned = []
    for char in protected:
        if char == "\x00" or char.isalnum() or char.isspace():
            cleaned.append(char)
        else:
            cleaned.append(" ")
    return " ".join("".join(cleaned).split()).replace("\x00", ".")


def _kg_in_range(value):
    from plan_check import PlanValidator

    return PlanValidator.MIN_BODY_WEIGHT_KG <= float(value) <= PlanValidator.MAX_BODY_WEIGHT_KG


def _weight_fits_target(target, weight):
    """A current weight has to sit within 60 to 140 percent of the stored target."""
    target_kg = _number(target)
    weight_kg = _number(weight)
    if target_kg is None or weight_kg is None:
        return True
    low = float(target_kg) * 0.6 - 1e-6
    high = float(target_kg) * 1.4 + 1e-6
    return low <= float(weight_kg) <= high


def _target_near_weight(target, weight):
    """True when the target sits within 60 to 140 percent of the current weight."""
    target_kg = _number(target)
    weight_kg = _number(weight)
    if target_kg is None or weight_kg is None or float(weight_kg) <= 0:
        return True
    low = float(weight_kg) * 0.6 - 1e-6
    high = float(weight_kg) * 1.4 + 1e-6
    return low <= float(target_kg) <= high


def _non_latin_letter(reply):
    if not isinstance(reply, str):
        return False
    for char in reply:
        if not char.isalpha():
            continue
        try:
            name = unicodedata.name(char)
        except ValueError:
            return True
        if "LATIN" not in name:
            return True
    return False


def _mask_asides(folded):
    """Shoe size and a pet count are not an age."""
    text = re.sub(r"\bsize\s+\d+\s+shoes?\b", " ", folded)
    text = re.sub(r"\b\d+\s+dogs?\b", " ", text)
    return text


def _harmless_aside(reply):
    """A shoe size or a pet count does not block a stored adult age."""
    folded = _fold(reply)
    if re.fullmatch(r"size\s+\d+\s+shoes?", folded):
        return True
    if re.fullmatch(r"\d+\s+dogs?", folded):
        return True
    return False


def _hints_age(reply):
    """True when the reply hints at age. The number itself is not read."""
    if not isinstance(reply, str) or not reply.strip():
        return False
    if any(char in reply for char in _AGE_EMOJI):
        return True
    if _non_latin_letter(reply):
        return True
    folded = _mask_asides(_fold(_mask_clocks(reply)))
    if re.search(r"\d", folded):
        return True
    for token in folded.split():
        if token in _AGE_WORDS or token in _NUMBER_WORDS or token.startswith("teen"):
            return True
    return False


def _explicit_edit(reply):
    """A profile edit that uses the whole reply, or None."""
    weight = _WEIGHT_EDIT.fullmatch(_soft(reply))
    if weight:
        return ("weight", weight.group(1) + " kg")
    folded = _fold(reply)
    days = _DAYS_EDIT.fullmatch(folded)
    if days:
        return ("days", days.group(1))
    height = _HEIGHT_EDIT.fullmatch(folded)
    if height:
        return ("height", height.group(1) + " cm")
    return None


def _apply_edit(state, edit):
    kind, value = edit
    state["confirmed"] = False
    state["record"] = None
    state["awaiting"] = None
    if kind == "weight":
        number = float(value.split()[0])
        if not _kg_in_range(number):
            state["awaiting"] = "weight"
            state["error"] = _WEIGHT_ASK
            return True
        state["answers"]["weight"] = value
    elif kind == "days":
        state["answers"]["training_days"] = value
        state["answers"]["days"] = _dates(value)
        state["answers"]["days_named"] = False
    elif kind == "height":
        state["answers"]["height"] = value
    state["error"] = None
    return True


def _typed_int(reply):
    folded = _fold(reply)
    if not re.fullmatch(r"\d{1,3}", folded):
        return None
    return int(folded)


def _clear_proposal(state):
    """Drop the confirmable proposal. The intake draft stays on disk."""
    state["confirmed"] = False
    state["record"] = None


def _reply_age(reply):
    """Only a reply to the age question. A number, optionally yo or years old."""
    folded = _fold(reply)
    for pattern in (
        r"(\d{1,3})\s+years\s+old",
        r"(\d{1,3})\s+years",
        r"(\d{1,3})\s*yo",
        r"(\d{1,3})",
    ):
        match = re.fullmatch(pattern, folded)
        if match is None:
            continue
        value = int(match.group(1))
        if 1 <= value <= 120:
            return value
    return None


def _nonblocking_stat(folded):
    """Height or a short duration. It is not an age, and it does not clear one."""
    if re.fullmatch(r"(?:im|i am)\s+\d+\s+foots?", folded):
        return True
    if re.fullmatch(r"(?:im|i am)\s+\d+\s+weeks?", folded):
        return True
    return False


_MINOR_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
}


_MINOR_UNITS = frozenset({
    "days", "day", "x", "reps", "rep", "sets", "set", "min", "mins", "minutes",
    "hr", "hours", "kg", "kgs", "lb", "lbs", "km", "mi", "miles", "times",
    "sessions", "%",
})
def _minor_tokens(reply):
    """Words for a minor-age scan. A clock such as 6:15 is not one of them.

    '17yo', '15yrs', '15y', and 'age15' split into an age and a suffix.
    """
    if not isinstance(reply, str):
        return []
    text = reply.strip().lower().replace("'", "").replace("\u2019", "")
    text = re.sub(r"\b(\d{1,2})(yo|yrs|yr|y)\b", r"\1 \2", text)
    text = re.sub(r"\bage(\d{1,3})\b", r"age \1", text)
    text = _CLOCK.sub(" ", text)
    text = re.sub(r"\b\d{1,2}:\d{2}\s*(?:am|pm)?\b", " ", text)
    text = text.replace("%", " % ")
    cleaned = []
    for char in text:
        if char.isalnum() or char.isspace() or char == "%":
            cleaned.append(char)
        else:
            cleaned.append(" ")
    return "".join(cleaned).split()


def _minor_value(token):
    if re.fullmatch(r"\d{1,2}", token):
        number = int(token)
        if 1 <= number <= 17:
            return number
        return None
    return _MINOR_WORDS.get(token)


def _am_pm_is_time(tokens, index):
    """am/pm is a unit only for a 1-12 hour in a time, such as 'at 6 am'.

    '16 am' is not a clock. A colon time is already removed before this.
    """
    if index < 0 or index >= len(tokens) or tokens[index] not in {"am", "pm"}:
        return False
    if index == 0 or not re.fullmatch(r"\d{1,2}", tokens[index - 1]):
        return False
    hour = int(tokens[index - 1])
    return 1 <= hour <= 12


def _next_is_unit(tokens, index):
    """A count, a clock, or a duration. '2 years ago' is a duration, not an age.

    '15 years old' is still an age: years counts only when the next word is ago.
    Months and weeks are durations on their own.
    """
    nxt = tokens[index + 1] if index + 1 < len(tokens) else ""
    nxt2 = tokens[index + 2] if index + 2 < len(tokens) else ""
    if nxt in _MINOR_UNITS:
        return True
    if nxt in {"months", "month", "weeks", "week"}:
        return True
    if nxt in {"years", "year"} and nxt2 == "ago":
        return True
    if nxt in {"am", "pm"}:
        return _am_pm_is_time(tokens, index + 1)
    return False


def _minor_cue(reply):
    """A later reply that says the person is under 18. It does not store the number.

    A number from 1 to 17, or a word from one to seventeen, clears the age
    unless the next word is a unit or the number is inside a clock time.
    '17yo', '15yrs', '15y', and 'age15' count. '16 am i allowed' counts.
    'at 6 am' does not.
    """
    folded = _fold(reply) if isinstance(reply, str) else ""
    if re.search(r"\bminor\b", folded):
        return True
    if re.search(r"\bunder\s+18\b", folded) or re.search(r"\bunder\s+eighteen\b", folded):
        return True
    if re.search(r"\bnot\s+18\s+yet\b", folded):
        return True
    if re.search(r"\bnot\s+an?\s+adult\b", folded):
        return True
    if re.search(r"\b(?:im|i am)\s+only\s+\d{1,3}\b", folded):
        return True
    if re.search(r"\bage\d{1,3}\b", folded):
        return True
    tokens = _minor_tokens(reply)
    for index, token in enumerate(tokens):
        if _minor_value(token) is None:
            continue
        if _next_is_unit(tokens, index):
            continue
        return True
    return False


def _counted_training(reply):
    """A days, reps, or minutes count. It does not ask for an age again."""
    tokens = _minor_tokens(reply)
    saw_unit = False
    for index, token in enumerate(tokens):
        if not re.fullmatch(r"\d+(?:\.\d+)?", token):
            continue
        if _next_is_unit(tokens, index):
            saw_unit = True
            continue
        if _minor_value(token) is not None:
            return False
    if _school_age_hint(_fold(reply) if isinstance(reply, str) else ""):
        return False
    return saw_unit


def _age_correction(reply):
    """A mention of age. It asks again. It does not store the number."""
    folded = _fold(reply) if isinstance(reply, str) else ""
    if not folded or _nonblocking_stat(folded):
        return False
    if _school_age_hint(folded) or _minor_cue(reply):
        return True
    if re.search(r"\bage\s*\d{1,3}\b", folded):
        return True
    if re.search(r"\b(?:im|i am)\s+actually\s+\d{1,3}\b", folded):
        return True
    if re.search(
        r"\bactually\s+\d{1,3}\b(?!\s*(?:kg|lb|lbs|pounds?|cm|foots?|weeks?)\b)",
        folded,
    ):
        return True
    if re.search(r"\b(?:im|i am)\s+\d{1,3}\b", folded):
        return True
    return False


def _clear_age(state):
    state["answers"].pop("age", None)
    state["need_age"] = True
    _clear_proposal(state)


def _safety_directory():
    return os.path.dirname(os.path.abspath(onboarding_state_path()))


def _read_safety():
    from safety_pending import read_pending

    return read_pending(_safety_directory(), _local_today(), "onboarding")


def _write_safety(kind, **extra):
    from safety_pending import write_pending

    return write_pending(_safety_directory(), kind, _local_today(), "onboarding", **extra)


def _clear_safety():
    from safety_pending import clear_pending

    return clear_pending(_safety_directory(), "onboarding")


def _follow_up_cause(labels):
    """injury_unclear is the only follow-up an Old/Recent tap can clear."""
    parsed, reason = validate_labels(labels) if labels is not None else (None, "missing")
    if reason is None and parsed.get("injury") == "unclear":
        return "injury_unclear"
    return "labels"


def _follow_up_open(state=None):
    """True when a follow-up is still waiting on a structured answer."""
    if isinstance(state, dict) and state.get("safety_followup"):
        return True
    pending = _read_safety()
    return isinstance(pending, dict) and pending.get("kind") == "follow_up"


def _adopt_pending(state):
    """A record already on disk applies to a new conversation the same day."""
    pending = _read_safety()
    if not isinstance(pending, dict):
        return state
    kind = pending.get("kind")
    if kind == "follow_up":
        state["safety_followup"] = True
        state["label_unclear"] = 1
    elif kind == "age_check":
        state["phase"] = "age"
        state["need_age"] = True
        state["answers"].pop("age", None)
        state["error"] = _AGE_ASK
    elif kind == "hold" and state.get("phase") != "symptom":
        state["phase"] = "symptom"
        state["confirmed"] = False
        message = pending.get("message")
        state["error"] = message if isinstance(message, str) and message.strip() else _REST_LINE
    return state


def submit_age(state, age):
    """Store a typed age. 13 to 100 only. Under 18 means no plan.

    The argument is an int. A sentence is not an age.
    """
    _clear_proposal(state)
    if isinstance(age, bool) or not isinstance(age, int) or age < 13 or age > 100:
        state["phase"] = "age"
        state["awaiting"] = None
        state["need_age"] = True
        state["error"] = _AGE_ASK
        if (_read_safety() or {}).get("kind") == "age_check":
            _write_safety("age_check")
        return True
    number = age
    state["answers"]["age"] = str(number)
    state["awaiting"] = None
    state["need_age"] = False
    _apply_age_readiness(state)
    if (_read_safety() or {}).get("kind") == "age_check":
        _clear_safety()
    if state.get("error"):
        if number < 18 or _first_missing(state) is None:
            state["phase"] = "blocked"
            _resume_pending_injury(state)
            return True
        state["error"] = None
        state["readiness"] = None
        state["phase"] = "intake"
        _resume_pending_injury(state)
        return True
    state["hold_message"] = None
    state["phase"] = "confirm"
    _resume_pending_injury(state)
    return True


def _take_age_number(state, reply):
    """The age step. Only a bare integer reaches submit_age."""
    folded = _fold(reply) if isinstance(reply, str) else ""
    if re.fullmatch(r"\d{1,3}", folded):
        return submit_age(state, int(folded))
    return submit_age(state, None)


def _reply_target_kg(reply):
    """A bare kg number, or the number after want or target. None when absent."""
    soft = _soft(reply)
    bare = re.fullmatch(r"(\d+(?:\.\d+)?)(?:\s*kg)?", soft)
    if bare:
        return float(bare.group(1))
    found = re.search(
        r"\b(?:want|target)\s+(\d+(?:\.\d+)?)(?:\s*(kg|lb|lbs|pounds?))?",
        soft,
    )
    if found is None:
        return None
    return _as_kg(found.group(1), found.group(2))


def _take_target_number(state, reply):
    """The reply after a target ask. A days or minutes phrase is not a weight.

    A target far from the current weight is warned about once. The next
    out-of-range answer keeps the current weight and asks for the goal.
    """
    value = _reply_target_kg(reply)
    current = _number(state["answers"].get("weight"))
    out_of_range = False
    if value is None:
        out_of_range = bool(state.get("target_far_once"))
    elif not _kg_in_range(value):
        out_of_range = True
    elif current is not None and (
        value < float(current) * 0.6 - 1e-6 or value > float(current) * 1.4 + 1e-6
    ):
        out_of_range = True
    if value is None and not out_of_range:
        state["awaiting"] = "target"
        state["error"] = _TARGET_ASK
        return
    if out_of_range:
        if state.get("target_far_once"):
            _drop_target_ask_for_goal(state)
            return
        shown = _kg_text(current) + " kg" if current is not None else ""
        if shown:
            _note_far_target(state, shown)
        else:
            state["awaiting"] = "target"
            state["error"] = _TARGET_ASK
        return
    state["answers"]["target"] = _kg_text(value) + " kg"
    state["awaiting"] = None
    state["error"] = None
    state.pop("target_far_once", None)


def _take_weight_number(state, reply):
    state["confirmed"] = False
    state["record"] = None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(?:\s+kg)?", _soft(reply))
    if match is None:
        state["awaiting"] = "weight"
        state["error"] = _WEIGHT_ASK
        return True
    number = float(match.group(1))
    if not _kg_in_range(number):
        state["awaiting"] = "weight"
        state["error"] = _WEIGHT_ASK
        return True
    shown = match.group(1)
    if shown.endswith(".0"):
        shown = shown[:-2]
    if not _weight_fits_target(state["answers"].get("target"), shown + " kg"):
        state["awaiting"] = "weight"
        state["error"] = _WEIGHT_ASK
        return True
    state["answers"]["weight"] = shown + " kg"
    state["awaiting"] = None
    state["error"] = None
    return True


_INJURY_AREAS = (
    ("old sprained ankle", "ankle"),
    ("sprained ankle", "ankle"),
    ("pulled hamstring", "hamstring"),
    ("shin splints", "ankle"),
    ("shin splint", "ankle"),
    ("slipped disc", "back"),
    ("groin strain", "hip"),
    ("groin", "hip"),
    ("calf tear", "calf"),
    ("achilles", "achilles"),
    ("hip replacement", "hip"),
    ("knee replacement", "knee"),
    ("herniated disc", "back"),
    ("bulging disc", "back"),
    ("plantar fasciitis", "ankle"),
    ("tennis elbow", "elbow"),
    ("golfers elbow", "elbow"),
    ("rotator cuff", "shoulder"),
    ("torn acl", "knee"),
    ("bad knees", "knee"),
    ("sciatica", "back"),
    ("meniscus", "knee"),
    ("lower back", "lower back"),
    ("low back", "lower back"),
    ("hamstrings", "hamstring"),
    ("hamstring", "hamstring"),
    ("shoulders", "shoulder"),
    ("shoulder", "shoulder"),
    ("knees", "knee"),
    ("knee", "knee"),
    ("ankles", "ankle"),
    ("ankle", "ankle"),
    ("wrists", "wrist"),
    ("wrist", "wrist"),
    ("elbows", "elbow"),
    ("elbow", "elbow"),
    ("neck", "neck"),
    ("hips", "hip"),
    ("hip", "hip"),
    ("acl", "knee"),
    ("back", "back"),
)
_LEG_EMOJI = "\U0001F9B5"
_HEAD_EMOJI = "\U0001F915"
_INJURY_ASK = "Which area is injured?"


def _leg_emoji_only(reply):
    """A lone leg emoji names no area. Ask which one. A head emoji is a symptom."""
    if not isinstance(reply, str):
        return False
    stripped = "".join(ch for ch in reply.strip() if not ch.isspace())
    return bool(stripped) and all(ch == _LEG_EMOJI for ch in stripped)


# A named injury skips the hold only with a past marker and no acute wording.
_NAMED_INJURIES = (
    ("old sprained ankle", "ankle"),
    ("torn rotator cuff", "shoulder"),
    ("sprained ankle", "ankle"),
    ("pulled hamstring", "hamstring"),
    ("shin splints", "ankle"),
    ("shin splint", "ankle"),
    ("herniated disc", "back"),
    ("bulging disc", "back"),
    ("slipped disc", "back"),
    ("groin strain", "hip"),
    ("calf tear", "calf"),
    ("torn acl", "knee"),
    ("bad knees", "knee"),
    ("rotator cuff", "shoulder"),
    ("plantar fasciitis", "ankle"),
    ("tennis elbow", "elbow"),
    ("golfers elbow", "elbow"),
    ("hip replacement", "hip"),
    ("knee replacement", "knee"),
    ("meniscus", "knee"),
    ("sciatica", "back"),
)
_PAST_MARKER = re.compile(
    r"\bold\b"
    r"|\byears?\s+ago\b"
    r"|\blast\s+year\b"
    r"|\bin\s+20\d{2}\b"
    r"|\bhealed\b"
    r"|\brecovered\b"
    r"|\bfine\s+now\b"
)
_ACUTE_MARKER = re.compile(
    r"\bpop(?:ped)?\b"
    r"|\bsnap(?:ped)?\b"
    r"|\bswell(?:ing|ed)?\b|\bswollen\b"
    r"|\bballoon(?:ed|ing)\b"
    r"|\bpuffy\b"
    r"|\bblack\s+and\s+blue\b"
    r"|\bbuckl(?:e|ed)\b"
    r"|\bgave\s+out\b|\bgave\s+way\b|\bgiving\s+way\b"
    r"|\blimp(?:ing)?\b"
    r"|\b(?:cant|cannot|can\s+not)\s+(?:walk|bear\s+weight|put\s+(?:any\s+)?weight|bend|straighten)\b"
    r"|\bon\s+crutches\b"
    r"|\bin\s+a\s+cast\b"
    r"|\bcracks?\b"
    r"|\bexcruciating\b"
    r"|\bagony\b"
    r"|\bstill\s+(?:hurts?|painful|hurting)\b"
    r"|\brecent\b"
    r"|\bsharp\s+pain\b"
    r"|\bsharp\b"
    r"|\bsevere\b"
    r"|\bstabbing\b"
    r"|\bfever\b"
    r"|\bnumb(?:ness)?\b"
    r"|\btingling\b"
    r"|\blocked\b"
    r"|\bdeformed\b"
    r"|\bbruised\s+badly\b"
    r"|\btoday\b|\btonight\b|\byesterday\b|\bjust\b|\bearlier\b"
    r"|\bthis\s+morning\b|\bthis\s+week\b"
    r"|\ban\s+hour\s+ago\b|\blast\s+night\b"
    r"|\bhours?\s+ago\b"
    r"|\b\d+\s+days?\s+ago\b"
    r"|\b\d+\s+weeks?\s+ago\b"
    r"|\bweeks?\s+ago\b"
    r"|\bduring\s+(?:my\s+)?(?:run|workout)\b"
)


def _named_injury_hits(folded):
    found = []
    for phrase, label in _NAMED_INJURIES:
        if re.search(rf"\b{re.escape(phrase)}\b", folded) and label not in found:
            found.append(label)
    return found


def _named_injury_present(folded):
    return bool(_named_injury_hits(folded))


def _named_injury_label(folded):
    found = _named_injury_hits(folded)
    return ", ".join(found)


def _strip_named_injury(reply):
    if not isinstance(reply, str):
        return False, ""
    text = reply
    matched = False
    for phrase, _label in _NAMED_INJURIES:
        pattern = re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE)
        if pattern.search(text):
            matched = True
            text = pattern.sub(" ", text)
    return matched, text


# A whole reply stores the injury as old only when it is one of these phrases.
# Optional punctuation is already folded away. A question mark is not.
_OLD_REPLY = re.compile(
    r"(?:old|its old|old one|healed|its healed|fully healed|old and healed|"
    r"years ago|\d+ years ago|\d+ year ago|long time ago|fine now|all good now|"
    r"recovered|fully recovered)"
)
_PAST_SPAN = (
    r"\bold and healed\b",
    r"\bfully healed\b",
    r"\bits healed\b",
    r"\bfully recovered\b",
    r"\ball good now\b",
    r"\bfine now\b",
    r"\blong time ago\b",
    r"\bits old\b",
    r"\bold one\b",
    r"\b\d+\s+years?\s+ago\b",
    r"\byears?\s+ago\b",
    r"\b\d+\s+months?\s+ago\b",
    r"\blast\s+year\b",
    r"\bin\s+20\d{2}\b",
    r"\bhealed\b",
    r"\brecovered\b",
    r"\bold\b",
)
_NEGATION_WORDS = frozenset({
    "not", "no", "never", "isnt", "hasnt", "havent", "didnt", "dont",
    "wasnt", "werent", "without", "nope",
})
_PAIN_OR_QUALIFIER = re.compile(
    r"\b(?:hurts?|hurt(?:ing)?|sore|aches?|aching|stiff|flare|"
    r"bothers?|bothering|reinjur\w*|tweaks?|tweaked|"
    r"pains?|painful|mostly|almost)\b"
    r"|\bacting\s+up\b"
)
_PAIN_PHRASES = (
    (re.compile(r"\blower back pain\b", re.IGNORECASE), "lower back"),
    (re.compile(r"\blow back pain\b", re.IGNORECASE), "lower back"),
    (re.compile(r"\bmy knee hurts\b", re.IGNORECASE), "knee"),
    (re.compile(r"\bknee hurts\b", re.IGNORECASE), "knee"),
    (re.compile(r"\bknee pain\b", re.IGNORECASE), "knee"),
    (re.compile(r"\bshoulder pain\b", re.IGNORECASE), "shoulder"),
    (re.compile(r"\bhip pain\b", re.IGNORECASE), "hip"),
    (re.compile(r"\bankle pain\b", re.IGNORECASE), "ankle"),
    (re.compile(r"\bneck pain\b", re.IGNORECASE), "neck"),
    (re.compile(r"\bwrist pain\b", re.IGNORECASE), "wrist"),
    (re.compile(r"(?<!lower )(?<!low )back pain\b", re.IGNORECASE), "back"),
    (re.compile(r"\bachilles tend(?:i|o)nitis\b", re.IGNORECASE), "achilles"),
)


def _injury_fold(reply):
    """Fold, and treat a curly apostrophe the same as a straight one."""
    if not isinstance(reply, str):
        return ""
    return _fold(reply.replace("\u2019", "'").replace("\u2018", "'"))


def _asks_question(reply):
    return isinstance(reply, str) and ("?" in reply or "？" in reply)


def _past_spans(folded):
    """Allowlisted past phrases, longest first, without overlap.

    'N months ago' counts only when N is at least 3.
    """
    occupied = []
    spans = []
    for pattern in _PAST_SPAN:
        for match in re.finditer(pattern, folded):
            if any(not (match.end() <= start or match.start() >= end) for start, end in occupied):
                continue
            text = match.group(0)
            if "month" in text:
                number = re.match(r"\d+", text)
                if number is None or int(number.group(0)) < 3:
                    continue
            occupied.append((match.start(), match.end()))
            spans.append((match.start(), match.end()))
    return spans


def _negated_before(folded, start):
    """True when a negation sits within the three words before this phrase."""
    words = folded[:start].split()
    return any(word in _NEGATION_WORDS for word in words[-3:])


def _valid_past(reply):
    """An allowlisted past phrase, with no nearby negation and no pain word.

    The phrase has to be one of the old-injury lines. A question mark, a
    negation within three words, or a pain or qualifier word anywhere in
    the message means it is not a past marker.
    """
    if _asks_question(reply):
        return False
    folded = _injury_fold(reply)
    if not folded or _PAIN_OR_QUALIFIER.search(folded):
        return False
    return any(not _negated_before(folded, start) for start, _end in _past_spans(folded))


def _rejected_past(reply):
    """A past phrase with a negation within three words. It does not skip the hold."""
    if _valid_past(reply):
        return False
    folded = _injury_fold(reply)
    spans = _past_spans(folded)
    if not spans:
        return False
    return all(_negated_before(folded, start) for start, _end in spans)


def _has_emoji(reply):
    """An emoji is not part of an old-injury answer. A question mark is not one."""
    if not isinstance(reply, str):
        return False
    return any(unicodedata.category(char) in {"So", "Sk"} for char in reply)


def _old_injury_reply(reply):
    """True only when the whole reply is an allowlisted old-injury answer."""
    if _asks_question(reply) or _has_emoji(reply):
        return False
    folded = _injury_fold(reply)
    if not folded:
        return False
    return _OLD_REPLY.fullmatch(folded) is not None


# Same phrases as the whole-reply allowlist, longest first, so a remainder
# can be those phrases and nothing else.
_OLD_PHRASES = (
    re.compile(r"\bold and healed\b"),
    re.compile(r"\bfully healed\b"),
    re.compile(r"\bits healed\b"),
    re.compile(r"\bfully recovered\b"),
    re.compile(r"\ball good now\b"),
    re.compile(r"\bfine now\b"),
    re.compile(r"\blong time ago\b"),
    re.compile(r"\bits old\b"),
    re.compile(r"\bold one\b"),
    re.compile(r"\b\d+\s+years\s+ago\b"),
    re.compile(r"\b\d+\s+year\s+ago\b"),
    re.compile(r"\byears\s+ago\b"),
    re.compile(r"\brecovered\b"),
    re.compile(r"\bhealed\b"),
    re.compile(r"\bold\b"),
)
_OLD_PLACE = "oldplace"
_PROFILE_NOISE = frozenset({
    "hold", "cut", "lose", "gain", "fat", "loss", "weight",
    "male", "female", "man", "woman",
    "kg", "kgs", "cm", "lb", "lbs", "pounds", "pound",
    "general", "training", "days", "day", "min", "mins", "minutes",
    "dumbbells", "barbell", "bodyweight", "beginner", "intermediate", "advanced",
    "full", "gym", "none", "no", "injuries", "injury",
    "and", "but", "or", "a", "an", "the", "its", "it", "is", "of", "with",
    "my", "i", "im", "to", "for", "on", "in", "at", "from",
    "want", "target",
})


def _strict_old_remainder(reply):
    """Store as old only when the injury name and separators leave an allowlist.

    Past phrases are masked first, then the injury name is removed. Profile
    words, bare numbers, and separators may go too. What remains has to be
    one or more allowlisted phrases and nothing else. A question mark or an
    emoji does not store.
    """
    if _asks_question(reply) or _has_emoji(reply):
        return False
    text = _injury_fold(reply)
    if not text:
        return False
    found = False
    for pattern in _OLD_PHRASES:
        if pattern.search(text):
            found = True
            text = pattern.sub(f" {_OLD_PLACE} ", text)
    if not found:
        return False
    for pattern, _label in _PAIN_PHRASES:
        text = pattern.sub(" ", text)
    for phrase, _label in _NAMED_INJURIES:
        text = re.sub(rf"\b{re.escape(phrase)}\b", " ", text)
    for phrase, _label in _INJURY_AREAS:
        text = re.sub(rf"\b{re.escape(phrase)}\b", " ", text)
    kept = []
    for token in text.split():
        if token == _OLD_PLACE:
            kept.append(token)
            continue
        if token.isdigit():
            continue
        if token in _PROFILE_NOISE:
            continue
        kept.append(token)
    return bool(kept) and all(token == _OLD_PLACE for token in kept)


def _loose_timing(reply):
    """A timing word that is not an exact old answer. Ask. Do not store it."""
    if _strict_old_remainder(reply) or _rejected_past(reply) or _acute_marker(reply):
        return False
    if _asks_question(reply):
        return False
    folded = _injury_fold(reply)
    folded = re.sub(r"\byears?\s+old\b", " ", folded)
    return bool(re.search(r"\b(?:old|healed|recovered|ago)\b", folded))


def _past_marker(reply):
    """Backward-compatible name. Only a strict allowlisted remainder counts."""
    return _strict_old_remainder(reply)


def _pain_phrase_label(folded):
    found = []
    for pattern, label in _PAIN_PHRASES:
        if pattern.search(folded) and label not in found:
            found.append(label)
    return ", ".join(found)


def _pending_injury_label(reply):
    folded = _fold(reply) if isinstance(reply, str) else ""
    labels = []
    for label in (_named_injury_label(folded), _pain_phrase_label(folded)):
        for part in label.split(","):
            part = part.strip()
            if part and part not in labels:
                labels.append(part)
    return ", ".join(labels)


def _injury_rest(reply):
    text = reply if isinstance(reply, str) else ""
    for phrase, _label in _NAMED_INJURIES:
        text = re.sub(rf"\b{re.escape(phrase)}\b", " ", text, flags=re.IGNORECASE)
    for pattern, _label in _PAIN_PHRASES:
        text = pattern.sub(" ", text)
    return text


def _acute_marker(reply):
    folded = _fold(reply) if isinstance(reply, str) else ""
    if _ACUTE_MARKER.search(folded):
        return True
    if re.search(r"\b10\s+10\b", folded):
        return True
    for match in re.finditer(r"\b(\d+)\s+months?\s+ago\b", folded):
        if int(match.group(1)) < 3:
            return True
    return False


def _injury_context(folded):
    """A named injury or a body area. Acute wording holds for any of them."""
    if _named_injury_present(folded):
        return True
    for phrase, _label in _INJURY_AREAS:
        if re.search(rf"\b{re.escape(phrase)}\b", folded):
            return True
    return False


def _untimed_named_injury(reply):
    """A named injury whose remainder is not the old-injury allowlist."""
    folded = _fold(reply) if isinstance(reply, str) else ""
    if not _named_injury_present(folded):
        return False
    if _strict_old_remainder(reply) or _acute_marker(reply) or _rejected_past(reply):
        return False
    return True


def _untimed_pain_phrase(reply):
    """Pain with no exact old remainder. It asks, it does not store."""
    folded = _fold(reply) if isinstance(reply, str) else ""
    if not _pain_phrase_label(folded):
        return False
    if _strict_old_remainder(reply) or _acute_marker(reply) or _rejected_past(reply):
        return False
    return True


def _plain_pause():
    from types import SimpleNamespace

    return SimpleNamespace(
        message="Plan paused. Rest today. Come back tomorrow, or after you see a doctor.",
        recommendations=[],
    )


def _pain_happening_now(folded):
    if re.search(r"\b(?:new|worsen\w+)\b", folded) and re.search(r"\bpain\b", folded):
        return True
    if re.search(r"\bright\s+now\b", folded) and re.search(r"\bpain\b", folded):
        return True
    return False


def _symptom_hold(reply):
    """Scan the whole message first. Hold a current symptom.

    A named injury is stored only when the remainder is the old-injury
    allowlist and the rest of the message does not pause. A negated past
    phrase holds. A pain phrase holds when the whole raw message flags.
    A clean pain phrase does not hold: the caller asks old or recent.
    Acute wording holds for every area.
    """
    from record_confirmation import reply_pause

    paused = reply_pause(reply)
    folded = _fold(reply) if isinstance(reply, str) else ""
    if isinstance(reply, str) and (_HEAD_EMOJI in reply or re.search(r"\bhead\b", folded)):
        return paused if paused is not None else reply_pause(_HEAD_EMOJI)
    if _pain_happening_now(folded):
        if paused is not None:
            return paused
        return _plain_pause()
    if _acute_marker(reply) and _injury_context(folded):
        return paused if paused is not None else _plain_pause()
    if _named_injury_present(folded) and _strict_old_remainder(reply):
        rest_pause = reply_pause(_injury_rest(reply))
        if rest_pause is None:
            return None
        return rest_pause
    if (_named_injury_present(folded) or _pain_phrase_label(folded)) and _rejected_past(reply):
        return paused if paused is not None else _plain_pause()
    if _untimed_pain_phrase(reply):
        if paused is not None:
            return paused
        return None
    if _untimed_named_injury(reply):
        return reply_pause(_injury_rest(reply))
    if paused is None:
        return None
    return paused


def _stated_injury(folded):
    """A named area wins over 'no injuries'. Ok, fine, and yes are not an answer."""
    found = []
    for phrase, label in _INJURY_AREAS:
        if not re.search(rf"\b{re.escape(phrase)}\b", folded):
            continue
        if label == "back" and "lower back" in found:
            continue
        if label not in found:
            found.append(label)
    if found:
        return ", ".join(found)
    for word in ("tweaked", "niggle", "sore", "surgery", "sprain", "tear", "injury", "pain"):
        if re.search(rf"\bno\s+{word}s?\b", folded):
            continue
        if word == "pain" and re.search(r"\bchest\s+pain\b", folded):
            continue
        if re.search(rf"\b{word}s?\b", folded):
            return word
    if re.search(r"\bno\s+injur(?:y|ies)\b", folded) or re.search(r"\binjur(?:y|ies)\s+none\b", folded):
        return "none"
    if folded in {"no", "none", "nope"} or re.search(r"\binjuries\s+none\b", folded):
        return "none"
    return None


def _store_named_injury(state, reply):
    label = _named_injury_label(_fold(reply))
    if not label:
        return False
    state["answers"]["injuries"] = label
    state.pop("pending_injury", None)
    return True


def _keep_pending_injury(state, reply):
    """Remember the injury on this message. Do not leave a stored none in its place."""
    label = _pending_injury_label(reply)
    if label:
        state["pending_injury"] = label
    elif not state.get("pending_injury"):
        state["pending_injury"] = "injury"
    if state.get("answers", {}).get("injuries") == "none":
        state["answers"].pop("injuries", None)


def _resume_pending_injury(state):
    """After a typed age, an old or unclear injury still needs the button."""
    if not state.get("ask_injury_after_age"):
        return
    if state.get("phase") in {"age", "blocked", "symptom"}:
        return
    state["ask_injury_after_age"] = False
    _ask_injury_when(state, "")


def _ask_injury_when(state, reply):
    label = _pending_injury_label(reply)
    if label:
        state["pending_injury"] = label
    state["awaiting"] = "injury_when"
    state["confirmed"] = False
    state["record"] = None
    state["safety_followup"] = True
    state["error"] = _INJURY_WHEN
    if state.get("phase") != "confirm":
        state["phase"] = "intake"


def _injury_when_kind(reply):
    """'store' for an allowlisted reply. An emoji on that reply asks again."""
    if _old_injury_reply(reply):
        return "store"
    if _has_emoji(reply):
        folded = _injury_fold(reply)
        if folded and _OLD_REPLY.fullmatch(folded) is not None:
            return "ask"
    return "hold"


def _take_injury_when(state, reply):
    kind = _injury_when_kind(reply)
    if kind == "store":
        label = state.get("pending_injury")
        if label:
            state["answers"]["injuries"] = label
        state.pop("pending_injury", None)
        state["awaiting"] = None
        state["error"] = None
        if state.get("phase") != "confirm":
            state["phase"] = "intake"
        return
    if kind == "ask":
        state["awaiting"] = "injury_when"
        state["error"] = _INJURY_WHEN
        if state.get("phase") != "confirm":
            state["phase"] = "intake"
        return
    state.pop("pending_injury", None)
    state["awaiting"] = None
    from record_confirmation import reply_pause

    paused = reply_pause(reply)
    _hold_symptom(state, reply, paused if paused is not None else _plain_pause())


def _ask_which_area(state):
    _clear_proposal(state)
    state["phase"] = "intake"
    state["awaiting"] = "injury"
    state["confirmed"] = False
    state["record"] = None
    state["error"] = _INJURY_ASK


def _take_injury_answer(state, reply):
    """An area tap only. A sentence such as 'my knee hurts' is not stored as old."""
    if _leg_emoji_only(reply):
        state["error"] = _INJURY_ASK
        state["awaiting"] = "injury"
        return
    area = _exact_area(reply)
    if not area:
        state["error"] = _INJURY_ASK
        state["awaiting"] = "injury"
        return
    state["answers"]["injuries"] = area
    state["awaiting"] = None
    state["error"] = None


def _injury_area(injuries):
    if not isinstance(injuries, str):
        return ""
    text = injuries.strip()
    if text.lower() in {"", "none", "no", "n/a", "na", "nope"}:
        return ""
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if len(parts) <= 1:
        return parts[0] if parts else text
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + ", and " + parts[-1]


def _injury_clause(injuries, old=False):
    """One plain sentence. An explicit no does not add it.

    An old, healed injury comes back gradually. Anything else stays off
    until a doctor or a physio clears the load.
    """
    area = _injury_area(injuries)
    if not area:
        return ""
    if old:
        return f"Your {area} is an old injury, so the load on it comes back gradually. "
    return (
        f"I kept weight off your {area}. "
        "Check with your doctor or a physio before loading it. "
    )


def _note_age_correction(state, reply):
    """A mention of age clears the stored number and asks again."""
    if not _age_correction(reply):
        return False
    _clear_age(state)
    if state.get("error") == _WEIGHT_ASK:
        return False
    state["phase"] = "age"
    state["awaiting"] = None
    state["error"] = _AGE_ASK
    return True


def _injury_button(reply):
    """Tap options for old-or-recent. The engine stores the enum, not the sentence.

    An emoji or any other mark is not the button. It does not store the injury.
    """
    if not isinstance(reply, str):
        return None
    if any(ord(char) > 127 for char in reply):
        return None
    raw = " ".join(reply.strip().lower().replace("&", " and ").split())
    if raw in {"old and healed", "old"}:
        return "old"
    if raw in {"recent or still painful", "recent"}:
        return "current"
    return None


def submit_injury_when(state, choice):
    """choice is 'old' or 'current'. A sentence is not a choice."""
    if choice == "old":
        label = state.get("pending_injury") or ""
        if label:
            state["answers"]["injuries"] = label
        if state["answers"].get("injuries"):
            state["answers"]["injury_old"] = True
        state.pop("pending_injury", None)
        state["awaiting"] = None
        state["error"] = None
        state["label_unclear"] = 0
        if state.get("phase") != "confirm":
            state["phase"] = "intake"
        return True
    if choice == "current":
        state.pop("pending_injury", None)
        state["awaiting"] = None
        state["label_unclear"] = 0
        _hold_symptom(state, choice, _plain_pause())
        return True
    return False


def _typed_all_no(text):
    """The exact words the PAR-Q line asks for. A sentence is not this token.

    Case and surrounding space do not matter. 'all no' and 'all no.' only.
    """
    if not isinstance(text, str):
        return False
    folded = " ".join(text.strip().lower().split())
    return folded in {"all no", "all no."}


def _par_q_all_no_button(text):
    """The all_no button, or the exact typed token that means the same thing."""
    return text == "all_no" or _typed_all_no(text)


def submit_par_q(state, choice):
    """'all_no', or a dict of PAR-Q key to bool. Raw text is not an answer."""
    if choice == "all_no":
        parsed = {key: False for key, _question in PAR_Q}
        _store_par_q(state, parsed, False)
        state["par_q_reply"] = "all no"
        state["label_unclear"] = 0
        return True
    if not isinstance(choice, dict):
        return False
    expected = {key for key, _question in PAR_Q}
    if set(choice) != expected:
        return False
    if any(value is not True and value is not False for value in choice.values()):
        return False
    _store_par_q(state, dict(choice), False)
    state["par_q_reply"] = "yes" if any(choice.values()) else "all no"
    state["label_unclear"] = 0
    return True


def _emergency_pause(reply):
    """The hold line. The decision was the backstop. The checker line is included when it has one."""
    from types import SimpleNamespace
    from record_confirmation import reply_pause

    message = hard_stop_message()
    paused = reply_pause(reply) if isinstance(reply, str) else None
    extra = getattr(paused, "message", None) if paused is not None else None
    if isinstance(extra, str) and extra.strip() and extra not in message:
        message = f"{message} {extra.strip()}"
    recommendations = list(getattr(paused, "recommendations", None) or [])
    return SimpleNamespace(message=message, recommendations=recommendations)


def _explicit_no_injuries(folded):
    """The profile line is the explicit no-injuries statement.

    The host label injury=none is the decision. These words only say which
    line that label belongs to. The words alone never fill injuries.
    """
    if not folded:
        return False
    return re.search(r"\bno injuries\b", folded) is not None


def _profile_line(folded):
    """Goal, body, or training facts. An injury sentence is not one of these by itself."""
    if not folded:
        return False
    if re.search(r"\b\d+(?:\.\d+)?\s*kg\b", folded) or re.search(r"\b\d{2,3}\s*cm\b", folded):
        return True
    if re.search(r"\b(?:lbs?|pounds?)\b", folded):
        return True
    if re.search(r"\b(?:male|female|man|woman)\b", folded) and re.search(
        r"\b(?:cut|lose|gain|hold)\b", folded
    ):
        return True
    if re.search(r"\b[1-7]\s+days?\b", folded):
        return True
    if "general training" in folded or re.search(r"\b(?:dumbbells|bodyweight|barbell|full gym)\b", folded):
        return True
    if re.search(r"\b(?:beginner|intermediate|advanced)\b", folded):
        return True
    if re.search(r"\bwant\b", folded):
        return True
    if re.fullmatch(r"(?:cut|lose|gain|hold)", folded):
        return True
    if re.search(
        r"\b(?:apple health|apple watch|garmin|oura|whoop|fitbit|food app|smart scale)\b",
        folded,
    ):
        return True
    return False


# Profile facts only. An injury word, a symptom, or "all" is not in this list,
# so those replies stay a follow-up and are not read as a plan edit.
_PROFILE_WORDS = frozenset({
    "hold", "cut", "lose", "gain", "fat", "weight", "height",
    "male", "female", "man", "woman",
    "kg", "cm", "lb", "lbs", "pound", "pounds",
    "now", "current", "want", "target", "my", "i", "im",
    "day", "days", "min", "mins", "minute", "minutes",
    "general", "training", "bodyweight", "dumbbells", "dumbbell", "barbell",
    "gym", "full", "beginner", "intermediate", "advanced",
    "running", "lifting", "parkrun",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "mon", "tue", "wed", "thu", "fri", "sat", "sun", "saturdays",
    "no", "injuries", "none", "nope",
    "apple", "health", "watch", "garmin", "oura", "whoop", "fitbit", "food",
    "app", "smart", "scale", "and", "a", "the", "to", "at", "of", "with",
    "for", "on", "in", "home", "have", "also", "most", "about", "can", "do",
    "week", "call", "me", "bench", "squat", "age",
})


def _profile_facts_only(reply):
    """Weight, height, days, and the other profile facts. Not a safety reply."""
    folded = _fold(reply) if isinstance(reply, str) else ""
    if not folded or not _profile_line(folded):
        return False
    tokens = folded.split()
    return bool(tokens) and all(token.isdigit() or token in _PROFILE_WORDS for token in tokens)


_COUNT_WORDS = frozenset({
    "day", "days", "min", "mins", "minute", "minutes", "rep", "reps",
    "set", "sets", "x", "kg",
})


def _count_only(reply):
    """A days, minutes, or reps count with no other words."""
    if not _counted_training(reply):
        return False
    folded = _fold(reply) if isinstance(reply, str) else ""
    tokens = folded.split()
    return bool(tokens) and all(token.isdigit() or token in _COUNT_WORDS for token in tokens)


_INJURY_NONE_TAP = {"none", "no", "nope", "no injuries", "injuries none"}


def _exact_area(reply):
    """The whole reply is one area tap. A sentence is not an area."""
    folded = _fold(reply) if isinstance(reply, str) else ""
    if not folded:
        return None
    for phrase, label in _INJURY_AREAS:
        if folded == phrase:
            return label
    return None


def _bare_yes(reply):
    return _fold(reply) in {"yes", "yep", "yeah", "yup"}


def _exact_token(state, reply):
    """A tap, an enum, or a typed slot. Free text is not one of these."""
    if not isinstance(reply, str):
        return False
    if _leg_emoji_only(reply):
        return True
    folded = _fold(reply)
    if not folded:
        return False
    if folded in {"hello", "hi", "hey", "skip"}:
        return True
    if state.get("asked") == "par_q" and _par_q_all_no_button(reply):
        return True
    if folded in _ACCEPT and not (state.get("phase") == "confirm" and state.get("safety_followup")):
        return True
    if state.get("awaiting") in {"target", "weight"}:
        return True
    if state.get("awaiting") == "injury" and _exact_area(reply):
        return True
    if _explicit_edit(reply) is not None:
        return True
    answers = state.get("answers") if isinstance(state.get("answers"), dict) else {}
    if (
        state.get("asked") in {"training", "par_q"}
        and "injuries" not in answers
        and (folded in _INJURY_NONE_TAP or _injury_button(reply))
    ):
        return True
    if folded in {"cut", "lose", "gain", "hold"}:
        return True
    if state.get("phase") == "confirm" and not state.get("safety_followup"):
        if (
            _bare_yes(reply)
            or _is_plan_yes(reply)
            or _schedule_aside(reply)
            or _harmless_aside(reply)
            or _nonblocking_stat(folded)
            or _count_only(reply)
        ):
            return True
    return False


def _remember_injury_text(state, reply):
    """Keep the area named in the follow-up, so an Old tap can store it."""
    folded = _fold(reply) if isinstance(reply, str) else ""
    label = _pending_injury_label(reply) or ""
    if not label:
        stated = _stated_injury(folded)
        if stated and stated != "none":
            label = stated
    if label and not state.get("pending_injury"):
        state["pending_injury"] = label


def _store_old_from_text(state, reply):
    """The area, once the label or the button already says old."""
    folded = _fold(reply) if isinstance(reply, str) else ""
    label = _named_injury_label(folded) or ""
    if not label:
        stated = _stated_injury(folded)
        if stated and stated != "none":
            label = stated
    if not label:
        label = state.get("pending_injury") or ""
    if label:
        state["answers"]["injuries"] = label
        state["answers"]["injury_old"] = True
    state.pop("pending_injury", None)
    state["awaiting"] = None
    state["label_unclear"] = 0


def _ask_label_followup(state, reply, labels):
    """One follow-up. The next unclear holds the day."""
    count = state.get("label_unclear") or 0
    if not isinstance(count, int) or count < 0:
        count = 0
    if count >= 1:
        _hold_symptom(state, reply, _plain_pause())
        return
    state["label_unclear"] = count + 1
    state["safety_followup"] = True
    cause = _follow_up_cause(labels)
    text = reply if isinstance(reply, str) else ""
    state["follow_up_text"] = text
    _write_safety("follow_up", cause=cause, text=text)
    _clear_proposal(state)
    parsed, reason = validate_labels(labels) if labels is not None else (None, "missing")
    if reason is None:
        _parse_profile_fields(state, reply)
    if cause == "injury_unclear":
        _ask_injury_when(state, reply)
        return
    state["error"] = _LABEL_FOLLOWUP
    if state.get("phase") == "confirm":
        state["phase"] = "confirm"


def _apply_label_decision(state, reply, labels):
    """One label action. True when this reply is finished."""
    count = state.get("label_unclear") or 0
    action = label_action(labels, count)
    if action == "follow_up":
        _ask_label_followup(state, reply, labels)
        return True
    if action == "hold":
        parsed, reason = validate_labels(labels)
        if reason is None and parsed["injury"] != "none":
            _keep_pending_injury(state, reply)
        flag = parsed["red_flag"] if reason is None else "none"
        if flag in {"chest_pain", "cardiac_symptoms", "breathing_difficulty", "fainting"}:
            _hold_symptom(state, reply, _emergency_pause(reply))
        else:
            _hold_symptom(state, reply, _plain_pause())
        return True
    if action == "clear_age":
        _parse_profile_fields(state, reply)
        parsed, reason = validate_labels(labels)
        injury = parsed["injury"] if reason is None else "none"
        if injury != "none":
            _keep_pending_injury(state, reply)
            state["ask_injury_after_age"] = True
        _clear_age(state)
        state["phase"] = "age"
        state["awaiting"] = None
        state["error"] = _AGE_ASK
        state["label_unclear"] = 0
        state["safety_followup"] = False
        _write_safety("age_check")
        return True
    if action == "swap":
        _parse_profile_fields(state, reply)
        saved = state.get("follow_up_text") if isinstance(state.get("follow_up_text"), str) else ""
        if saved and not state.get("pending_injury"):
            _remember_injury_text(state, saved)
        _store_old_from_text(state, saved or reply)
        state["safety_followup"] = False
        _clear_safety()
        state["error"] = None
        if state.get("phase") != "confirm":
            state["phase"] = "intake"
        return True
    if action in {"note", "pass"}:
        if _follow_up_open(state):
            _hold_symptom(state, reply, _plain_pause())
            return True
        state["label_unclear"] = 0
        state["safety_followup"] = False
        if action == "note" and isinstance(reply, str):
            state["answers"]["remark"] = reply
        _accept_labeled_profile(state, reply, labels)
        return False
    return False


def _accept_labeled_profile(state, reply, labels):
    """Profile facts after a pass or a note.

    injury=none on that labeled profile line is the structured None answer.
    The words in the line are not matched. A tap writes only its own field.
    """
    if not _exact_token(state, reply):
        _parse_profile_fields(state, reply)
    parsed, reason = validate_labels(labels) if labels is not None else (None, "missing")
    if reason is not None or parsed.get("injury") != "none":
        return
    folded = _fold(reply) if isinstance(reply, str) else ""
    if not _profile_line(folded) or not _explicit_no_injuries(folded):
        return
    if "injuries" not in state["answers"]:
        state["answers"]["injuries"] = "none"


def _take_injury_choice(state, reply, labels):
    """A button, or a label that already says old or current.

    An invalid label is a follow-up. It is never read as the old button.
    """
    parsed = None
    if labels is not None:
        parsed, reason = validate_labels(labels)
        if reason is not None:
            _ask_label_followup(state, reply, labels)
            return
        if parsed["red_flag"] != "none":
            _apply_label_decision(state, reply, labels)
            return
        if parsed["minor_signal"]:
            _apply_label_decision(state, reply, labels)
            return
        if parsed["injury"] in {"old", "current"}:
            if parsed["injury"] == "old":
                _store_old_from_text(state, reply if state.get("pending_injury") else reply)
            submit_injury_when(state, parsed["injury"])
            state["safety_followup"] = False
            return
        if parsed["injury"] == "unclear":
            _ask_label_followup(state, reply, labels)
            return
        _ask_label_followup(state, reply, labels)
        return
    choice = _injury_button(reply)
    if choice == "old":
        submit_injury_when(state, "old")
        return
    if choice == "current":
        submit_injury_when(state, "current")
        return
    _ask_label_followup(state, reply, labels)


def _take_exact(state, reply):
    """An exact tap or enum. This does not read PAR-Q or an injury sentence."""
    if _follow_up_open(state):
        _hold_symptom(state, reply, _plain_pause())
        return
    state["label_unclear"] = 0
    state["safety_followup"] = False
    if _leg_emoji_only(reply):
        _ask_which_area(state)
        state["safety_followup"] = True
        return
    if state.get("phase") == "confirm" and not state.get("safety_followup") and _handle_confirm(state, reply):
        return
    if state.get("awaiting") == "target":
        _take_target_number(state, reply)
        return
    if state.get("awaiting") == "weight":
        _take_weight_number(state, reply)
        return
    if state.get("awaiting") == "injury":
        _take_injury_answer(state, reply)
        return
    folded = _fold(reply) if isinstance(reply, str) else ""
    if state.get("asked") == "par_q" and _par_q_all_no_button(reply):
        submit_par_q(state, "all_no")
        return
    if folded == "skip":
        _remember_skip(state)
        return
    if (
        folded in _INJURY_NONE_TAP
        and "injuries" not in state["answers"]
        and state.get("asked") in {"training", "par_q"}
    ):
        state["answers"]["injuries"] = "none"
        return
    button = _injury_button(reply)
    if (
        button
        and "injuries" not in state["answers"]
        and state.get("asked") in {"training", "par_q"}
    ):
        if button == "current":
            _hold_symptom(state, reply, _plain_pause())
            return
        _ask_which_area(state)
        return
    if folded in {"cut", "lose", "gain", "hold"}:
        state["answers"]["goal"] = folded
        return
    edit = _explicit_edit(reply)
    if edit is not None:
        _apply_edit(state, edit)
        return
    if folded in _ACCEPT and state.get("asked") in {"goal", "training"}:
        _fill_group(state, state["asked"])
        return
    if state.get("phase") == "confirm":
        _review_confirm_edit(state, reply)


def _consume_pending(state, reply, labels):
    """True when a pending record used this reply. Confirm stays closed.

    A follow-up clears only for an Old/Recent tap or a valid red_flag, minor,
    or injury old/current label. A pass, a note, or a missing label is the
    second unclear and holds. The turn that clears the follow-up does not
    confirm. An age check clears only for a typed int.
    """
    from safety_pending import resolves_follow_up, typed_age

    pending = _read_safety()
    kind = pending.get("kind") if isinstance(pending, dict) else None
    # "Which area?" is its own tap. A knee/back answer is not a failed follow-up.
    if (
        state.get("awaiting") == "injury"
        and labels is None
        and _exact_area(reply)
        and kind not in {"hold", "age_check"}
    ):
        _clear_safety()
        state["safety_followup"] = False
        state["confirmed"] = False
        _take_injury_answer(state, reply)
        return True
    if kind not in {"follow_up", "age_check", "hold"}:
        if state.get("safety_followup") or state.get("awaiting") == "injury_when":
            kind = "follow_up"
        else:
            return False
    state["confirmed"] = False
    if kind == "hold":
        if hold_is_active():
            _adopt_hold(state)
            _handle_symptom(state, reply)
        else:
            _hold_symptom(state, reply, _plain_pause())
        return True
    if kind == "age_check":
        number = typed_age(reply) if labels is None else None
        if number is None:
            state["phase"] = "age"
            state["awaiting"] = None
            state["need_age"] = True
            state["error"] = _AGE_ASK
            return True
        submit_age(state, number)
        state["confirmed"] = False
        return True
    cause = pending.get("cause") if isinstance(pending, dict) else None
    if state.get("awaiting") == "injury_when":
        cause = "injury_unclear"
    # A bare number outside the age step is not a safety answer.
    if (
        kind == "follow_up"
        and labels is None
        and typed_age(reply) is not None
        and state.get("phase") not in {"age", "blocked"}
    ):
        state["error"] = _INJURY_WHEN if cause == "injury_unclear" else _LABEL_FOLLOWUP
        return True
    button = _injury_button(reply) if labels is None else None
    if resolves_follow_up(labels, button=button, injury_unclear=cause == "injury_unclear"):
        saved = ""
        if isinstance(pending, dict) and isinstance(pending.get("text"), str):
            saved = pending["text"]
        elif isinstance(state.get("follow_up_text"), str):
            saved = state["follow_up_text"]
        if saved:
            state["follow_up_text"] = saved
            _remember_injury_text(state, saved)
        _clear_safety()
        state["safety_followup"] = False
        state["cleared_follow_up"] = True
        if labels is None and button in {"old", "current"}:
            _take_injury_choice(state, reply, None)
        else:
            _apply_label_decision(state, reply, labels)
        state["confirmed"] = False
        return True
    _hold_symptom(state, reply, _plain_pause())
    return True


_GAP_WORDS = {
    "goal": "your goal (cut, lose, gain, or hold)",
    "weight": "your weight in kg",
    "height": "your height in cm",
    "age": "your age as a number",
    "sex": "sex",
    "days": "which days you train",
    "minutes": "session minutes",
    "equipment": "equipment",
    "experience": "your level (beginner, intermediate, or advanced)",
}


def _payload_gaps(state):
    """Required profile fields still empty. Sport, name, and food do not block."""
    answers = state.get("answers") if isinstance(state.get("answers"), dict) else {}
    missing = []
    for key in ("goal", "weight", "height", "age", "sex"):
        if answers.get(key) in (None, ""):
            missing.append(key)
    if not answers.get("days"):
        missing.append("days")
    for key in ("minutes", "equipment", "experience"):
        if answers.get(key) in (None, ""):
            missing.append(key)
    return missing


def _combined_profile_ask(gaps):
    parts = [_GAP_WORDS[key] for key in gaps if key in _GAP_WORDS]
    if len(parts) == 1:
        return f"Still need {parts[0]}."
    if len(parts) == 2:
        return f"Still need {parts[0]} and {parts[1]}."
    return "Still need " + ", ".join(parts[:-1]) + ", and " + parts[-1] + "."


def _clear_resolved_asks(state):
    answers = state.get("answers") if isinstance(state.get("answers"), dict) else {}
    error = state.get("error")
    if error == _AGE_ASK and answers.get("age") not in (None, ""):
        state["error"] = None
    if error in {_WEIGHT_ASK, _CURRENT_WEIGHT_ASK} and answers.get("weight") not in (None, ""):
        state["error"] = None
        if state.get("awaiting") == "weight":
            state["awaiting"] = None
    if error == _TARGET_ASK and answers.get("target") not in (None, ""):
        state["error"] = None
        if state.get("awaiting") == "target":
            state["awaiting"] = None
    if (
        isinstance(error, str)
        and error.startswith("That target looks far")
        and answers.get("target") not in (None, "")
    ):
        state["error"] = None
        state["awaiting"] = None
        state.pop("target_far_once", None)


def _release_age_phase_if_filled(state):
    age = _number(state["answers"].get("age"))
    if age is None:
        return
    if age < 18:
        _apply_age_readiness(state)
        if state.get("error"):
            state["phase"] = "blocked"
            return
    if state.get("phase") == "age":
        state["phase"] = "intake"
        state["need_age"] = False
        if state.get("error") == _AGE_ASK:
            state["error"] = None


def _merge_profile_payload(state, payload):
    """Store every valid profile field. Invalid fields are dropped, not asked as a group."""
    from profile_payload import accept_profile

    fields, rejected = accept_profile(payload)
    state["from_profile_payload"] = True
    state["profile_rejected"] = list(rejected)
    day_indexes = fields.pop("day_indexes", None)
    for key, value in fields.items():
        state["answers"][key] = value
    if day_indexes:
        state["answers"]["training_days"] = str(len(day_indexes))
        state["answers"]["days"] = _dates(len(day_indexes), day_indexes)
        state["answers"]["days_named"] = True
    if state["answers"].get("age") not in (None, ""):
        state["need_age"] = False
    _release_age_phase_if_filled(state)
    _clear_resolved_asks(state)


def _finish_profile(state, profile):
    if not isinstance(profile, dict):
        return
    if hold_is_active() or state.get("phase") == "symptom":
        return
    if state.get("safety_followup"):
        return
    _merge_profile_payload(state, profile)


def _clock_hhmm(value):
    """21:00, 9pm, 9 pm, and 9:30am. None when the text is not a clock."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.strip().lower().split())
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if match is not None:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if hour > 23 or minute > 59:
            return None
        return f"{hour:02d}:{minute:02d}"
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", text)
    if match is None:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if hour < 1 or hour > 12 or minute > 59:
        return None
    if match.group(3) == "am":
        hour = 0 if hour == 12 else hour
    elif hour != 12:
        hour += 12
    return f"{hour:02d}:{minute:02d}"


_WEEKDAY_CLOCK = {
    "sun": "Sun",
    "sunday": "Sun",
    "mon": "Mon",
    "monday": "Mon",
    "tue": "Tue",
    "tues": "Tue",
    "tuesday": "Tue",
    "wed": "Wed",
    "wednesday": "Wed",
    "thu": "Thu",
    "thur": "Thu",
    "thurs": "Thu",
    "thursday": "Thu",
    "fri": "Fri",
    "friday": "Fri",
    "sat": "Sat",
    "saturday": "Sat",
}


def _weekly_clock(value):
    """A weekday plus a clock, or None. A bare word is not a weekly time."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"([A-Za-z]+)\s+(.+)", " ".join(value.split()))
    if match is None:
        return None
    day = _WEEKDAY_CLOCK.get(match.group(1).lower())
    clock = _clock_hhmm(match.group(2))
    if day is None or clock is None:
        return None
    return f"{day} {clock}"


_ROUTINE_TIME_ALIASES = {
    "daily_checkin": "daily_checkin",
    "morning": "daily_checkin",
    "evening_followup": "evening_followup",
    "evening": "evening_followup",
    "weekly_review": "weekly_review",
    "weekly": "weekly_review",
}


def _canonical_routine_times(times):
    """morning, evening, and weekly are aliases. The canonical key wins."""
    if not isinstance(times, dict):
        return {}
    ranked = {}
    for key, value in times.items():
        if not isinstance(key, str):
            continue
        raw = key.strip().lower()
        name = _ROUTINE_TIME_ALIASES.get(raw)
        if not name:
            continue
        priority = 1 if raw == name else 0
        current = ranked.get(name)
        if current is None or priority >= current[0]:
            ranked[name] = (priority, value)
    return {name: pair[1] for name, pair in ranked.items()}


def _overlay_routine_times(state, times):
    """Keep a valid clock. A bad value falls back to that routine's default."""
    from routines import DEFAULT_LOOP_TIMES

    current = dict(DEFAULT_LOOP_TIMES)
    saved = state.get("times") if isinstance(state.get("times"), dict) else {}
    for key, default in DEFAULT_LOOP_TIMES.items():
        if saved.get(key):
            current[key] = saved[key]
    times = _canonical_routine_times(times)
    if not times:
        state["times"] = current
        state.pop("routine_time_note", None)
        return
    ignored = False
    if "daily_checkin" in times:
        parsed = _clock_hhmm(times.get("daily_checkin"))
        if parsed:
            current["daily_checkin"] = parsed
        else:
            current["daily_checkin"] = DEFAULT_LOOP_TIMES["daily_checkin"]
            ignored = True
    if "evening_followup" in times:
        parsed = _clock_hhmm(times.get("evening_followup"))
        if parsed:
            current["evening_followup"] = parsed
        else:
            current["evening_followup"] = DEFAULT_LOOP_TIMES["evening_followup"]
            ignored = True
    if "weekly_review" in times:
        parsed = _weekly_clock(times.get("weekly_review"))
        if parsed:
            current["weekly_review"] = parsed
        else:
            current["weekly_review"] = DEFAULT_LOOP_TIMES["weekly_review"]
            ignored = True
    state["times"] = current
    if ignored:
        state["routine_time_note"] = "A routine time was ignored and the default was kept."
    else:
        state.pop("routine_time_note", None)


def _plan_answer(state):
    """What the built week contains. The question text is not read."""
    sessions = state.get("sessions") or []
    names = [row.get("name") for row in sessions if isinstance(row, dict)]
    if "Easy run" in names or "Long run" in names:
        return "The week includes strength and running: easy runs and a long run."
    return "This week is strength sessions."


def _structured_confirm_allowed(state):
    if hold_is_active() or state.get("phase") == "symptom":
        return False
    if state.get("safety_followup") or state.get("cleared_follow_up"):
        return False
    pending = _read_safety()
    if isinstance(pending, dict) and pending.get("kind") in {"follow_up", "age_check", "hold"}:
        return False
    if _first_missing(state) is not None:
        return False
    return True


def _apply_structured_confirm(state, confirm, token, reply=""):
    """confirm true accepts the shown plan. A question is answered from the week.

    The record quotes the user's text and marks the source host_confirm.
    The string "true" is not the flag.
    """
    if not isinstance(confirm, dict) or confirm.get("confirm") is not True:
        return token
    if not _structured_confirm_allowed(state):
        return token
    from record_confirmation import _host_confirm_refusal

    quoted_early = reply if isinstance(reply, str) and reply.strip() else "yes"
    if _host_confirm_refusal(quoted_early):
        state["phase"] = "confirm"
        state["confirmed"] = False
        state["record"] = None
        state["error"] = None
        return token
    if token is None:
        token = _CONFIRM_PHASE.set(True)
    state["phase"] = "confirm"
    quoted = reply if isinstance(reply, str) and reply.strip() else "yes"
    if not state.get("confirmed"):
        _confirm(state, quoted, source="host_confirm")
    if not state.get("confirmed"):
        return token
    _overlay_routine_times(state, confirm.get("routine_times"))
    question = confirm.get("question")
    if isinstance(question, str) and question.strip():
        state["confirm_note"] = _plan_answer(state)
    return token


def apply_reply(state, reply, labels=None, profile=None):
    """One user reply. Hard-stop first, then host labels, then a structured slot.

    A profile payload is the source for height and weight. Free text does not
    fill those two when this turn has a payload that leaves them out.

    Labels are the argument. They are never read out of reply.
    A profile payload is the argument. It is never read out of reply.
    A pending follow-up, age check, or hold blocks confirm.
    """
    state["error"] = None
    state["cleared_follow_up"] = False
    state["skip_body_from_text"] = isinstance(profile, dict)
    text = reply if isinstance(reply, str) else ""
    if hold_is_active():
        _adopt_hold(state)
        _handle_symptom(state, text)
        return
    if hard_stop(text):
        _hold_symptom(state, text, _emergency_pause(text))
        return
    if _consume_pending(state, text, labels):
        return
    if state.get("awaiting") == "injury_when":
        _take_injury_choice(state, text, labels)
        if state.get("phase") != "symptom":
            _finish_profile(state, profile)
        return
    if (
        state.get("phase") == "confirm"
        and state.get("safety_followup")
        and labels is None
        and _bare_yes(text)
    ):
        _hold_symptom(state, text, _plain_pause())
        return
    phase = state.get("phase")
    if phase == "symptom":
        _handle_symptom(state, text)
        return
    if phase == "age":
        if labels is not None and _apply_label_decision(state, text, labels):
            return
        _finish_profile(state, profile)
        if state.get("phase") == "blocked":
            return
        if _number(state["answers"].get("age")) is not None and state.get("phase") != "age":
            return
        _handle_age(state, text, labels)
        return
    if phase == "blocked":
        _handle_blocked(state, text, labels)
        return
    if labels is not None:
        if _apply_label_decision(state, text, labels):
            if state.get("phase") != "age":
                _finish_profile(state, profile)
            return
        # Merge before a yes. A same-turn edit has to be visible to confirm.
        _finish_profile(state, profile)
        if _exact_token(state, text):
            _take_exact(state, text)
        elif state.get("phase") == "confirm":
            _review_confirm_edit(state, text)
        return
    if _exact_token(state, text):
        _finish_profile(state, profile)
        _take_exact(state, text)
        return
    if _profile_facts_only(text) and not state.get("safety_followup"):
        _parse_profile_fields(state, text)
        state["label_unclear"] = 0
        _finish_profile(state, profile)
        return
    from safety_pending import typed_age

    if labels is None and typed_age(text) is not None and phase not in {"age", "blocked"}:
        return
    _ask_label_followup(state, text, None)


def _symptom_hold_message(paused):
    text = (getattr(paused, "message", None) or "").strip()
    if _REST_LINE not in text:
        text = (text + " " + _REST_LINE).strip()
    return text


def onboarding_state_path():
    """Dated symptom hold and the answers to resume the next day."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "onboarding_state.json")


def _remember_timezone(state):
    """Keep the profile timezone. The box zone fills in when none was saved."""
    answers = state.get("answers")
    if not isinstance(answers, dict):
        answers = {}
        state["answers"] = answers
    if _usable_zone(answers.get("timezone")) is None:
        answers["timezone"] = _default_timezone_name()
    return answers["timezone"].strip()


def _write_onboarding_state(state):
    zone_name = _remember_timezone(state)
    payload = {
        "answers": state.get("answers") if isinstance(state.get("answers"), dict) else {},
        "checks_again": True,
        "timezone": zone_name,
        "hold": {
            "date": _local_today(zone_name).isoformat(),
            "message": state.get("hold_message") or _REST_LINE,
        },
    }
    path = onboarding_state_path()
    temporary = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
            handle.write("\n")
        os.replace(temporary, path)
    except OSError:
        return False
    return True


def _arm_memory_hold(state):
    """Keep today's hold in this process when the file could not be saved.

    A restarted process does not see it. The file is the only hold that
    survives a new process.
    """
    global _memory_hold
    zone_name = _timezone_name(state.get("answers") if isinstance(state.get("answers"), dict) else None)
    answers = dict(state.get("answers") or {})
    answers["timezone"] = zone_name
    state["answers"] = answers
    _memory_hold = {
        "answers": answers,
        "checks_again": True,
        "timezone": zone_name,
        "hold": {
            "date": _local_today(zone_name).isoformat(),
            "message": state.get("hold_message") or _REST_LINE,
        },
    }


def _persist_hold(state):
    """Write the hold. A failed write is the reply, and onboarding stops."""
    global _memory_hold
    if _write_onboarding_state(state):
        _memory_hold = None
        return True
    _arm_memory_hold(state)
    state["phase"] = "symptom"
    state["confirmed"] = False
    state["record"] = None
    state["error"] = _HOLD_WRITE_FAILED
    return False


def _can_refresh_hold():
    """A bad or future-dated file stays as it is. A missing or today's hold can be written."""
    kind, saved = _read_hold_file()
    if kind == "missing" or kind == "expired":
        return True
    return _hold_is_today(saved)


def _read_hold_file():
    """('missing', None), ('active', payload or None), or ('expired', payload).

    A missing file is not a hold. A date strictly before the user's local
    today has stopped counting, and the file stays. Unreadable, garbage,
    corrupt, and future-dated files are an active hold. The in-memory copy
    is checked the same way. The hold is active when either one is active,
    including when an expired file is still on disk.
    """
    file_kind, file_saved = _read_hold_on_disk()
    mem_kind, mem_saved = "missing", None
    if isinstance(_memory_hold, dict):
        mem_kind, mem_saved = _classify_saved(_memory_hold)
    if mem_kind == "active" or file_kind == "active":
        if mem_kind == "active" and mem_saved is not None:
            return "active", mem_saved
        if file_kind == "active":
            return "active", file_saved
        return "active", mem_saved
    if file_kind == "expired":
        return "expired", file_saved
    if mem_kind == "expired":
        return "expired", mem_saved
    return "missing", None


def _read_hold_on_disk():
    path = onboarding_state_path()
    if not os.path.lexists(path):
        return "missing", None
    try:
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
    except OSError:
        return "active", None
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return "active", None
    return _classify_saved(loaded)


def _classify_saved(loaded):
    if not isinstance(loaded, dict):
        return "active", None
    hold = loaded.get("hold")
    if not isinstance(hold, dict):
        return "active", None
    text = hold.get("date")
    if not isinstance(text, str):
        return "active", None
    try:
        hold_day = date.fromisoformat(text)
    except ValueError:
        return "active", None
    today = _local_today(_timezone_name(saved=loaded))
    if hold_day < today:
        return "expired", loaded
    return "active", loaded


def hold_is_active():
    """True while a symptom hold blocks onboarding, including a bad hold file."""
    kind, _saved = _read_hold_file()
    return kind == "active"


def persist_active_hold():
    """Write a memory hold to disk. A file that is already active stays as it is."""
    if not hold_is_active():
        return False
    disk_kind, _disk = _read_hold_on_disk()
    if disk_kind == "active":
        return True
    if not isinstance(_memory_hold, dict):
        return False
    path = onboarding_state_path()
    temporary = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(_memory_hold, handle)
            handle.write("\n")
        os.replace(temporary, path)
    except OSError:
        return False
    return True


def active_hold_message():
    """The line to show while a hold blocks, or None when nothing is held."""
    if not hold_is_active():
        return None
    _kind, saved = _read_hold_file()
    if _hold_is_today(saved):
        hold = saved.get("hold") if isinstance(saved, dict) else {}
        message = hold.get("message") if isinstance(hold, dict) else ""
        if isinstance(message, str) and message.strip():
            return message.strip()
        return _REST_LINE
    return _HOLD_CLOSED


def _typed_date(reply):
    if not isinstance(reply, str):
        return None
    text = reply.strip()
    if text.lower().startswith("clear_hold"):
        parts = text.split(None, 1)
        text = parts[1].strip() if len(parts) == 2 else ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _clear_date(saved):
    """The date that has to be typed. A file with no date uses the local today."""
    if isinstance(saved, dict):
        hold = saved.get("hold")
        if isinstance(hold, dict) and isinstance(hold.get("date"), str):
            try:
                return date.fromisoformat(hold["date"]).isoformat()
            except ValueError:
                pass
    if isinstance(saved, dict):
        return _local_today(_timezone_name(saved=saved)).isoformat()
    return _local_today().isoformat()


def clear_hold(reply):
    """Operator-only CLI step. The bot never runs this because a user asks or types a date.

    Clear a corrupt or future-dated hold when the operator types that date.
    A hold dated today is not cleared. It stops on a later local date.
    Type the date in the file as YYYY-MM-DD. A corrupt or unreadable file
    has no date, so type today's local date.
    """
    global _memory_hold
    kind, saved = _read_hold_file()
    if kind != "active":
        return "There is no hold to clear."
    if _hold_is_today(saved):
        return "A hold dated today stays until the next local day. It is not cleared."
    wanted = _clear_date(saved)
    typed = _typed_date(reply)
    if typed != wanted:
        return f"Type the date {wanted} to clear this hold."
    path = onboarding_state_path()
    if os.path.lexists(path):
        try:
            os.remove(path)
        except OSError:
            return "Stop. The hold file could not be cleared. Please check it."
    _memory_hold = None
    return "The hold is cleared."


def _hold_is_today(saved):
    if not isinstance(saved, dict):
        return False
    hold = saved.get("hold")
    if not isinstance(hold, dict) or not isinstance(hold.get("date"), str):
        return False
    try:
        hold_day = date.fromisoformat(hold["date"])
    except ValueError:
        return False
    return hold_day == _local_today(_timezone_name(saved=saved))


def _adopt_hold(state):
    """Force the in-memory attempt onto the hold. It does not clear the file."""
    _kind, saved = _read_hold_file()
    state["phase"] = "symptom"
    state["confirmed"] = False
    state["record"] = None
    state["checks_again"] = True
    state["awaiting"] = None
    state["need_age"] = False
    if isinstance(saved, dict) and isinstance(saved.get("answers"), dict):
        state["answers"] = saved["answers"]
    if _hold_is_today(saved):
        hold = saved.get("hold") if isinstance(saved.get("hold"), dict) else {}
        message = hold.get("message") if isinstance(hold.get("message"), str) else ""
        state["hold_message"] = message.strip() or _REST_LINE
    else:
        state["hold_message"] = _HOLD_CLOSED
    state["error"] = state["hold_message"]


def _clear_onboarding_state():
    """A symptom hold is not deleted. It stops counting on a later local date."""
    return False


def _end_onboarding_for_today(state, paused):
    """A symptom happening now ends onboarding until the next local date."""
    _clear_proposal(state)
    state["phase"] = "symptom"
    state["awaiting"] = None
    state["need_age"] = False
    state["checks_again"] = True
    state["confirmed"] = False
    state["record"] = None
    state["hold_message"] = _symptom_hold_message(paused)
    if not _can_refresh_hold():
        state["error"] = _HOLD_CLOSED
        return True
    if not _persist_hold(state):
        return True
    state["error"] = state["hold_message"]
    _write_safety("hold", message=state["hold_message"])
    return True


def _hold_symptom(state, reply, paused):
    """Leave confirm for the rest of the day. Nothing in this conversation resumes it."""
    return _end_onboarding_for_today(state, paused)


def _hold_age(state):
    """Leave confirm and ask for a typed age. A later yes is not a confirm."""
    _clear_proposal(state)
    state["phase"] = "age"
    state["awaiting"] = None
    state["need_age"] = True
    state["error"] = _AGE_ASK
    return True


def _handle_symptom(state, reply):
    """The day is over. A typed age can only block a minor. It never resumes."""
    from record_confirmation import reply_pause

    _clear_proposal(state)
    state["phase"] = "symptom"
    paused = reply_pause(reply)
    if paused is not None:
        return _end_onboarding_for_today(state, paused)
    state["confirmed"] = False
    state["record"] = None
    if not isinstance(state.get("answers"), dict):
        state["answers"] = {}
    stored_age = state["answers"].get("age")
    number = _typed_int(reply)
    typed_minor = number is not None and 1 <= number <= 120 and number < 18
    under = ""
    if typed_minor:
        state["answers"]["age"] = str(number)
        _apply_age_readiness(state)
        under = state.get("error") or ""
        if stored_age is None:
            state["answers"].pop("age", None)
        else:
            state["answers"]["age"] = stored_age
    age = _number(state["answers"].get("age"))
    if age is not None and age < 18 and not under:
        _apply_age_readiness(state)
        under = state.get("error") or ""
    hold = state.get("hold_message") or _REST_LINE
    if under:
        state["error"] = under if hold in under else f"{hold} {under}".strip()
    else:
        state["error"] = hold
    state["phase"] = "symptom"
    _clear_proposal(state)
    state["confirmed"] = False
    state["record"] = None
    if _can_refresh_hold():
        saved_error = state["error"]
        if not _persist_hold(state):
            return True
        state["error"] = saved_error
    return True


def _handle_age(state, reply, labels=None):
    """The host passes an int to submit_age. A sentence here is a follow-up."""
    from safety_pending import typed_age

    _clear_proposal(state)
    if labels is not None and _apply_label_decision(state, reply, labels):
        return True
    if (
        labels is None
        and isinstance(reply, str)
        and reply.strip()
        and typed_age(reply) is None
    ):
        _ask_label_followup(state, reply, None)
        return True
    state["phase"] = "age"
    state["awaiting"] = None
    state["need_age"] = True
    state["error"] = _AGE_ASK
    return True


def _handle_blocked(state, reply, labels=None):
    """Under 18, or readiness failed. A yes repeats that refusal."""
    _clear_proposal(state)
    if labels is not None and _apply_label_decision(state, reply, labels):
        return True
    if isinstance(reply, str) and re.fullmatch(r"[0-9]{1,3}", reply.strip()):
        return submit_age(state, int(reply.strip()))
    _apply_age_readiness(state)
    state["phase"] = "blocked"
    _clear_proposal(state)
    return True


def _schedule_aside(reply):
    """A clock or a list of weekdays. It does not ask for the age again.

    'yes at 7', 'yes 7 pm', 'at 6 am', and '10 am' are times. A bare 'at 7' is not.
    """
    if not isinstance(reply, str):
        return False
    raw = " ".join(reply.strip().lower().split()).strip(".,!;")
    if re.fullmatch(r"\d{1,2}:\d{2}(?:\s*(?:am|pm))?", raw):
        return True
    if re.fullmatch(r"yes,?\s+at\s+(?:[1-9]|1[0-2])", raw):
        return True
    if re.fullmatch(r"yes,?\s+(?:[1-9]|1[0-2])\s*(?:am|pm)", raw):
        return True
    if re.fullmatch(r"at\s+(?:[1-9]|1[0-2])\s*(?:am|pm)", raw):
        return True
    if re.fullmatch(r"(?:[1-9]|1[0-2])\s*(?:am|pm)", raw):
        return True
    folded = _fold(reply)
    tokens = folded.split()
    weekdays = {
        "mon", "monday", "tue", "tues", "tuesday", "wed", "wednesday",
        "thu", "thur", "thurs", "thursday", "fri", "friday",
        "sat", "saturday", "sun", "sunday",
    }
    return bool(tokens) and all(token in weekdays for token in tokens)


def _handle_confirm(state, reply):
    """Confirm only when the whole reply is a plan-yes.

    A clear weight or profile edit updates the profile and the proposal is
    shown again. A clock or a harmless aside stays on the proposal. Age and
    injury changes come from the typed age and the host labels, not from
    leftover words.
    """
    if state.get("awaiting") == "weight":
        return _take_weight_number(state, reply)
    if _is_plan_yes(reply):
        state["awaiting"] = None
        _confirm(state, reply)
        return True
    edit = _explicit_edit(reply)
    if edit is not None:
        return _apply_edit(state, edit)
    if _harmless_aside(reply) or _nonblocking_stat(_fold(reply)):
        state["error"] = None
        state["phase"] = "confirm"
        return True
    if _counted_training(reply):
        state["error"] = None
        state["phase"] = "confirm"
        return True
    if _schedule_aside(reply):
        state["error"] = None
        state["phase"] = "confirm"
        return True
    return False


def _apply_age_readiness(state):
    from readiness_screen import ReadinessScreen, passing_readiness

    screen = ReadinessScreen().screen_intake(_readiness_intake(state))
    state["readiness"] = screen
    state["confirmed"] = False
    state["record"] = None
    age = _number(state["answers"].get("age"))
    if age is not None and age < 18:
        state["error"] = _under_18_message(screen)
        return
    if not passing_readiness(screen):
        state["error"] = " ".join(screen.reasons) or "Readiness has to pass before a plan is built."
        return
    state["error"] = None


def _review_confirm_edit(state, reply):
    """A confirm-step reply that fell through still cannot stay confirmable."""
    age = _number(state["answers"].get("age"))
    if age is not None and age < 18:
        from readiness_screen import ReadinessScreen

        screen = ReadinessScreen().screen_intake(_readiness_intake(state))
        state["readiness"] = screen
        _clear_proposal(state)
        state["phase"] = "blocked"
        state["error"] = _under_18_message(screen)


def _is_plan_yes(reply):
    from record_confirmation import is_clear_yes
    from routines import plan_schedule

    return is_clear_yes(reply) or plan_schedule(reply) is not None


def _under_18_message(screen):
    text = " ".join(screen.reasons) if getattr(screen, "reasons", None) else (
        "There is no training plan for anyone under 18."
    )
    if "calorie" not in text.lower() or "protein" not in text.lower():
        text += " No calorie target and no protein target."
    return text


def _number(text):
    if text in (None, ""):
        return None
    match = re.search(r"\d+(?:\.\d+)?", str(text))
    if not match:
        return None
    value = float(match.group(0))
    return int(value) if value == int(value) else value


def _profile(state):
    answers = state["answers"]
    profile = {
        "days": list(answers.get("days") or _dates(answers.get("training_days") or 3)),
        "minutes": _number(answers.get("minutes")) or 45,
        "equipment": answers.get("equipment") or "bodyweight",
        "experience": answers.get("experience") or "beginner",
        "sport": answers.get("sport") or "general training",
        "injuries": answers.get("injuries") or "none",
        "goal": answers.get("goal") or "hold",
        "par_q": {
            key: value for key, value in state["par_q"].items() if isinstance(value, bool)
        },
    }
    sex = answers.get("sex")
    weight = _number(answers.get("weight"))
    age = _number(answers.get("age"))
    height = _number(answers.get("height"))
    if all(value not in (None, "") for value in (sex, weight, age, height)):
        profile["sex"] = sex
        profile["weight_kg"] = weight
        profile["age"] = age
        profile["height_cm"] = height
    if answers.get("injury_old") is True:
        profile["injury_old"] = True
    event = answers.get("event")
    if isinstance(event, dict):
        profile["event"] = {
            key: event[key] for key in ("name", "month", "date") if key in event
        }
    return profile


def _readiness_intake(state):
    answers = state["answers"]
    intake = {
        "par_q": {
            key: value for key, value in state["par_q"].items() if isinstance(value, bool)
        },
    }
    age = _number(answers.get("age"))
    if age is not None:
        intake["age"] = age
    if answers.get("sex"):
        intake["sex"] = answers["sex"]
    weight = _number(answers.get("weight"))
    if weight is not None:
        intake["weight_kg"] = weight
    height = _number(answers.get("height"))
    if height is not None:
        intake["height_cm"] = height
    return intake


def _check_in(state):
    """The symptom check uses the user's words. It does not invent a clear day."""
    from red_flag_check import RedFlagChecker

    reply = state.get("par_q_reply") or ""
    checker = RedFlagChecker()
    scanned = checker.scan_text(reply)
    if scanned.pause_plan:
        return scanned
    folded = _fold(reply)
    explicit_no = (
        folded in {"no", "none", "nope"}
        or bare_all_no(reply) is True
        or _safe_all_no(reply)
    )
    clear = (
        len(state["par_q"]) == len(PAR_Q)
        and all(value is False for value in state["par_q"].values())
    )
    if explicit_no and clear:
        answers = {aliases[0]: "no" for _flag, aliases in checker.CHECKLIST_GROUPS}
        return checker.scan_check_in({"symptom_checklist": answers, "notes": reply})
    return checker.scan_check_in({"notes": reply})


_PLAN_INPUT_KEYS = (
    "goal",
    "weight",
    "target",
    "height",
    "age",
    "sex",
    "days",
    "training_days",
    "minutes",
    "equipment",
    "experience",
    "sport",
    "injuries",
    "injury_old",
    "event",
)


def _freeze_input(value):
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze_input(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_input(item) for item in value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _plan_input_snapshot(state):
    """Plan inputs at the start of a reply. Name, food, and sources are not inputs."""
    answers = state.get("answers") if isinstance(state.get("answers"), dict) else {}
    snap = {key: _freeze_input(answers.get(key)) for key in _PLAN_INPUT_KEYS}
    par_q = state.get("par_q") if isinstance(state.get("par_q"), dict) else {}
    snap["par_q"] = tuple(
        (key, par_q.get(key) if isinstance(par_q.get(key), bool) else None)
        for key, _question in PAR_Q
    )
    return snap


def _plan_inputs_changed(state):
    """True when this reply edited the plan. Filling an open PAR-Q with all no is not an edit."""
    before = state.get("plan_inputs_before")
    if not isinstance(before, dict):
        return True
    after = _plan_input_snapshot(state)
    for key in _PLAN_INPUT_KEYS:
        if before.get(key) != after.get(key):
            return True
    if before.get("par_q") == after.get("par_q"):
        return False
    before_q = dict(before.get("par_q") or ())
    after_q = dict(after.get("par_q") or ())
    if any(value is True for value in before_q.values()):
        return True
    if any(value is not False for value in after_q.values()):
        return True
    return False


def _assumed_all_no(state):
    """A copy whose PAR-Q is all no. None when a yes is already stored."""
    par_q = state.get("par_q") if isinstance(state.get("par_q"), dict) else {}
    if any(par_q.get(key) is True for key, _question in PAR_Q):
        return None
    preview = dict(state)
    preview["par_q"] = {key: False for key, _question in PAR_Q}
    preview["par_q_reply"] = "all no"
    preview["par_q_unclear"] = False
    return preview


def _remember_shown_plan(state, preview=None):
    """Store the hash of the proposal the user is about to see."""
    digest = _shown_plan_hash(state if preview is None else preview)
    if digest:
        state["shown_plan_hash"] = digest
    else:
        state.pop("shown_plan_hash", None)
    return digest


def _show_proposal(state):
    text = _proposal(state)
    _remember_shown_plan(state)
    return text


def _optional_tracker_line(state):
    """One optional tracker line after a profile filled training. Not a new turn."""
    if state.get("tracker_offered"):
        return ""
    if not state.get("from_profile_payload"):
        return ""
    answers = state.get("answers") if isinstance(state.get("answers"), dict) else {}
    if "sources" in answers:
        return ""
    for key in ("training_days", "minutes", "equipment", "experience"):
        if answers.get(key) in (None, ""):
            return ""
    return _TRACKER_LINE


def _with_tracker_line(state, text):
    line = _optional_tracker_line(state)
    if not line:
        return text
    state["tracker_offered"] = True
    return text + "\n" + line


def _par_q_and_proposal(state, par_q_text):
    """The PAR-Q step shows the week once the rest of the profile is complete."""
    par_q_text = _with_tracker_line(state, par_q_text)
    preview = _assumed_all_no(state)
    if preview is not None and _remember_shown_plan(state, preview):
        return par_q_text + "\n" + _proposal(state)
    state.pop("shown_plan_hash", None)
    return par_q_text


def _confirm(state, reply, source="user"):
    from plan_builder import PlanBuilder
    from readiness_screen import ReadinessScreen, passing_readiness
    from record_confirmation import (
        ConfirmationRecorder,
        _mark_first_plan,
        _store_onboarding_record,
        hash_plan,
    )
    from red_flag_check import is_passing_check_in

    if not confirm_phase_active():
        state["error"] = _OUTSIDE_RUN_CHAT
        state["confirmed"] = False
        state["record"] = None
        return
    if hold_is_active():
        persist_active_hold()
        _adopt_hold(state)
        state["confirmed"] = False
        state["record"] = None
        return
    if state.get("cleared_follow_up") or state.get("safety_followup") or _read_safety():
        state["confirmed"] = False
        state["record"] = None
        return
    if _first_missing(state) is not None:
        return
    screen = ReadinessScreen().screen_intake(_readiness_intake(state))
    state["readiness"] = screen
    if not passing_readiness(screen):
        age = _number(state["answers"].get("age"))
        if age is not None and age < 18:
            state["error"] = _under_18_message(screen)
        else:
            state["error"] = " ".join(screen.reasons) or "Readiness has to pass before a plan is built."
        return
    check_in = _check_in(state)
    if not is_passing_check_in(check_in):
        state["error"] = check_in.message
        return
    built = PlanBuilder().propose(_profile(state), check_in, readiness_result=screen)
    if not built.get("ok"):
        state["error"] = built.get("message", "The week did not pass.")
        return
    # The yes has to match the week that was shown, and this reply cannot
    # have edited it. A mismatch shows that week again and waits.
    digest = hash_plan(built["confirm"])
    if _plan_inputs_changed(state) or state.get("shown_plan_hash") != digest:
        state["confirmed"] = False
        state["record"] = None
        state["error"] = None
        return
    confirm = _mark_first_plan(built["confirm"])
    record = ConfirmationRecorder().record(confirm, reply, source, check_in)
    if not record.confirmed:
        state["error"] = record.message
        return
    if not _store_onboarding_record(record, built["confirm"]):
        from seal_secret import DATA_FILE_MESSAGE

        state["error"] = DATA_FILE_MESSAGE
        state["confirmed"] = False
        state["record"] = None
        return
    saved = PlanBuilder().save(
        built["plan"],
        record,
        onboarding_week_path(),
        built["sessions"],
        check_in_result=check_in,
        readiness_result=screen,
    )
    if not saved.get("saved"):
        state["error"] = saved.get("message") or "The week could not be saved."
        state["confirmed"] = False
        state["record"] = None
        return
    from routines import first_checkin_day, start_daily_loop

    state["error"] = None
    state["record"] = record
    state["plan"] = built["plan"]
    state["sessions"] = built["sessions"]
    state["confirmed"] = True
    loop = start_daily_loop("yes" if source == "host_confirm" else reply)
    state["routines_on"] = loop["enabled"]
    state["times"] = loop["times"]
    days = _profile(state).get("days") or []
    if days:
        state["first_checkin"] = first_checkin_day(min(days), now=_now())
    clear_pending_profile()
    _clear_safety()


_MONTH_NAMES = (
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _event_phrase(event):
    if not isinstance(event, dict):
        return ""
    name = event.get("name")
    if not isinstance(name, str) or not name.strip():
        return ""
    month = event.get("month")
    if isinstance(month, int) and 1 <= month <= 12:
        return f"{name.strip()} in {_MONTH_NAMES[month]}"
    raw = event.get("date")
    if isinstance(raw, str) and raw.strip():
        return f"{name.strip()} on {raw.strip()}"
    return name.strip()


_SHORT_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_FULL_DAYS = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
)


def _lb_from_stored(weight):
    """Pounds from the stored kilogram figure, rounded to a whole number."""
    kg = _number(weight)
    if kg is None:
        return None
    return str(int(round(float(kg) / 0.45359237))) + " lb"


def _ft_in_from_stored(height):
    """Feet and inches from the stored centimeter figure."""
    cm = _number(height)
    if cm is None:
        return None
    total = float(cm) / 2.54
    feet = int(total // 12)
    inches = int(round(total - feet * 12))
    if inches == 12:
        feet += 1
        inches = 0
    return f"{feet} ft {inches} in"


def _proposal_profile(answers):
    """Weight, level, sport, and event. Blank fields are left out.

    Pounds and feet are the stored kg and cm, converted. A later weight edit
    changes the figure that is shown.
    """
    bits = []
    if answers.get("weight_units") == "lb":
        weight = _lb_from_stored(answers.get("weight"))
    else:
        stored = answers.get("weight")
        weight = stored.strip() if isinstance(stored, str) else ""
    if isinstance(weight, str) and weight.strip():
        bits.append(weight.strip())
    if answers.get("height_units") == "ft":
        height = _ft_in_from_stored(answers.get("height"))
        if isinstance(height, str) and height.strip():
            bits.append(height.strip())
    level = answers.get("experience")
    if isinstance(level, str) and level.strip():
        bits.append(level.strip())
    sport = answers.get("sport")
    if isinstance(sport, str) and sport.strip():
        bits.append(sport.strip())
    event = _event_phrase(answers.get("event"))
    if event:
        bits.append(event)
    if not bits:
        return ""
    return ", ".join(bits) + ". "


def _propose_preview(state):
    """The week the proposal shows. None when it cannot be built. Does not set an error."""
    from plan_builder import PlanBuilder
    from readiness_screen import ReadinessScreen, passing_readiness
    from red_flag_check import is_passing_check_in

    preview = _assumed_all_no(state)
    source = preview if preview is not None else state
    screen = ReadinessScreen().screen_intake(_readiness_intake(source))
    if not passing_readiness(screen):
        return None
    check_in = _check_in(source)
    if not is_passing_check_in(check_in):
        return None
    built = PlanBuilder().propose(_profile(source), check_in, readiness_result=screen)
    if not isinstance(built, dict) or not built.get("ok"):
        return None
    return built


def _shown_plan_hash(state):
    """Hash of the unmarked week this profile would confirm. None when it cannot be built."""
    from record_confirmation import hash_plan

    built = _propose_preview(state)
    if built is None:
        return None
    return hash_plan(built["confirm"])


def _session_line(row):
    if not isinstance(row, dict):
        return ""
    raw = row.get("date")
    try:
        label = _SHORT_DAYS[date.fromisoformat(str(raw)[:10]).weekday()]
    except (TypeError, ValueError):
        label = "Day"
    name = row.get("name") if isinstance(row.get("name"), str) and row.get("name").strip() else "Session"
    exercises = row.get("exercises") if isinstance(row.get("exercises"), list) else []
    if name in {"Easy run", "Long run"} and exercises and isinstance(exercises[0], dict):
        reps = exercises[0].get("reps") or ""
        detail = str(reps).strip()
        return f"{label} {name}: {detail}." if detail else f"{label} {name}."
    names = []
    for item in exercises:
        if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip():
            names.append(item["name"].strip())
    if names:
        return f"{label} {name}: {', '.join(names)}."
    return f"{label} {name}."


def _week_block(built):
    if not isinstance(built, dict):
        return ""
    lines = [_session_line(row) for row in built.get("sessions") or []]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def _nutrition_line(built):
    plan = built.get("plan") if isinstance(built, dict) else None
    nutrition = plan.get("nutrition") if isinstance(plan, dict) else None
    if not isinstance(nutrition, dict):
        return ""
    calories = nutrition.get("calories")
    protein = nutrition.get("protein_g")
    if calories in (None, "") or protein in (None, ""):
        return ""
    return f"Daily: {calories} kcal, {protein} g protein. "


def _picked_days_line(answers):
    if answers.get("days_named"):
        return ""
    names = []
    for item in answers.get("days") or []:
        try:
            names.append(_FULL_DAYS[date.fromisoformat(str(item)[:10]).weekday()])
        except (TypeError, ValueError):
            continue
    if not names:
        return ""
    if len(names) == 1:
        listed = names[0]
    elif len(names) == 2:
        listed = f"{names[0]} and {names[1]}"
    else:
        listed = ", ".join(names[:-1]) + ", and " + names[-1]
    return f"I picked {listed}. You can change them. "


def _proposal(state):
    answers = state["answers"]
    days = answers.get("training_days", "3")
    minutes = answers.get("minutes", "45")
    goal = answers.get("goal", "hold")
    equipment = answers.get("equipment", "bodyweight")
    scheduled = answers.get("days") or []
    start = f"The first session is {min(scheduled)}. " if scheduled else ""
    injury = _injury_clause(answers.get("injuries"), old=answers.get("injury_old") is True)
    age = _number(answers.get("age"))
    lead = f"Plan for age {age}. " if age is not None else ""
    from plan_builder import running_week

    sport_line = ""
    if running_week(_profile(state)):
        sport_line = "The week includes strength and running: easy runs and a long run. "
    built = _propose_preview(state)
    week = _week_block(built)
    food = _nutrition_line(built)
    return (
        f"{lead}"
        f"{_proposal_profile(answers)}"
        f"{days} days, {minutes} min, {goal}, {equipment}. "
        f"{_picked_days_line(answers)}"
        f"{week}"
        f"{food}"
        f"{start}"
        f"{injury}"
        f"{sport_line}"
        "One yes confirms the plan and starts the morning check-in at 07:00, "
        "the evening follow-up at 20:00, and the weekly review Sunday at 18:00. "
        "Routines, each is opt-in. "
        "One example: yes, morning 6:30."
    )


def _unclear_par_q(state):
    from readiness_screen import ReadinessScreen

    known = {key: value for key, value in state["par_q"].items() if isinstance(value, bool)}
    state["readiness"] = ReadinessScreen().check_par_q(known)
    missing = [
        key.replace("_", " ")
        for key, _question in PAR_Q
        if not isinstance(state["par_q"].get(key), bool)
    ]
    return "Still need a yes or no: " + ", ".join(missing) + "."


def pending_profile_path():
    """Draft answers during intake. Removed once the plan is confirmed."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pending_profile.json")


def onboarding_week_path():
    """The confirmed week written by run_chat. Not a second confirm path."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "week.json")


def clear_pending_profile(path=None):
    """Delete the draft. The profile memory and the saved week keep the answers.

    This is an onboarding confirm step. A direct call outside run_chat does nothing.
    """
    if not confirm_phase_active():
        return False
    target = pending_profile_path() if path is None else path
    if os.path.isfile(target):
        os.remove(target)
        return True
    return False


def _confirmed_line(state):
    times = state.get("times") or {}
    enabled = state.get("routines_on") or []
    parts = []
    if "daily_checkin" in enabled:
        parts.append(f"morning at {times.get('daily_checkin', '07:00')}")
    if "evening_followup" in enabled:
        parts.append(f"evening at {times.get('evening_followup', '20:00')}")
    if "weekly_review" in enabled:
        parts.append(f"weekly {times.get('weekly_review', 'Sun 18:00')}")
    note = state.get("confirm_note")
    extra = note.strip() if isinstance(note, str) and note.strip() else ""
    if not parts:
        line = "Confirmed."
    else:
        listed = ", ".join(parts)
        line = "Confirmed. " + listed[0].upper() + listed[1:] + "."
    if extra:
        line = f"{line} {extra}"
    ignored = state.get("routine_time_note")
    if isinstance(ignored, str) and ignored.strip():
        line = f"{line} {ignored.strip()}"
    return line


def speak(state):
    """The next bot reply. The first one is question 1 when nothing is known."""
    from seal_secret import DATA_FILE_MESSAGE

    state.pop("skip_body_from_text", None)

    if hold_is_active() and state.get("phase") != "symptom":
        _adopt_hold(state)
    error = state.get("error")
    if isinstance(error, str) and DATA_FILE_MESSAGE in error:
        return DATA_FILE_MESSAGE
    if state["confirmed"]:
        return _confirmed_line(state)
    error = state.get("error")
    if isinstance(error, str) and error:
        return error
    held = state.get("phase")
    if held == "age":
        state["error"] = _AGE_ASK
        return _AGE_ASK
    if held == "symptom":
        message = state.get("hold_message") or _AGE_ASK
        state["error"] = message
        return message
    if held == "blocked":
        _apply_age_readiness(state)
        state["phase"] = "blocked"
        _clear_proposal(state)
        if state.get("error"):
            return state["error"]
        state["error"] = _AGE_ASK
        return _AGE_ASK
    if state.get("from_profile_payload"):
        gaps = _payload_gaps(state)
        if gaps:
            if gaps == ["age"]:
                state["phase"] = "age"
                state["need_age"] = True
                state["asked"] = "goal"
                state["error"] = _AGE_ASK
                return _AGE_ASK
            state["phase"] = "intake"
            goal_keys = {"goal", "weight", "height", "age", "sex"}
            state["asked"] = "goal" if any(key in goal_keys for key in gaps) else "training"
            return _combined_profile_ask(gaps)
    missing = _first_missing(state)
    if missing is None and state.get("checks_again"):
        _apply_age_readiness(state)
        if state.get("error"):
            state["phase"] = "blocked"
            _clear_proposal(state)
            return state["error"]
        from red_flag_check import is_passing_check_in

        check_in = _check_in(state)
        if not is_passing_check_in(check_in):
            state["phase"] = "intake"
            state["asked"] = "par_q"
            state["error"] = check_in.message
            return check_in.message
        state["checks_again"] = False
    missing = _first_missing(state)
    if missing is not None:
        if missing["id"] == "goal" and _missing_keys(state, missing) == ["age"]:
            state["phase"] = "age"
            state["need_age"] = True
            state["asked"] = "goal"
            state["error"] = _AGE_ASK
            return _AGE_ASK
        state["phase"] = "intake"
        state["asked"] = missing["id"]
        if missing["id"] == "training" and _missing_keys(state, missing) == ["injuries"]:
            if _missing_keys(state, _group("par_q")):
                state["asked"] = "par_q"
            return _injury_and_par_q(state)
        if missing["id"] == "par_q" and (
            state["par_q"] or state.get("par_q_skipped") or state.get("par_q_unclear")
        ):
            return _unclear_par_q(state)
        if missing["id"] == "par_q":
            return _par_q_and_proposal(state, missing["text"])
        return missing["text"]
    state["phase"] = "confirm"
    state["asked"] = None
    return _show_proposal(state)


def _state_for_attempt():
    """The attempt a new conversation starts from.

    An active hold, including a bad hold file, stays closed. A hold whose
    date is already a previous local day reopens on the red-flag check.
    The file is not removed.
    """
    kind, saved = _read_hold_file()
    if kind == "active":
        state = _blank()
        _adopt_hold(state)
        return state
    answers = {}
    if isinstance(saved, dict) and isinstance(saved.get("answers"), dict):
        answers = saved["answers"]
    if kind == "expired" and saved.get("checks_again") and answers:
        state = _blank()
        state["answers"] = answers
        state["par_q"] = {}
        state["phase"] = "intake"
        state["asked"] = "par_q"
        state["checks_again"] = True
        state["readiness"] = None
        state["par_q_reply"] = ""
        state["confirmed"] = False
        state["record"] = None
        return state
    return _blank()


def open_chat():
    """Same start as run_chat, before any reply. The bot calls run_chat."""
    state = _state_for_attempt()
    return state, speak(state)


def _host_reply(reply):
    """A string, an int age, (text, labels), or {text, labels, age, profile, confirm}."""
    if isinstance(reply, bool):
        return "", None, None, None, None
    if isinstance(reply, int):
        return str(reply), None, reply, None, None
    if isinstance(reply, tuple) and len(reply) == 2:
        text, labels = reply
        return text if isinstance(text, str) else "", labels, None, None, None
    if isinstance(reply, dict) and "text" in reply:
        age = reply.get("age")
        if isinstance(age, bool):
            age = None
        profile = reply.get("profile") if isinstance(reply.get("profile"), dict) else None
        confirm = reply.get("confirm") if isinstance(reply.get("confirm"), dict) else None
        return reply.get("text") or "", reply.get("labels"), age, profile, confirm
    if isinstance(reply, str):
        return reply, None, None, None, None
    return "", None, None, None, None


def run_chat(replies):
    """The onboarding entry. A hold dated today is checked before any reply.

    Confirm helpers run only while this loop is on a confirm-phase reply.
    An int at the age step is submit_age. A tuple is (text, labels).
    Labels are never parsed out of the text.
    A follow-up or an age check from an earlier attempt is not this attempt.
    A hold still is. Inside this attempt the pending file blocks confirm.
    """
    if not hold_is_active():
        pending = _read_safety()
        if isinstance(pending, dict) and pending.get("kind") in {"follow_up", "age_check"}:
            _clear_safety()
    state = _state_for_attempt()
    bots = []
    for reply in replies:
        text, labels, age, profile, confirm = _host_reply(reply)
        state["plan_inputs_before"] = _plan_input_snapshot(state)
        token = None
        if state.get("phase") == "confirm":
            token = _CONFIRM_PHASE.set(True)
        try:
            host_age = age if isinstance(age, int) and not isinstance(age, bool) else None
            if (
                host_age is None
                and labels is None
                and state.get("phase") in {"age", "blocked"}
                and re.fullmatch(r"[0-9]{1,3}", text.strip())
            ):
                host_age = int(text.strip())
            pending = _read_safety()
            follow_up = state.get("safety_followup") or (
                isinstance(pending, dict) and pending.get("kind") == "follow_up"
            )
            if (
                host_age is not None
                and state.get("phase") in {"age", "blocked"}
                and labels is None
                and not follow_up
                and not hard_stop(text)
            ):
                submit_age(state, host_age)
                if isinstance(profile, dict) and state.get("phase") != "symptom":
                    _merge_profile_payload(state, profile)
            elif (
                state.get("asked") == "par_q"
                and labels is None
                and not follow_up
                and not hard_stop(text)
                and _par_q_all_no_button(text)
            ):
                submit_par_q(state, "all_no")
                if isinstance(profile, dict):
                    _merge_profile_payload(state, profile)
            else:
                apply_reply(state, text, labels, profile)
            token = _apply_structured_confirm(state, confirm, token, text)
            bots.append(speak(state))
        finally:
            if token is not None:
                _CONFIRM_PHASE.reset(token)
        if state["confirmed"]:
            break
    state["turns"] = len(bots)
    return state, bots


def happy_path_turns():
    """Bot turns from hello to a confirmed plan on the short path."""
    state, _bots = run_chat(HAPPY_PATH)
    return state["turns"] if state["confirmed"] else None
