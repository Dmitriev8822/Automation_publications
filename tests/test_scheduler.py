"""Tests for scheduler creation and application startup wiring."""

from __future__ import annotations

import importlib

import pytest

from app.scheduler import create_scheduler


def test_create_scheduler_uses_requested_interval() -> None:
    scheduler = create_scheduler(lambda: None, interval_minutes=7)

    jobs = scheduler.get_jobs()

    assert len(jobs) == 1
    assert jobs[0].id == "publish_post"
    assert jobs[0].trigger.interval.total_seconds() == 7 * 60


def test_create_scheduler_registers_job_function() -> None:
    calls: list[str] = []
    scheduler = create_scheduler(lambda: calls.append("called"), interval_minutes=1)

    scheduler.get_jobs()[0].func()

    assert calls == ["called"]


def test_scheduler_job_logs_exceptions_without_reraising(caplog: pytest.LogCaptureFixture) -> None:
    def failing_job() -> None:
        raise RuntimeError("boom")

    scheduler = create_scheduler(failing_job, interval_minutes=1)

    scheduler.get_jobs()[0].func()

    assert "Scheduled publication job failed" in caplog.text
    assert "boom" in caplog.text


def test_main_import_does_not_start_application(monkeypatch: pytest.MonkeyPatch) -> None:
    started = False

    def fake_start(*args, **kwargs):
        nonlocal started
        started = True

    monkeypatch.setattr("apscheduler.schedulers.background.BackgroundScheduler.start", fake_start)

    import app.main

    importlib.reload(app.main)

    assert started is False


def test_main_does_not_start_scheduler_when_startup_tests_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main as app_main

    class DummySettings:
        log_level = "INFO"
        publish_interval_minutes = 1

    class DummyScheduler:
        started = False

        def start(self) -> None:
            self.started = True

        def shutdown(self, wait: bool = False) -> None:
            pass

    dummy_scheduler = DummyScheduler()
    monkeypatch.setattr(app_main, "get_settings", lambda: DummySettings())
    monkeypatch.setattr(app_main, "configure_logging", lambda log_level: None)
    monkeypatch.setattr(app_main, "run_startup_tests", lambda: False)
    monkeypatch.setattr(app_main, "build_scheduler", lambda settings: dummy_scheduler)

    assert app_main.main() == 1
    assert dummy_scheduler.started is False
