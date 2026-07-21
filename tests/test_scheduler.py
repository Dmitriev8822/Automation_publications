"""Tests for scheduler creation and application startup wiring."""

from __future__ import annotations

import importlib

import pytest

from datetime import datetime, timedelta, timezone

from app.scheduler import (
    add_content_plan_reminder_jobs,
    create_content_plan_scheduler,
    create_scheduler,
    remove_content_plan_reminder_jobs,
)


def test_create_scheduler_uses_requested_interval() -> None:
    scheduler = create_scheduler(lambda: None, interval_minutes=7)

    jobs = scheduler.get_jobs()

    assert len(jobs) == 1
    assert jobs[0].id == "publish_post"
    assert jobs[0].trigger.interval.total_seconds() == 7 * 60


def test_create_scheduler_runs_first_job_immediately() -> None:
    scheduler = create_scheduler(lambda: None, interval_minutes=7)

    job = scheduler.get_jobs()[0]

    assert job.next_run_time is not None


def test_create_content_plan_scheduler_registers_date_jobs() -> None:
    run_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    scheduler = create_content_plan_scheduler(lambda: None, [(42, run_at)])

    jobs = scheduler.get_jobs()

    assert len(jobs) == 1
    assert jobs[0].id == "content_plan_item_42"
    assert jobs[0].trigger.run_date == run_at


def test_build_runtime_uses_exact_content_plan_jobs_without_periodic_news(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main as app_main

    run_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    class DummySettings:
        publish_interval_minutes = 1

    class DummyTelegramPublisher:
        def __init__(self, settings) -> None:
            self.settings = settings

        def register_manual_publish_handler(self, handler) -> None:
            self.manual_handler = handler

        def register_content_plan_handler(self, generator, saver) -> None:
            self.content_plan_handler = (generator, saver)

    class DummyAIClient:
        def __init__(self, settings) -> None:
            self.settings = settings

        def generate_content_plan(self, request: str):
            return request

    class DummyPostRepository:
        pass

    class DummyContentPlanRepository:
        def save_plan(self, plan) -> int:
            return 1

        def get_scheduled_item_slots(self):
            return [(5, run_at)]

    calls: list[str] = []

    def fake_create_and_publish_post(*args, **kwargs):
        calls.append("news")

    def fake_publish_due_content_plan_items(*args, **kwargs):
        calls.append("content_plan")
        return []

    monkeypatch.setattr(app_main, "validate_runtime_settings", lambda settings: None)
    monkeypatch.setattr(app_main, "init_db", lambda: None)
    monkeypatch.setattr(app_main, "PostRepository", DummyPostRepository)
    monkeypatch.setattr(app_main, "ContentPlanRepository", DummyContentPlanRepository)
    monkeypatch.setattr(app_main, "AIClient", DummyAIClient)
    monkeypatch.setattr(app_main, "TelegramPublisher", DummyTelegramPublisher)
    monkeypatch.setattr(
        app_main, "create_and_publish_post", fake_create_and_publish_post
    )
    monkeypatch.setattr(
        app_main, "publish_due_content_plan_items", fake_publish_due_content_plan_items
    )

    runtime = app_main.build_runtime(DummySettings())
    job = runtime.scheduler.get_jobs()[0]
    job.func()

    assert job.id == "content_plan_item_5"
    assert calls == ["content_plan"]


def test_remove_content_plan_reminder_jobs_keeps_publication_jobs() -> None:
    run_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    scheduler = create_content_plan_scheduler(lambda: None, [(42, run_at)])
    add_content_plan_reminder_jobs(scheduler, lambda item_id: None, [(42, run_at)], 5)

    remove_content_plan_reminder_jobs(scheduler)

    assert [job.id for job in scheduler.get_jobs()] == ["content_plan_item_42"]


def test_build_runtime_applies_persistent_reminders_to_existing_and_new_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main as app_main

    first_run_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    second_run_at = datetime.now(timezone.utc) + timedelta(minutes=20)

    class DummySettings:
        publish_interval_minutes = 1

    class DummyTelegramPublisher:
        def __init__(self, settings) -> None:
            self.settings = settings
            self.reminder_minutes_before = None
            self.reminder_chat_id = None

        def register_manual_publish_handler(self, handler) -> None:
            pass

        def register_content_plan_handler(self, generator, saver) -> None:
            self.save_plan = saver

        def register_reminders_handler(self, handler) -> None:
            self.reminders_handler = handler

        def register_publication_approval_handler(self, *handlers) -> None:
            pass

    class DummyAIClient:
        def __init__(self, settings) -> None:
            pass

        def generate_content_plan(self, request: str):
            return request

    class DummyPostRepository:
        pass

    class DummyContentPlanRepository:
        def __init__(self) -> None:
            self.slots = [(1, first_run_at)]

        def save_plan(self, plan) -> int:
            self.slots = [(1, first_run_at), (2, second_run_at)]
            return 10

        def get_scheduled_item_slots(self):
            return self.slots

    class DummyReminderSettingsRepository:
        def get_settings(self):
            return True, 5, 777

        def enable(self, minutes, chat_id) -> None:
            pass

        def disable(self) -> None:
            pass

    monkeypatch.setattr(app_main, "validate_runtime_settings", lambda settings: None)
    monkeypatch.setattr(app_main, "init_db", lambda: None)
    monkeypatch.setattr(app_main, "PostRepository", DummyPostRepository)
    monkeypatch.setattr(app_main, "ContentPlanRepository", DummyContentPlanRepository)
    monkeypatch.setattr(
        app_main, "ReminderSettingsRepository", DummyReminderSettingsRepository
    )
    monkeypatch.setattr(app_main, "AIClient", DummyAIClient)
    monkeypatch.setattr(app_main, "TelegramPublisher", DummyTelegramPublisher)

    runtime = app_main.build_runtime(DummySettings())

    assert runtime.telegram_publisher.reminder_minutes_before == 5
    assert runtime.telegram_publisher.reminder_chat_id == 777
    assert sorted(job.id for job in runtime.scheduler.get_jobs()) == [
        "content_plan_item_1",
        "content_plan_reminder_1",
    ]

    runtime.telegram_publisher.save_plan(object())

    assert {job.id for job in runtime.scheduler.get_jobs()} == {
        "content_plan_item_1",
        "content_plan_item_2",
        "content_plan_reminder_1",
        "content_plan_reminder_2",
    }


def test_build_runtime_scheduled_content_plan_job_does_not_pass_ai_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main as app_main

    captured_ai_clients: list[object] = []

    class DummySettings:
        publish_interval_minutes = 1

    class DummyTelegramPublisher:
        def __init__(self, settings) -> None:
            self.reminder_minutes_before = None
            self.reminder_chat_id = None

        def register_manual_publish_handler(self, *args) -> None:
            pass

        def register_content_plan_handler(self, *args) -> None:
            pass

    class DummyAIClient:
        def __init__(self, settings) -> None:
            pass

        def generate_content_plan(self, request: str):
            return request

    class DummyPostRepository:
        pass

    class DummyContentPlanRepository:
        def get_scheduled_item_slots(self):
            return [(1, datetime.now(timezone.utc) + timedelta(minutes=10))]

    class DummyReminderSettingsRepository:
        def get_settings(self):
            return False, None, None

        def enable(self, minutes, chat_id) -> None:
            pass

        def disable(self) -> None:
            pass

    def fake_publish_due(telegram_publisher, content_plan_repository, ai_client=None):
        captured_ai_clients.append(ai_client)
        return []

    monkeypatch.setattr(app_main, "validate_runtime_settings", lambda settings: None)
    monkeypatch.setattr(app_main, "init_db", lambda: None)
    monkeypatch.setattr(app_main, "PostRepository", DummyPostRepository)
    monkeypatch.setattr(app_main, "ContentPlanRepository", DummyContentPlanRepository)
    monkeypatch.setattr(
        app_main, "ReminderSettingsRepository", DummyReminderSettingsRepository
    )
    monkeypatch.setattr(app_main, "AIClient", DummyAIClient)
    monkeypatch.setattr(app_main, "TelegramPublisher", DummyTelegramPublisher)
    monkeypatch.setattr(app_main, "publish_due_content_plan_items", fake_publish_due)

    runtime = app_main.build_runtime(DummySettings())
    runtime.scheduler.get_job("content_plan_item_1").func()

    assert captured_ai_clients == [None]


def test_create_scheduler_registers_job_function() -> None:
    calls: list[str] = []
    scheduler = create_scheduler(lambda: calls.append("called"), interval_minutes=1)

    scheduler.get_jobs()[0].func()

    assert calls == ["called"]


def test_scheduler_job_logs_exceptions_without_reraising(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def failing_job() -> None:
        raise RuntimeError("boom")

    scheduler = create_scheduler(failing_job, interval_minutes=1)

    scheduler.get_jobs()[0].func()

    assert "Scheduled publication job failed" in caplog.text
    assert "boom" in caplog.text


def test_run_startup_tests_suppresses_existing_root_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_main_import_does_not_start_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = False

    def fake_start(*args, **kwargs):
        nonlocal started
        started = True

    monkeypatch.setattr(
        "apscheduler.schedulers.background.BackgroundScheduler.start", fake_start
    )

    import app.main

    importlib.reload(app.main)

    assert started is False


def test_main_does_not_start_scheduler_when_startup_tests_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_main_returns_error_when_dependency_setup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_main_check_mode_initializes_dependencies_without_starting_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_main_returns_error_when_manual_polling_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    class DummyTelegramPublisher:
        def start_manual_polling(self) -> None:
            raise RuntimeError("bad telegram token")

    dummy_scheduler = DummyScheduler()
    monkeypatch.setattr(app_main, "get_settings", lambda: DummySettings())
    monkeypatch.setattr(app_main, "configure_logging", lambda log_level: None)
    monkeypatch.setattr(app_main, "run_startup_tests", lambda: True)
    monkeypatch.setattr(
        app_main,
        "build_runtime",
        lambda settings: app_main.ApplicationRuntime(
            scheduler=dummy_scheduler,
            telegram_publisher=DummyTelegramPublisher(),
        ),
    )

    assert app_main.main() == 1
    assert dummy_scheduler.started is True
    assert dummy_scheduler.shutdown_called is True


def test_main_check_telegram_validates_token_without_startup_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main as app_main

    class DummySettings:
        log_level = "INFO"

    class DummyTelegramPublisher:
        channel_id = "@test_channel"

        def __init__(self, settings) -> None:
            self.settings = settings

        def validate_bot_token(self) -> str:
            return "@test_news_bot"

    startup_tests_called = False

    def fake_startup_tests() -> bool:
        nonlocal startup_tests_called
        startup_tests_called = True
        return True

    monkeypatch.setattr(app_main, "get_settings", lambda: DummySettings())
    monkeypatch.setattr(app_main, "configure_logging", lambda log_level: None)
    monkeypatch.setattr(app_main, "run_startup_tests", fake_startup_tests)
    monkeypatch.setattr(app_main, "TelegramPublisher", DummyTelegramPublisher)

    assert app_main.main(["--check-telegram"]) == 0
    assert startup_tests_called is False


def test_main_check_telegram_returns_error_for_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main as app_main

    class DummySettings:
        log_level = "INFO"

    class DummyTelegramPublisher:
        def __init__(self, settings) -> None:
            self.settings = settings

        def validate_bot_token(self) -> str:
            raise RuntimeError("bad token")

    monkeypatch.setattr(app_main, "get_settings", lambda: DummySettings())
    monkeypatch.setattr(app_main, "configure_logging", lambda log_level: None)
    monkeypatch.setattr(app_main, "TelegramPublisher", DummyTelegramPublisher)

    assert app_main.main(["--check-telegram"]) == 1
