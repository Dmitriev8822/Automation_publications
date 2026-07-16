# Модуль config

`app/config.py` загружает настройки из переменных окружения и `.env` через `pydantic-settings`.

В `dev` и `test` реальные ключи OpenRouter и Telegram могут отсутствовать. В `prod` функция `validate_runtime_settings()` требует `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHANNEL_ID`.
