# Архитектура MVP сервиса Telegram-публикаций

## Цель проекта

Сервис автоматически находит свежие новости по заданной теме, выбирает ещё не опубликованную новость, генерирует Telegram-пост и изображение, публикует результат в канал и сохраняет факт публикации в SQLite.

## Общий процесс

```text
app/main.py
  ↓
быстрые тесты без внешних API
  ↓
app/scheduler.py
  ↓ каждые PUBLISH_INTERVAL_MINUTES минут
app/service.py
  ↓
app/ai.py → поиск новости, генерация текста, генерация изображения
app/database.py → проверка дублей и сохранение результата
app/telegram.py → публикация в Telegram
```

## Модули

| Модуль | Файл | Ответственность |
| --- | --- | --- |
| config | `app/config.py` | Загрузка и валидация настроек из `.env` |
| schemas | `app/schemas.py` | Общие Pydantic-сущности и enum-статусы |
| database | `app/database.py` | SQLite, SQLAlchemy, репозиторий публикаций |
| ai | `app/ai.py` | OpenRouter: поиск новостей, генерация текста и изображения |
| telegram | `app/telegram.py` | pyTelegramBotAPI: отправка текста/изображений в канал |
| service | `app/service.py` | Главный сценарий создания и публикации поста |
| scheduler | `app/scheduler.py` | Периодический запуск сценария через APScheduler |
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
