# Модуль AI/OpenRouter

`app/ai.py` содержит `AIClient` — адаптер к OpenRouter для трёх операций бизнес-процесса:
поиск свежих новостей, генерация текста Telegram-поста и генерация реального изображения.
Модуль не публикует сообщения в Telegram и не сохраняет данные в БД.

## Публичный интерфейс

```python
from app.ai import AIClient

ai_client = AIClient()
news_items = ai_client.find_fresh_news()
generated_post = ai_client.generate_post(news_items[0])
image = ai_client.generate_image(generated_post)
```

Методы возвращают Pydantic-схемы из `app.schemas`:

- `find_fresh_news() -> list[News]` — новости уже отсортированы по приоритету публикации, самая подходящая первая.
- `generate_post(news: News) -> GeneratedPost` — готовый текст поста, заголовок, `image_prompt` и ссылка на источник.
- `generate_image(post: GeneratedPost) -> ImageAsset | None` — реальное изображение из OpenRouter Images API как байты `data` или URL; возвращает `None`, если генерация изображений отключена или API не вернул пригодный файл.

## OpenRouter API

Клиент отправляет `POST` на endpoint `OPENROUTER_BASE_URL/chat/completions` с Bearer-токеном из
`OPENROUTER_API_KEY`. По умолчанию используется более новая модель `openai/gpt-4.1-mini`. Запрос использует
OpenAI-compatible chat completions формат: `model`, `messages` и `response_format`.

По официальной документации OpenRouter chat completions создаются через `POST /chat/completions`, а
`response_format` поддерживает JSON mode и `json_schema` structured outputs. Поэтому `AIClient` сначала передаёт
`response_format = {"type": "json_schema", ...}` и дополнительно просит модель возвращать только JSON. Если провайдер
или конкретная модель отклоняет строгую JSON Schema с HTTP 400/другой ошибкой запроса, клиент автоматически повторяет
тот же запрос с более совместимым `response_format = {"type": "json_object"}`. Это сохраняет работу сервиса с моделями,
у которых structured outputs временно недоступны или отличаются по требованиям.

## Prompt'ы

### Поиск новостей

System prompt задаёт роль редактора новостей и требует JSON-only ответ. User prompt включает:

- тему `NEWS_TOPIC`;
- язык саммари `NEWS_LANGUAGE`;
- лимит `MAX_NEWS_ITEMS`;
- требование сортировать по релевантности и свежести;
- формат объекта `{"news": [...]}`.

Ожидаемый JSON:

```json
{
  "news": [
    {
      "title": "...",
      "source_url": "https://example.com/news",
      "source_name": "Example",
      "summary": "...",
      "published_at": "2026-07-16T10:00:00Z"
    }
  ]
}
```

### Генерация поста

System prompt задаёт роль автора Telegram-постов и требует JSON-only ответ. User prompt включает:

- язык `POST_LANGUAGE`;
- стиль `POST_STYLE`;
- максимальную длину `POST_MAX_LENGTH`;
- флаги `INCLUDE_SOURCE_LINK` и `INCLUDE_HASHTAGS`;
- данные новости: заголовок, саммари, источник и URL.

Ожидаемый JSON:

```json
{
  "title": "...",
  "text": "...",
  "image_prompt": "...",
  "source_url": "https://example.com/news"
}
```

Если модель вернула текст длиннее `POST_MAX_LENGTH`, клиент обрезает его до настроенного лимита.

### Генерация изображения

`generate_image()` использует не chat completions, а dedicated OpenRouter Images API: `POST {OPENROUTER_BASE_URL}/images`. Это важно, потому что обычная текстовая модель `OPENROUTER_MODEL=openai/gpt-4.1-mini` может написать JSON с картинкой или путём, но не обязана реально создать Telegram-пригодный файл. Для реальной генерации используется отдельная настройка `OPENROUTER_IMAGE_MODEL`.

Клиент отправляет в Images API:

- `model = OPENROUTER_IMAGE_MODEL`;
- `prompt` из заголовка, текста поста и `image_prompt`;
- `n = 1`;
- `quality = OPENROUTER_IMAGE_QUALITY`, если настройка задана;
- `size = OPENROUTER_IMAGE_SIZE`, если настройка задана и выбранная модель поддерживает `size`;
- `output_format = OPENROUTER_IMAGE_FORMAT`, если настройка задана и выбранная модель поддерживает `output_format`.

Ожидаемый ответ OpenRouter содержит `data[0].b64_json` и `media_type`. Клиент декодирует `b64_json` в реальные байты перед передачей `ImageAsset` в Telegram. Если API не вернул изображение, метод логирует предупреждение и возвращает `None`, чтобы сервис мог опубликовать пост без изображения.

```json
{
  "data": [
    {
      "b64_json": "iVBORw0KGgo...",
      "media_type": "image/png"
    }
  ],
  "usage": {"cost": 0.04}
}
```

## Обработка ошибок

- Ошибки HTTP-клиента и статусов OpenRouter нормализуются в `OpenRouterRequestError`; перед окончательной ошибкой клиент делает fallback с `json_object`, если первый запрос с `json_schema` был отклонён.
- Невалидная структура ответа нормализуется в `OpenRouterResponseError`.
- Невалидный base64 в `b64_json` изображения приводит к `OpenRouterResponseError`, чтобы не отправлять в Telegram повреждённый файл.
- Если OpenRouter Images API вернул пустой список или пустой image item, `generate_image()` возвращает `None`, и публикация продолжается без изображения.
- `find_fresh_news()` при пустом ответе, невалидном JSON или ошибке валидации возвращает пустой список: это
  безопасно для пайплайна публикаций, потому что сервис может пропустить текущий запуск.
- `generate_post()` и `generate_image()` выбрасывают понятные исключения, потому что на этих этапах уже выбран
  конкретный материал и ошибку важно видеть вызывающему сервису.
- Если `ENABLE_IMAGE_GENERATION=false`, `generate_image()` не делает HTTP-запрос и возвращает `None`.
- Клиент пишет подробные консольные логи о запросах к OpenRouter: endpoint, модель, имя ожидаемой JSON-схемы, тему поиска, лимит новостей, наличие API-ключа без вывода секрета, успешное завершение и ошибки HTTP-клиента.
- При ошибке поиска новостей `find_fresh_news()` сохраняет текст последней ошибки в `AIClient.last_error_message`, чтобы `service.py` мог показать пользователю, что пустой список связан не с отсутствием новостей, а со сбоем запроса. Например, `401 Unauthorized` в логах означает, что OpenRouter отклонил ключ и биллинг не увеличится, потому что запрос не был авторизован.

## Настройки

На генерацию влияют:

- `OPENROUTER_API_KEY` — ключ OpenRouter;
- `OPENROUTER_MODEL` — модель для chat completions; дефолт `openai/gpt-4.1-mini`;
- `OPENROUTER_BASE_URL` — базовый URL OpenRouter API;
- `OPENROUTER_IMAGE_MODEL` — отдельная модель для OpenRouter Images API;
- `OPENROUTER_IMAGE_SIZE` — опциональный размер изображения, если поддерживается выбранной моделью;
- `OPENROUTER_IMAGE_QUALITY` — качество изображения;
- `OPENROUTER_IMAGE_FORMAT` — опциональный формат изображения, если поддерживается выбранной моделью;
- `NEWS_TOPIC` — тема поиска новостей;
- `NEWS_LANGUAGE` — язык новостного саммари;
- `POST_LANGUAGE` — язык Telegram-поста;
- `MAX_NEWS_ITEMS` — лимит возвращаемых новостей;
- `POST_STYLE` — стиль поста;
- `POST_MAX_LENGTH` — максимальная длина текста;
- `INCLUDE_SOURCE_LINK` — добавлять ли ссылку на источник;
- `INCLUDE_HASHTAGS` — добавлять ли хештеги;
- `ENABLE_IMAGE_GENERATION` — включить или отключить генерацию изображений.

## Тестирование без реального API

Unit-тесты передают в `AIClient` fake HTTP-клиент с методом `post()`. Fake возвращает объект с `json()` и
`raise_for_status()`, имитируя OpenRouter chat completions response:

```json
{
  "choices": [
    {"message": {"content": "{...json...}"}}
  ]
}
```

Так тестируются успешный парсинг новостей и постов, вызов Images API, парсинг ссылки на изображение, декодирование `b64_json`/data URL изображения, пустой image item, пустой ответ, невалидный JSON и отключение изображения без сетевых запросов.

## Назначение

См. описание выше в этом документе.

## Публичные классы и функции

См. описание выше в этом документе.

## Используемые настройки

См. описание выше в этом документе.

## Взаимодействие с другими модулями

См. описание выше в этом документе.

## Пример использования

См. описание выше в этом документе.
