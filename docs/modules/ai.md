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
- `generate_image(post: GeneratedPost) -> ImageAsset | None` — реальное изображение из OpenRouter Images API как байты `data` или URL; возвращает `None`, если генерация изображений отключена или API не вернул пригодный файл. Причина последнего пропуска сохраняется в `AIClient.last_image_error_message`, чтобы сервис мог показать её пользователю.

## OpenRouter API

Клиент отправляет `POST` на endpoint `OPENROUTER_BASE_URL/chat/completions` с Bearer-токеном из
`OPENROUTER_API_KEY`. По умолчанию используется более новая модель `openai/gpt-4.1-mini`. Запрос использует
OpenAI-compatible chat completions формат: `model`, `messages` и `response_format`. Для поиска свежих новостей
клиент дополнительно включает OpenRouter server tool `openrouter:web_search` в поле `tools`, если
`OPENROUTER_ENABLE_WEB_SEARCH=true`. По официальной документации OpenRouter этот server tool даёт любой модели
доступ к real-time web information, а выбранная модель сама формирует поисковый запрос; engine по умолчанию `auto`
использует native provider search, когда он доступен, или fallback через Exa.

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
- формат объекта `{"news": [...]}`;
- обязательное использование web-search-backed источников с реальными публичными URL, когда включён `OPENROUTER_ENABLE_WEB_SEARCH`.

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

System prompt задаёт роль автора Telegram-постов, требует JSON-only ответ и отдельно указывает всегда соблюдать редакционный шаблон из user prompt. User prompt включает:

- язык `POST_LANGUAGE`;
- стиль `POST_STYLE`;
- максимальную длину `POST_MAX_LENGTH`;
- флаги `INCLUDE_SOURCE_LINK` и `INCLUDE_HASHTAGS`;
- встроенный `NEWS_POST_TEMPLATE_PROMPT`, который задаёт единый шаблон новостного Telegram-поста: короткий заголовок, лид, 2–4 компактных абзаца деталей, опциональный контекст и короткое завершение без видимых служебных меток;
- правила живости и вариативности: менять начало, ритм предложений и лексику между публикациями, но сохранять единый нейтрально-информативный стиль канала;
- ограничения фактологии: использовать только данные из выбранной новости, не выдумывать даты, источники, реакции или выводы;
- запрет кликбейта, канцелярита и повторяющихся фраз вроде «важно отметить», «стоит подчеркнуть», «данная ситуация», «на сегодняшний день»;
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

System prompt задаёт роль генератора безопасного editorial image asset и явно запрещает возвращать только переписанный текстовый prompt вместо изображения. User prompt передаёт заголовок, текст поста и `image_prompt`. Ожидаемый JSON должен содержать хотя бы одно из полей `base64_data`, `data` или `url`, а также опциональный `mime_type`. Поле `file_path` считается пригодным только если такой файл уже реально существует на хосте приложения; модель не должна придумывать локальные пути вида `assets/example.jpg`.

Если OpenRouter/модель возвращает `base64_data` или data URL в поле `data`, клиент декодирует строку из base64 в реальные байты изображения перед передачей `ImageAsset` в Telegram. Это важно: отправка base64-строки как обычного UTF-8 текста приводит к невалидному файлу изображения. Если модель вернула только несуществующий `file_path`, клиент логирует предупреждение и возвращает `None`, чтобы сервис опубликовал пост без изображения вместо падения Telegram-публикации с `FileNotFoundError`.

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

- Ошибки HTTP-клиента и статусов OpenRouter нормализуются в `OpenRouterRequestError` с HTTP-статусом и, если доступно, текстом ошибки из ответа OpenRouter. Перед окончательной ошибкой клиент делает fallback с `json_object`, если первый запрос с `json_schema` был отклонён.
- Невалидная структура ответа нормализуется в `OpenRouterResponseError`.
- Невалидный base64 в `data`/`base64_data` изображения также приводит к `OpenRouterResponseError`, чтобы не отправлять в Telegram повреждённый файл.
- Несуществующий `file_path`, возвращённый моделью, игнорируется. Если других источников изображения нет, `generate_image()` возвращает `None`, и публикация продолжается без изображения.
- `find_fresh_news()` при пустом ответе, невалидном JSON или ошибке валидации возвращает пустой список: это
  безопасно для пайплайна публикаций, потому что сервис может пропустить текущий запуск.
- `generate_post()` и `generate_image()` выбрасывают понятные исключения, потому что на этих этапах уже выбран
  конкретный материал и ошибку важно видеть вызывающему сервису.
- Если `ENABLE_IMAGE_GENERATION=false`, `generate_image()` не делает HTTP-запрос, возвращает `None` и сохраняет `last_image_error_message = "ENABLE_IMAGE_GENERATION=false"`. Это дефолтное значение в репозитории, поэтому для реальной генерации картинок в `.env` нужно явно поставить `ENABLE_IMAGE_GENERATION=true`.
- Клиент пишет подробные консольные логи о запросах к OpenRouter: endpoint, модель, имя ожидаемой JSON-схемы, тему поиска, лимит новостей, наличие API-ключа без вывода секрета, успешное завершение и ошибки HTTP-клиента.
- При ошибке поиска новостей `find_fresh_news()` сохраняет текст последней ошибки в `AIClient.last_error_message`, чтобы `service.py` мог показать пользователю, что пустой список связан не с отсутствием новостей, а со сбоем запроса. Например, `401 Unauthorized` или `403 Forbidden` означает, что OpenRouter отклонил ключ, доступ к модели или настройки аккаунта, и биллинг не увеличится, потому что запрос не был авторизован.

## Настройки

На генерацию влияют:

- `OPENROUTER_API_KEY` — ключ OpenRouter;
- `OPENROUTER_MODEL` — модель для chat completions; дефолт `openai/gpt-4.1-mini`. Если в `.env` случайно указан старый суффикс `:online` (например `openai/gpt-4.1-mini:online`), клиент автоматически использует базовую модель без этого суффикса, потому что web search теперь включается отдельным параметром `OPENROUTER_ENABLE_WEB_SEARCH`;
- `OPENROUTER_BASE_URL` — базовый URL OpenRouter API;
- `OPENROUTER_ENABLE_WEB_SEARCH` — включает OpenRouter `openrouter:web_search` server tool для `find_fresh_news()`;
- `OPENROUTER_WEB_SEARCH_ENGINE` — engine server tool, по умолчанию `auto`;
- `OPENROUTER_WEB_SEARCH_MAX_RESULTS` — максимальное число web-search результатов для grounding;
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

Так тестируются успешный парсинг новостей и постов, подключение `openrouter:web_search` только к поиску новостей, парсинг ссылки на изображение, декодирование base64/data URL изображения, игнорирование несуществующего `file_path`, пустой ответ, невалидный JSON и отключение изображения без сетевых запросов.

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

## Генерация контент-плана

`AIClient.generate_content_plan(description: str) -> ContentPlan` принимает свободное описание пользователя и возвращает структурированный `ContentPlan`. В prompt передается текущее время и `APP_TIMEZONE`; наивные даты в ответе AI нормализуются в этот timezone. Метод использует тот же OpenRouter chat completions endpoint и JSON Schema response format. Ожидаемый ответ имеет вид:

```json
{
  "plan": {
    "title": "...",
    "period_start": "2026-07-20T09:00:00Z",
    "period_end": "2026-07-26T18:00:00Z",
    "items": [
      {
        "scheduled_at": "2026-07-20T10:00:00Z",
        "title": "...",
        "text": "...",
        "image_prompt": "...",
        "source_url": "https://example.com/optional"
      }
    ]
  }
}
```

Пустое описание отклоняется `ValueError`, невалидный JSON или схема — `OpenRouterResponseError`.

## Итеративное согласование контент-плана

`AIClient.generate_content_plan(description: str, dialog_context: list[str] | None = None) -> ContentPlan` поддерживает историю диалога. Первое сообщение пользователя остается основным запросом, а последующие уточнения и краткие описания предыдущих вариантов передаются в prompt как контекст правок. Это позволяет продолжать чат до финального согласования плана без потери контекста.

## Перегенерация пунктов контент-плана

Для напоминаний перед публикацией добавлены методы:

- `regenerate_content_plan_item_text(item, instruction="") -> ContentPlanItem` — перегенерирует заголовок, текст и `image_prompt` выбранного пункта;
- `regenerate_content_plan_item_image_prompt(item, instruction="") -> ContentPlanItem` — перегенерирует только описание картинки.

Оба метода используют OpenRouter chat completions с JSON Schema и возвращают обновленный `ContentPlanItem`; сохранение результата выполняет `ContentPlanRepository`.
