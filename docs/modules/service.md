# Модуль `service`

## Назначение

`app/service.py` собирает главный бизнес-сценарий MVP: выбирает свежую неопубликованную новость, генерирует Telegram-пост и изображение, публикует сообщение в Telegram и обновляет статус публикации в репозитории.

Модуль не создает реальные клиенты OpenRouter, Telegram или SQLAlchemy-объекты. Все зависимости передаются извне, поэтому бизнес-логику можно тестировать fake-реализациями без внешних API.

## Публичная функция

```python
def create_and_publish_post(ai_client, telegram_publisher, repository, progress_callback=None) -> PublishedPost | None:
    ...
```

Функция возвращает:

- `PublishedPost` со статусом `published`, если сценарий успешно завершился;
- `None`, если свежих новостей нет или все найденные новости уже опубликованы;
- пробрасывает исходное исключение, если генерация или публикация завершилась ошибкой. Перед повторным выбрасыванием ошибки сервис пытается сохранить статус `failed`, если уже известен `source_url`.

Опциональный `progress_callback(message: str)` используется ручным запуском из Telegram-бота: сервис отправляет короткие сообщения о поиске новости через OpenRouter, генерации текста, сохранении, публикации и ошибках. Если callback сам падает, ошибка логируется и не останавливает публикацию.

## Зависимости

Сервис использует только публичные контракты соседних модулей.

### `ai_client`

- `find_fresh_news() -> list[News]` — возвращает список свежих новостей.
- `generate_post(news) -> GeneratedPost` — генерирует текст поста и промпт изображения.
- `generate_image(post) -> ImageAsset | None` — генерирует изображение или возвращает `None`, если изображения отключены.

### `telegram_publisher`

- `publish_post(post, image) -> int` — публикует пост в Telegram и возвращает `message_id`.

### `repository`

- `is_published(source_url) -> bool` — проверяет, опубликован ли источник.
- `save_generated(post) -> PublishedPost` — сохраняет статус `generated`.
- `mark_published(source_url, message_id) -> PublishedPost` — сохраняет статус `published` и Telegram `message_id`.
- `mark_failed(source_url, error_message) -> PublishedPost` — сохраняет статус `failed` и текст ошибки.

## Алгоритм

1. Запросить свежие новости через `ai_client.find_fresh_news()`.
2. Последовательно проверить найденные новости через `repository.is_published(news.source_url)`.
3. Выбрать первую новость, которая еще не опубликована.
4. Если такой новости нет, вернуть `None`.
5. Сгенерировать пост через `ai_client.generate_post(news)`.
6. Сохранить промежуточный статус `generated` через `repository.save_generated(generated_post)`.
7. Сгенерировать изображение через `ai_client.generate_image(generated_post)`.
8. Опубликовать пост через `telegram_publisher.publish_post(generated_post, image)`.
9. Сохранить итоговый статус `published` через `repository.mark_published(source_url, message_id)`.
10. Вернуть `PublishedPost`, полученный от репозитория.

## Статусы

- `generated` — пост сгенерирован и сохранен до публикации.
- `published` — пост опубликован в Telegram, сохранен `telegram_message_id`.
- `failed` — генерация или публикация завершилась ошибкой; сервис сохраняет сообщение об ошибке, если известен `source_url`.

## Логирование и ошибки

Сервис логирует ключевые шаги: поиск новостей, пропуск опубликованных источников, выбор новости, генерацию, сохранение, публикацию и обновление статусов. При переданном `progress_callback` те же ключевые этапы дополнительно отправляются пользователю в Telegram в виде коротких сообщений. Если AI-клиент вернул пустой список из-за ошибки и заполнил `last_error_message`, ручной запуск дополнительно отправляет предупреждение `OpenRouter не вернул новости из-за ошибки: ...` перед сообщением об отсутствии свежих новостей.

Если ошибка возникает после определения `source_url`, сервис вызывает `repository.mark_failed(source_url, error_message)`, затем повторно выбрасывает исходное исключение. Если само сохранение статуса `failed` тоже завершается ошибкой, это дополнительно логируется, но не скрывает исходную причину сбоя.

## Тестирование без внешних API

Unit-тесты должны передавать fake-объекты вместо реальных клиентов:

- fake `ai_client` возвращает заранее подготовленные `News`, `GeneratedPost` и `ImageAsset`;
- fake `telegram_publisher` возвращает фиксированный `message_id` или выбрасывает тестовую ошибку;
- fake `repository` хранит вызовы в списках и позволяет проверять порядок и аргументы.

Так можно проверить успешный сценарий, пропуск уже опубликованных новостей, возврат `None`, ошибки генерации текста, ошибки генерации изображения, ошибки Telegram и корректность вызова `mark_failed`.

## Публичные классы и функции

См. описание выше в этом документе.

## Используемые настройки

См. описание выше в этом документе.

## Взаимодействие с другими модулями

См. описание выше в этом документе.

## Обработка ошибок

См. описание выше в этом документе.

## Пример использования

См. описание выше в этом документе.


## Ручное согласование новости

Для схемы ручной публикации добавлены функции:

- `create_manual_publication_draft(ai_client, repository, progress_callback=None) -> ManualPublicationDraft | None` — ищет первую неопубликованную новость, генерирует текст и изображение, но не сохраняет и не публикует черновик до решения пользователя;
- `publish_manual_publication_draft(draft, telegram_publisher, repository) -> PublishedPost` — после кнопки `Принять` сохраняет `generated`, публикует в Telegram и переводит запись в `published`;
- `regenerate_manual_publication_text(draft, ai_client) -> ManualPublicationDraft` — заново генерирует текст и картинку для того же источника;
- `regenerate_manual_publication_image(draft, ai_client) -> ManualPublicationDraft` — заново генерирует только изображение для текущего текста.

Так ручная публикация соответствует пользовательской схеме: подготовка → согласование → принять/отменить/перегенерировать текст и изображение/перегенерировать картинку отдельно. Legacy-функция `create_and_publish_post()` сохранена для совместимости и автоматического сценария без интерактивного согласования.

## Выполнение контент-плана

`publish_due_content_plan_items(telegram_publisher, content_plan_repository) -> list[ContentPlanItem]` публикует все пункты согласованных контент-планов, у которых наступил `scheduled_at` и статус остается `scheduled`.

Алгоритм:

1. Получить due-пункты через `content_plan_repository.get_due_items()`.
2. Для каждого пункта собрать `GeneratedPost` из сохраненного текста.
3. Опубликовать пост через `telegram_publisher.publish_post(post, None)`.
4. При успехе вызвать `mark_item_published(item_id, message_id)`.
5. При ошибке вызвать `mark_item_failed(item_id, error_message)` и продолжить обработку следующих пунктов, чтобы scheduler не остановился.

## Предпубликационное согласование пунктов контент-плана

`publish_due_content_plan_items(telegram_publisher, content_plan_repository, ai_client=None)` может получать `ai_client` только для обратной совместимости или специальных вызовов: если он передан явно, перед публикацией пункта контент-плана генерируется картинка по `image_prompt`. Актуальный runtime `app/main.py` намеренно не передает `ai_client` в плановую публикацию, чтобы после согласования контент-плана в группу уходил сохраненный текст без повторного AI-вызова перед отправкой.

Для сценария напоминаний добавлены функции:

- `approve_content_plan_item_publication(item_id, telegram_publisher, content_plan_repository, ai_client=None)` — после одобрения пользователя не публикует пункт сразу, а проверяет, что он все еще `scheduled`, и оставляет его в расписании; публикация произойдет только по date-job в `scheduled_at`;
- `reject_content_plan_item_publication(item_id, content_plan_repository, reason=None)` — отменяет пункт после отказа пользователя;
- `regenerate_content_plan_item_text(item_id, ai_client, content_plan_repository, instruction="")` — просит AI обновить текст по свободной инструкции пользователя из Telegram и сохраняет результат;
- `regenerate_content_plan_item_image(item_id, ai_client, content_plan_repository, instruction="")` — просит AI обновить prompt картинки и сохраняет результат;
- `reject_content_plan_publication(plan_id, content_plan_repository, reason=None)` — отменяет все scheduled-пункты выбранного плана;
- `regenerate_content_plan(plan_id, ai_client, content_plan_repository, instruction="")` — просит AI перестроить весь контент-план по свободной инструкции пользователя и сохраняет обновленную версию.

Так `service.py` остается единственным местом бизнес-процесса публикации и управляет связкой AI → изображение → Telegram → статус в БД. После успешного одобрения статус остается `scheduled`, поэтому запланированный ранее date-job выполнит публикацию в исходное время. Если пользователь не отвечает на напоминание, пункт также остается `scheduled` и публикуется по таймеру; только явный отказ переводит пункт в отмененное состояние.
