#!/usr/bin/env python3
"""Grouped onboarding questions. One message holds several answers."""

PAR_Q = (
    ("chest_pain_at_rest", "Do you have chest pain while resting?"),
    ("chest_pain_during_activity", "Do you have chest pain during activity?"),
    ("loss_of_balance_dizziness", "Do you lose balance because of dizziness?"),
    ("loss_of_consciousness", "Have you lost consciousness?"),
    ("bone_joint_problem_worsened_by_activity", "Do you have a bone or joint problem that activity makes worse?"),
    ("currently_taking_medications", "Do you currently take medication for blood pressure or a heart condition?"),
    ("doctor_advised_supervised_only", "Has a doctor said you should only train with supervision?"),
)


def _par_q_text():
    lines = [
        "Answer every PAR-Q question. Everyone gets these 7, not only older adults. Reply yes or no for each.",
    ]
    for key, question in PAR_Q:
        lines.append(f"- {key}: {question}")
    lines.append(
        "A skipped or unclear PAR-Q answer runs readiness_screen, the same as a yes. "
        "There is no training until readiness_screen passes."
    )
    return "\n".join(lines)


GROUPS = (
    {
        "id": "body",
        "asks": ("name", "sex", "age", "height", "weight"),
        "text": (
            "Tell me what to call you, your sex, age, height, and weight. "
            "You can skip one. I will not guess a skipped age, sex, or weight. "
            "Always ask age. They may skip it."
        ),
    },
    {
        "id": "par_q",
        "asks": tuple(key for key, _question in PAR_Q),
        "text": _par_q_text(),
    },
    {
        "id": "training",
        "asks": ("training_days", "minutes", "equipment", "experience", "injuries", "sport"),
        "text": (
            "Which days do you train, how many minutes, what equipment do you have "
            "(none or bodyweight is fine), what is your experience "
            "(beginner, intermediate, or advanced), any injuries (or none), "
            "and which sport? Any sport is fine."
        ),
    },
    {
        "id": "food",
        "asks": ("food_style", "goal"),
        "text": (
            "What food style should I plan around, and what is the goal: "
            "cut, lose, gain, or hold? If you skip the goal, the goal is hold."
        ),
    },
)


def messages():
    """A few grouped messages. Not one question at a time."""
    if len(GROUPS) < 2:
        return []
    return [group["text"] for group in GROUPS]
