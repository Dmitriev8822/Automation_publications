# Automation_publications

MVP-сервис для автоматической подготовки и публикации постов в Telegram-канал. Приложение ищет свежую новость по заданной теме через OpenRouter, генерирует Telegram-текст и опциональное изображение, публикует результат в канал и сохраняет факт публикации в SQLite.

## Возможности

- модульная архитектура приложения в пакете `app/`;
- общие Pydantic-контракты для обмена данными между модулями;
- интеграции с OpenRouter, Telegram Bot API, SQLite/SQLAlchemy и APScheduler;
- быстрые startup-тесты без обращений к реальным внешним API;
- отдельный режим `--check`, чтобы проверить готовность окружения после заполнения `.env` без запуска бесконечного scheduler-цикла.

## Структура проекта

```text
app/
  __init__.py
  ai.py
  config.py
  database.py
  main.py
  scheduler.py
  schemas.py
  service.py
  telegram.py
docs/
  ARCHITECTURE.md
  modules/
  tasks/
tests/
.env.example
requirements.txt
README.md
```

## Быстрый запуск

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

4. Заполните в `.env` реальные секреты и параметры канала:

   ```dotenv
   APP_ENV=prod
   OPENROUTER_API_KEY=sk-or-...
   TELEGRAM_BOT_TOKEN=123456:...
   TELEGRAM_CHANNEL_ID=@your_channel
   ```

   Не храните реальные секреты в `.env.example` или в Git.

5. Проверьте тесты и runtime-конфигурацию без запуска scheduler:

   ```bash
   python -m app.main --check
   ```

6. Запустите сервис:

   ```bash
   python -m app.main
   ```

После запуска приложение выполняет быстрые тесты, валидирует production-секреты, инициализирует SQLite-БД и стартует APScheduler. Публикация запускается по интервалу `PUBLISH_INTERVAL_MINUTES`.

## Настройки `.env`

| Переменная | Обязательна для `APP_ENV=prod` | Назначение |
| --- | --- | --- |
| `APP_ENV` | да | Окружение: `dev`, `test` или `prod`. Для реального запуска используйте `prod`. |
| `LOG_LEVEL` | нет | Уровень логирования, например `INFO` или `DEBUG`. |
| `DATABASE_URL` | нет | SQLite URL, по умолчанию `sqlite:///./data/publications.db`. |
| `PUBLISH_INTERVAL_MINUTES` | нет | Период публикаций в минутах, минимум `1`. |
| `OPENROUTER_API_KEY` | да | API-ключ OpenRouter. |
| `OPENROUTER_MODEL` | нет | Модель OpenRouter для поиска новостей и генерации постов; по умолчанию `openai/gpt-4.1-mini`. |
| `OPENROUTER_BASE_URL` | нет | Базовый URL OpenRouter API. |
| `TELEGRAM_BOT_TOKEN` | да | Токен Telegram-бота от BotFather. |
| `TELEGRAM_CHANNEL_ID` | да | Username канала вида `@channel_name` или числовой идентификатор. |
| `NEWS_TOPIC` | нет | Тема новостей. |
| `NEWS_LANGUAGE` | нет | Язык найденных новостей/саммари. |
| `POST_LANGUAGE` | нет | Язык Telegram-поста. |
| `MAX_NEWS_ITEMS` | нет | Сколько новостей запрашивать за один проход. |
| `POST_STYLE` | нет | Стиль поста. |
| `POST_MAX_LENGTH` | нет | Максимальная длина текста поста. |
| `INCLUDE_SOURCE_LINK` | нет | Добавлять ли ссылку на источник. |
| `INCLUDE_HASHTAGS` | нет | Добавлять ли хэштеги. |
| `ENABLE_IMAGE_GENERATION` | нет | Включить генерацию/подготовку изображения. |

## Проверки

Быстрый набор unit-тестов:

```bash
pytest
```

Проверка готовности реального окружения после заполнения `.env`:

```bash
python -m app.main --check
```

## Общие контракты

Все модули импортируют общие типы только из `app.schemas`:

```python
from app.schemas import News, GeneratedPost, ImageAsset, PublishedPost, PostStatus
```

Подробное описание архитектуры находится в `docs/ARCHITECTURE.md`, а документация модулей — в `docs/modules/`.
