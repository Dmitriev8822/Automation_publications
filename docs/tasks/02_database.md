# Задача 02. Модуль базы данных

## Цель

Реализовать хранение опубликованных постов в SQLite через SQLAlchemy и защиту от повторной публикации одной новости.

## Работать в файлах

- `app/database.py`
- `app/schemas.py` при необходимости согласования типов
- `tests/test_database.py`
- `docs/modules/database.md`

## Что реализовать

1. SQLAlchemy engine на основе `settings.database_url`.
2. `SessionLocal` или фабрику сессий.
3. SQLAlchemy-модель `PostRecord` с полями:
   - `id`;
   - `source_url`, уникальное и обязательное;
   - `title`;
   - `text`;
   - `status`;
   - `telegram_message_id`;
   - `error_message`;
   - `created_at`;
   - `updated_at`.
4. Функцию `init_db() -> None`.
5. Репозиторий `PostRepository` с методами:
   - `is_published(source_url: str) -> bool`;
   - `save_generated(post: GeneratedPost) -> PublishedPost`;
   - `mark_published(source_url: str, telegram_message_id: int) -> PublishedPost`;
   - `mark_failed(source_url: str, error_message: str) -> PublishedPost`;
   - `get_by_source_url(source_url: str) -> PublishedPost | None`.

## Интерфейсы для других модулей

`service.py` должен работать с репозиторием через методы выше и не должен напрямую использовать SQLAlchemy.

Пример:

```python
if repository.is_published(news.source_url):
    continue

repository.save_generated(generated_post)
repository.mark_published(generated_post.source_url, message_id)
```

## Откуда брать информацию

- Общие схемы: `app/schemas.py`.
- Настройки подключения: `app/config.py`.
- Архитектура: `docs/ARCHITECTURE.md`.

## Что нельзя делать

- Не публиковать в Telegram из `database.py`.
- Не вызывать OpenRouter из `database.py`.
- Не хранить секреты в БД.
- Не допускать дублей по `source_url`.

## Тесты

Проверить:

- создание таблиц;
- сохранение generated-поста;
- `is_published` для опубликованного и неопубликованного URL;
- уникальность `source_url`;
- `mark_published`;
- `mark_failed`.

Тесты должны использовать временную SQLite-БД или SQLite in-memory.

## Документация после реализации

Создать `docs/modules/database.md` и описать:

- структуру таблицы;
- публичные методы репозитория;
- правила статусов;
- как запустить тесты БД.
