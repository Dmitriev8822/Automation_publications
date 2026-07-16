# Задача 00. Общие контракты, структура проекта и документация

## Цель

Создать базовую структуру проекта и общие контракты, на которые будут опираться все остальные модули.

## Работать в файлах

- `app/__init__.py`
- `app/schemas.py`
- `docs/ARCHITECTURE.md`
- `docs/modules/schemas.md`
- `README.md`
- `requirements.txt`
- `.env.example`
- `.gitignore`

## Что реализовать

1. Создать директорию `app/` и файл `app/__init__.py`.
2. Создать `app/schemas.py` с Pydantic-моделями:
   - `News`;
   - `GeneratedPost`;
   - `ImageAsset`;
   - `PublishedPost`;
   - `PostStatus`.
3. Добавить валидацию:
   - `News.source_url` обязателен и должен быть URL;
   - `GeneratedPost.text` не должен быть пустым;
   - `ImageAsset` должен содержать `data`, `url` или `file_path`;
   - `PublishedPost.status` должен быть значением `PostStatus`.
4. Создать `requirements.txt` с основными зависимостями:
   - `openrouter` или HTTP-клиент для OpenRouter;
   - `pyTelegramBotAPI`;
   - `SQLAlchemy`;
   - `APScheduler`;
   - `pydantic`;
   - `pydantic-settings`;
   - `pytest`.
5. Создать `.env.example` с полным списком переменных окружения.
6. Обновить `README.md` кратким описанием проекта, установки и запуска.

## Интерфейсы для других модулей

Модуль `schemas` является источником общих типов. Остальные модули должны импортировать сущности только отсюда:

```python
from app.schemas import News, GeneratedPost, ImageAsset, PublishedPost, PostStatus
```

## Откуда брать информацию

- Основное ТЗ: `doc`.
- Архитектурные контракты: `docs/ARCHITECTURE.md`.

## Что нельзя делать

- Не добавлять реальные ключи в `.env.example`.
- Не создавать внешние API-вызовы в `schemas.py`.
- Не смешивать Pydantic-модели с SQLAlchemy-моделями.

## Тесты

Добавить или подготовить тесты на валидацию схем в `tests/test_schemas.py`.

## Документация после реализации

Создать `docs/modules/schemas.md` и описать:

- все модели;
- поля моделей;
- правила валидации;
- примеры создания объектов.
