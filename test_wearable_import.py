#!/usr/bin/env python3
"""Tests for wearable_import.py."""

import io
import zipfile

from wearable_import import GROK_SUMMARY_PROMPT, WearableImport


EXPORT = """<?xml version="1.0" encoding="UTF-8"?>
<HealthData>
  <Record type="HKQuantityTypeIdentifierBodyMass" unit="kg" value="80"
    startDate="2026-10-01 08:00:00 -0700" endDate="2026-10-01 08:00:00 -0700"/>
  <Record type="HKQuantityTypeIdentifierBodyMass" unit="lb" value="176.37"
    startDate="2026-10-02 08:00:00 -0700" endDate="2026-10-02 08:00:00 -0700"/>
  <Record type="HKQuantityTypeIdentifierStepCount" unit="count" value="4000"
    startDate="2026-10-01 09:00:00 -0700" endDate="2026-10-01 10:00:00 -0700"/>
  <Record type="HKQuantityTypeIdentifierStepCount" unit="count" value="2500"
    startDate="2026-10-01 18:00:00 -0700" endDate="2026-10-01 19:00:00 -0700"/>
  <Record type="HKCategoryTypeIdentifierSleepAnalysis"
    value="HKCategoryValueSleepAnalysisInBed"
    startDate="2026-10-01 22:00:00 -0700" endDate="2026-10-02 07:00:00 -0700"/>
  <Record type="HKCategoryTypeIdentifierSleepAnalysis"
    value="HKCategoryValueSleepAnalysisAsleepUnspecified"
    startDate="2026-10-01 23:00:00 -0700" endDate="2026-10-02 06:30:00 -0700"/>
  <Workout workoutActivityType="HKWorkoutActivityTypeRunning" duration="30"
    durationUnit="min" startDate="2026-10-02 07:00:00 -0700" endDate="2026-10-02 07:30:00 -0700"/>
</HealthData>
"""


def called():
    raise AssertionError("fetcher should not be called")


class TestAppleHealth:
    def test_export_reads_weight_steps_sleep_and_workouts(self):
        result = WearableImport().parse_apple_health(EXPORT)
        assert result["ok"] is True
        assert result["connected"] is False
        assert result["applied"] is False
        assert result["weights"][0] == {"date": "2026-10-01", "kg": 80}
        assert result["weights"][1]["date"] == "2026-10-02"
        assert 79 < result["weights"][1]["kg"] < 81
        assert result["steps"] == [{"date": "2026-10-01", "steps": 6500}]
        assert result["sleep"] == [{"date": "2026-10-01", "hours": 7.5}]
        assert result["workouts"][0]["activity"] == "Running"
        assert result["workouts"][0]["minutes"] == 30

    def test_zip_export_is_read_from_export_xml(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("apple_health_export/export.xml", EXPORT)
        result = WearableImport().parse_apple_health(buffer.getvalue())
        assert result["ok"] is True
        assert result["steps"][0]["steps"] == 6500

    def test_bad_xml_stores_nothing(self):
        result = WearableImport().parse_apple_health("<HealthData>")
        assert result["ok"] is False
        assert result["stored"] is False
        assert result["connected"] is False

    def test_a_file_export_is_read(self, tmp_path):
        path = tmp_path / "export.xml"
        path.write_text(EXPORT)
        result = WearableImport().parse_apple_health(str(path))
        assert result["weights"][0]["kg"] == 80


class TestScreenshot:
    def test_prompt_asks_for_a_summary_and_no_account(self):
        text = GROK_SUMMARY_PROMPT.lower()
        assert "steps" in text
        assert "sleep" in text
        assert "do not connect" in text

    def test_summary_without_a_yes_is_not_stored(self):
        result = WearableImport().store_summary(
            {"steps": 8000, "sleep_hours": 7},
            user_ok=False,
        )
        assert result["stored"] is False
        assert result["connected"] is False
        assert "ok" in result["message"].lower()

    def test_a_yes_stores_the_summary_without_connecting(self):
        result = WearableImport().store_summary(
            {"date": "2026-10-30", "steps": 8000, "sleep_hours": 7.5, "resting_hr": 52, "weight_kg": 80},
            user_ok=True,
        )
        assert result["stored"] is True
        assert result["connected"] is False
        assert result["applied"] is False
        assert result["reading"]["steps"] == 8000
        assert result["reading"]["resting_hr"] == 52

    def test_a_string_yes_does_not_count(self):
        result = WearableImport().store_summary({"steps": 1000}, user_ok="true")
        assert result["stored"] is False

    def test_bad_summary_numbers_are_refused(self):
        result = WearableImport().store_summary(
            {"resting_hr": 10, "steps": 1000},
            user_ok=True,
        )
        assert result["stored"] is False


class TestGarmin:
    def test_flag_off_does_not_connect_or_call_out(self):
        result = WearableImport().fetch_garmin(user_ok=True, fetcher=called, enabled=False)
        assert result["connected"] is False
        assert result["stored"] is False
        assert "off" in result["message"].lower()

    def test_flag_on_without_a_yes_does_not_call_out(self):
        result = WearableImport().fetch_garmin(user_ok=False, fetcher=called, enabled=True)
        assert result["connected"] is False
        assert "ok" in result["message"].lower()

    def test_flag_on_with_a_yes_stores_the_fetcher_result(self):
        def fetcher():
            return {"steps": 9000, "sleep_hours": 8}

        result = WearableImport().fetch_garmin(user_ok=True, fetcher=fetcher, enabled=True)
        assert result["connected"] is True
        assert result["stored"] is True
        assert result["applied"] is False
        assert result["reading"]["steps"] == 9000

    def test_a_bad_fetcher_payload_is_not_stored(self):
        result = WearableImport().fetch_garmin(
            user_ok=True,
            fetcher=lambda: {"steps": -5},
            enabled=True,
        )
        assert result["stored"] is False
        assert result["connected"] is False
