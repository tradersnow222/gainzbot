import pytest


@pytest.fixture(autouse=True)
def _isolate_onboarding_files(tmp_path, monkeypatch):
    """Keep the dated symptom hold and the one first-plan record off the shared data dir."""
    state = tmp_path / "onboarding_state.json"
    record = tmp_path / "onboarding_record.json"
    week = tmp_path / "week.json"
    daily_week = tmp_path / "daily_week.json"
    monkeypatch.setattr("onboarding.onboarding_state_path", lambda: str(state))
    monkeypatch.setattr("onboarding.onboarding_week_path", lambda: str(week))
    monkeypatch.setattr("record_confirmation.onboarding_record_path", lambda: str(record))
    monkeypatch.setattr("onboarding._memory_hold", None)

    def week_file(self):
        if self.week_path:
            return self.week_path
        return str(daily_week)

    monkeypatch.setattr("daily_loop.DailyLoop._week_file", week_file)
