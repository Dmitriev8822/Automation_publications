# Задача 05. Модуль service

## Цель

Реализовать главный бизнес-сценарий: найти свежую неопубликованную новость, сгенерировать пост и изображение, опубликовать в Telegram и сохранить результат в БД.

## Работать в файлах

- `app/service.py`
- `app/schemas.py` при необходимости согласования типов
- `tests/test_service.py`
- `docs/modules/service.md`

## Что реализовать

1. Функцию или класс сервиса:

```python
def create_and_publish_post(
    ai_client,
    telegram_publisher,
    repository,
) -> PublishedPost | None:
    ...
```

2. Последовательность:
   - получить список новостей через `ai_client.find_fresh_news()`;
   - выбрать первую новость, для которой `repository.is_published(news.source_url)` возвращает `False`;
   - сгенерировать пост через `ai_client.generate_post(news)`;
   - сохранить статус `generated` через `repository.save_generated(generated_post)`;
   - сгенерировать изображение через `ai_client.generate_image(generated_post)`;
   - опубликовать через `telegram_publisher.publish_post(generated_post, image)`;
   - сохранить статус `published` через `repository.mark_published(...)`;
   - вернуть `PublishedPost`.
3. Если нет новых новостей, вернуть `None`.
4. Если публикация или генерация падает, сохранить `failed`, если уже известен `source_url`.
5. Добавить логирование ключевых шагов.

## Интерфейсы для других модулей

Сервис является точкой сборки. Он должен использовать только публичные контракты:

```python
ai_client.find_fresh_news()
ai_client.generate_post(news)
ai_client.generate_image(post)
repository.is_published(source_url)
repository.save_generated(post)
repository.mark_published(source_url, message_id)
repository.mark_failed(source_url, error_message)
telegram_publisher.publish_post(post, image)
```

## Откуда брать информацию

- Общий процесс: `docs/ARCHITECTURE.md`.
- Контракты схем: `app/schemas.py`.
- Документация модулей `ai`, `telegram`, `database` после их реализации.

## Что нельзя делать

- Не создавать реальные клиенты OpenRouter/Telegram внутри unit-тестов.
- Не использовать SQLAlchemy напрямую, только репозиторий.
- Не читать `.env` напрямую.
- Не делать sleep/цикл расписания в `service.py`; это задача `scheduler.py`.

## Тесты

Проверить с fake-клиентами:

- успешный полный сценарий;
- пропуск уже опубликованных новостей;
- возврат `None`, если новых новостей нет;
- ошибка генерации текста;
- ошибка генерации изображения;
- ошибка Telegram;
- корректный вызов `mark_failed`.

## Документация после реализации

Создать `docs/modules/service.md` и описать:

- пошаговый алгоритм;
- какие зависимости передаются в сервис;
- какие статусы сохраняются;
- как тестировать бизнес-логику без внешних API.
