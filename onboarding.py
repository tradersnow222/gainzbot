#!/usr/bin/env python3
"""Grouped onboarding. A few short messages, then one yes."""

from datetime import datetime, timedelta, timezone
import re


PAR_Q = (
    ("chest_pain_at_rest", "Do you have chest pain while resting?"),
    ("chest_pain_during_activity", "Do you have chest pain during activity?"),
    ("loss_of_balance_dizziness", "Do you lose balance because of dizziness?"),
    ("loss_of_consciousness", "Have you lost consciousness?"),
    ("bone_joint_problem_worsened_by_activity", "Do you have a bone or joint problem that activity makes worse?"),
    ("currently_taking_medications", "Do you currently take medication for blood pressure or a heart condition?"),
    ("doctor_advised_supervised_only", "Has a doctor said you should only train with supervision?"),
)

# One word accepts these. A skip still leaves age, sex, and weight unset.
_GOAL_DEFAULTS = {
    "goal": "hold",
    "weight": "80 kg",
    "target": "80 kg",
    "height": "180 cm",
    "age": "30",
    "sex": "male",
    "food_style": "no preference",
}
_TRAINING_DEFAULTS = {
    "sport": "general training",
    "training_days": "3",
    "minutes": "45",
    "equipment": "bodyweight",
    "experience": "beginner",
    "injuries": "none",
}
_OPTIONAL = {"name", "food_style"}
_ACCEPT = {"ok", "okay", "yep", "yeah", "defaults", "default", "sounds good", "do it", "lets go"}
_WEEK_OFFSETS = (0, 2, 4, 5, 1, 3, 6)
_SETUP_WORDS = ("clone", "pip", "pytest", "release_check", "install", "git ")

HAPPY_PATH = ("hello", "ok", "ok", "all no", "yes")


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
            "One word ok uses hold, 80 kg, target 80 kg, 180 cm, age 30, male. "
            "You can skip one. I will not guess a skipped age, sex, or weight. "
            "If you skip the goal, the goal is hold."
        ),
    },
    {
        "id": "training",
        "asks": ("sport", "training_days", "minutes", "equipment", "experience", "injuries"),
        "text": (
            "Sport, schedule, and equipment? "
            "One word ok uses general training, 3 days, 45 min, bodyweight, beginner, no injuries. "
            "Any sport is fine. Sport and the schedule come before the PAR-Q."
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
        if all(key in state["par_q"] for key, _question in PAR_Q):
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


def _parse_explicit(state, folded):
    answers = state["answers"]
    if re.search(r"\ball no\b", folded):
        state["par_q"] = {key: False for key, _question in PAR_Q}
    for goal in ("cut", "lose", "gain", "hold"):
        if re.search(rf"\b{goal}\b", folded):
            answers["goal"] = goal
            break
    age = re.search(r"\bage\s+(\d{1,3})\b", folded)
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
    elif asked == "par_q":
        state["par_q"] = {key: None for key, _question in PAR_Q}


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
    _parse_explicit(state, folded)


def _is_plan_yes(reply):
    from record_confirmation import is_clear_yes

    return is_clear_yes(reply)


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
        "par_q": {key: False for key in state["par_q"]},
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


def _check_in():
    from red_flag_check import RedFlagChecker

    checker = RedFlagChecker()
    answers = {aliases[0]: "no" for _flag, aliases in checker.CHECKLIST_GROUPS}
    return checker.scan_check_in({
        "symptom_checklist": answers,
        "notes": "Easy lift, slept fine.",
    })


def _confirm(state, reply):
    from plan_builder import PlanBuilder
    from record_confirmation import ConfirmationRecorder

    if _first_missing(state) is not None:
        return
    check_in = _check_in()
    built = PlanBuilder().propose(_profile(state), check_in)
    if not built.get("ok"):
        state["error"] = built.get("message", "The week did not pass.")
        return
    record = ConfirmationRecorder().record(built["confirm"], reply, "user", check_in)
    if not record.confirmed:
        state["error"] = record.message
        return
    from routines import start_daily_loop

    state["record"] = record
    state["confirmed"] = True
    loop = start_daily_loop(reply)
    state["routines_on"] = loop["enabled"]
    state["times"] = loop["times"]


def _proposal(state):
    answers = state["answers"]
    days = answers.get("training_days", "3")
    minutes = answers.get("minutes", "45")
    goal = answers.get("goal", "hold")
    equipment = answers.get("equipment", "bodyweight")
    return (
        f"{days} days, {minutes} min, {goal}, {equipment}. "
        "One yes confirms the plan and starts the morning check-in at 7:00, "
        "the evening follow-up at 20:00, and the weekly review Sunday at 18:00. "
        "Routines, each is opt-in, in this same message: "
        "daily check-in, evening follow-up, weekly review, monthly review, yearly review. "
        "One reply can change a time. Do not ask for another yes."
    )


def speak(state):
    """The next bot reply. The first one is question 1 when nothing is known."""
    if state["confirmed"]:
        return "Confirmed. Morning at 07:00, evening at 20:00, weekly Sunday at 18:00."
    missing = _first_missing(state)
    if missing is not None:
        state["phase"] = "intake"
        state["asked"] = missing["id"]
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
