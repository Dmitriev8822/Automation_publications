# Модуль database

## Назначение

`app.database` отвечает за хранение сгенерированных и опубликованных постов в SQLite через SQLAlchemy. Модуль защищает приложение от повторной публикации одной новости за счёт уникального поля `source_url`.

## Публичные классы и функции

- `engine` — SQLAlchemy engine, созданный на основе `settings.database_url`.
- `SessionLocal` — фабрика сессий SQLAlchemy для работы приложения.
- `Base` — базовый класс декларативных SQLAlchemy-моделей.
- `PostRecord` — ORM-модель таблицы `posts`.
- `ReminderSettingsRecord` — ORM-модель таблицы `reminder_settings` с постоянной настройкой напоминаний.
- `init_db() -> None` — создаёт каталог для файловой SQLite-БД и таблицы, если они ещё не существуют.
- `PostRepository` — репозиторий для бизнес-логики без прямого доступа к SQLAlchemy.
  - `is_published(source_url: str) -> bool` — возвращает `True`, если URL уже имеет статус `published`.
  - `save_generated(post: GeneratedPost) -> PublishedPost` — сохраняет новый сгенерированный пост со статусом `generated`.
  - `mark_published(source_url: str, telegram_message_id: int) -> PublishedPost` — переводит пост в статус `published` и сохраняет Telegram message id.
  - `mark_failed(source_url: str, error_message: str) -> PublishedPost` — переводит пост в статус `failed` и сохраняет текст ошибки.
  - `get_by_source_url(source_url: str) -> PublishedPost | None` — возвращает сохранённый пост по URL или `None`.
- `ReminderSettingsRepository` — репозиторий постоянной настройки напоминаний.
  - `get_settings() -> tuple[bool, int | None, int | str | None]` — возвращает флаг включения, минуты до публикации и чат для уведомлений.
  - `enable(minutes_before: int, chat_id: int | str) -> None` — включает напоминания для всех запланированных публикаций.
  - `disable() -> None` — отключает напоминания, сохраняя последний чат.

## Используемые настройки

Модуль использует `app.config.get_settings()` и настройки `DATABASE_URL`, `APP_TIMEZONE`. Значение БД по умолчанию для локальной разработки — SQLite-файл `sqlite:///./data/publications.db`. `APP_TIMEZONE` используется для нормализации наивных времен контент-плана перед сохранением в локальном времени приложения.

## Взаимодействие с другими модулями

Другие модули должны работать с публикациями только через `PostRepository`. `service.py` вызывает методы репозитория для проверки дублей, сохранения сгенерированного поста и фиксации результата публикации. SQLAlchemy-модель `PostRecord` не должна использоваться в бизнес-логике напрямую.

## Обработка ошибок

- Дубли по `source_url` запрещены уникальным индексом БД. При попытке сохранить второй пост с тем же URL SQLAlchemy выбросит `IntegrityError`.
- `mark_published()` и `mark_failed()` выбрасывают `LookupError`, если запись с переданным `source_url` не найдена.
- Модуль не публикует в Telegram, не вызывает OpenRouter и не хранит секреты.

## Структура таблицы

Таблица `posts` содержит поля:

| Поле | Назначение |
| --- | --- |
| `id` | Первичный ключ записи. |
| `source_url` | URL исходной новости, обязательный и уникальный. |
| `title` | Заголовок сгенерированного поста. |
| `text` | Текст сгенерированного поста. |
| `status` | Текущий статус: `generated`, `published` или `failed`. |
| `telegram_message_id` | ID сообщения в Telegram после успешной публикации. |
| `error_message` | Текст ошибки при неуспешной публикации или генерации. |
| `created_at` | UTC-время создания записи. |
| `updated_at` | UTC-время последнего обновления записи. |

## Правила статусов

- `generated` — пост сгенерирован и сохранён, но ещё не опубликован.
- `published` — пост опубликован в Telegram; `telegram_message_id` заполнен.
- `failed` — обработка или публикация завершилась ошибкой; `error_message` заполнен.

`is_published()` возвращает `True` только для статуса `published`. Записи со статусами `generated` и `failed` не считаются опубликованными.

## Тестирование

Тесты находятся в `tests/test_database.py` и используют временную SQLite in-memory БД. Запуск только тестов БД:

```bash
pytest tests/test_database.py
```

Полный запуск тестов проекта:

```bash
pytest
```

## Пример использования

```python
from app.database import PostRepository, init_db
from app.schemas import GeneratedPost

init_db()
repository = PostRepository()

post = GeneratedPost(
    title="Новость",
    text="Текст публикации",
    image_prompt="Иллюстрация новости",
    source_url="https://example.com/news/1",
)

if not repository.is_published(str(post.source_url)):
    repository.save_generated(post)
    repository.mark_published(str(post.source_url), telegram_message_id=1001)
```

## Консольное логирование

Модуль пишет INFO-логи при инициализации БД, создании директории SQLite, проверке дублей, сохранении `generated`, переводе в `published`, переводе в `failed` и загрузке записи по `source_url`. Эти сообщения помогают понять, дошёл ли бизнес-сценарий до БД и какой `source_url` проверяется или обновляется.

## Хранение контент-планов

Для согласованных контент-планов добавлены таблицы `content_plans` и `content_plan_items`.

`ContentPlanRepository` предоставляет методы:

- `save_plan(plan: ContentPlan) -> int` — сохраняет согласованный план и возвращает id.
- `get_due_items(now: datetime | None = None) -> list[tuple[int, ContentPlanItem]]` — возвращает пункты со статусом `scheduled`, время которых уже наступило.
- `get_scheduled_item_slots() -> list[tuple[int, datetime]]` — возвращает id и `scheduled_at` всех еще запланированных пунктов, чтобы scheduler мог поставить отдельный `date`-job на каждый пункт.
- `mark_item_published(item_id: int, telegram_message_id: int) -> ContentPlanItem` — фиксирует успешную публикацию пункта.
- `mark_item_failed(item_id: int, error_message: str) -> ContentPlanItem` — фиксирует ошибку публикации пункта.

Пункты плана имеют статусы `scheduled`, `published`, `failed`. `init_db()` создает таблицы контент-планов вместе с таблицей публикаций.

## Отмена и редактирование пунктов контент-плана

Для предпубликационного согласования добавлен статус `cancelled`: пункт не будет опубликован после отказа пользователя.

`ContentPlanRepository` дополнительно предоставляет методы:

- `get_item(item_id: int) -> ContentPlanItem` — загрузить один пункт для напоминания или ручного действия;
- `update_item_content(item_id: int, item: ContentPlanItem) -> ContentPlanItem` — сохранить обновленные AI заголовок, текст и `image_prompt`;
- `mark_item_cancelled(item_id: int, error_message: str | None = None) -> ContentPlanItem` — отменить публикацию пункта.


## Хранение настроек напоминаний

Постоянная настройка меню `⏰ Напоминания` хранится в таблице `reminder_settings`. `ReminderSettingsRepository` возвращает выключенное состояние, если запись еще не создана; при включении сохраняет количество минут до публикации и `chat_id`, а при отключении сбрасывает минуты и флаг `enabled`. Эта настройка не привязана к конкретному контент-плану, поэтому `app.main` может применять ее ко всем старым и новым пунктам со статусом `scheduled`.
