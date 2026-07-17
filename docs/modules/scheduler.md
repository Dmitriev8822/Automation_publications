# Модуль Scheduler

## Назначение

`app.scheduler` отвечает только за настройку APScheduler jobs. Актуальный режим для контент-плана — отдельный `date`-job на каждый пункт плана: пост публикуется в собственное поле `scheduled_at`, а не во время общей проверки раз в `PUBLISH_INTERVAL_MINUTES`.

Старый interval-scheduler для новостных публикаций оставлен как заготовка `create_scheduler(...)`, но больше не используется в актуальном `build_runtime()` приложения.

## Публичные классы и функции

- `create_content_plan_scheduler(job_func, scheduled_items=None) -> BackgroundScheduler` — создает scheduler и регистрирует `date`-jobs для переданных пар `(item_id, scheduled_at)`.
- `add_content_plan_item_jobs(scheduler, job_func, scheduled_items) -> None` — добавляет или заменяет `date`-jobs вида `content_plan_item_<id>`. Используется при старте приложения и после сохранения нового контент-плана.
- `create_scheduler(job_func, interval_minutes) -> BackgroundScheduler` — legacy-заготовка interval-job `publish_post`; сохранена для будущего возврата периодической публикации, но не подключена к основному runtime.

Все job-функции оборачиваются защитным обработчиком: исключения логируются через `logger.exception`, но не пробрасываются наружу, чтобы scheduler продолжал работать.

## Используемые настройки

Актуальный scheduler контент-плана не использует `PUBLISH_INTERVAL_MINUTES` для публикаций. Время берется из БД: `ContentPlanItem.scheduled_at`.

`PUBLISH_INTERVAL_MINUTES` остается только для legacy-функции `create_scheduler(...)`.

## Взаимодействие с другими модулями

`app.main.build_runtime()`:

1. Создает `ContentPlanRepository`.
2. Берет сохраненные слоты через `content_plan_repository.get_scheduled_item_slots()`.
3. Создает scheduler через `create_content_plan_scheduler(...)`.
4. Оборачивает сохранение нового плана так, чтобы после `save_plan(...)` вызвать `add_content_plan_item_jobs(...)` и зарегистрировать новые точные времена запуска.

`app.scheduler` не содержит бизнес-логики публикации. Фактическая публикация due-пунктов остается в `app.service.publish_due_content_plan_items(...)`.

## Обработка ошибок

Если job публикации падает, исключение логируется, но не останавливает scheduler. Ошибки отдельных пунктов контент-плана дополнительно обрабатываются в `app.service`: пункт помечается как `failed`, а обработка следующих пунктов продолжается.

## Тестирование

Релевантные проверки:

```bash
pytest tests/test_scheduler.py
pytest tests/test_database.py
```

Тесты проверяют legacy interval-заготовку, регистрацию `date`-jobs для контент-плана и то, что `build_runtime()` больше не запускает периодическую новостную публикацию.

## Пример использования

```python
from app.scheduler import create_content_plan_scheduler, add_content_plan_item_jobs

scheduler = create_content_plan_scheduler(publish_due_items, [(5, scheduled_at)])
add_content_plan_item_jobs(scheduler, publish_due_items, [(6, another_time)])
scheduler.start()
```
