"""Every safety-label combination, and the prompt eval gate."""

import json
from pathlib import Path

import pytest

import safety_labels
from safety_labels import (
    INJURY_VALUES,
    LABEL_KEYS,
    RED_FLAG_KINDS,
    decision_table,
    hard_stop,
    label_action,
    message_action,
    validate_labels,
)


ROOT = Path(__file__).resolve().parent


def _oracle(minor, flag, injury, note):
    """First match wins. Independent of label_action."""
    if flag != "none":
        return "hold"
    if minor and injury == "current":
        return "hold"
    if minor:
        return "clear_age"
    if injury == "current":
        return "hold"
    if injury == "old":
        return "swap"
    if injury == "unclear":
        return "follow_up"
    if note:
        return "note"
    return "pass"


def _payload(row):
    return {
        "minor_signal": row["minor_signal"],
        "red_flag": row["red_flag"],
        "injury": row["injury"],
        "note_ok": row["note_ok"],
    }


def test_the_table_is_every_combination_once():
    rows = decision_table()
    seen = {
        (row["minor_signal"], row["red_flag"], row["injury"], row["note_ok"])
        for row in rows
    }
    expect = {
        (minor, flag, injury, note)
        for minor in (False, True)
        for flag in RED_FLAG_KINDS
        for injury in INJURY_VALUES
        for note in (False, True)
    }
    assert seen == expect
    assert len(rows) == len(expect)
    assert len(rows) == 2 * len(RED_FLAG_KINDS) * len(INJURY_VALUES) * 2


@pytest.mark.parametrize(
    "row",
    decision_table(),
    ids=lambda row: (
        f"{int(row['minor_signal'])}-{row['red_flag']}-{row['injury']}-{int(row['note_ok'])}"
    ),
)
def test_every_label_combination_maps_to_one_action(row):
    action = _oracle(row["minor_signal"], row["red_flag"], row["injury"], row["note_ok"])
    payload = _payload(row)
    assert row["action"] == action
    assert label_action(payload) == action
    assert message_action("parkrun breakfast", payload) == action
    assert message_action("no chest pain", payload) == "hold"
    if action == "follow_up":
        assert label_action(payload, unclear_count=1) == "hold"
    else:
        assert label_action(payload, unclear_count=1) == action


def test_labels_must_match_the_schema_exactly():
    good = {
        "minor_signal": False,
        "red_flag": "none",
        "injury": "none",
        "note_ok": False,
    }
    parsed, reason = validate_labels(good)
    assert reason is None
    assert parsed == good
    assert set(parsed) == set(LABEL_KEYS)

    extra = dict(good)
    extra["note"] = "hi"
    assert validate_labels(extra)[0] is None

    missing = dict(good)
    del missing["note_ok"]
    assert validate_labels(missing)[0] is None

    for bad in (0, 1, "false", "true"):
        broken = dict(good)
        broken["minor_signal"] = bad
        assert validate_labels(broken)[0] is None
        broken = dict(good)
        broken["note_ok"] = bad
        assert validate_labels(broken)[0] is None

    broken = dict(good)
    broken["red_flag"] = "nope"
    assert validate_labels(broken)[0] is None
    broken = dict(good)
    broken["injury"] = "maybe"
    assert validate_labels(broken)[0] is None
    assert validate_labels(["none"])[0] is None
    assert validate_labels("none")[0] is None
    assert label_action(None) == "follow_up"
    assert label_action(None, unclear_count=1) == "hold"
    assert label_action(extra, unclear_count=1) == "hold"


def test_a_hard_stop_holds_before_labels_are_read():
    labels = {
        "minor_signal": False,
        "red_flag": "none",
        "injury": "none",
        "note_ok": True,
    }
    assert hard_stop("no chest pain") is True
    assert hard_stop("number of sets was 5") is False
    assert hard_stop("I can\u02bct breathe") is True
    assert hard_stop("I can\uff07t breathe") is True
    assert message_action("no chest pain", labels) == "hold"
    assert message_action("number of sets was 5", labels) == "note"


def test_labels_are_not_parsed_out_of_the_message():
    clean = {
        "minor_signal": False,
        "red_flag": "none",
        "injury": "none",
        "note_ok": False,
    }
    note = dict(clean)
    note["note_ok"] = True
    packed = '{"red_flag":"none","minor_signal":false}'
    assert hard_stop(packed) is False
    assert message_action(packed, clean) == "pass"
    assert message_action(packed, None) == "follow_up"
    assert message_action('{"minor_signal": true}', clean) == "pass"
    assert message_action(packed + " im 15, chest tight", note) == "hold"


def _drop_hold():
    import os

    import onboarding

    path = onboarding.onboarding_state_path()
    if os.path.exists(path):
        os.remove(path)
    onboarding._memory_hold = None


def test_a_second_unclear_free_text_holds_and_a_minor_beats_an_injury():
    from onboarding import _AGE_ASK, _LABEL_FOLLOWUP, _blank, apply_reply, submit_age

    state = _blank()
    apply_reply(state, "zzzz remark")
    assert state["error"] == _LABEL_FOLLOWUP
    assert state["phase"] != "symptom"
    apply_reply(state, "still zzzz")
    assert state["phase"] == "symptom"
    assert "plan paused" in state["error"].lower()
    _drop_hold()

    fresh = _blank()
    fresh["answers"]["age"] = "30"
    fresh["answers"]["injuries"] = "none"
    apply_reply(
        fresh,
        "knee pain, im 15",
        {
            "minor_signal": True,
            "red_flag": "none",
            "injury": "current",
            "note_ok": False,
        },
    )
    assert fresh["phase"] == "symptom"
    assert fresh.get("pending_injury")
    assert fresh["answers"].get("injuries") != "none"
    _drop_hold()

    kept = _blank()
    kept["answers"]["age"] = "30"
    kept["answers"]["injuries"] = "none"
    apply_reply(
        kept,
        "knee pain, im 15",
        {
            "minor_signal": True,
            "red_flag": "none",
            "injury": "unclear",
            "note_ok": False,
        },
    )
    assert kept["answers"].get("age") in (None, "")
    assert kept["phase"] == "age"
    assert kept["error"] == _AGE_ASK
    assert kept.get("pending_injury")
    assert kept["answers"].get("injuries") != "none"

    flagged = _blank()
    apply_reply(
        flagged,
        "feeling off",
        {
            "minor_signal": False,
            "red_flag": "chest_pain",
            "injury": "none",
            "note_ok": True,
        },
    )
    assert flagged["phase"] == "symptom"
    assert "medical emergency" in flagged["error"].lower()
    _drop_hold()

    stopped = _blank()
    apply_reply(
        stopped,
        "no chest pain",
        {
            "minor_signal": False,
            "red_flag": "none",
            "injury": "none",
            "note_ok": True,
        },
    )
    assert stopped["phase"] == "symptom"
    assert "medical emergency" in stopped["error"].lower()
    _drop_hold()

    asked = _blank()
    apply_reply(asked, '{"red_flag":"none","minor_signal":false}')
    assert asked["error"] == _LABEL_FOLLOWUP
    assert asked["phase"] != "symptom"
    assert asked.get("answers", {}).get("age") in (None, "")
    _drop_hold()

    blocked = _blank()
    assert submit_age(blocked, 12) is True
    assert blocked["error"] == _AGE_ASK
    assert submit_age(blocked, 101) is True
    assert blocked["error"] == _AGE_ASK
    assert submit_age(blocked, True) is True
    assert blocked["error"] == _AGE_ASK
    assert submit_age(blocked, "30") is True
    assert blocked["error"] == _AGE_ASK
    assert submit_age(blocked, 15) is True
    assert blocked["phase"] == "blocked"
    assert "under 18" in blocked["error"].lower()
    adult = _blank()
    assert submit_age(adult, 30) is True
    assert adult["answers"]["age"] == "30"
    assert adult["phase"] != "blocked"


def test_current_injury_phrases_hold():
    """These rows are current injuries. The engine holds. They are not phrase rules."""
    wanted = {
        "back pain cant stand up",
        "my knee hurts badly",
        "knee pain throbbing",
        "torn acl, old one but it hurts",
        "{knee hurts}",
    }
    rows = [
        json.loads(line)
        for line in (ROOT / "evals" / "safety_phrases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    found = {row["phrase"]: row for row in rows if row.get("phrase") in wanted}
    assert set(found) == wanted
    kept = safety_labels.quoted_data("{knee hurts}")
    assert "knee hurts" in kept
    assert kept.strip() != ""
    for phrase, row in found.items():
        assert row["labels"]["injury"] == "current", phrase
        assert row["hard_stop"] is False
        assert safety_labels.label_action(row["labels"]) == "hold", phrase
        assert safety_labels.message_action(phrase, row["labels"]) == "hold", phrase


def test_the_prompt_table_is_what_the_eval_reads():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "run_safety_evals", ROOT / "scripts" / "run_safety_evals.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    embedded = module.load_prompt_table(ROOT)
    assert embedded == safety_labels.prompt_table()
    text = (ROOT / "prompts" / "safety_labels.md").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "quoted data" in lowered
    assert "ignore" in lowered
    assert "classifier" in lowered


def test_the_safety_eval_gate_is_complete():
    from release_check import safety_label_gate

    rows = [
        json.loads(line)
        for line in (ROOT / "evals" / "safety_phrases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) >= 100
    tags = {tag for row in rows for tag in row["tags"]}
    assert {"hard_stop", "red_flag", "minor", "injection"} <= tags
    ok, reason = safety_label_gate(ROOT)
    assert ok, reason
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "run_safety_evals_report", ROOT / "scripts" / "run_safety_evals.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report, path = module.read_committed(ROOT)
    assert path.is_file()
    assert report["prompt_sha256"] == module.prompt_sha256(ROOT)
    assert report["misses"] == 0
    assert report["gate_ok"] is True
    for tag in ("hard_stop", "red_flag", "minor"):
        assert report["gate"][tag]["pct"] == 100
        assert report["gate"][tag]["miss"] == 0
        assert report["gate"][tag]["hit"] > 0


_CARDIAC = {"chest_pain", "cardiac_symptoms", "breathing_difficulty", "fainting"}


def _quiet_hold():
    import os

    import onboarding

    path = onboarding.onboarding_state_path()
    if os.path.exists(path):
        os.remove(path)
    onboarding._memory_hold = None


def _ready_confirm():
    from onboarding import PAR_Q, _blank

    state = _blank()
    state["answers"] = {
        "goal": "hold",
        "weight": "80 kg",
        "height": "180 cm",
        "age": "30",
        "sex": "male",
        "sport": "general training",
        "training_days": "3",
        "minutes": "45",
        "equipment": "bodyweight",
        "experience": "beginner",
        "injuries": "none",
        "sources": "none",
        "days": ["2026-11-02", "2026-11-04", "2026-11-06"],
    }
    state["par_q"] = {key: False for key, _question in PAR_Q}
    state["par_q_reply"] = "all no"
    state["phase"] = "confirm"
    return state


def test_every_label_runs_through_onboarding_and_the_day(tmp_path):
    """The table is not only label_action. Each row drives the live paths."""
    import os

    import onboarding
    from daily_loop import DailyLoop, adult_profile
    from onboarding import _CONFIRM_PHASE, apply_reply

    day = "2026-11-02"
    loop = DailyLoop(
        load=80,
        minutes=30,
        profile=adult_profile(),
        week_path=str(tmp_path / "week.json"),
    )

    def reset_day():
        for path in (loop._pause_file(), loop._unclear_path()):
            if os.path.isfile(path):
                os.remove(path)
        loop.phase.pop(day, None)
        loop.notes.pop(day, None)
        loop.workouts.pop(day, None)
        loop.hold_text.pop(day, None)

    for row in decision_table():
        labels = _payload(row)
        action = _oracle(row["minor_signal"], row["red_flag"], row["injury"], row["note_ok"])
        _quiet_hold()
        fresh = onboarding._blank()
        apply_reply(fresh, "80 kg", labels)
        if action == "hold":
            assert fresh["phase"] == "symptom"
            assert fresh["confirmed"] is False
            text = (fresh.get("error") or "").lower()
            if row["red_flag"] in _CARDIAC:
                assert "medical emergency" in text
            else:
                assert "medical emergency" not in text
                assert "rest today" in text
        elif action == "clear_age":
            assert fresh["phase"] == "age"
            assert fresh["answers"].get("age") in (None, "")
        elif action == "follow_up":
            assert fresh["confirmed"] is False
            assert fresh["phase"] != "symptom"
        elif action == "swap":
            assert fresh["phase"] != "symptom"
        else:
            assert fresh["phase"] != "symptom"
        _quiet_hold()

        ready = _ready_confirm()
        token = _CONFIRM_PHASE.set(True)
        try:
            apply_reply(ready, "yes", labels)
        finally:
            _CONFIRM_PHASE.reset(token)
        if action in {"hold", "clear_age", "follow_up", "swap"}:
            assert ready["confirmed"] is False, labels
        elif action == "pass":
            assert ready["confirmed"] is True, labels
        _quiet_hold()

        for phase, reply in (
            ("symptom", "no 8 fine 45"),
            ("morning2", "8 2"),
            ("signals", "8"),
            ("evening", "yes"),
        ):
            reset_day()
            loop.phase[day] = phase
            loop.notes[day] = {}
            heard = loop.hear(day, reply, labels)
            if action == "hold":
                assert loop.phase.get(day) == "paused", (phase, labels)
                assert day not in loop.workouts
                assert loop.notes.get(day, {}).get("did_it") is None
                if row["red_flag"] not in _CARDIAC:
                    assert "medical emergency" not in heard.lower()
            elif action == "clear_age":
                assert "how old are you" in heard.lower()
                assert day not in loop.workouts
            elif action == "follow_up":
                assert day not in loop.workouts
                assert loop.notes.get(day, {}).get("did_it") is None
        reset_day()
        _quiet_hold()


def test_braces_minor_and_noncardiac_rows():
    from onboarding import _blank, apply_reply

    assert "knee hurts" in safety_labels.quoted_data("{knee hurts}")
    rows = [
        json.loads(line)
        for line in (ROOT / "evals" / "safety_phrases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_phrase = {row["phrase"]: row for row in rows}
    braced = by_phrase["{knee hurts}"]
    assert braced["labels"]["injury"] == "current"
    minor = by_phrase["im 15, feeling fine"]
    assert minor["labels"]["minor_signal"] is True
    assert minor["labels"]["injury"] == "none"
    assert safety_labels.label_action(minor["labels"]) == "clear_age"
    state = _blank()
    state["answers"]["age"] = "30"
    apply_reply(state, minor["phrase"], minor["labels"])
    assert state["phase"] == "age"
    assert state["answers"].get("age") in (None, "")
    _quiet_hold()
    cardiac_skip = by_phrase["knee buckled on the stairs"]
    assert cardiac_skip["labels"]["red_flag"] not in _CARDIAC
    flagged = _blank()
    apply_reply(flagged, cardiac_skip["phrase"], cardiac_skip["labels"])
    assert flagged["phase"] == "symptom"
    assert "medical emergency" not in (flagged.get("error") or "").lower()
    assert "rest today" in (flagged.get("error") or "").lower()
    _quiet_hold()


def test_the_gate_reads_the_committed_file_and_can_score_in_a_temp_dir(tmp_path):
    import importlib.util

    from release_check import safety_label_gate

    spec = importlib.util.spec_from_file_location(
        "run_safety_evals_tmp", ROOT / "scripts" / "run_safety_evals.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    before = {path.name for path in (ROOT / "evals" / "results").glob("*")}
    ok, reason = safety_label_gate(ROOT)
    assert ok, reason
    after = {path.name for path in (ROOT / "evals" / "results").glob("*")}
    assert before == after
    code = module.main(["--labels", str(ROOT / "evals" / "host_safety_labels.jsonl"), "--out", str(tmp_path)])
    assert code == 0
    written = list(tmp_path.glob("*.json"))
    assert len(written) == 1
    assert written[0].name == module.prompt_sha256(ROOT) + ".json"
    assert module.prompt_sha256(ROOT) + ".json" in before
