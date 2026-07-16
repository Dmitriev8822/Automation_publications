# Модуль telegram

`app/telegram.py` задаёт интерфейс `TelegramPublisher` и каркас `TeleBotPublisher`.

Публичный метод `publish_post(post, image=None)` должен публиковать готовый пост и возвращать `telegram_message_id`.
