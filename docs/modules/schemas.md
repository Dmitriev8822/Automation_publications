# Модуль schemas

## Назначение

`app.schemas` содержит общие Pydantic-модели и enum-статусы, которые используются всеми модулями приложения для обмена данными. Модуль не выполняет внешние API-вызовы и не содержит SQLAlchemy-моделей.

## Публичные классы и функции

### `PostStatus`

Enum жизненного цикла публикации:

| Значение | Назначение |
| --- | --- |
| `generated` | Пост сгенерирован, но ещё не опубликован. |
| `published` | Пост успешно опубликован в Telegram. |
| `failed` | Генерация или публикация завершилась ошибкой. |

### `News`

Новость, выбранная как источник для будущего поста.

| Поле | Тип | Описание |
| --- | --- | --- |
| `title` | `str` | Заголовок новости. |
| `source_url` | `AnyUrl` | Обязательная ссылка на источник. |
| `source_name` | `str` | Название источника. |
| `summary` | `str` | Краткое содержание новости. |
| `published_at` | `datetime | None` | Дата публикации новости, если известна. |

### `GeneratedPost`

Текст и промпт изображения, созданные на основе новости.

| Поле | Тип | Описание |
| --- | --- | --- |
| `title` | `str` | Заголовок поста. |
| `text` | `str` | Непустой и не состоящий только из пробелов текст Telegram-поста. |
| `image_prompt` | `str` | Промпт для генерации изображения. |
| `source_url` | `AnyUrl` | Ссылка на исходную новость. |

### `ImageAsset`

Изображение или ссылка на изображение для публикации.

| Поле | Тип | Описание |
| --- | --- | --- |
| `data` | `bytes | None` | Бинарные данные изображения. |
| `url` | `AnyUrl | None` | URL изображения. |
| `file_path` | `str | None` | Локальный путь к файлу изображения. Хранится как строка без ОС-зависимой нормализации, чтобы POSIX-пути оставались стабильными на Windows. |
| `mime_type` | `str` | MIME-тип, по умолчанию `image/png`. |

### `PublishedPost`

Запись о публикации, которой обмениваются сервисный, Telegram- и database-модули.

| Поле | Тип | Описание |
| --- | --- | --- |
| `id` | `int | None` | Идентификатор записи в БД, если уже сохранена. |
| `source_url` | `AnyUrl` | Ссылка на исходную новость. |
| `title` | `str` | Заголовок опубликованного или подготовленного поста. |
| `text` | `str` | Текст поста. |
| `status` | `PostStatus` | Статус публикации. |
| `telegram_message_id` | `int | None` | ID сообщения в Telegram после успешной публикации. |
| `error_message` | `str | None` | Сообщение об ошибке при статусе `failed`. |

## Используемые настройки

Модуль не читает переменные окружения и не зависит от настроек приложения.

## Взаимодействие с другими модулями

Другие модули должны импортировать сущности только из `app.schemas`:

```python
from app.schemas import News, GeneratedPost, ImageAsset, PublishedPost, PostStatus
```

## Обработка ошибок

Ошибки входных данных обрабатываются средствами Pydantic и приводят к `ValidationError`.

Правила валидации:

- `News.source_url`, `GeneratedPost.source_url` и `PublishedPost.source_url` обязательны и должны быть корректными URL;
- `GeneratedPost.text` должен содержать минимум один непробельный символ;
- `ImageAsset` должен содержать хотя бы одно из полей `data`, `url` или `file_path`;
- `PublishedPost.status` должен быть одним из значений `PostStatus`.

## Тестирование

Проверки находятся в `tests/test_schemas.py` и запускаются командой:

```bash
pytest tests/test_schemas.py
```

## Пример использования

```python
from app.schemas import GeneratedPost, ImageAsset, News, PostStatus, PublishedPost

news = News(
    title="Новая автоматизация",
    source_url="https://example.com/news/1",
    source_name="Example News",
    summary="Краткое описание новости.",
)

post = GeneratedPost(
    title=news.title,
    text="Готовый текст для Telegram.",
    image_prompt="Modern automation illustration",
    source_url=news.source_url,
)

image = ImageAsset(url="https://example.com/image.png")

published = PublishedPost(
    source_url=post.source_url,
    title=post.title,
    text=post.text,
    status=PostStatus.GENERATED,
)
```
