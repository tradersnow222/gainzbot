#!/usr/bin/env python3
"""
Record a user's explicit confirmation of a plan or plan change.

Fail closed. Only a clear yes from the user, in their exact words, confirms
one exact plan version. Any later edit needs a new confirmation.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import hashlib
import hmac
import json
import os
import re
import sys
import unicodedata
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guardrails.validate import InputValidator
from red_flag_check import RedFlagChecker, is_passing_check_in


CLEAR_YES = {
    "yes",
    "yes i confirm",
    "yes i confirm this plan",
    "yes i confirm this change",
    "i confirm",
    "i confirm this plan",
    "i confirm this change",
}


def hash_plan(plan) -> str:
    """Stable hash of one exact plan version.

    first_plan and its seal are part of this hash. A later week with the
    flag copied on does not match a first-plan confirmation.
    """
    payload = json.dumps(plan, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _first_plan_body(plan):
    return {
        key: value
        for key, value in plan.items()
        if key not in ("first_plan", "first_plan_seal")
    }


def _carries_load_or_calories(plan_body, sessions):
    """True when this week has a load or a calorie target to put in changes."""
    training = plan_body.get("training") if isinstance(plan_body.get("training"), dict) else None
    if training is not None:
        if training.get("current_load") not in (None, "") or training.get("previous_load") not in (None, ""):
            return True
    nutrition = plan_body.get("nutrition")
    if isinstance(nutrition, dict) and nutrition.get("calories") not in (None, ""):
        return True
    for row in sessions:
        if isinstance(row, dict) and row.get("load") not in (None, ""):
            return True
    return False


def _is_later_week(plan):
    """A raised load or a calorie change is not the one first plan.

    A week with no changes field is still a later week when it carries a
    load or calories. The sealed first plan that has a load also stores
    that load in changes. A plan and sessions with neither a load nor a
    changes field can still be the first plan.
    """
    if not isinstance(plan, dict):
        return True
    body = _first_plan_body(plan)
    plan_body = body.get("plan")
    sessions = body.get("sessions")
    if not isinstance(plan_body, dict) or not isinstance(sessions, list) or not sessions:
        return True
    if any(not isinstance(row, dict) for row in sessions):
        return True
    training = plan_body.get("training") if isinstance(plan_body.get("training"), dict) else None
    previous = training.get("previous_load") if training else None
    current = training.get("current_load") if training else None
    if previous not in (None, "") and current not in (None, "") and previous != current:
        return True
    if "changes" not in body or not isinstance(body.get("changes"), dict):
        if "changes" in body:
            return True
        if _carries_load_or_calories(plan_body, sessions):
            return True
    else:
        changes = body["changes"]
        if "load" in changes:
            if training is None or changes.get("load") != current or current != previous:
                return True
        if "calories" in changes:
            nutrition = plan_body.get("nutrition")
            if not isinstance(nutrition, dict) or nutrition.get("calories") != changes.get("calories"):
                return True
        if set(changes) - {"load", "calories"}:
            return True
    if previous not in (None, ""):
        for row in sessions:
            if row.get("load") != previous:
                return True
    return False


def first_plan_seal(plan):
    """HMAC over the first week. A later week gets no seal."""
    from seal_secret import seal_hex

    if _is_later_week(plan):
        return ""
    payload = json.dumps(
        _first_plan_body(plan),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return seal_hex(b"first_plan", payload)


def _mark_first_plan(plan):
    """Seal the first plan. Only onboarding, and tests, call this.

    A later week is returned unmarked. A bare first_plan flag is not this.
    """
    if not isinstance(plan, dict):
        return plan
    marked = _first_plan_body(plan)
    if _is_later_week(marked):
        return marked
    marked["first_plan"] = True
    try:
        marked["first_plan_seal"] = first_plan_seal(marked)
    except OSError:
        marked["first_plan_seal"] = ""
    return marked


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def onboarding_record_path():
    """The one first-plan confirmation for this install."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "onboarding_record.json")


def _store_onboarding_record(record, week):
    """Remember the onboarding confirmation. A later week is not stored."""
    if not isinstance(record, ConfirmationRecord) or record.confirmed is not True:
        return False
    if _is_later_week(week):
        return False
    marked = _mark_first_plan(week)
    seal = marked.get("first_plan_seal") if isinstance(marked, dict) else ""
    if not isinstance(seal, str) or not seal:
        return False
    try:
        if hash_plan(marked) != record.plan_hash:
            return False
    except (TypeError, ValueError):
        return False
    payload = {
        "plan_hash": record.plan_hash,
        "record_id": record.record_id,
        "week": json.loads(_canonical(week)),
        "first_plan_seal": seal,
    }
    path = onboarding_record_path()
    folder = os.path.dirname(path)
    temporary = path + ".tmp"
    try:
        os.makedirs(folder, exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
            handle.write("\n")
        os.replace(temporary, path)
    except OSError:
        return False
    return True


def _read_onboarding_record():
    try:
        with open(onboarding_record_path(), encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def covers_first_plan(record, week) -> bool:
    """True when this record is the stored onboarding first plan for this week.

    The week is not sealed here. A later week does not match the stored record.
    """
    stored = _read_onboarding_record()
    if not isinstance(stored, dict) or not isinstance(record, ConfirmationRecord):
        return False
    if record.confirmed is not True or not confirmation_seal_matches(record):
        return False
    if record.plan_hash != stored.get("plan_hash") or record.record_id != stored.get("record_id"):
        return False
    if not isinstance(week, dict) or _canonical(week) != _canonical(stored.get("week")):
        return False
    seal = stored.get("first_plan_seal")
    if not isinstance(seal, str) or not seal:
        return False
    try:
        expected = first_plan_seal(week)
    except OSError:
        return False
    if not expected or len(seal) != len(expected) or not hmac.compare_digest(seal, expected):
        return False
    marked = _first_plan_body(week)
    marked["first_plan"] = True
    marked["first_plan_seal"] = seal
    try:
        return hash_plan(marked) == record.plan_hash
    except (TypeError, ValueError):
        return False


# Emoji that may sit beside a bare yes. Every other symbol stays and refuses.
_ALLOWED_EMOJI = frozenset("👍💪🔥✅✔")
_SKIN_TONE = re.compile("[\U0001F3FB-\U0001F3FF]")
_CLOCK_SKEW = timedelta(minutes=5)
_VARIATION = re.compile("[\uFE0E\uFE0F]")


def normalize_reply(reply: str) -> str:
    """Fold a reply for the clear-yes check. The stored quote stays exact.

    Only ASCII punctuation other than '?', whitespace, and Unicode format
    characters are removed. Letters from other scripts, digits, marks, and
    symbols stay, so they cannot vanish into a bare yes.
    """
    text = InputValidator.normalize_unicode(reply).lower().strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    kept = []
    for ch in text:
        category = unicodedata.category(ch)
        if category == "Cf" or ch.isspace():
            kept.append(" ")
            continue
        if ch != "?" and ord(ch) < 128 and category.startswith("P"):
            continue
        kept.append(ch)
    return re.sub(r"\s+", " ", "".join(kept)).strip()


# Exact phrases only. Allowed emoji may sit beside them.
# A reply that adds a symptom, a change, a question, or a condition is not here.
_BARE_YES = CLEAR_YES | {
    "yep",
    "yeah",
    "ok",
    "okay",
    "sounds good",
    "lets go",
    "ok fine",
    "do it",
    "confirm",
    "confirmed",
    "lock it in",
}


def _has_format_character(reply: str) -> bool:
    return any(unicodedata.category(ch) == "Cf" for ch in reply)


def is_clear_yes(reply) -> bool:
    """True only for a friendly yes, plus ordinary punctuation or the allowed emoji.

    Allowed words: yes, yep, yeah, sounds good, let's go, ok, do it,
    confirm, confirmed, lock it in, and the fixed lines in CLEAR_YES
    such as 'I confirm this plan'. A reply that adds a symptom, a change,
    a question, or a condition refuses. A question mark, a format character,
    another script, or any other symbol refuses the reply.
    """
    if not isinstance(reply, str) or not reply.strip():
        return False
    if "?" in reply or "？" in reply or _has_format_character(reply):
        return False
    if "</3" in reply:
        return False
    folded = normalize_reply(reply)
    if "?" in folded or "</3" in folded:
        return False
    folded = _SKIN_TONE.sub("", folded)
    folded = _VARIATION.sub("", folded)
    folded = folded.replace("<3", " ")
    stripped = "".join(ch for ch in folded if ch not in _ALLOWED_EMOJI)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    if re.fullmatch(r"lets go+", stripped):
        return True
    if stripped == "" and "👍" in folded:
        return True
    return stripped in _BARE_YES


def is_plan_yes(reply, proposal_hash) -> bool:
    """The plan-step yes for one proposal hash.

    A bare is_clear_yes is not enough. The hash has to name the proposal
    being confirmed, and a symptom in the reply still refuses.
    """
    if not isinstance(proposal_hash, str) or not proposal_hash.strip():
        return False
    if reply_pause(reply) is not None:
        return False
    return is_clear_yes(reply)


def _first_plan_confirm(plan) -> bool:
    """True only when onboarding sealed this object as the first plan.

    A copied first_plan flag, or a seal from a different week, does not
    count. A load or calorie proposal still needs a bare yes.
    """
    if not isinstance(plan, dict) or plan.get("first_plan") is not True:
        return False
    if not isinstance(plan.get("plan"), dict):
        return False
    if not isinstance(plan.get("sessions"), list):
        return False
    seal = plan.get("first_plan_seal")
    if not isinstance(seal, str) or not seal:
        return False
    try:
        expected = first_plan_seal(plan)
    except OSError:
        return False
    if len(seal) != len(expected):
        return False
    return hmac.compare_digest(seal, expected)


def reply_pause(reply):
    """The red-flag result when this reply must pause, else None."""
    if not isinstance(reply, str) or not reply.strip():
        return None
    scanned = RedFlagChecker().scan_text(reply)
    if scanned.pause_plan:
        return scanned
    return None


def new_record_id() -> str:
    """One id for one yes. A copy keeps this id. A new yes gets a new one."""
    return str(uuid.uuid4())


def _confirmation_payload(record) -> str:
    body = {
        "confirmed": record.confirmed is True,
        "plan_hash": record.plan_hash if isinstance(record.plan_hash, str) else "",
        "quoted_words": record.quoted_words if isinstance(record.quoted_words, str) else "",
        "record_id": record.record_id if isinstance(record.record_id, str) else "",
        "speaker": record.speaker if isinstance(record.speaker, str) else "",
        "timestamp": record.timestamp if isinstance(record.timestamp, str) else "",
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _confirmation_seal(record):
    from seal_secret import seal_hex

    try:
        return seal_hex(b"confirmation", _confirmation_payload(record))
    except OSError:
        return None


def confirmation_seal_matches(record) -> bool:
    """True only when record_confirmation set the marker on this exact record."""
    if not isinstance(record, ConfirmationRecord):
        return False
    seal = record.issuer_seal if isinstance(record.issuer_seal, str) else ""
    if not seal:
        return False
    expected = _confirmation_seal(record)
    if not isinstance(expected, str) or not expected or not seal:
        return False
    if len(seal) != len(expected):
        return False
    return hmac.compare_digest(seal, expected)


def timestamp_is_current(stamp, now=None) -> bool:
    """True when the stamp is UTC Z and not past a small clock skew."""
    if not isinstance(stamp, str):
        return False
    try:
        parsed = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    current = now if now is not None else datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return parsed <= current + _CLOCK_SKEW


def _issue(record):
    """Mark a record this module just built. A copy with edited fields will not match."""
    from seal_secret import DATA_FILE_MESSAGE

    seal = _confirmation_seal(record)
    if not seal:
        record.confirmed = False
        record.issuer_seal = ""
        record.errors = list(record.errors) + [DATA_FILE_MESSAGE]
        record.message = DATA_FILE_MESSAGE
        return record
    record.issuer_seal = seal
    return record


@dataclass
class ConfirmationRecord:
    """One confirmation attempt. confirmed is true only when every check passed."""
    confirmed: bool
    plan_hash: str
    quoted_words: str
    speaker: str
    message: str
    errors: List[str]
    record_id: str = field(default_factory=new_record_id)
    timestamp: str = ""
    issuer_seal: str = ""

    def to_dict(self) -> Dict:
        return {
            "confirmed": self.confirmed,
            "plan_hash": self.plan_hash,
            "quoted_words": self.quoted_words,
            "speaker": self.speaker,
            "message": self.message,
            "errors": self.errors,
            "record_id": self.record_id,
            "timestamp": self.timestamp,
            "issuer_seal": self.issuer_seal,
        }


class ConfirmationRecorder:
    """Records a clear yes from the user for one exact plan version."""

    def record(
        self,
        plan,
        reply=None,
        speaker=None,
        check_in_result=None,
    ) -> ConfirmationRecord:
        """
        Record a confirmation.

        plan, reply, speaker, and check_in_result can also be passed together
        as one object with those fields.
        """
        if reply is None and isinstance(plan, dict) and "plan" in plan and "reply" in plan:
            payload = plan
            plan = payload.get("plan")
            reply = payload.get("reply")
            speaker = payload.get("speaker", payload.get("source"))
            check_in_result = payload.get(
                "check_in_result", payload.get("check_in")
            )

        errors: List[str] = []
        quoted = reply if isinstance(reply, str) else ""
        speaker_text = speaker.strip() if isinstance(speaker, str) else ""
        plan_hash = ""
        if isinstance(plan, dict):
            try:
                plan_hash = hash_plan(plan)
            except (TypeError, ValueError):
                plan_hash = ""
                errors.append("That plan could not be recorded.")
        else:
            errors.append("The plan has to be an object.")

        paused = reply_pause(reply)
        schedule = None
        # A routine-time yes confirms the first week only. A later load or
        # calorie proposal still needs a bare yes.
        if paused is None and _first_plan_confirm(plan):
            from routines import plan_schedule

            schedule = plan_schedule(reply)
        if not isinstance(reply, str) or not reply.strip():
            errors.append("The confirmation has to be the user's own words.")
        elif paused is not None:
            errors.append(paused.message)
        elif not is_clear_yes(reply) and schedule is None:
            errors.append(
                "That reply is not a clear yes. "
                "Vague replies like 'sure I guess', 'looks fine', or 'whatever' do not confirm a plan."
            )

        if speaker_text.lower() not in {"user", "the user"}:
            errors.append("The confirmation has to come from the user.")

        if check_in_result is None:
            errors.append("A passing check-in is required.")
        elif not is_passing_check_in(check_in_result):
            errors.append("That check-in did not pass.")

        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if errors:
            return _issue(ConfirmationRecord(
                confirmed=False,
                plan_hash=plan_hash,
                quoted_words=quoted,
                speaker=speaker_text,
                message="Not confirmed. " + " ".join(errors),
                errors=errors,
                timestamp=stamp,
            ))

        return _issue(ConfirmationRecord(
            confirmed=True,
            plan_hash=plan_hash,
            quoted_words=reply,
            speaker=speaker_text,
            message=f"Confirmed. Quoted words: {reply}",
            errors=[],
            timestamp=stamp,
        ))

    def covers(self, record: Optional[ConfirmationRecord], plan) -> bool:
        """True when this record confirms this exact plan version."""
        if not confirmation_seal_matches(record):
            return False
        if not timestamp_is_current(record.timestamp):
            return False
        if record.confirmed is not True:
            return False
        if not isinstance(plan, dict):
            return False
        try:
            current = hash_plan(plan)
        except (TypeError, ValueError):
            return False
        return bool(record.plan_hash) and record.plan_hash == current
