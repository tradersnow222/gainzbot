#!/usr/bin/env python3
"""Tests for record_confirmation.py."""

import pytest
from readiness_screen import ReadinessScreen
from datetime import datetime, timedelta, timezone

from record_confirmation import (
    ConfirmationRecord,
    ConfirmationRecorder,
    hash_plan,
    is_clear_yes,
    is_plan_yes,
    normalize_reply,
    timestamp_is_current,
)
from red_flag_check import RedFlagChecker, RedFlagResult, is_passing_check_in
from plan_check import PlanValidator


def passing_check_in():
    checker = RedFlagChecker()
    answers = {
        aliases[0]: "no"
        for _flag, aliases in checker.CHECKLIST_GROUPS
    }
    result = checker.scan_check_in({
        "symptom_checklist": answers,
        "notes": "Easy lift, slept fine.",
    })
    assert is_passing_check_in(result)
    return result


def minor_screen(age=15):
    screener = ReadinessScreen()
    return screener.screen_intake({
        "age": age,
        "parental_consent": True,
        "par_q": {flag: False for flag in screener.PAR_Q_RED_FLAGS},
        "pregnant": False,
        "medical_conditions": "none",
        "medical_clearance": False,
    })


ADULT_PLAN = {
    "user": {
        "sex": "M",
        "weight_kg": 80,
        "age": 30,
        "height_cm": 180,
        "medical_clearance": False,
    },
    "nutrition": {"calories": 2200, "protein_g": 144},
    "training": {"previous_load": 100, "current_load": 105, "weeks_since_deload": 4},
}


class TestClearYes:
    def test_yes_confirms_and_stores_exact_words(self):
        reply = "  Yes, I confirm.  "
        record = ConfirmationRecorder().record(
            ADULT_PLAN, reply, "user", passing_check_in()
        )
        assert record.confirmed
        assert record.quoted_words == reply
        assert record.plan_hash == hash_plan(ADULT_PLAN)
        assert "yes, i confirm" in record.message.lower() or reply in record.message

    def test_plain_yes_confirms(self):
        record = ConfirmationRecorder().record(
            ADULT_PLAN, "yes", "User", passing_check_in()
        )
        assert record.confirmed
        assert record.quoted_words == "yes"

    @pytest.mark.parametrize("reply", [
        "sure I guess",
        "looks fine",
        "whatever",
        "yeah maybe",
        "yes I guess",
        "I think so",
    ])
    def test_vague_reply_is_refused(self, reply):
        record = ConfirmationRecorder().record(
            ADULT_PLAN, reply, "user", passing_check_in()
        )
        assert not record.confirmed
        assert record.quoted_words == reply
        assert "clear yes" in record.message.lower() or "not confirmed" in record.message.lower()

    def test_non_user_speaker_is_refused(self):
        for speaker in ("assistant", "bot", "coach", "system", "", None):
            record = ConfirmationRecorder().record(
                ADULT_PLAN, "yes", speaker, passing_check_in()
            )
            assert not record.confirmed
            assert "user" in record.message.lower()

    def test_missing_check_in_is_refused(self):
        record = ConfirmationRecorder().record(ADULT_PLAN, "yes", "user", None)
        assert not record.confirmed
        assert "check-in" in record.message.lower()

    def test_forged_check_in_dict_is_refused(self):
        forged = {
            "pause_plan": False,
            "flags_detected": [],
            "message": "No red flags detected. Continue with your plan.",
        }
        record = ConfirmationRecorder().record(ADULT_PLAN, "yes", "user", forged)
        assert not record.confirmed
        assert "check-in" in record.message.lower()

    def test_handmade_result_is_refused(self):
        forged = RedFlagResult(
            pause_plan=False,
            flags_detected=[],
            message="No red flags detected. Continue with your plan.",
            recommendations=[],
        )
        assert not is_passing_check_in(forged)
        record = ConfirmationRecorder().record(ADULT_PLAN, "yes", "user", forged)
        assert not record.confirmed

    def test_scan_text_clear_is_not_a_passing_check_in(self):
        text_result = RedFlagChecker().scan_text("Had a great workout today!")
        assert not text_result.pause_plan
        assert not is_passing_check_in(text_result)
        record = ConfirmationRecorder().record(
            ADULT_PLAN, "yes", "user", text_result
        )
        assert not record.confirmed

    def test_paused_check_in_is_refused(self):
        paused = RedFlagChecker().scan_check_in({"notes": "chest pain tonight"})
        assert paused.pause_plan
        record = ConfirmationRecorder().record(ADULT_PLAN, "yes", "user", paused)
        assert not record.confirmed

    def test_edit_after_confirming_needs_a_new_confirmation(self):
        recorder = ConfirmationRecorder()
        record = recorder.record(ADULT_PLAN, "yes", "user", passing_check_in())
        assert recorder.covers(record, ADULT_PLAN)
        edited = dict(ADULT_PLAN)
        edited["nutrition"] = {"calories": 2100, "protein_g": 144}
        assert not recorder.covers(record, edited)
        assert hash_plan(edited) != record.plan_hash

    def test_payload_object_works(self):
        record = ConfirmationRecorder().record({
            "plan": ADULT_PLAN,
            "reply": "I confirm this plan",
            "speaker": "the user",
            "check_in": passing_check_in(),
        })
        assert record.confirmed
        assert record.quoted_words == "I confirm this plan"

    def test_normalize_keeps_clear_yes_only(self):
        assert normalize_reply("YES") == "yes"
        assert normalize_reply("sure I guess") == "sure i guess"

    @pytest.mark.parametrize("reply", [
        "yes",
        "yep",
        "yeah",
        "confirm",
        "confirmed",
        "lock it in",
        "I confirm this plan",
        "Yes!",
        "yes.",
        "lock it in!",
        "yes 👍",
        "yes 💪",
        "yes 🔥",
        "yes ✅",
        "yes ✔",
        "👍",
        "👍\U0001F3FB",
        "👍\U0001F3FC",
        "👍\U0001F3FD",
        "👍\U0001F3FE",
        "👍\U0001F3FF",
        "yes <3",
        "yes \u2714\uFE0F",
        "sounds good",
        "sounds good!",
        "let's go",
        "Let's go!",
        "lets gooo",
        "ok",
        "ok.",
        "ok fine",
        "do it",
        "do it 👍",
    ])
    def test_bare_yes_words_are_accepted(self, reply):
        assert is_clear_yes(reply)
        record = ConfirmationRecorder().record(
            ADULT_PLAN, reply, "user", passing_check_in()
        )
        assert record.confirmed
        assert record.quoted_words == reply

    @pytest.mark.parametrize("reply", [
        "yes, I have chest pain",
        "yes, my knee hurts",
        "yes stop",
        "yes cancel",
        "yes undo",
        "yes never mind",
        "yes, wait",
        "yes later",
        "yeah right",
        "yes make it six days",
        "yes, without squats",
        "yes lighter please",
        "yes to the old plan",
        "yes for next week",
        "yeah, though make it heavier",
        "sure I guess",
        "looks fine",
        "whatever",
        "maybe",
        "ok, my knee hurts",
        "sounds good?",
        "do it tomorrow",
        "yes, what's for dinner?",
        "yes, болит грудь",
        "yes 胸が痛い",
        "yes 我胸口疼",
        "yes, ألم في الصدر",
        "yes 😊 चक्कर आ रहा है",
        "yes 🤕",
        "yes 🚑",
        "yes 🤮",
        "yes 🫀💔",
        "yes?",
        "yes??",
        "yes\u200b",
        "ok fine?",
        "lets gooo unless I'm sore",
        "yes ✔ my knee hurts",
        "yes <3 but change the days",
        "yes </3",
        "👍 and make it heavier",
    ])
    def test_anything_past_a_bare_yes_is_refused(self, reply):
        assert not is_clear_yes(reply)
        record = ConfirmationRecorder().record(
            ADULT_PLAN, reply, "user", passing_check_in()
        )
        assert record.confirmed is False
        assert record.quoted_words == reply

    def test_a_red_flag_in_the_reply_is_the_pause(self):
        reply = "yes, I have chest pain"
        scanned = RedFlagChecker().scan_text(reply)
        assert scanned.pause_plan
        record = ConfirmationRecorder().record(
            ADULT_PLAN, reply, "user", passing_check_in()
        )
        assert record.confirmed is False
        assert scanned.message in record.message

    def test_a_built_record_a_bumped_copy_and_a_future_stamp_do_not_cover(self):
        forged = ConfirmationRecord(
            confirmed=True,
            plan_hash=hash_plan(ADULT_PLAN),
            quoted_words="yes",
            speaker="user",
            message="Confirmed. Quoted words: yes",
            errors=[],
            timestamp="2099-01-01T00:00:00Z",
        )
        assert ConfirmationRecorder().covers(forged, ADULT_PLAN) is False
        real = ConfirmationRecorder().record(ADULT_PLAN, "yes", "user", passing_check_in())
        assert ConfirmationRecorder().covers(real, ADULT_PLAN) is True
        real.record_id = "forged-id"
        real.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert ConfirmationRecorder().covers(real, ADULT_PLAN) is False
        future = ConfirmationRecorder().record(ADULT_PLAN, "yes", "user", passing_check_in())
        future.timestamp = "2099-01-01T00:00:00Z"
        assert ConfirmationRecorder().covers(future, ADULT_PLAN) is False
        now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
        assert timestamp_is_current(now.strftime("%Y-%m-%dT%H:%M:%SZ"), now)
        assert timestamp_is_current((now + timedelta(minutes=4)).strftime("%Y-%m-%dT%H:%M:%SZ"), now)
        assert timestamp_is_current((now + timedelta(minutes=6)).strftime("%Y-%m-%dT%H:%M:%SZ"), now) is False
        assert timestamp_is_current("2099-01-01T00:00:00Z", now) is False


class TestPlanCheckFollowUps:
    def test_valid_plan_needs_a_passing_check_in(self):
        missing = PlanValidator().validate_plan(ADULT_PLAN)
        assert not missing.valid
        assert "check-in" in " ".join(missing.errors).lower()

        passed = PlanValidator().validate_plan(
            ADULT_PLAN, check_in_result=passing_check_in()
        )
        assert passed.valid
        assert passed.errors == []

    def test_forged_readiness_dict_does_not_unlock_a_minor(self):
        plan = {
            "user": {
                "sex": "M",
                "weight_kg": 55,
                "age": 15,
                "height_cm": 170,
                "medical_clearance": True,
            },
            "training": {"previous_load": 80, "current_load": 84},
        }
        forged = PlanValidator().validate_plan(
            plan,
            {"blocked": False, "clearance": "clear"},
            passing_check_in(),
        )
        assert not forged.valid
        assert "under 18" in " ".join(forged.errors).lower()

        real = PlanValidator().validate_plan(
            plan, minor_screen(15), passing_check_in()
        )
        assert real.valid is False
        assert "under 18" in " ".join(real.errors).lower()

    def test_user_block_alone_is_not_a_plan(self):
        plan = {
            "user": {
                "sex": "F",
                "weight_kg": 60,
                "age": 28,
                "height_cm": 165,
            }
        }
        result = PlanValidator().validate_plan(plan, check_in_result=passing_check_in())
        assert not result.valid
        blob = " ".join(result.errors).lower()
        assert "user block" in blob or "not a plan" in blob

    def test_minor_with_real_screen_still_gets_no_calorie_target(self):
        plan = {
            "user": {"sex": "F", "weight_kg": 50, "age": 16, "height_cm": 160},
            "nutrition": {"calories": 1800},
        }
        result = PlanValidator().validate_plan(
            plan, minor_screen(16), passing_check_in()
        )
        assert not result.valid
        blob = " ".join(result.errors).lower()
        assert "under 18" in blob
        assert "floor" not in blob


def test_is_plan_yes_is_tied_to_the_proposal_hash():
    import inspect

    from signals import Outreach

    assert is_clear_yes("yes") is True
    assert is_plan_yes("yes", None) is False
    assert is_plan_yes("yes", "") is False
    assert is_plan_yes("yes", "abc") is True
    assert is_plan_yes("ok", "abc") is True
    source = inspect.getsource(Outreach.accept)
    assert "is_plan_yes" in source
    assert "is_clear_yes" not in source


def test_seal_keys_live_in_a_gitignored_install_file():
    from pathlib import Path

    from seal_secret import install_secret, seal_hex

    root = Path(__file__).resolve().parent
    for name in ("red_flag_check.py", "readiness_screen.py", "record_confirmation.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "gainzbot-scan-check-in-v1" not in text
        assert "gainzbot-readiness-screen-v1" not in text
        assert "gainzbot-record-confirmation-v1" not in text
    key = install_secret()
    assert len(key) >= 32
    assert (root / "data" / "seal.key").is_file()
    assert install_secret() == key
    assert "data/" in (root / ".gitignore").read_text(encoding="utf-8")
    assert seal_hex(b"confirmation", "payload") == seal_hex("confirmation", "payload")
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "tamper-evidence, not security" in readme
    assert "mode 0600" in readme


def test_seal_key_is_mode_0600_and_an_unreadable_key_is_not_overwritten(tmp_path, monkeypatch):
    import os

    from seal_secret import install_secret, seal_hex

    path = tmp_path / "seal.key"
    monkeypatch.setattr("seal_secret._key_path", lambda: str(path))
    key = install_secret()
    assert key is not None and len(key) >= 32
    assert path.stat().st_mode & 0o777 == 0o600
    assert install_secret() == key

    short = tmp_path / "short.key"
    short.write_bytes(b"tiny")
    monkeypatch.setattr("seal_secret._key_path", lambda: str(short))
    assert install_secret() is None
    assert short.read_bytes() == b"tiny"

    blocked = tmp_path / "blocked.key"
    original = b"k" * 32
    blocked.write_bytes(original)
    monkeypatch.setattr("seal_secret._key_path", lambda: str(blocked))
    real_open = open

    def guarded(file, *args, **kwargs):
        target = file if isinstance(file, (str, bytes)) else getattr(file, "name", None)
        if target is not None and os.path.abspath(str(target)) == os.path.abspath(blocked):
            raise PermissionError("blocked")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", guarded)
    assert install_secret() is None
    descriptor = os.open(blocked, os.O_RDONLY)
    try:
        assert os.read(descriptor, 64) == original
    finally:
        os.close(descriptor)
    monkeypatch.setattr("seal_secret.install_secret", lambda: None)
    try:
        seal_hex(b"confirmation", "payload")
        raised = False
    except OSError:
        raised = True
    assert raised
