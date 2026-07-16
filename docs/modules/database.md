# Модуль database

`app/database.py` содержит SQLAlchemy-модель `PostRecord`, создание session factory и репозиторий `PostRepository`.

`PostRepository` предоставляет методы `is_news_published()` и `save_post()`, чтобы `app/service.py` не зависел от деталей SQLAlchemy.
