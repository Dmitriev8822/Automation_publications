# Модуль main

## Назначение

`app/main.py` — точка входа приложения. Модуль не содержит бизнес-логику публикации: он загружает настройки, настраивает логирование, запускает быстрые startup-тесты, инициализирует зависимости и стартует APScheduler.

Дополнительно модуль поддерживает режим проверки `--check`: он выполняет те же startup-проверки и сборку зависимостей, но не запускает бесконечный scheduler-цикл. Этот режим нужен после заполнения `.env`, чтобы убедиться, что сервис готов к запуску.

## Публичные классы и функции

- `configure_logging(log_level: str) -> None` — настраивает root logging.
- `run_startup_tests(args: Sequence[str] = STARTUP_TEST_ARGS) -> bool` — запускает быстрые тесты через `pytest` и возвращает результат.
- `build_scheduler(settings: Settings) -> BackgroundScheduler` — валидирует runtime-настройки, инициализирует БД, создает `AIClient`, `TelegramPublisher`, `PostRepository` и регистрирует job публикации.
- `parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace` — разбирает CLI-аргументы приложения.
- `main(argv: Sequence[str] | None = None) -> int` — основной сценарий запуска приложения.

CLI:

```bash
python -m app.main
python -m app.main --check
```

## Используемые настройки

Модуль получает настройки через `app.config.get_settings()` и использует:

- `LOG_LEVEL` — уровень логирования;
- `APP_ENV` — режим окружения, в `prod` обязательны реальные секреты;
- `DATABASE_URL` — URL SQLite-БД;
- `PUBLISH_INTERVAL_MINUTES` — интервал запуска job;
- `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL` — настройки AI-клиента;
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID` — настройки Telegram-публикатора;
- настройки темы, языка и формата поста, которые передаются в `AIClient` через `Settings`.

## Взаимодействие с другими модулями

`main.py` собирает зависимости по архитектурной схеме:

1. `get_settings()` из `app.config` загружает `.env`.
2. `run_startup_tests()` запускает быстрый набор `pytest`.
3. `validate_runtime_settings(settings)` проверяет обязательные production-секреты.
4. `init_db()` из `app.database` создает таблицы.
5. `PostRepository`, `AIClient` и `TelegramPublisher` создаются и передаются в `app.service.create_and_publish_post()` через scheduler job.
6. `create_scheduler()` из `app.scheduler` регистрирует периодический запуск публикации.

## Обработка ошибок

- Если startup-тесты не прошли, `main()` возвращает `1` и не запускает scheduler.
- Если production-секреты отсутствуют, `validate_runtime_settings()` выбрасывает `ValueError`, и приложение не стартует.
- Если не удается создать Telegram/OpenRouter-зависимости, ошибка возникает на этапе `build_scheduler()` до запуска scheduler.
- Ошибки внутри самой publication job логируются в `app.scheduler` и не останавливают будущие запуски.
- При штатном `KeyboardInterrupt` или `SystemExit` scheduler останавливается через `shutdown(wait=False)`.

## Тестирование

Релевантные тесты:

```bash
pytest tests/test_scheduler.py
pytest
```

Тесты проверяют, что импорт `app.main` не запускает приложение, scheduler не стартует при провале startup-тестов, а режим `--check` инициализирует зависимости без запуска scheduler.

## Пример использования

Проверка окружения после заполнения `.env`:

```bash
python -m app.main --check
```

Запуск сервиса:

```bash
python -m app.main
```
