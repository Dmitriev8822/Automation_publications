# Задача 06. Scheduler и точка входа приложения

## Цель

Реализовать запуск приложения: быстрые тесты при старте, инициализацию БД и периодический запуск публикации через APScheduler.

## Работать в файлах

- `app/scheduler.py`
- `app/main.py`
- `tests/test_scheduler.py`
- `docs/modules/scheduler.md`
- `docs/modules/main.md`

## Что реализовать

1. В `app/scheduler.py` создать функцию:

```python
def create_scheduler(job_func, interval_minutes: int) -> BackgroundScheduler:
    ...
```

2. В `app/main.py` реализовать:
   - настройку логирования;
   - загрузку настроек;
   - `validate_runtime_settings(settings)`;
   - запуск быстрых тестов через `pytest`;
   - `init_db()`;
   - создание `AIClient`, `TelegramPublisher`, `PostRepository`;
   - запуск scheduler.
3. При провале startup-тестов приложение не должно запускать scheduler.
4. Ошибки job-функции должны логироваться, но не должны останавливать scheduler.

## Интерфейсы для других модулей

`main.py` собирает зависимости:

```python
settings = get_settings()
repository = PostRepository(...)
ai_client = AIClient(settings)
telegram_publisher = TelegramPublisher(settings)

job = lambda: create_and_publish_post(ai_client, telegram_publisher, repository)
scheduler = create_scheduler(job, settings.publish_interval_minutes)
```

## Откуда брать информацию

- Настройки: `app/config.py`.
- БД: `app/database.py`.
- AI: `app/ai.py`.
- Telegram: `app/telegram.py`.
- Service: `app/service.py`.
- Архитектура: `docs/ARCHITECTURE.md`.

## Что нельзя делать

- Не выполнять реальные OpenRouter/Telegram запросы в startup-тестах.
- Не дублировать бизнес-логику из `service.py`.
- Не хранить бесконечный цикл в unit-тестах.

## Тесты

Проверить:

- создание scheduler с нужным интервалом;
- что job-функция регистрируется;
- что при провале тестов scheduler не стартует;
- что `main.py` можно импортировать без запуска приложения.

## Документация после реализации

Создать:

- `docs/modules/scheduler.md` — как работает расписание;
- `docs/modules/main.md` — как приложение стартует и собирает зависимости.
