# Модуль schemas

`app/schemas.py` содержит общие Pydantic-контракты проекта: `News`, `GeneratedPost`, `ImageAsset`, `PublishedPost` и `PostStatus`.

Модуль не обращается к внешним API и используется остальными частями приложения как единый источник типов данных.
