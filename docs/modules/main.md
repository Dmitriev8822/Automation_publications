# Main

`app.main` — точка входа приложения и место сборки зависимостей.

## Порядок старта

1. Загружаются настройки через `get_settings()` из `app.config`.
2. Настраивается root-logging с уровнем из `LOG_LEVEL`.
3. Запускаются startup-тесты через `pytest`.
4. Если startup-тесты завершились ошибкой, приложение возвращает код `1` и не запускает scheduler.
5. Выполняется runtime-валидация настроек через `validate_runtime_settings(settings)`.
6. Инициализируется БД вызовом `init_db()`.
7. Создаются зависимости:
   - `PostRepository()`;
   - `AIClient(settings)`;
   - `TelegramPublisher(settings)`.
8. Собирается job-функция, которая вызывает `create_and_publish_post(ai_client, telegram_publisher, repository)`.
9. Создается scheduler через `create_scheduler(job, settings.publish_interval_minutes)` и запускается `scheduler.start()`.

## Импорт без запуска

Модуль можно безопасно импортировать в тестах и других инструментах: приложение стартует только при выполнении файла как скрипта благодаря блоку `if __name__ == "__main__"`.

## Startup-тесты

Startup-тесты запускаются до создания scheduler. Они не должны выполнять реальные OpenRouter или Telegram запросы; интеграции проверяются через моки и fake-клиенты в unit-тестах.
