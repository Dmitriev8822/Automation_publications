# Модуль config

## Назначение

`app.config` централизованно загружает настройки приложения из переменных окружения и файла `.env` через `pydantic-settings`. Остальные модули должны получать конфигурацию через `get_settings()` или принимать готовый объект `Settings` снаружи.

## Публичные классы и функции

- `Settings` — Pydantic-модель настроек на базе `BaseSettings`.
- `get_settings() -> Settings` — возвращает кэшированный экземпляр настроек.
- `validate_runtime_settings(settings: Settings) -> None` — проверяет обязательные runtime-настройки для production-режима.

## Используемые настройки

| Переменная | Поле `Settings` | Дефолт | Обязательна в `prod` | Назначение |
| --- | --- | --- | --- | --- |
| `APP_ENV` | `app_env` | `dev` | нет | Режим запуска: `dev`, `test`, `prod`. |
| `LOG_LEVEL` | `log_level` | `INFO` | нет | Уровень логирования. |
| `DATABASE_URL` | `database_url` | `sqlite:///./data/publications.db` | нет | URL подключения к БД. |
| `PUBLISH_INTERVAL_MINUTES` | `publish_interval_minutes` | `30` | нет | Интервал публикаций в минутах. |
| `OPENROUTER_API_KEY` | `openrouter_api_key` | пусто | да | API-ключ OpenRouter. |
| `OPENROUTER_MODEL` | `openrouter_model` | `openai/gpt-4.1-mini` | нет | Модель OpenRouter для поиска новостей и текста. |
| `OPENROUTER_IMAGE_MODEL` | `openrouter_image_model` | `openai/gpt-image-1-mini` | нет | Модель OpenRouter Images API для реальных изображений. |
| `OPENROUTER_IMAGE_SIZE` | `openrouter_image_size` | пусто | нет | Опциональный размер изображения, если поддерживается выбранной image-моделью. |
| `OPENROUTER_IMAGE_QUALITY` | `openrouter_image_quality` | `low` | нет | Качество изображения. |
| `OPENROUTER_IMAGE_FORMAT` | `openrouter_image_format` | пусто | нет | Опциональный формат изображения, если поддерживается выбранной image-моделью. |
| `OPENROUTER_BASE_URL` | `openrouter_base_url` | `https://openrouter.ai/api/v1` | нет | Base URL OpenRouter API. |
| `OPENROUTER_ENABLE_WEB_SEARCH` | `openrouter_enable_web_search` | `true` | нет | Включает OpenRouter `openrouter:web_search` server tool для поиска свежих новостей. |
| `OPENROUTER_WEB_SEARCH_ENGINE` | `openrouter_web_search_engine` | `auto` | нет | Engine web-search server tool; `auto` выбирает native search или fallback. |
| `OPENROUTER_WEB_SEARCH_MAX_RESULTS` | `openrouter_web_search_max_results` | `5` | нет | Максимум результатов web-search для grounding новостей. |
| `TELEGRAM_BOT_TOKEN` | `telegram_bot_token` | пусто | да | Токен Telegram-бота. |
| `TELEGRAM_CHANNEL_ID` | `telegram_channel_id` | пусто | да | ID или username Telegram-канала. |
| `NEWS_TOPIC` | `news_topic` | `technology` | нет | Тема поиска новостей. |
| `NEWS_LANGUAGE` | `news_language` | `ru` | нет | Язык исходных новостей. |
| `POST_LANGUAGE` | `post_language` | `ru` | нет | Язык генерируемого поста. |
| `MAX_NEWS_ITEMS` | `max_news_items` | `5` | нет | Максимальное число новостей для обработки. |
| `POST_STYLE` | `post_style` | `concise` | нет | Стиль текста поста. |
| `POST_MAX_LENGTH` | `post_max_length` | `1000` | нет | Максимальная длина поста. |
| `INCLUDE_SOURCE_LINK` | `include_source_link` | `true` | нет | Добавлять ссылку на источник в пост. |
| `INCLUDE_HASHTAGS` | `include_hashtags` | `true` | нет | Добавлять хэштеги в пост. |
| `ENABLE_IMAGE_GENERATION` | `enable_image_generation` | `false` | нет | Включать генерацию изображения. |

## Взаимодействие с другими модулями

Другие модули не должны читать `.env` вручную. Основной способ использования:

```python
from app.config import get_settings

settings = get_settings()
```

В тестах можно создавать изолированный экземпляр без чтения `.env`:

```python
settings = Settings(_env_file=None, APP_ENV="test")
```

## Обработка ошибок

- Если `APP_ENV` не равен `dev`, `test` или `prod`, `Settings` выбрасывает ошибку валидации Pydantic.
- Если `validate_runtime_settings()` вызывается для `prod` без `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN` или `TELEGRAM_CHANNEL_ID`, выбрасывается `ValueError`.
- В `prod` `TELEGRAM_BOT_TOKEN` дополнительно проверяется на базовый формат Telegram-токена `<bot_id>:<secret>`, чтобы ошибка конфигурации была понятной до создания `TeleBot`.
- В `dev` и `test` реальные секреты не обязательны.
- Модуль не вызывает `sys.exit()`.

## Тестирование

Тесты находятся в `tests/test_config.py` и проверяют дефолты, переопределение через environment variables, production-валидацию и отсутствие ошибки без секретов в `dev`/`test`.

Запуск:

```bash
pytest tests/test_config.py
```

## Пример использования

Пример `.env` для локальной разработки:

```dotenv
APP_ENV=dev
LOG_LEVEL=INFO
DATABASE_URL=sqlite:///./data/publications.db
PUBLISH_INTERVAL_MINUTES=30
OPENROUTER_API_KEY=
OPENROUTER_MODEL=openai/gpt-4.1-mini
OPENROUTER_IMAGE_MODEL=openai/gpt-image-1-mini
OPENROUTER_IMAGE_QUALITY=low
# Optional: set only if the selected image model supports these parameters.
# OPENROUTER_IMAGE_SIZE=1024x1024
# OPENROUTER_IMAGE_FORMAT=jpeg
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
TELEGRAM_BOT_TOKEN=123456789:replace_with_real_secret
TELEGRAM_CHANNEL_ID=@your_channel
NEWS_TOPIC=technology
NEWS_LANGUAGE=ru
POST_LANGUAGE=ru
MAX_NEWS_ITEMS=5
POST_STYLE=concise
POST_MAX_LENGTH=1000
INCLUDE_SOURCE_LINK=true
INCLUDE_HASHTAGS=true
ENABLE_IMAGE_GENERATION=false
```
