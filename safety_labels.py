#!/usr/bin/env python3
"""Host-supplied safety labels. The engine does not read labels out of user text.

Precedence for every message, first match wins:
hard-stop keywords on the raw text, then red_flag, then minor_signal,
then injury, then note_ok. One label is enough. The others do not have to agree.
"""

import json
import re
import unicodedata


# Kinds the red-flag checker already uses, plus none.
RED_FLAG_KINDS = (
    "none",
    "chest_pain",
    "cardiac_symptoms",
    "breathing_difficulty",
    "fainting",
    "numbness",
    "stroke_signs",
    "face_droop",
    "abnormal_bleeding",
    "blue_lips",
    "self_harm",
    "self_harm_thoughts",
    "disordered_eating",
    "purging",
    "very_low_intake",
    "rhabdomyolysis",
    "heat_illness",
    "palpitations",
    "referred_pain",
    "blood_clot",
    "head_injury",
    "nausea",
    "extreme_fatigue",
    "cauda_equina",
    "spinal_emergency",
    "injury",
    "sharp_joint_pain",
    "tendon_snap",
    "other_medical",
)
INJURY_VALUES = ("none", "old", "current", "unclear")
LABEL_KEYS = ("minor_signal", "red_flag", "injury", "note_ok")

# Short hard-stop list plus the emergency phrases already used by the checks.
# Matched on folded text with no negation window. "no chest pain" still holds.
HARD_STOP_PHRASES = (
    "chest pain",
    "chest tightness",
    "chest tight",
    "chest hurts",
    "chest injury",
    "fainting",
    "fainted",
    "passed out",
    "feel faint",
    "numbness",
    "numb",
    "cant breathe",
    "cannot breathe",
    "trouble breathing",
    "shortness of breath",
    "bladder",
    "bowel",
    "peed myself",
    "wet myself",
    "incontinence",
    "cant control bladder",
    "tingling",
    "cant feel",
    "pain shooting down",
    "cracked rib",
    "bruised rib",
    "broken rib",
    "saddle",
    "slurred",
    "face droop",
    "palpitation",
    "dizzy",
    "sharp pain",
    "loss of consciousness",
    "my head",
    "pain in my chest",
    "tightness in my chest",
    "chest feels tight",
    "black out",
    "blacked out",
)

# Apostrophes that should disappear so "can't" and "can’t" both become "cant".
_APOSTROPHES = ("'", "\u2019", "\u2018", "\u02bc", "\uff07", "\u02b9", "\u2032")

_HARD_STOP_MESSAGE = (
    "Medical emergency. Stop all activity and seek immediate medical attention."
)


def fold_text(reply):
    """Lowercase, drop apostrophes, keep letters and digits."""
    if not isinstance(reply, str):
        return ""
    text = reply.strip().lower()
    for mark in _APOSTROPHES:
        text = text.replace(mark, "")
    cleaned = []
    for char in text:
        if char.isalnum() or char.isspace():
            cleaned.append(char)
        else:
            cleaned.append(" ")
    return " ".join("".join(cleaned).split())


# Existing emergency marks that are not words. Checked on the raw reply.
_HARD_STOP_MARKS = ("\U0001F915",)


def _phrase_hit(folded, phrase):
    """A whole phrase, with a trailing plural s allowed. 'numb' is not 'number'."""
    if not phrase or not folded:
        return False
    return re.search(
        rf"(?<![a-z0-9]){re.escape(phrase)}s?(?![a-z0-9])",
        folded,
    ) is not None


def _gapped_sharp_pain(folded):
    """'sharp knee pain' is the same hard stop as 'sharp pain'."""
    if not folded:
        return False
    return re.search(r"\bsharp\b(?:\s+[a-z]+){0,3}\spain\b", folded) is not None


def hard_stop(reply):
    """True when the raw text contains a hard-stop phrase. Negation is ignored."""
    if not isinstance(reply, str) or not reply.strip():
        return False
    if any(mark in reply for mark in _HARD_STOP_MARKS):
        return True
    folded = fold_text(reply)
    if not folded:
        return False
    if any(_phrase_hit(folded, phrase) for phrase in HARD_STOP_PHRASES):
        return True
    return _gapped_sharp_pain(folded)


def hard_stop_message():
    return _HARD_STOP_MESSAGE


def _bool_value(value):
    return value is True or value is False


def validate_labels(payload):
    """Exact schema. Known enums only. No extra keys.

    Returns (labels, None) or (None, reason).
    """
    if not isinstance(payload, dict):
        return None, "labels must be an object"
    if set(payload) != set(LABEL_KEYS):
        return None, "labels must be exactly minor_signal, red_flag, injury, and note_ok"
    if not _bool_value(payload.get("minor_signal")):
        return None, "minor_signal must be a boolean"
    if not _bool_value(payload.get("note_ok")):
        return None, "note_ok must be a boolean"
    flag = payload.get("red_flag")
    if not isinstance(flag, str) or flag not in RED_FLAG_KINDS:
        return None, "red_flag must be none or a known kind"
    injury = payload.get("injury")
    if not isinstance(injury, str) or injury not in INJURY_VALUES:
        return None, "injury must be none, old, current, or unclear"
    return {
        "minor_signal": payload["minor_signal"],
        "red_flag": flag,
        "injury": injury,
        "note_ok": payload["note_ok"],
    }, None


def label_action(payload, unclear_count=0):
    """The one action for this label set. Missing or invalid counts as unclear.

    Actions: hold, clear_age, swap, follow_up, note, pass.
    A second unclear returns hold.
    """
    count = unclear_count if isinstance(unclear_count, int) and unclear_count >= 0 else 0
    labels, reason = validate_labels(payload)
    if reason is not None:
        return "hold" if count >= 1 else "follow_up"
    if labels["red_flag"] != "none":
        return "hold"
    # A current injury or a red flag holds even when the same message is a minor.
    if labels["minor_signal"] and labels["injury"] == "current":
        return "hold"
    if labels["minor_signal"]:
        return "clear_age"
    injury = labels["injury"]
    if injury == "current":
        return "hold"
    if injury == "old":
        return "swap"
    if injury == "unclear":
        return "hold" if count >= 1 else "follow_up"
    if labels["note_ok"]:
        return "note"
    return "pass"


def message_action(reply, payload, unclear_count=0):
    """Hard-stop on the raw text, then the label action. Labels are never read from reply."""
    if hard_stop(reply):
        return "hold"
    return label_action(payload, unclear_count)


def expected_action(minor_signal, red_flag, injury, note_ok, unclear_count=0, text=""):
    """The table oracle. Hard-stop text holds before any label."""
    if hard_stop(text):
        return "hold"
    return label_action(
        {
            "minor_signal": minor_signal,
            "red_flag": red_flag,
            "injury": injury,
            "note_ok": note_ok,
        },
        unclear_count,
    )


def decision_table():
    """Every label combination, with the action the engine must take."""
    rows = []
    for minor in (False, True):
        for flag in RED_FLAG_KINDS:
            for injury in INJURY_VALUES:
                for note in (False, True):
                    rows.append({
                        "minor_signal": minor,
                        "red_flag": flag,
                        "injury": injury,
                        "note_ok": note,
                        "action": expected_action(minor, flag, injury, note),
                    })
    return rows


def clean_label_text(reply):
    """Drop emoji and control characters so a prompt can quote the reply as data."""
    if not isinstance(reply, str):
        return ""
    kept = []
    for char in reply:
        category = unicodedata.category(char)
        if category.startswith("C"):
            continue
        kept.append(char)
    return "".join(kept)


def prompt_table():
    """A local phrase table for classify_from_table. The host prompt does not use it."""
    hard_stop = list(HARD_STOP_PHRASES)
    for mark in _HARD_STOP_MARKS:
        if mark not in hard_stop:
            hard_stop.append(mark)
    return {
        "hard_stop": hard_stop,
        "minor": [
            "minor",
            "teen",
            "not an adult",
            "high school",
            "under 18",
            "under eighteen",
            "not 18",
            "turning 18",
            "fifteen",
            "sixteen",
            "seventeen",
            "im 13",
            "im 14",
            "im 15",
            "im 16",
            "im 17",
            "i am 13",
            "i am 14",
            "i am 15",
            "i am 16",
            "i am 17",
            "13yo",
            "14yo",
            "15yo",
            "16yo",
            "17yo",
            "15\u6b73",
        ],
        "minor_age": {"min": 13, "max": 17},
        "red_flag": {
            "pain in my chest": "chest_pain",
            "tightness in my chest": "chest_pain",
            "chest feels tight": "chest_pain",
            "chest pain": "chest_pain",
            "chest tightness": "chest_pain",
            "chest tight": "chest_pain",
            "chest hurts": "chest_pain",
            "cant breathe": "breathing_difficulty",
            "trouble breathing": "breathing_difficulty",
            "out of breath": "breathing_difficulty",
            "fainting": "fainting",
            "fainted": "fainting",
            "passed out": "fainting",
            "feel faint": "fainting",
            "blacked out": "fainting",
            "black out": "fainting",
            "dizzy": "fainting",
            "numbness": "numbness",
            "numb": "numbness",
            "tingling": "numbness",
            "cant feel": "numbness",
            "cant straighten": "injury",
            "bladder": "cauda_equina",
            "bowel": "cauda_equina",
            "peed myself": "cauda_equina",
            "wet myself": "cauda_equina",
            "incontinence": "cauda_equina",
            "loss of consciousness": "fainting",
            "my head": "head_injury",
            "slurred": "stroke_signs",
            "face droop": "face_droop",
            "palpitation": "palpitations",
            "fluttering": "palpitations",
            "coughing blood": "abnormal_bleeding",
            "wheezing": "breathing_difficulty",
            "throw up": "purging",
            "vomited": "nausea",
            "500 calories": "very_low_intake",
            "want to disappear": "self_harm",
            "vision blurry": "head_injury",
            "cracked rib": "injury",
            "bruised rib": "injury",
            "broken rib": "injury",
            "sharp pain": "sharp_joint_pain",
            "stabbing": "sharp_joint_pain",
            "severe back pain": "injury",
            "shooting down": "blood_clot",
            "knee buckled": "injury",
            "swelled": "injury",
            "fever": "heat_illness",
            "covid": "heat_illness",
            "pregnant": "injury",
        },
        "injury_current": [
            "hurts",
            "still recovering",
            "gives way",
            "not healed",
            "swelled",
            "swollen",
            "on crutches",
            "this morning",
            "hours ago",
            "cant stand up",
            "throbbing",
        ],
        "injury_unclear": [
            "pain",
            "torn",
            "tore",
            "sprain",
            "sprained",
            "tendinitis",
            "tendonitis",
            "tear",
            "rehab",
            "surgery",
            "flares",
            "disc",
            "unstable",
        ],
        "injury_old": [
            "years ago",
            "old and healed",
            "fully healed",
        ],
        "healed_word": "healed",
        "note": [
            "parkrun",
            "breakfast",
            "lunch",
            "dinner",
            "coffee",
            "ate",
            "oats",
        ],
    }


_INSTRUCTION_WORD = (
    r"(?:as|a|an|the|this|to|be|is|set|label|labels|note_ok|safe|ok|none|"
    r"red_flag|minor_signal|false|true|please)"
)


def quoted_data(reply):
    """The user reply with label JSON and classifier instructions removed.

    What remains is data. A line that tells the classifier how to label is not a fact.
    The instruction words stop after a short prefix, so the rest of the message stays.
    Braces that are not a label object stay, so '{knee hurts}' is still an injury.
    """
    text = reply if isinstance(reply, str) else ""

    def _drop_label_json(match):
        blob = match.group(0)
        try:
            obj = json.loads(blob)
        except json.JSONDecodeError:
            return blob
        if isinstance(obj, dict) and any(key in obj for key in LABEL_KEYS):
            return " "
        return blob

    text = re.sub(r"\{[^{}]*\}", _drop_label_json, text)
    text = re.sub(
        rf"(?i)\bclassifier\b[:\s]*(?:{_INSTRUCTION_WORD}\b[:\s]*){{0,8}}",
        " ",
        text,
    )
    text = re.sub(
        rf"(?i)\blabel this\b[:\s]*(?:{_INSTRUCTION_WORD}\b[:\s]*){{0,8}}",
        " ",
        text,
    )
    return text


def _has_phrase(folded, phrase):
    return _phrase_hit(folded, phrase)


def _any_phrase(folded, phrases):
    for phrase in phrases or []:
        if isinstance(phrase, str) and _has_phrase(folded, phrase):
            return True
    return False


def _minor_age(folded, span):
    """A stated age from 13 to 17, with an age cue. A bare number is not enough."""
    if not isinstance(span, dict) or not folded:
        return False
    lo = span.get("min")
    hi = span.get("max")
    if isinstance(lo, bool) or isinstance(hi, bool):
        return False
    if not isinstance(lo, int) or not isinstance(hi, int) or lo > hi:
        return False
    nums = "|".join(str(number) for number in range(lo, hi + 1))
    if re.search(rf"\b(?:{nums})\s*yo\b", folded):
        return True
    return re.search(
        rf"\b(?:im|i am|age|actually)(?:\s+[a-z]+){{0,3}}\s+(?:{nums})\b",
        folded,
    ) is not None


def _flag_hit(folded, phrase):
    if phrase == "sharp pain" and _gapped_sharp_pain(folded):
        return True
    return _has_phrase(folded, phrase)


def classify_from_table(reply, table):
    """Apply a local phrase table. The host prompt and the eval gate do not call this.

    Hard-stop and red-flag words win. A current word is current even beside old wording.
    An injury noun with no clear timing is unclear. A note is only a clean leftover.
    """
    raw = reply if isinstance(reply, str) else ""
    quoted = quoted_data(raw)
    folded = fold_text(quoted)
    labels = {
        "minor_signal": False,
        "red_flag": "none",
        "injury": "none",
        "note_ok": False,
    }
    if not isinstance(table, dict):
        return labels, False
    stopped = False
    for phrase in table.get("hard_stop") or []:
        if not isinstance(phrase, str) or not phrase:
            continue
        if any(ord(char) > 127 for char in phrase):
            if phrase in raw or phrase in quoted:
                stopped = True
                break
        elif _flag_hit(folded, phrase):
            stopped = True
            break
    for phrase in table.get("minor") or []:
        if isinstance(phrase, str) and _has_phrase(folded, phrase):
            labels["minor_signal"] = True
            break
    if _minor_age(folded, table.get("minor_age")):
        labels["minor_signal"] = True
    flag = "none"
    for phrase, kind in (table.get("red_flag") or {}).items():
        if isinstance(phrase, str) and _flag_hit(folded, phrase) and kind in RED_FLAG_KINDS:
            flag = kind
            break
    if stopped and flag == "none":
        flag = "chest_pain" if _has_phrase(folded, "chest") else "injury"
    labels["red_flag"] = flag
    if flag == "none":
        current = _any_phrase(folded, table.get("injury_current"))
        old_phrases = [
            phrase for phrase in (table.get("injury_old") or []) if isinstance(phrase, str)
        ]
        clean_phrases = [
            phrase for phrase in old_phrases if phrase in {"old and healed", "fully healed"}
        ]
        timed_phrases = [phrase for phrase in old_phrases if phrase not in set(clean_phrases)]
        named = _any_phrase(folded, table.get("injury_unclear"))
        healed = table.get("healed_word")
        clean_old = _any_phrase(folded, clean_phrases)
        if isinstance(healed, str) and _has_phrase(folded, healed) and not clean_old:
            named = True
        timed_old = _any_phrase(folded, timed_phrases)
        if current:
            labels["injury"] = "current"
        elif clean_old and named:
            labels["injury"] = "unclear"
        elif clean_old:
            labels["injury"] = "old"
        elif timed_old and named:
            labels["injury"] = "unclear"
        elif named:
            labels["injury"] = "unclear"
    if flag == "none" and not labels["minor_signal"] and labels["injury"] == "none":
        for phrase in table.get("note") or []:
            if isinstance(phrase, str) and _has_phrase(folded, phrase):
                labels["note_ok"] = True
                break
    return labels, stopped
