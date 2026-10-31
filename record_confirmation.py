#!/usr/bin/env python3
"""
Record a user's explicit confirmation of a plan or plan change.

Fail closed. Only a clear yes from the user, in their exact words, confirms
one exact plan version. Any later edit needs a new confirmation.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
import hashlib
import json
import os
import re
import sys
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


def normalize_reply(reply: str) -> str:
    """Fold a reply for the clear-yes check. The stored quote stays exact."""
    text = InputValidator.normalize_unicode(reply).lower().strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    text = re.sub(r"[^a-z0-9'\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# Exact phrases only. Punctuation and emoji fold away. Any other word refuses.
_BARE_YES = CLEAR_YES | {
    "yep",
    "yeah",
    "confirm",
    "confirmed",
    "lock it in",
}


def is_clear_yes(reply) -> bool:
    """True only for a bare yes, with nothing after it but punctuation or emoji.

    Allowed words: yes, yep, yeah, confirm, confirmed, lock it in,
    and the fixed lines in CLEAR_YES such as 'I confirm this plan'.
    """
    if not isinstance(reply, str) or not reply.strip():
        return False
    return normalize_reply(reply) in _BARE_YES


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
            return ConfirmationRecord(
                confirmed=False,
                plan_hash=plan_hash,
                quoted_words=quoted,
                speaker=speaker_text,
                message="Not confirmed. " + " ".join(errors),
                errors=errors,
                timestamp=stamp,
            )

        return ConfirmationRecord(
            confirmed=True,
            plan_hash=plan_hash,
            quoted_words=reply,
            speaker=speaker_text,
            message=f"Confirmed. Quoted words: {reply}",
            errors=[],
            timestamp=stamp,
        )

    def covers(self, record: Optional[ConfirmationRecord], plan) -> bool:
        """True when this record confirms this exact plan version."""
        if record is None or not record.confirmed:
            return False
        if not isinstance(plan, dict):
            return False
        try:
            current = hash_plan(plan)
        except (TypeError, ValueError):
            return False
        return bool(record.plan_hash) and record.plan_hash == current
