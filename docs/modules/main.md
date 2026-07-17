# Модуль main

## Назначение

`app/main.py` — точка входа приложения. Модуль не содержит бизнес-логику публикации: он загружает настройки, настраивает логирование, запускает быстрые startup-тесты, инициализирует зависимости, стартует APScheduler с точными `date`-jobs для пунктов контент-плана и запускает Telegram long polling для кнопки ручной публикации.

Дополнительно модуль поддерживает режим проверки `--check`: он выполняет те же startup-проверки и сборку зависимостей, но не запускает бесконечный scheduler-цикл. Этот режим нужен после заполнения `.env`, чтобы убедиться, что сервис готов к запуску.

## Публичные классы и функции

- `configure_logging(log_level: str) -> None` — настраивает root logging.
- `run_startup_tests(args: Sequence[str] = STARTUP_TEST_ARGS) -> bool` — запускает быстрые тесты через `pytest`, временно подавляет application-логи тестовых fake-сценариев и возвращает результат.
- `build_scheduler(settings: Settings) -> BackgroundScheduler` — валидирует runtime-настройки, инициализирует БД, создает `AIClient`, `TelegramPublisher`, `PostRepository` и регистрирует job публикации.
- `build_runtime(settings: Settings) -> ApplicationRuntime` — собирает зависимости для scheduled и manual publication entrypoints, регистрирует кнопку ручной публикации в Telegram и возвращает scheduler вместе с Telegram publisher.
- `parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace` — разбирает CLI-аргументы приложения.
- `main(argv: Sequence[str] | None = None) -> int` — основной сценарий запуска приложения.

CLI:

```bash
python -m app.main
python -m app.main --check
python app/main.py
python app/main.py --check
```

## Используемые настройки

Модуль получает настройки через `app.config.get_settings()` и использует:

- `LOG_LEVEL` — уровень логирования;
- `APP_ENV` — режим окружения, в `prod` обязательны реальные секреты;
- `DATABASE_URL` — URL SQLite-БД;
- `PUBLISH_INTERVAL_MINUTES` — legacy-настройка для старой interval-заготовки; в актуальном runtime контент-план публикуется по `scheduled_at` из БД;
- `APP_TIMEZONE` — IANA timezone, в котором трактуются пользовательские времена контент-плана без явного UTC offset;
- `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL` — настройки AI-клиента;
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID` — настройки Telegram-публикатора;
- настройки темы, языка и формата поста, которые передаются в `AIClient` через `Settings`.

## Взаимодействие с другими модулями

`main.py` собирает зависимости по архитектурной схеме:

1. `get_settings()` из `app.config` загружает `.env`.
2. `run_startup_tests()` запускает быстрый набор `pytest` и временно отключает вывод application-логов из тестов, чтобы при штатном `python app/main.py` пользователь видел только результат тестов, а не ожидаемые тестовые traceback-и.
3. `validate_runtime_settings(settings)` проверяет обязательные production-секреты.
4. `init_db()` из `app.database` создает таблицы.
5. `PostRepository`, `ContentPlanRepository`, `AIClient` и `TelegramPublisher` создаются и передаются в сервисные сценарии через scheduler job.
6. Scheduler регистрирует отдельные `date`-jobs для пунктов контент-плана по времени `scheduled_at` из БД. Плановая новостная публикация раз в `PUBLISH_INTERVAL_MINUTES` больше не подключена к актуальному runtime; новость можно запустить вручную через Telegram-кнопку.
7. Для Telegram-бота регистрируется кнопка `📰 Опубликовать новость`; ее handler вызывает тот же `create_and_publish_post(...)`, но передает `progress_callback`, чтобы пользователь видел короткие статусы выполнения.
8. `create_content_plan_scheduler()` и `add_content_plan_item_jobs()` из `app.scheduler` регистрируют точные запуски пунктов контент-плана.
9. После старта scheduler запускается `TelegramPublisher.start_manual_polling()`, чтобы бот принимал `/start` и нажатия кнопки.

## Обработка ошибок

- При прямом запуске `python app/main.py` модуль добавляет корень репозитория в `sys.path`, чтобы абсолютные импорты `app.*` работали так же, как при `python -m app.main`.
- Если startup-тесты не прошли, `main()` возвращает `1` и не запускает scheduler; логи, созданные внутри самих тестов, на время pytest подавляются.
- Если production-секреты отсутствуют или Telegram-токен не похож на формат `<bot_id>:<secret>`, `validate_runtime_settings()` выбрасывает `ValueError`; `main()` логирует понятную ошибку старта и возвращает код `1` до создания Telegram-клиента.
- Если не удается создать Telegram/OpenRouter-зависимости, ошибка возникает на этапе `build_scheduler()` до запуска scheduler; при CLI-запуске она превращается в лог `Application startup failed: ...` и код возврата `1`.
- Ошибки внутри самой publication job логируются в `app.scheduler` и не останавливают будущие запуски. Плановая новостная публикация по интервалу оставлена только как legacy-заготовка и не используется в `build_runtime()`.
- При штатном `KeyboardInterrupt` или `SystemExit` scheduler останавливается через `shutdown(wait=False)`.

## Тестирование

Релевантные тесты:

```bash
pytest tests/test_scheduler.py
pytest
```

Тесты проверяют, что импорт `app.main` не запускает приложение, scheduler не стартует при провале startup-тестов, а режим `--check` инициализирует зависимости без запуска scheduler.

## Пример использования

Проверка окружения после заполнения `.env` (для реального запуска в `prod` нужны настоящий `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN` формата `<bot_id>:<secret>` и `TELEGRAM_CHANNEL_ID`; без них сервис не сможет создать внешние клиенты):

```bash
python -m app.main --check
```

Запуск сервиса:

```bash
python -m app.main
# или прямой запуск файла из корня репозитория
python app/main.py
```

## Консольное логирование

Точка входа пишет INFO-логи о запуске startup-тестов, сборке зависимостей, создании репозитория, AI-клиента, Telegram publisher и scheduler с точными временами контент-плана. Это позволяет отделить ошибки конфигурации/инициализации от ошибок бизнес-сценария публикации.

## Подключение контент-плана

`build_runtime()` дополнительно создает `ContentPlanRepository`, регистрирует `TelegramPublisher.register_content_plan_handler(...)` с оберткой сохранения и после каждого сохраненного плана обновляет `date`-jobs через `add_content_plan_item_jobs(...)`. При старте приложения уже сохраненные пункты со статусом `scheduled` берутся из `get_scheduled_item_slots()` и сразу попадают в scheduler. Публикация происходит в согласованное время каждого пункта, а не общей проверкой раз в полчаса.


## Постоянные напоминания

`build_runtime()` создает `ReminderSettingsRepository` и при старте загружает сохраненную настройку меню `⏰ Напоминания`. Если напоминания включены, runtime выставляет `telegram_publisher.reminder_minutes_before` и `telegram_publisher.reminder_chat_id`, затем регистрирует reminder-jobs для всех уже сохраненных пунктов контент-плана. При сохранении нового контент-плана `build_runtime()` повторно применяет эту настройку, поэтому уведомления появляются и для старых, и для новых публикаций. Если пользователь вводит `0` или команду отключения в меню напоминаний, настройка сохраняется как выключенная, а все reminder-jobs удаляются без удаления jobs самих публикаций.


Reminder-job перед отправкой уведомления заново читает пункт контент-плана из БД и проверяет, что его статус всё еще `scheduled`. Если пользователь уже одобрил, отменил или публикация завершилась до срабатывания reminder-job, уведомление не отправляется повторно.
