#!/usr/bin/env python3
"""Tests for wearable_import.py."""

import io
import zipfile

from record_confirmation import ConfirmationRecorder
from red_flag_check import RedFlagChecker, is_passing_check_in
from wearable_import import GROK_SUMMARY_PROMPT, WearableImport

APPLE = {"source": "apple_health"}
GARMIN = {"source": "garmin"}


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


def apple(source):
    return WearableImport().parse_apple_health(source, recorded(APPLE))


def summary(reading):
    return WearableImport().store_summary(reading, recorded(reading))


class TestAppleHealth:
    def test_export_reads_weight_steps_sleep_and_workouts(self):
        result = apple(EXPORT)
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
        result = apple(buffer.getvalue())
        assert result["ok"] is True
        assert result["steps"][0]["steps"] == 6500

    def test_bad_xml_stores_nothing(self):
        result = apple("<HealthData>")
        assert result["ok"] is False
        assert result["stored"] is False
        assert result["connected"] is False

    def test_a_file_export_is_read(self, tmp_path):
        path = tmp_path / "export.xml"
        path.write_text(EXPORT)
        result = apple(str(path))
        assert result["weights"][0]["kg"] == 80


class TestScreenshot:
    def test_prompt_asks_for_a_summary_and_no_account(self):
        text = GROK_SUMMARY_PROMPT.lower()
        assert "steps" in text
        assert "sleep" in text
        assert "do not connect" in text

    def test_summary_without_a_yes_is_not_stored(self):
        reading = {"date": "2026-10-30", "steps": 8000, "sleep_hours": 7}
        result = WearableImport().store_summary(reading)
        assert result["stored"] is False
        assert result["connected"] is False
        assert "record_confirmation" in result["message"]

    def test_a_yes_stores_the_summary_without_connecting(self):
        reading = {
            "date": "2026-10-30",
            "steps": 8000,
            "sleep_hours": 7.5,
            "resting_hr": 52,
            "weight_kg": 80,
        }
        result = summary(reading)
        assert result["stored"] is True
        assert result["connected"] is False
        assert result["applied"] is False
        assert result["reading"]["steps"] == 8000
        assert result["reading"]["resting_hr"] == 52

    def test_a_bare_true_does_not_count(self):
        reading = {"date": "2026-10-30", "steps": 1000}
        result = WearableImport().store_summary(reading, True)
        assert result["stored"] is False
        assert result["connected"] is False

    def test_bad_summary_numbers_are_refused(self):
        reading = {"date": "2026-10-30", "resting_hr": 10, "steps": 1000}
        result = summary(reading)
        assert result["stored"] is False


class TestGarmin:
    def test_flag_off_does_not_connect_or_call_out(self):
        result = WearableImport().fetch_garmin(
            confirmation=recorded(GARMIN), fetcher=called, enabled=False,
        )
        assert result["connected"] is False
        assert result["stored"] is False
        assert "off" in result["message"].lower()

    def test_flag_on_without_a_yes_does_not_call_out(self):
        result = WearableImport().fetch_garmin(confirmation=True, fetcher=called, enabled=True)
        assert result["connected"] is False
        assert "record_confirmation" in result["message"]

    def test_flag_on_with_a_yes_stores_the_fetcher_result(self):
        def fetcher():
            return {"date": "2026-10-30", "steps": 9000, "sleep_hours": 8}

        result = WearableImport().fetch_garmin(
            confirmation=recorded(GARMIN), fetcher=fetcher, enabled=True,
        )
        assert result["connected"] is True
        assert result["stored"] is True
        assert result["applied"] is False
        assert result["reading"]["steps"] == 9000

    def test_a_bad_fetcher_payload_is_not_stored(self):
        result = WearableImport().fetch_garmin(
            confirmation=recorded(GARMIN),
            fetcher=lambda: {"date": "2026-10-30", "steps": -5},
            enabled=True,
        )
        assert result["stored"] is False
        assert result["connected"] is False


def record_xml(weight="80", steps="4000"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<HealthData>
  <Record type="HKQuantityTypeIdentifierBodyMass" unit="kg" value="{weight}"
    startDate="2026-10-01 08:00:00 -0700" endDate="2026-10-01 08:00:00 -0700"/>
  <Record type="HKQuantityTypeIdentifierStepCount" unit="count" value="{steps}"
    startDate="2026-10-01 09:00:00 -0700" endDate="2026-10-01 10:00:00 -0700"/>
</HealthData>
"""


class TestBounds:
    def test_apple_health_needs_a_recorded_confirmation(self):
        missed = WearableImport().parse_apple_health(EXPORT)
        bare = WearableImport().parse_apple_health(EXPORT, True)
        other = WearableImport().parse_apple_health(EXPORT, recorded(GARMIN))
        assert missed["stored"] is False
        assert bare["stored"] is False
        assert other["stored"] is False
        assert "record_confirmation" in missed["message"]

    def test_weight_outside_25_to_350_kg_is_rejected(self):
        light = {"date": "2026-10-30", "weight_kg": 24.9}
        heavy = {"date": "2026-10-30", "weight_kg": 350.1}
        assert summary(light)["stored"] is False
        assert "25" in summary(heavy)["message"]
        assert apple(record_xml(weight="10"))["stored"] is False
        garmin = WearableImport().fetch_garmin(
            confirmation=recorded(GARMIN),
            fetcher=lambda: {"date": "2026-10-30", "weight_kg": 400},
            enabled=True,
        )
        assert garmin["stored"] is False
        assert garmin["connected"] is False

    def test_steps_over_100000_a_day_are_rejected(self):
        reading = {"date": "2026-10-30", "steps": 100001}
        assert summary(reading)["stored"] is False
        assert "100,000" in summary(reading)["message"]
        assert apple(record_xml(steps="100001"))["stored"] is False
        garmin = WearableImport().fetch_garmin(
            confirmation=recorded(GARMIN),
            fetcher=lambda: {"date": "2026-10-30", "steps": 100001},
            enabled=True,
        )
        assert garmin["stored"] is False

    def test_the_bounds_themselves_are_kept(self):
        reading = {"date": "2026-10-30", "steps": 100000, "weight_kg": 25}
        low = summary(reading)
        assert low["stored"] is True
        assert low["reading"]["steps"] == 100000
        assert low["reading"]["weight_kg"] == 25
        high = summary({"date": "2026-10-30", "weight_kg": 350})
        assert high["stored"] is True
        assert high["reading"]["weight_kg"] == 350

    def test_summary_dates_must_be_real(self):
        for day in ("10/20/2026", "yesterday", None):
            reading = {"date": day, "steps": 8000}
            result = summary(reading)
            assert result["stored"] is False
            assert "date" in result["message"].lower()

    def test_a_real_summary_timestamp_is_kept(self):
        reading = {"date": "2026-10-30T15:00:00Z", "steps": 8000}
        result = summary(reading)
        assert result["stored"] is True
        assert result["reading"]["date"] == "2026-10-30"
