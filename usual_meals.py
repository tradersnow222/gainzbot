#!/usr/bin/env python3
"""Offer to save a usual meal, and save it only after a recorded yes."""

from record_confirmation import ConfirmationRecord, ConfirmationRecorder


def offer(food_log, name="breakfast"):
    usuals = getattr(food_log, "usuals", None)
    if not isinstance(usuals, dict) or not hasattr(food_log, "_usual_name"):
        return {"ok": False, "offer": False, "message": "No usual meal can be read."}
    key = food_log._usual_name(name)
    if not key:
        return {"ok": False, "offer": False, "message": "Name the usual meal."}
    if key in usuals:
        return {"ok": True, "offer": False, "message": f"Usual {key} is already saved."}
    return {
        "ok": True,
        "offer": True,
        "message": f"No usual {key} is remembered yet. Say yes to save one with remember_usual.",
    }


def plan_to_confirm(food_log, name, items, calories, protein_g):
    """The exact object record_confirmation has to cover."""
    if not hasattr(food_log, "_meal") or not hasattr(food_log, "_usual_name"):
        return {"ok": False, "plan": None, "message": "No usual meal can be read."}
    key = food_log._usual_name(name)
    if not key:
        return {"ok": False, "plan": None, "message": "Name the usual meal."}
    parsed = food_log._meal(items, calories, protein_g)
    if not parsed.get("ok"):
        return {"ok": False, "plan": None, "message": parsed.get("message", "The meal could not be read.")}
    meal = parsed["meal"]
    return {
        "ok": True,
        "plan": {
            "remember_usual": key,
            "items": list(meal["items"]),
            "calories": meal["calories"],
            "protein_g": meal["protein_g"],
        },
    }


def save_usual(food_log, name, items, calories, protein_g, confirmation=None):
    ready = plan_to_confirm(food_log, name, items, calories, protein_g)
    if not ready["ok"]:
        return {"ok": False, "stored": False, "message": ready["message"]}
    plan = ready["plan"]
    if not isinstance(confirmation, ConfirmationRecord) or not ConfirmationRecorder().covers(confirmation, plan):
        return {
            "ok": False,
            "stored": False,
            "message": "This usual meal needs record_confirmation before it is saved.",
        }
    remembered = food_log.remember_usual(name, plan["items"], plan["calories"], plan["protein_g"])
    if not remembered.get("ok"):
        return {"ok": False, "stored": False, "message": remembered.get("message", "The meal was not saved.")}
    return {
        "ok": True,
        "stored": True,
        "applied": False,
        "message": remembered.get("message", "Saved."),
        "meal": remembered.get("meal"),
    }
