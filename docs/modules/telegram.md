# Модуль telegram

## Назначение

`app.telegram` публикует уже сгенерированный текст поста и опциональное изображение в Telegram-канал через `pyTelegramBotAPI`. Модуль не генерирует контент, не ищет новости и не записывает статус публикации в БД.

## Публичные классы и функции

- `TelegramPublisher` — адаптер публикации в Telegram.
- `TelegramPublisher.publish_post(post: GeneratedPost, image: ImageAsset | None = None) -> int` — публикует текстовый пост или изображение с подписью и возвращает `telegram_message_id`.

## Настройки

Модуль использует настройки из `app.config.Settings`:

| Переменная | Назначение |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | токен бота, полученный у BotFather |
| `TELEGRAM_CHANNEL_ID` | username канала вида `@channel_name` или числовой идентификатор канала |

Если одна из настроек отсутствует, `TelegramPublisher` выбрасывает `ValueError` с понятным сообщением.

## Как создать бота

1. Откройте Telegram и найдите `@BotFather`.
2. Выполните команду `/newbot`.
3. Укажите имя и username бота.
4. Сохраните выданный токен в переменную `TELEGRAM_BOT_TOKEN`.

## Как добавить бота администратором канала

1. Откройте настройки Telegram-канала.
2. Перейдите в раздел администраторов.
3. Добавьте созданного бота.
4. Выдайте боту право публиковать сообщения.
5. Укажите канал в `TELEGRAM_CHANNEL_ID`, например `@my_channel`.

## Как работает публикация

- Если `image` не передан, `publish_post()` вызывает `send_message(chat_id=..., text=post.text)`.
- Если `image` передан, `publish_post()` вызывает `send_photo(chat_id=..., photo=..., caption=post.text)`.
- Для `ImageAsset` поддерживаются `data`, `file_path` и `url`.
- Метод возвращает `message.message_id` из ответа Telegram.
- Ошибки Telegram API оборачиваются в `RuntimeError` с префиксом `Telegram publication failed`.

## Тестирование без реального Telegram

Unit-тесты должны передавать fake/mock bot в `TelegramPublisher(settings=..., bot=...)`. Такой бот реализует методы `send_message()` и `send_photo()` и возвращает объект с `message_id`. Это позволяет проверить публикацию текста, изображений, возврат ID и проброс ошибок без реальных HTTP-запросов.

Запуск тестов модуля:

```bash
pytest tests/test_telegram.py
```

## Пример использования

```python
from app.telegram import TelegramPublisher

telegram_publisher = TelegramPublisher()
message_id = telegram_publisher.publish_post(generated_post, image)
```

## Используемые настройки

См. описание выше в этом документе.

## Взаимодействие с другими модулями

См. описание выше в этом документе.

## Обработка ошибок

См. описание выше в этом документе.
