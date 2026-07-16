# Automation_publications

MVP-сервис для автоматической подготовки и публикации постов в Telegram-канал. Приложение ищет свежую новость по заданной теме через OpenRouter, генерирует текст и изображение, публикует результат в Telegram и сохраняет факт публикации в SQLite.

## Возможности

- модульная архитектура приложения в пакете `app/`;
- общие Pydantic-контракты для обмена данными между модулями;
- интеграции, запланированные архитектурой: OpenRouter, Telegram Bot API, SQLite/SQLAlchemy и APScheduler;
- быстрые тесты без обращений к реальным внешним API.

## Структура проекта

```text
app/
  __init__.py
  schemas.py
docs/
  ARCHITECTURE.md
  modules/
    schemas.md
  tasks/
tests/
  test_schemas.py
.env.example
requirements.txt
README.md
```

## Установка

1. Создайте и активируйте виртуальное окружение:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

2. Установите зависимости:

   ```bash
   pip install -r requirements.txt
   ```

3. Создайте локальный файл настроек:

   ```bash
   cp .env.example .env
   ```

4. Заполните `.env` реальными значениями ключей и параметров. Не храните реальные секреты в `.env.example` или в Git.

## Запуск

На текущем этапе реализованы общие схемы и тесты их валидации:

```bash
pytest
```

После реализации остальных модулей точкой входа будет `app/main.py`: приложение должно запускать быстрые тесты, инициализировать инфраструктуру и стартовать планировщик публикаций.

## Общие контракты

Все модули должны импортировать общие типы только из `app.schemas`:

```python
from app.schemas import News, GeneratedPost, ImageAsset, PublishedPost, PostStatus
```

Подробное описание моделей и правил валидации находится в `docs/modules/schemas.md`.
