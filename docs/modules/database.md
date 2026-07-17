# Модуль database

## Назначение

`app.database` отвечает за хранение сгенерированных и опубликованных постов в SQLite через SQLAlchemy. Модуль защищает приложение от повторной публикации одной новости за счёт уникального поля `source_url`.

## Публичные классы и функции

- `engine` — SQLAlchemy engine, созданный на основе `settings.database_url`.
- `SessionLocal` — фабрика сессий SQLAlchemy для работы приложения.
- `Base` — базовый класс декларативных SQLAlchemy-моделей.
- `PostRecord` — ORM-модель таблицы `posts`.
- `init_db() -> None` — создаёт каталог для файловой SQLite-БД и таблицы, если они ещё не существуют.
- `PostRepository` — репозиторий для бизнес-логики без прямого доступа к SQLAlchemy.
  - `is_published(source_url: str) -> bool` — возвращает `True`, если URL уже имеет статус `published`.
  - `save_generated(post: GeneratedPost) -> PublishedPost` — сохраняет новый сгенерированный пост со статусом `generated`.
  - `mark_published(source_url: str, telegram_message_id: int) -> PublishedPost` — переводит пост в статус `published` и сохраняет Telegram message id.
  - `mark_failed(source_url: str, error_message: str) -> PublishedPost` — переводит пост в статус `failed` и сохраняет текст ошибки.
  - `get_by_source_url(source_url: str) -> PublishedPost | None` — возвращает сохранённый пост по URL или `None`.

## Используемые настройки

Модуль использует `app.config.get_settings()` и настройку `DATABASE_URL`. Значение по умолчанию для локальной разработки — SQLite-файл `sqlite:///./data/publications.db`.

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
- `mark_item_published(item_id: int, telegram_message_id: int) -> ContentPlanItem` — фиксирует успешную публикацию пункта.
- `mark_item_failed(item_id: int, error_message: str) -> ContentPlanItem` — фиксирует ошибку публикации пункта.

Пункты плана имеют статусы `scheduled`, `published`, `failed`. `init_db()` создает таблицы контент-планов вместе с таблицей публикаций.
