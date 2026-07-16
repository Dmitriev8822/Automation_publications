# Задача 01. Модуль конфигурации

## Цель

Реализовать централизованную загрузку настроек из `.env` через `pydantic-settings`.

## Работать в файлах

- `app/config.py`
- `.env.example`
- `tests/test_config.py`
- `docs/modules/config.md`

## Что реализовать

1. Создать `Settings` на базе `BaseSettings`.
2. Поддержать переменные:
   - `APP_ENV`;
   - `LOG_LEVEL`;
   - `DATABASE_URL`;
   - `PUBLISH_INTERVAL_MINUTES`;
   - `OPENROUTER_API_KEY`;
   - `OPENROUTER_MODEL`;
   - `OPENROUTER_BASE_URL`;
   - `TELEGRAM_BOT_TOKEN`;
   - `TELEGRAM_CHANNEL_ID`;
   - `NEWS_TOPIC`;
   - `NEWS_LANGUAGE`;
   - `POST_LANGUAGE`;
   - `MAX_NEWS_ITEMS`;
   - `POST_STYLE`;
   - `POST_MAX_LENGTH`;
   - `INCLUDE_SOURCE_LINK`;
   - `INCLUDE_HASHTAGS`;
   - `ENABLE_IMAGE_GENERATION`.
3. Сделать функцию `get_settings() -> Settings`.
4. Сделать функцию `validate_runtime_settings(settings: Settings) -> None`.
5. В `prod`-режиме требовать наличие OpenRouter и Telegram-настроек.
6. В `dev` и `test` разрешить отсутствие реальных ключей.

## Интерфейсы для других модулей

Другие модули должны получать настройки так:

```python
from app.config import get_settings

settings = get_settings()
```

## Откуда брать информацию

- Переменные окружения: `.env.example`.
- Общий процесс: `docs/ARCHITECTURE.md`.

## Что нельзя делать

- Не читать `.env` вручную через `os.getenv` в других модулях.
- Не хранить секреты в коде.
- Не завершать процесс через `sys.exit()` внутри `config.py`; лучше выбрасывать исключение.

## Тесты

Проверить:

- дефолтные значения;
- переопределение через environment variables;
- ошибку в `prod`, если нет обязательных секретов;
- отсутствие ошибки в `dev` без секретов.

## Документация после реализации

Создать `docs/modules/config.md` и описать:

- список переменных;
- дефолтные значения;
- какие переменные обязательны в `prod`;
- пример `.env` для локальной разработки.
