#!/usr/bin/env python3
"""Grouped onboarding. A few short messages, then one yes."""

from datetime import datetime, timedelta, timezone
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
    "injuries": "none",
    "sources": "none",
}
_OPTIONAL = {"name", "food_style", "sources", "target"}
_ACCEPT = {"ok", "okay", "yep", "yeah", "defaults", "default", "sounds good", "do it", "lets go"}
_WEEK_OFFSETS = (0, 2, 4, 5, 1, 3, 6)
_SETUP_WORDS = ("clone", "pip", "pytest", "release_check", "install", "git ")

HAPPY_PATH = (
    "hello",
    "hold, male, age 30, 80 kg, 180 cm",
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
            "One word ok uses general training, 3 days, 45 min, bodyweight, beginner, no injuries. "
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
    """The first thing the bot says. No setup in front of it."""
    return GROUPS[0]["text"]


def _fold(reply):
    if not isinstance(reply, str):
        return ""
    text = reply.strip().lower().replace("'", "")
    cleaned = []
    for char in text:
        cleaned.append(char if char.isalnum() or char.isspace() else " ")
    return " ".join("".join(cleaned).split())


def _dates(count):
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    count = max(1, min(7, int(count)))
    return [(monday + timedelta(days=_WEEK_OFFSETS[index])).isoformat() for index in range(count)]


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
    return False


def _asks_instead(text):
    """A question mark or a sad or doubtful face is unclear before punctuation is removed."""
    return "?" in text or "？" in text or _SAD_FACE.search(text) is not None


def bare_all_no(text):
    """True only when the whole reply is an all-no phrase.

    Fillers, a thumb emoji, punctuation, and whitespace may sit beside it.
    A question mark, a full-width question mark, or a sad or doubtful face
    such as ':(' or ':-(' is unclear even when the words underneath are
    an all-no phrase.
    None means this is not an all-no reply. False means the reply tried to
    say all no and also said something else, so nothing is stored as no.
    """
    if not isinstance(text, str):
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
    kind = bare_all_no(text)
    if kind is True:
        return "all_no", {key: False for key, _question in PAR_Q}
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
    for goal in ("cut", "lose", "gain", "hold"):
        if re.search(rf"\b{goal}\b", folded):
            answers["goal"] = goal
            break
    age = re.search(r"\bage\s+(\d{1,3})\b", folded)
    if not age:
        age = re.search(r"\b(?:im|i am)\s+actually\s+(\d{1,3})\b", folded)
    if age:
        answers["age"] = age.group(1)
    height = re.search(r"\b(\d{2,3})\s*cm\b", folded)
    if height:
        answers["height"] = height.group(1) + " cm"
    target = re.search(r"\btarget\s+(\d+(?:\.\d+)?)\s*kg\b", folded)
    if target:
        answers["target"] = target.group(1) + " kg"
    weight = re.search(r"\b(\d+(?:\.\d+)?)\s*kg\b", folded)
    if weight and "weight" not in answers:
        answers["weight"] = weight.group(1) + " kg"
    if re.search(r"\b(female|woman)\b", folded):
        answers["sex"] = "female"
    elif re.search(r"\b(male|man)\b", folded):
        answers["sex"] = "male"
    days = re.search(r"\b([1-7])\s+days?\b", folded)
    if days:
        answers["training_days"] = days.group(1)
        answers["days"] = _dates(days.group(1))
    minutes = re.search(r"\b(\d{2,3})\s+min\b", folded)
    if minutes:
        answers["minutes"] = minutes.group(1)
    for equipment in ("full gym", "bodyweight", "dumbbells", "barbell", "none"):
        if equipment in folded:
            answers["equipment"] = equipment
            break
    for experience in ("beginner", "intermediate", "advanced"):
        if re.search(rf"\b{experience}\b", folded):
            answers["experience"] = experience
            break
    if "no injuries" in folded or "injuries none" in folded:
        answers["injuries"] = "none"
    if "general training" in folded:
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


def apply_reply(state, reply):
    folded = _fold(reply)
    if state["phase"] == "confirm" and _is_plan_yes(reply):
        _confirm(state, reply)
        return
    if folded == "skip":
        _remember_skip(state)
        return
    if folded in _ACCEPT and state.get("asked") in {"goal", "training"}:
        _fill_group(state, state["asked"])
        return
    _parse_explicit(state, reply)
    if state["phase"] == "confirm":
        _review_confirm_edit(state, reply)


def _review_confirm_edit(state, reply):
    """A confirm-step reply that is not a yes still updates the profile."""
    from record_confirmation import reply_pause

    paused = reply_pause(reply)
    if paused is not None:
        state["confirmed"] = False
        state["error"] = paused.message
        return
    age = _number(state["answers"].get("age"))
    if age is not None and age < 18:
        from readiness_screen import ReadinessScreen

        screen = ReadinessScreen().screen_intake(_readiness_intake(state))
        state["readiness"] = screen
        state["confirmed"] = False
        state["record"] = None
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
    explicit_no = folded in {"no", "none", "nope"} or bare_all_no(reply) is True
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
    from record_confirmation import ConfirmationRecorder
    from red_flag_check import is_passing_check_in

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
    record = ConfirmationRecorder().record(built["confirm"], reply, "user", check_in)
    if not record.confirmed:
        state["error"] = record.message
        return
    from routines import first_checkin_day, start_daily_loop

    state["error"] = None
    state["record"] = record
    state["confirmed"] = True
    loop = start_daily_loop(reply)
    state["routines_on"] = loop["enabled"]
    state["times"] = loop["times"]
    days = _profile(state).get("days") or []
    if days:
        state["first_checkin"] = first_checkin_day(min(days))
    clear_pending_profile()


def _proposal(state):
    answers = state["answers"]
    days = answers.get("training_days", "3")
    minutes = answers.get("minutes", "45")
    goal = answers.get("goal", "hold")
    equipment = answers.get("equipment", "bodyweight")
    return (
        f"{days} days, {minutes} min, {goal}, {equipment}. "
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


def clear_pending_profile(path=None):
    """Delete the draft. The profile memory and the saved week keep the answers."""
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

    error = state.get("error")
    if isinstance(error, str) and DATA_FILE_MESSAGE in error:
        return DATA_FILE_MESSAGE
    if state["confirmed"]:
        return _confirmed_line(state)
    error = state.get("error")
    if isinstance(error, str) and error:
        return error
    missing = _first_missing(state)
    if missing is not None:
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


def run_chat(replies):
    """Bot replies for these user messages, through the confirmed plan."""
    state = _blank()
    bots = []
    for reply in replies:
        apply_reply(state, reply)
        bots.append(speak(state))
        if state["confirmed"]:
            break
    state["turns"] = len(bots)
    return state, bots


def happy_path_turns():
    """Bot turns from hello to a confirmed plan on the short path."""
    state, _bots = run_chat(HAPPY_PATH)
    return state["turns"] if state["confirmed"] else None
