# Модуль Telegram

## Назначение

`app/telegram.py` публикует уже сгенерированный текст поста и, при наличии, изображение в Telegram-канал через `pyTelegramBotAPI`. Модуль не генерирует контент, не ищет новости и не сохраняет статус публикации в БД.

## Как создать бота

1. Откройте Telegram и найдите `@BotFather`.
2. Выполните команду `/newbot`.
3. Укажите имя и username бота.
4. Сохраните выданный токен в переменную окружения `TELEGRAM_BOT_TOKEN`.

## Как добавить бота администратором канала

1. Откройте настройки Telegram-канала.
2. Перейдите в раздел администраторов.
3. Добавьте созданного бота.
4. Дайте боту право публиковать сообщения.
5. Укажите идентификатор канала в `TELEGRAM_CHANNEL_ID`, например `@my_channel` или числовой id.

## Настройки

Модуль использует централизованные настройки из `app.config`:

- `TELEGRAM_BOT_TOKEN` — токен бота от `@BotFather`;
- `TELEGRAM_CHANNEL_ID` — канал, куда нужно публиковать посты.

Если обязательные настройки отсутствуют, `TelegramPublisher` выбрасывает `ValueError` с понятным описанием проблемы.

## Публичный интерфейс

```python
from app.telegram import TelegramPublisher

message_id = TelegramPublisher().publish_post(generated_post, image)
```

`publish_post(post, image=None)` возвращает `telegram_message_id` как `int`.

## Публикация текста и изображения

- Если `image` не передан, модуль вызывает `send_message` и публикует `GeneratedPost.text` как обычное текстовое сообщение.
- Если `image` передан, модуль вызывает `send_photo`, передаёт изображение и использует `GeneratedPost.text` как подпись.
- Изображение можно передать через `ImageAsset.data`, `ImageAsset.file_path` или `ImageAsset.url`.

## Ошибки

Ошибки Telegram API и другие ошибки отправки оборачиваются в `RuntimeError` с префиксом `Failed to publish Telegram post`, чтобы вызывающий сервис мог сохранить статус неуспешной публикации.

## Тестирование без реального Telegram

Unit-тесты должны передавать fake/mock bot в `TelegramPublisher(settings, bot=fake_bot)`. В этом режиме настоящий `telebot.TeleBot` не создаётся, HTTP-запросы не выполняются, а тесты проверяют вызовы `send_message`, `send_photo`, возврат `message_id` и проброс ошибок.
