# Модуль AI/OpenRouter

`app/ai.py` содержит `AIClient` — адаптер к OpenRouter для трёх операций бизнес-процесса:
поиск свежих новостей, генерация текста Telegram-поста и генерация изображения/заготовки изображения.
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
- `generate_image(post: GeneratedPost) -> ImageAsset | None` — изображение как `data`, `url` или `file_path`; возвращает `None`, если генерация изображений отключена.

## OpenRouter API

Клиент отправляет `POST` на endpoint `OPENROUTER_BASE_URL/chat/completions` с Bearer-токеном из
`OPENROUTER_API_KEY`. Запрос использует OpenAI-compatible chat completions формат: `model`, `messages` и
`response_format`.

По официальной документации OpenRouter chat completions создаются через `POST /chat/completions`, а
`response_format` поддерживает JSON mode и `json_schema` structured outputs. Поэтому `AIClient` передаёт
`response_format = {"type": "json_schema", ...}` и дополнительно просит модель возвращать только JSON.

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

System prompt задаёт роль генератора безопасного editorial image asset. User prompt передаёт заголовок,
текст поста и `image_prompt`. Ожидаемый JSON должен содержать хотя бы одно из полей `data`, `url` или
`file_path`, а также опциональный `mime_type`.

```json
{
  "url": "https://example.com/image.png",
  "mime_type": "image/png"
}
```

## Обработка ошибок

- Ошибки HTTP-клиента и статусов OpenRouter нормализуются в `OpenRouterRequestError`.
- Невалидная структура ответа нормализуется в `OpenRouterResponseError`.
- `find_fresh_news()` при пустом ответе, невалидном JSON или ошибке валидации возвращает пустой список: это
  безопасно для пайплайна публикаций, потому что сервис может пропустить текущий запуск.
- `generate_post()` и `generate_image()` выбрасывают понятные исключения, потому что на этих этапах уже выбран
  конкретный материал и ошибку важно видеть вызывающему сервису.
- Если `ENABLE_IMAGE_GENERATION=false`, `generate_image()` не делает HTTP-запрос и возвращает `None`.

## Настройки

На генерацию влияют:

- `OPENROUTER_API_KEY` — ключ OpenRouter;
- `OPENROUTER_MODEL` — модель для chat completions;
- `OPENROUTER_BASE_URL` — базовый URL OpenRouter API;
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

Так тестируются успешный парсинг новостей и постов, парсинг ссылки на изображение, пустой ответ, невалидный JSON и отключение изображения без сетевых запросов.
