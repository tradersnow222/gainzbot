#!/usr/bin/env python3
"""Grouped onboarding. A few short messages, then one yes."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import contextvars
import json
import os
import re
import unicodedata


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

HAPPY_PATH = (
    "hello",
    "hold, male, age 30, 80 kg, 180 cm, no injuries",
    "30",
    "ok",
    "all no",
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


def _current_weight(text):
    """A current body weight in kg or lb. 'ask' means the number is out of range."""
    cleaned = _without_target_clause(text)
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


def _weight_kg_in(text):
    cleaned = re.sub(
        r"\b\d+(?:\.\d+)?\s+to\s+\d+(?:\.\d+)?\s*(?:kg|lb|lbs|pounds?)\b",
        " ",
        text,
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
        return "ask"
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
    """'all no..' is not a single final . ! or ?. A smile such as :) stays."""
    if not isinstance(text, str):
        return False
    run = 0
    for char in reversed(text.rstrip()):
        if char.isspace():
            break
        if char in ".!?":
            run += 1
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


def _parse_explicit(state, reply):
    answers = state["answers"]
    folded = _fold(reply)
    status, parsed = read_par_q(reply)
    if status == "unclear":
        _store_par_q(state, parsed, True)
        state["par_q_reply"] = reply if isinstance(reply, str) else folded
    elif status == "all_no":
        _store_par_q(state, parsed, False)
        state["par_q_reply"] = reply if isinstance(reply, str) else folded
    elif parsed:
        state["par_q_unclear"] = False
        _store_par_q(state, parsed, False)
        state["par_q_reply"] = reply if isinstance(reply, str) else folded
    if re.search(r"\b(?:lose\s+fat|lose\s+weight|fat\s+loss|cut)\b", folded):
        answers["goal"] = "cut"
    else:
        for goal in ("cut", "lose", "gain", "hold"):
            if re.search(rf"\b{goal}\b", folded):
                answers["goal"] = goal
                break
    height = re.search(r"\b(\d{2,3})\s*cm\b", folded)
    if height:
        answers["height"] = height.group(1) + " cm"
    soft = _soft(reply)
    target = _target_from_want(soft)
    need_weight = False
    if isinstance(target, tuple) and target[0] == "need_weight":
        answers["target"] = target[1]
        need_weight = True
    elif target == "ask" and state.get("phase") != "age":
        state["awaiting"] = "target"
        if state.get("error") in (None, ""):
            state["error"] = _TARGET_ASK
    elif target is not None:
        answers["target"] = target
        if state.get("awaiting") == "target":
            state["awaiting"] = None
    weight = _current_weight(soft)
    if weight == "ask":
        state["error"] = _WEIGHT_ASK
        if target is not None:
            answers.pop("target", None)
            if state.get("awaiting") == "target":
                state["awaiting"] = None
    elif weight is not None and "weight" not in answers:
        answers["weight"] = weight
        need_weight = False
    if need_weight and "weight" not in answers and state.get("phase") != "age":
        state["awaiting"] = "weight"
        state["error"] = _WEIGHT_ASK
    if re.search(r"\b(female|woman)\b", folded):
        answers["sex"] = "female"
    elif re.search(r"\b(male|man)\b", folded):
        answers["sex"] = "male"
    named_days = _training_weekdays(folded)
    days = re.search(r"\b([1-7])\s+days?\b", folded)
    if days:
        answers["training_days"] = days.group(1)
        answers["days"] = _dates(days.group(1), named_days or None)
    elif named_days:
        answers["training_days"] = str(len(named_days))
        answers["days"] = _dates(len(named_days), named_days)
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
    stated = _stated_injury(folded)
    if stated == "none":
        if "injuries" not in answers:
            answers["injuries"] = "none"
    elif stated is not None and answers.get("injuries") in (None, "", "none"):
        answers["injuries"] = stated
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
    r"|\b\d{1,2}\s*(?:am|pm)\b"
    r"|\bat\s+(?:[1-9]|1[0-2])\b",
    re.IGNORECASE,
)


def _mask_clocks(reply):
    """Drop a parsed routine time so its digits are not an age hint."""
    if not isinstance(reply, str):
        return ""
    return _CLOCK.sub(lambda match: re.sub(r"\d", " ", match.group(0)), reply)


_AGE_ASK = "How old are you? Please type the number."
_WEIGHT_ASK = "That weight looks off. What's your weight in kg?"
_TARGET_ASK = "What's your target weight in kg?"
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
    "sessions", "am", "pm", "%",
})


def _minor_tokens(reply):
    """Words for a minor-age scan. A clock such as 6:15 is not one of them."""
    if not isinstance(reply, str):
        return []
    text = reply.strip().lower().replace("'", "").replace("\u2019", "")
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


def _minor_cue(reply):
    """A later reply that says the person is under 18. It does not store the number.

    A number from 1 to 17, or a word from one to seventeen, clears the age
    unless the next word is a unit or the number is inside a clock time.
    """
    folded = _fold(reply) if isinstance(reply, str) else ""
    if re.search(r"\bminor\b", folded):
        return True
    if re.search(r"\bunder\s+18\b", folded):
        return True
    if re.search(r"\bnot\s+18\s+yet\b", folded):
        return True
    if re.search(r"\b(?:im|i am)\s+only\s+\d{1,3}\b", folded):
        return True
    tokens = _minor_tokens(reply)
    for index, token in enumerate(tokens):
        if _minor_value(token) is None:
            continue
        nxt = tokens[index + 1] if index + 1 < len(tokens) else ""
        if nxt in _MINOR_UNITS:
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
        nxt = tokens[index + 1] if index + 1 < len(tokens) else ""
        if nxt in _MINOR_UNITS:
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
    if re.search(r"\bage\b", folded) and re.search(r"\b\d{1,3}\b", folded):
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


def _take_age_number(state, reply):
    """Readiness runs on the typed number. Leftover text is not an age."""
    _clear_proposal(state)
    number = _reply_age(reply)
    if number is None or not 1 <= number <= 120:
        state["phase"] = "age"
        state["awaiting"] = None
        state["need_age"] = True
        state["error"] = _AGE_ASK
        return True
    state["answers"]["age"] = str(number)
    state["awaiting"] = None
    state["need_age"] = False
    _apply_age_readiness(state)
    if state.get("error"):
        if number < 18 or _first_missing(state) is None:
            state["phase"] = "blocked"
            return True
        state["error"] = None
        state["readiness"] = None
        state["phase"] = "intake"
        return True
    state["hold_message"] = None
    state["phase"] = "confirm"
    return True


def _take_target_number(state, reply):
    """The reply after a target ask. A days or minutes phrase is not a weight."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(?:\s*kg)?", _soft(reply))
    if match is None or not _kg_in_range(float(match.group(1))):
        state["awaiting"] = "target"
        state["error"] = _TARGET_ASK
        return
    shown = match.group(1)
    if shown.endswith(".0"):
        shown = shown[:-2]
    state["answers"]["target"] = shown + " kg"
    state["awaiting"] = None
    state["error"] = None


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


# A past injury can skip the hold. 'healed' and a bare 'achilles' cannot.
_STRUCTURAL_PHRASES = (
    "old sprained ankle",
    "torn rotator cuff",
    "sprained ankle",
    "pulled hamstring",
    "shin splints",
    "shin splint",
    "slipped disc",
    "groin strain",
    "calf tear",
    "torn acl",
)
_ACUTE_MARKER = re.compile(
    r"\bpop(?:ped)?\b"
    r"|\bsnap(?:ped)?\b"
    r"|\bswell(?:ing|ed)?\b|\bswollen\b"
    r"|\b(?:cant|cannot|can\s+not)\s+(?:walk|bear\s+weight|put\s+(?:any\s+)?weight)\b"
    r"|\bgave\s+out\b|\bgiving\s+way\b"
    r"|\bsharp\s+pain\b"
    r"|\bnumb(?:ness)?\b"
    r"|\btingling\b"
    r"|\blocked\b"
    r"|\bdeformed\b"
    r"|\bbruised\s+badly\b"
    r"|\btoday\b|\btonight\b|\byesterday\b|\bjust\b"
    r"|\bthis\s+morning\b|\bthis\s+week\b"
    r"|\ban\s+hour\s+ago\b|\blast\s+night\b"
)


def _structural_remainder(reply):
    """The reply with each matched structural phrase removed.

    False means none of those phrases were present.
    """
    if not isinstance(reply, str):
        return False, ""
    text = reply
    matched = False
    for phrase in _STRUCTURAL_PHRASES:
        pattern = re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE)
        if pattern.search(text):
            matched = True
            text = pattern.sub(" ", text)
    return matched, text


def _acute_marker(reply):
    folded = _fold(reply) if isinstance(reply, str) else ""
    return _ACUTE_MARKER.search(folded) is not None


def _pain_happening_now(folded):
    if re.search(r"\b(?:new|worsen\w+)\b", folded) and re.search(r"\bpain\b", folded):
        return True
    if re.search(r"\bright\s+now\b", folded) and re.search(r"\bpain\b", folded):
        return True
    return False


def _symptom_hold(reply):
    """Scan first. Hold a current symptom.

    A structural phrase skips the hold only when the rest of the message
    does not pause and the message has no acute marker. Healed and a bare
    achilles are not structural phrases.
    """
    from record_confirmation import reply_pause

    paused = reply_pause(reply)
    folded = _fold(reply) if isinstance(reply, str) else ""
    if isinstance(reply, str) and (_HEAD_EMOJI in reply or re.search(r"\bhead\b", folded)):
        return paused if paused is not None else reply_pause(_HEAD_EMOJI)
    if _pain_happening_now(folded):
        if paused is not None:
            return paused
        from types import SimpleNamespace
        return SimpleNamespace(
            message="Plan paused. Rest today. Come back tomorrow, or after you see a doctor."
        )
    if paused is None:
        return None
    matched, rest = _structural_remainder(reply)
    if matched and reply_pause(rest) is None and not _acute_marker(reply):
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


def _ask_which_area(state):
    _clear_proposal(state)
    state["phase"] = "intake"
    state["awaiting"] = "injury"
    state["confirmed"] = False
    state["record"] = None
    state["error"] = _INJURY_ASK


def _take_injury_answer(state, reply):
    if _leg_emoji_only(reply):
        state["error"] = _INJURY_ASK
        state["awaiting"] = "injury"
        return
    stated = _stated_injury(_fold(reply))
    if stated is None:
        state["error"] = _INJURY_ASK
        state["awaiting"] = "injury"
        return
    state["answers"]["injuries"] = stated
    state["awaiting"] = None
    state["error"] = None


def _injury_clause(injuries):
    """One plain sentence. An explicit no does not add it."""
    if not isinstance(injuries, str):
        return ""
    text = injuries.strip()
    if text.lower() in {"", "none", "no", "n/a", "na", "nope"}:
        return ""
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if len(parts) <= 1:
        area = parts[0] if parts else text
    elif len(parts) == 2:
        area = f"{parts[0]} and {parts[1]}"
    else:
        area = ", ".join(parts[:-1]) + ", and " + parts[-1]
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


def apply_reply(state, reply):
    state["error"] = None
    if hold_is_active():
        _adopt_hold(state)
        _handle_symptom(state, reply)
        return
    paused = _symptom_hold(reply)
    if paused is not None:
        _hold_symptom(state, reply, paused)
        return
    if _leg_emoji_only(reply):
        _ask_which_area(state)
        return
    phase = state.get("phase")
    if phase == "symptom":
        _handle_symptom(state, reply)
        return
    if phase == "age":
        if _age_correction(reply) and _reply_age(reply) is None:
            _clear_age(state)
            state["phase"] = "age"
            state["awaiting"] = None
            state["error"] = _AGE_ASK
            return
        _handle_age(state, reply)
        return
    if phase == "blocked":
        _handle_blocked(state, reply)
        return
    if state.get("awaiting") == "injury":
        _take_injury_answer(state, reply)
        return
    folded = _fold(reply)
    if phase == "confirm" and _handle_confirm(state, reply):
        return
    if state.get("awaiting") == "target":
        _take_target_number(state, reply)
        return
    if folded == "skip":
        _remember_skip(state)
        return
    if folded in _ACCEPT and state.get("asked") in {"goal", "training"}:
        _fill_group(state, state["asked"])
        return
    _parse_explicit(state, reply)
    if _note_age_correction(state, reply):
        return
    if state["phase"] == "confirm":
        _review_confirm_edit(state, reply)


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


def _handle_age(state, reply):
    """A typed number runs readiness. A yes stays here and does not confirm."""
    from record_confirmation import reply_pause

    _clear_proposal(state)
    paused = reply_pause(reply)
    if paused is not None:
        return _hold_symptom(state, reply, paused)
    return _take_age_number(state, reply)


def _handle_blocked(state, reply):
    """Under 18, or readiness failed. A yes repeats that refusal."""
    from record_confirmation import reply_pause

    _clear_proposal(state)
    paused = reply_pause(reply)
    if paused is not None:
        return _hold_symptom(state, reply, paused)
    if _reply_age(reply) is not None:
        return _take_age_number(state, reply)
    _apply_age_readiness(state)
    state["phase"] = "blocked"
    _clear_proposal(state)
    return True


def _handle_confirm(state, reply):
    """Confirm only when the whole reply is a plan-yes.

    Anything else is an edit. A clear weight or profile edit updates the
    profile and the proposal is shown again. A symptom ends onboarding for
    the day. An age hint asks for a typed age, and readiness runs on that
    number before the plan is shown again.
    """
    from record_confirmation import reply_pause

    paused = reply_pause(reply)
    if paused is not None:
        return _hold_symptom(state, reply, paused)
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
    if _age_correction(reply):
        _clear_age(state)
        return _hold_age(state)
    if _counted_training(reply):
        state["error"] = None
        state["phase"] = "confirm"
        return True
    return _hold_age(state)


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
    from record_confirmation import reply_pause

    paused = reply_pause(reply)
    if paused is not None:
        _hold_symptom(state, reply, paused)
        return
    age = _number(state["answers"].get("age"))
    if age is not None and age < 18:
        from readiness_screen import ReadinessScreen

        screen = ReadinessScreen().screen_intake(_readiness_intake(state))
        state["readiness"] = screen
        _clear_proposal(state)
        state["phase"] = "blocked"
        state["error"] = _under_18_message(screen)


def _is_plan_yes(reply):
    from record_confirmation import is_clear_yes, reply_pause
    from routines import plan_schedule

    if reply_pause(reply) is not None:
        return False
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


def _confirm(state, reply):
    from plan_builder import PlanBuilder
    from readiness_screen import ReadinessScreen, passing_readiness
    from record_confirmation import ConfirmationRecorder, _mark_first_plan, _store_onboarding_record
    from red_flag_check import is_passing_check_in

    if not confirm_phase_active():
        state["error"] = _OUTSIDE_RUN_CHAT
        state["confirmed"] = False
        state["record"] = None
        return
    if hold_is_active():
        _adopt_hold(state)
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
    confirm = _mark_first_plan(built["confirm"])
    record = ConfirmationRecorder().record(confirm, reply, "user", check_in)
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
    loop = start_daily_loop(reply)
    state["routines_on"] = loop["enabled"]
    state["times"] = loop["times"]
    days = _profile(state).get("days") or []
    if days:
        state["first_checkin"] = first_checkin_day(min(days), now=_now())
    clear_pending_profile()


def _proposal(state):
    answers = state["answers"]
    days = answers.get("training_days", "3")
    minutes = answers.get("minutes", "45")
    goal = answers.get("goal", "hold")
    equipment = answers.get("equipment", "bodyweight")
    scheduled = answers.get("days") or []
    start = f"The first session is {min(scheduled)}. " if scheduled else ""
    injury = _injury_clause(answers.get("injuries"))
    return (
        f"{days} days, {minutes} min, {goal}, {equipment}. "
        f"{start}"
        f"{injury}"
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
    if not parts:
        return "Confirmed."
    line = ", ".join(parts)
    return "Confirmed. " + line[0].upper() + line[1:] + "."


def speak(state):
    """The next bot reply. The first one is question 1 when nothing is known."""
    from seal_secret import DATA_FILE_MESSAGE

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
        if missing["id"] == "par_q" and (
            state["par_q"] or state.get("par_q_skipped") or state.get("par_q_unclear")
        ):
            return _unclear_par_q(state)
        return missing["text"]
    state["phase"] = "confirm"
    state["asked"] = None
    return _proposal(state)


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


def run_chat(replies):
    """The onboarding entry. A hold dated today is checked before any reply.

    Confirm helpers run only while this loop is on a confirm-phase reply.
    If a reply leaves a field blank, the next line asks for that field.
    """
    state = _state_for_attempt()
    bots = []
    for reply in replies:
        token = None
        if state.get("phase") == "confirm":
            token = _CONFIRM_PHASE.set(True)
        try:
            apply_reply(state, reply)
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
