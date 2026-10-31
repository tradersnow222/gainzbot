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
    """Stable hash of one exact plan version."""
    payload = json.dumps(plan, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
        if not isinstance(reply, str) or not reply.strip():
            errors.append("The confirmation has to be the user's own words.")
        elif paused is not None:
            errors.append(paused.message)
        elif not is_clear_yes(reply):
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
