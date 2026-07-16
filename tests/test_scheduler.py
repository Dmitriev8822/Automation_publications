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


def test_run_startup_tests_suppresses_existing_root_handlers(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main as app_main

    root_logger = app_main.logging.getLogger()
    handler = app_main.logging.StreamHandler()
    handler.setLevel(app_main.logging.INFO)
    root_logger.addHandler(handler)
    observed_handler_levels: list[int] = []

    def fake_pytest_main(args):
        observed_handler_levels.append(handler.level)
        app_main.logging.getLogger("app.service").error("hidden startup-test log")
        return app_main.pytest.ExitCode.OK

    monkeypatch.setattr(app_main.pytest, "main", fake_pytest_main)

    try:
        assert app_main.run_startup_tests(("tests", "-q")) is True
        assert observed_handler_levels == [app_main.logging.CRITICAL + 1]
        assert handler.level == app_main.logging.INFO
    finally:
        root_logger.removeHandler(handler)


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
    monkeypatch.setattr(
        app_main,
        "build_runtime",
        lambda settings: app_main.ApplicationRuntime(
            scheduler=dummy_scheduler,
            telegram_publisher=object(),
        ),
    )

    assert app_main.main() == 1
    assert dummy_scheduler.started is False


def test_main_returns_error_when_dependency_setup_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main as app_main

    class DummySettings:
        log_level = "INFO"

    monkeypatch.setattr(app_main, "get_settings", lambda: DummySettings())
    monkeypatch.setattr(app_main, "configure_logging", lambda log_level: None)
    monkeypatch.setattr(app_main, "run_startup_tests", lambda: True)
    monkeypatch.setattr(
        app_main,
        "build_runtime",
        lambda settings: (_ for _ in ()).throw(ValueError("bad runtime settings")),
    )

    assert app_main.main(["--check"]) == 1


def test_main_check_mode_initializes_dependencies_without_starting_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main as app_main

    class DummySettings:
        log_level = "INFO"
        publish_interval_minutes = 1

    class DummyScheduler:
        started = False
        shutdown_called = False

        def start(self) -> None:
            self.started = True

        def shutdown(self, wait: bool = False) -> None:
            self.shutdown_called = True

    dummy_scheduler = DummyScheduler()
    monkeypatch.setattr(app_main, "get_settings", lambda: DummySettings())
    monkeypatch.setattr(app_main, "configure_logging", lambda log_level: None)
    monkeypatch.setattr(app_main, "run_startup_tests", lambda: True)
    monkeypatch.setattr(
        app_main,
        "build_runtime",
        lambda settings: app_main.ApplicationRuntime(
            scheduler=dummy_scheduler,
            telegram_publisher=object(),
        ),
    )

    assert app_main.main(["--check"]) == 0
    assert dummy_scheduler.started is False
    assert dummy_scheduler.shutdown_called is False


def test_main_can_run_as_script_path_for_help() -> None:
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "app/main.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Run the Telegram publication automation service" in result.stdout
    assert "ModuleNotFoundError" not in result.stderr
