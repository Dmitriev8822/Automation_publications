# Модуль content_plan

## Назначение

Контент-план объединяет сценарий, в котором пользователь в Telegram нажимает кнопку `Контент план`, описывает желаемый план в свободной форме, получает структурированный результат от AI, может перегенерировать его или согласовать. После согласования план сохраняется в SQLite, а наступившие пункты публикуются планировщиком.

## Публичные классы и функции

- `app.schemas.ContentPlan` — структурированный план на период.
- `app.schemas.ContentPlanItem` — один запланированный пост с `scheduled_at`, текстом и статусом.
- `app.schemas.ContentPlanItemStatus` — статусы `scheduled`, `published`, `failed`.
- `app.ai.AIClient.generate_content_plan(description)` — превращает свободное описание пользователя в `ContentPlan`.
- `app.database.ContentPlanRepository.save_plan(plan)` — сохраняет согласованный план.
- `app.database.ContentPlanRepository.get_due_items()` — возвращает пункты, время публикации которых наступило.
- `app.database.ContentPlanRepository.mark_item_published(...)` и `mark_item_failed(...)` — фиксируют результат публикации пункта.
- `app.service.publish_due_content_plan_items(...)` — бизнес-сценарий выполнения наступивших пунктов плана.
- `app.telegram.TelegramPublisher.register_content_plan_handler(...)` — Telegram-диалог генерации, перегенерации и согласования плана.

## Используемые настройки

Используются существующие настройки OpenRouter (`OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`, `POST_LANGUAGE`) и Telegram (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID`). Отдельные переменные окружения для контент-плана не добавлены.

## Взаимодействие с другими модулями

`main.py` передает в Telegram-обработчик `AIClient.generate_content_plan` и `ContentPlanRepository.save_plan`. Планировщик вызывает `create_and_publish_post()` для новостей и затем `publish_due_content_plan_items()` для согласованных контент-планов. Низкоуровневые вызовы Telegram и SQLAlchemy остаются внутри модулей `telegram` и `database`.

## Обработка ошибок

Если AI возвращает невалидный план, `AIClient` выбрасывает `OpenRouterResponseError`. Если публикация пункта плана падает, `publish_due_content_plan_items()` не останавливает планировщик, а помечает конкретный пункт как `failed` с текстом ошибки.

## Тестирование

Покрыто unit-тестами без реальных внешних API: генерация структурированного плана через fake HTTP-клиент, сохранение и выборка наступивших пунктов во временной SQLite-БД, публикация due-пунктов через fake Telegram publisher.

## Пример использования

```python
plan = ai_client.generate_content_plan("План на следующую неделю: 3 поста про автоматизацию")
plan_id = content_plan_repository.save_plan(plan)
published_items = publish_due_content_plan_items(telegram_publisher, content_plan_repository)
```
