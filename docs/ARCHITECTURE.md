# Архитектура MVP сервиса Telegram-публикаций

## Цель проекта

Сервис автоматически находит свежие новости по заданной теме, выбирает ещё не опубликованную новость, генерирует Telegram-пост и изображение, публикует результат в канал и сохраняет факт публикации в SQLite. Также бот умеет принимать от пользователя свободное описание контент-плана на период, превращать его через AI в структурированный план, давать пользователю перегенерировать или согласовать результат, сохранять согласованный план в БД и публиковать его пункты по расписанию.

## Общий процесс

```text
app/main.py
  ↓
быстрые тесты без внешних API
  ↓
app/scheduler.py
  ↓ точные date-jobs по scheduled_at пунктов контент-плана
app/service.py
  ↓
app/ai.py → поиск новости, генерация текста, генерация изображения
app/database.py → проверка дублей и сохранение результата
app/telegram.py → публикация в Telegram
```

Дополнительно `app/main.py` регистрирует в Telegram-боте кнопку ручной публикации и кнопку `Контент план`. Ручная публикация вызывает тот же бизнес-сценарий `app/service.py`, что и scheduler. Диалог контент-плана принимает свободное описание, вызывает `AIClient.generate_content_plan()`, показывает структурированный результат с кнопками перегенерации и согласования, а после согласования сохраняет план через `ContentPlanRepository`. Планировщик регистрирует отдельные `date`-jobs для пунктов согласованных планов и в согласованное время вызывает `publish_due_content_plan_items()`. Периодическая новостная публикация раз в `PUBLISH_INTERVAL_MINUTES` оставлена как legacy-заготовка, но не используется в актуальном runtime.

## Модули

| Модуль | Файл | Ответственность |
| --- | --- | --- |
| config | `app/config.py` | Загрузка и валидация настроек из `.env` |
| schemas | `app/schemas.py` | Общие Pydantic-сущности и enum-статусы для постов и контент-планов |
| database | `app/database.py` | SQLite, SQLAlchemy, репозитории публикаций и контент-планов |
| ai | `app/ai.py` | OpenRouter: поиск новостей, генерация текста, изображения и структурированного контент-плана |
| telegram | `app/telegram.py` | pyTelegramBotAPI: отправка текста/изображений в канал и кнопка ручной публикации |
| service | `app/service.py` | Главные сценарии создания новостного поста и выполнения согласованного контент-плана |
| scheduler | `app/scheduler.py` | Точные APScheduler date-jobs для пунктов контент-плана; legacy interval-заготовка для новостей |
| main | `app/main.py` | Точка входа: тесты, инициализация БД, запуск планировщика |
| tests | `tests/` | Быстрые тесты без реальных OpenRouter и Telegram API |
| docs | `docs/` | Описание архитектуры, задач и документация модулей |

## Общие интерфейсы между модулями

Все агенты должны придерживаться этих контрактов, чтобы независимо разработанные модули собрались в единый продукт.

### `News`

```python
class News(BaseModel):
    title: str
    source_url: str
    source_name: str
    summary: str
    published_at: datetime | None = None
```

### `GeneratedPost`

```python
class GeneratedPost(BaseModel):
    title: str
    text: str
    image_prompt: str
    source_url: str
```

### `ImageAsset`

```python
class ImageAsset(BaseModel):
    data: bytes | None = None
    url: str | None = None
    file_path: str | None = None
    mime_type: str = "image/png"
```

`ImageAsset` должен содержать хотя бы одно из полей `data`, `url`, `file_path`.

### `PublishedPost`

```python
class PublishedPost(BaseModel):
    id: int | None = None
    source_url: str
    title: str
    text: str
    status: PostStatus
    telegram_message_id: int | None = None
    error_message: str | None = None
```

### `PostStatus`

```python
class PostStatus(str, Enum):
    GENERATED = "generated"
    PUBLISHED = "published"
    FAILED = "failed"
```



### `ContentPlanItemStatus`

```python
class ContentPlanItemStatus(str, Enum):
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    FAILED = "failed"
```

### `ContentPlanItem`

```python
class ContentPlanItem(BaseModel):
    scheduled_at: datetime
    title: str
    text: str
    image_prompt: str = ""
    source_url: AnyUrl | None = None
    status: ContentPlanItemStatus = ContentPlanItemStatus.SCHEDULED
    telegram_message_id: int | None = None
    error_message: str | None = None
```

### `ContentPlan`

```python
class ContentPlan(BaseModel):
    title: str
    period_start: datetime
    period_end: datetime
    items: list[ContentPlanItem]
    raw_request: str | None = None
```

## Ключевые правила интеграции

1. `service.py` управляет бизнес-процессом и не содержит низкоуровневых деталей OpenRouter, Telegram или SQLAlchemy.
2. `ai.py`, `telegram.py` и `database.py` предоставляют классы/функции с устойчивыми интерфейсами.
3. Внешние зависимости передаются в сервис через параметры или фабрики, чтобы тесты могли использовать fake/mock-реализации.
4. Тесты не должны обращаться к реальным OpenRouter и Telegram API.
5. Повторная публикация одной новости запрещена: `source_url` должен быть уникальным в БД.
6. Каждый агент после реализации своего модуля обязан дополнить документацию своего модуля в `docs/modules/`.

## Документация после реализации

Каждый модуль должен иметь итоговый документ:

```text
docs/modules/<module>.md
```

В нём агент должен описать:

- назначение модуля;
- публичные классы и функции;
- какие настройки использует модуль;
- какие ошибки обрабатывает;
- как модуль тестировать;
- примеры использования, если уместно.
