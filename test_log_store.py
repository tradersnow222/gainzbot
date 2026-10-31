#!/usr/bin/env python3
"""Tests for the on-disk log and the scripts that read and write it."""

import json
import os
from pathlib import Path

from dashboard import Dashboard
from log_store import LogStore
from morning_checkin import MorningCheckIn
from photo_food_log import FoodLog
from record_confirmation import ConfirmationRecorder
from red_flag_check import RedFlagChecker, is_passing_check_in
from set_logger import SetLogger
from trend_review import TrendReview


ROOT = Path(__file__).resolve().parent


def passing_check_in():
    checker = RedFlagChecker()
    answers = {aliases[0]: "no" for _flag, aliases in checker.CHECKLIST_GROUPS}
    result = checker.scan_check_in({
        "symptom_checklist": answers,
        "notes": "Easy lift, slept fine.",
    })
    assert is_passing_check_in(result)
    return result


def recorded(plan):
    return ConfirmationRecorder().record(plan, "yes", "user", passing_check_in())


def test_a_missing_path_fails_closed(tmp_path):
    refused = LogStore(None).append("meals", {"date": "2026-10-30"})
    assert refused["ok"] is False
    assert "path" in refused["message"].lower()
    blank = LogStore("  ")
    assert blank.error


def test_the_first_append_creates_the_file_and_a_reload_sees_it(tmp_path):
    path = tmp_path / "log.json"
    store = LogStore(path)
    saved = store.append("weights", {"date": "2026-10-30", "kg": 80})
    assert saved["stored"] is True
    again = LogStore(path)
    assert again.error is None
    assert again.data["weights"] == [{"date": "2026-10-30", "kg": 80}]
    assert again.data["meals"] == []


def test_a_corrupt_file_is_not_appended_to(tmp_path):
    path = tmp_path / "log.json"
    path.write_text("{", encoding="utf-8")
    store = LogStore(path)
    refused = store.append("sets", {"date": "2026-10-30", "exercise": "squat", "weight": 100, "reps": 5})
    assert refused["ok"] is False
    assert path.read_text(encoding="utf-8") == "{"


def test_unknown_kind_and_bad_entries_are_refused(tmp_path):
    path = tmp_path / "log.json"
    store = LogStore(path)
    assert store.append("notes", {"date": "2026-10-30"})["ok"] is False
    assert store.append("meals", ["oats"])["ok"] is False
    assert store.append("meals", {"date": "2026-10-30", "calories": float("nan")})["ok"] is False
    assert not path.exists()


def test_an_unknown_key_fails_the_whole_file(tmp_path):
    path = tmp_path / "log.json"
    path.write_text(json.dumps({"meals": [], "extra": []}), encoding="utf-8")
    store = LogStore(path)
    assert store.error
    assert store.as_dashboard() is None
    assert store.as_trend() is None


def test_a_write_failure_rolls_back(tmp_path, monkeypatch):
    path = tmp_path / "log.json"
    store = LogStore(path)
    store.append("weights", {"date": "2026-10-29", "kg": 80})

    def boom():
        raise OSError("disk full")

    monkeypatch.setattr(store, "_write", boom)
    refused = store.append("weights", {"date": "2026-10-30", "kg": 81})
    assert refused["ok"] is False
    assert store.data["weights"] == [{"date": "2026-10-29", "kg": 80}]


def test_dashboard_and_trend_read_the_saved_rows(tmp_path):
    path = tmp_path / "log.json"
    store = LogStore(path)
    store.append("meals", {"date": "2026-10-28", "calories": 500, "protein_g": 30, "items": ["oats"]})
    store.append("meals", {"date": "2026-10-29", "calories": 600, "protein_g": 40, "items": ["rice"]})
    store.append("weights", {"date": "2026-10-28", "kg": 80})
    store.append("weights", {"date": "2026-10-29", "kg": 80.2})
    store.append("sets", {"date": "2026-10-29", "exercise": "squat", "weight": 100, "reps": 5})
    built = Dashboard().build_saved(path, as_of="2026-10-29", window_days=7)
    assert built["applied"] is False
    assert built["enough_data"] is True
    titles = [chart["title"] for chart in built["charts"]]
    assert titles[0] == "Weight"
    reviewed = TrendReview().review_saved(path, as_of="2026-10-29T00:00:00Z", window_days=7)
    assert reviewed["applied"] is False
    assert reviewed["proposals"] == []


def test_a_bad_log_does_not_invent_a_dashboard_or_a_change(tmp_path):
    path = tmp_path / "log.json"
    path.write_text("[]", encoding="utf-8")
    built = Dashboard().build_saved(path)
    assert built["enough_data"] is False
    assert built["applied"] is False
    assert built["message"] != "Dashboard ready."
    reviewed = TrendReview().review_saved(path)
    assert reviewed["proposals"] == []
    assert reviewed["message"] == "No change proposed."
    assert reviewed["applied"] is False


def test_a_bad_confirmation_history_proposes_nothing(tmp_path):
    path = tmp_path / "log.json"
    LogStore(path).append("confirmations", {
        "date": "2026-10-20",
        "confirmed": True,
        "changes": {"load": 100, "notes": "nope"},
    })
    for day in ("2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29"):
        LogStore(path).append("weights", {"date": day, "kg": 80})
    reviewed = TrendReview().review_saved(path, as_of="2026-10-29T00:00:00Z", window_days=7)
    assert reviewed["message"] == "No change proposed."
    assert reviewed["proposals"] == []


def test_food_sets_and_checkins_append(tmp_path):
    used = tmp_path / "used.json"
    path = tmp_path / "log.json"
    meal = {"items": ["rice", "chicken"], "calories": 600, "protein_g": 40}
    food = FoodLog(used)
    stored = food.store_estimate(meal, "2026-10-30", recorded(meal), log_path=path)
    assert stored["stored"] is True
    log = LogStore(path)
    assert log.data["meals"][0]["calories"] == 600
    assert log.data["used_records"][0]["record_id"]
    assert log.data["confirmations"][0]["kind"] == "meal"
    assert "changes" not in log.data["confirmations"][0]
    again = FoodLog(used).store_estimate(meal, "2026-10-30", recorded(meal), log_path=path)
    assert again["stored"] is True
    same = ConfirmationRecorder().record(meal, "yes", "user", passing_check_in())
    first = FoodLog(tmp_path / "used-b.json")
    assert first.store_estimate(meal, "2026-10-30", same, log_path=tmp_path / "log-b.json")["stored"] is True
    assert first.store_estimate(meal, "2026-10-30", same, log_path=tmp_path / "log-b.json")["stored"] is False

    lifted = SetLogger().log_set("squat", 100, 5, "2026-10-30", log_path=path)
    assert lifted["stored"] is True
    assert LogStore(path).data["sets"][-1]["exercise"] == "squat"

    entry = {"sleep": 8, "soreness": 1, "energy": 5, "stress": 1, "date": "2026-10-30"}
    checked = MorningCheckIn().check_in(entry, log_path=path)
    assert checked["ok"] is True
    assert LogStore(path).data["checkins"][-1]["sleep"] == 8
    missing_date = MorningCheckIn().check_in(
        {"sleep": 8, "soreness": 1, "energy": 5, "stress": 1},
        log_path=path,
    )
    assert missing_date["ok"] is False
    assert missing_date["proposal"] is None


def test_a_failed_log_save_keeps_the_meal_and_the_set_out(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    used = tmp_path / "used.json"
    meal = {"items": ["rice"], "calories": 500, "protein_g": 30}
    food = FoodLog(used)
    yes = recorded(meal)
    refused = food.store_estimate(meal, "2026-10-30", yes, log_path=blocked)
    assert refused["stored"] is False
    assert food.entries == []
    assert yes.record_id not in food.used_ids
    logger = SetLogger()
    missed = logger.log_set("squat", 100, 5, "2026-10-30", log_path=blocked)
    assert missed["ok"] is False
    assert logger.sets == []
    checked = MorningCheckIn().check_in(
        {"sleep": 8, "soreness": 1, "energy": 5, "stress": 1, "date": "2026-10-30"},
        log_path=blocked,
    )
    assert checked["ok"] is False
    assert checked["proposal"] is None


def test_a_failed_used_list_drops_the_meal_from_the_log(tmp_path, monkeypatch):
    path = tmp_path / "log.json"
    meal = {"items": ["rice"], "calories": 500, "protein_g": 30}
    food = FoodLog(tmp_path / "used.json")

    def boom(self, path, used_ids):
        raise OSError("disk full")

    monkeypatch.setattr(FoodLog, "_write_used", boom)
    refused = food.store_estimate(meal, "2026-10-30", recorded(meal), log_path=path)
    assert refused["stored"] is False
    assert food.entries == []
    assert food.used_ids == []
    assert LogStore(path).data["meals"] == []


def test_twenty_four_hours_of_sleep_is_kept_and_a_tenth_more_is_refused():
    """A calendar day holds 24 hours of sleep, and 24.1 does not fit."""
    ok = MorningCheckIn().check_in({"sleep": 24, "soreness": 1, "energy": 5, "stress": 1})
    assert ok["ok"] is True
    assert ok["day"] == "push"
    over = MorningCheckIn().check_in({"sleep": 24.1, "soreness": 1, "energy": 5, "stress": 1})
    assert over["ok"] is False
    assert "24" in over["message"]
    from wearable_import import WearableImport

    reading = {"date": "2026-10-30", "sleep_hours": 24}
    stored = WearableImport().store_summary(reading, recorded(reading))
    assert stored["stored"] is True
    longer = {"date": "2026-10-30", "sleep_hours": 24.1}
    refused = WearableImport().store_summary(longer, recorded(longer))
    assert refused["stored"] is False
    guide = (ROOT / "template" / "saved-logs.md").read_text(encoding="utf-8")
    assert "trend_review.TrendReview.review_saved" in guide
    assert "trend_review.review_saved" not in guide.replace("trend_review.TrendReview.review_saved", "")
    assert "does not store a proposed load" in guide
    assert "TrendReview.apply" in guide
    assert "\u2014" not in guide


def test_a_raw_confirmed_dict_is_not_a_baseline(tmp_path):
    from confirmed_change import last_confirmed_change

    path = tmp_path / "log.json"
    LogStore(path).append("confirmations", {
        "date": "2026-10-21T00:00:00Z",
        "confirmed": True,
        "changes": {"load": 100},
    })
    logs = LogStore(path).as_trend()
    assert "confirmed_changes" not in logs
    found = last_confirmed_change(logs.get("confirmed_changes"), "load", "2026-10-28T00:00:00Z")
    assert found.value is None


def test_apply_writes_a_covering_record_as_the_baseline(tmp_path):
    from confirmed_change import last_confirmed_change

    path = tmp_path / "log.json"
    proposal = {"summary": "Raise the load.", "changes": {"load": 110}}
    yes = recorded(proposal)
    missed = TrendReview().apply(proposal, yes, log_path=path, as_of="2026-10-21")
    assert missed["applied"] is False
    assert LogStore(path).data["confirmations"] == []
    applied = TrendReview().apply(
        proposal, yes, log_path=path, as_of="2026-10-21T00:00:00Z"
    )
    assert applied["applied"] is True
    logs = LogStore(path).as_trend()
    found = last_confirmed_change(logs["confirmed_changes"], "load", "2026-10-22T00:00:00Z")
    assert found.ok is True
    assert found.value == 110


def test_an_easy_day_does_not_store_a_proposed_load(tmp_path):
    path = tmp_path / "log.json"
    history = [{
        "date": "2026-10-21T00:00:00Z",
        "confirmed": True,
        "changes": {"load": 100},
    }]
    checked = MorningCheckIn().check_in(
        {"sleep": 5, "soreness": 1, "energy": 5, "stress": 1, "date": "2026-10-28"},
        confirmed_changes=history,
        as_of="2026-10-28T00:00:00Z",
        log_path=path,
    )
    assert checked["ok"] is True
    assert checked["proposal"]["changes"]["load"] == 90
    assert "load" not in LogStore(path).data["checkins"][-1]
    assert LogStore(path).as_trend()["training"] == []
