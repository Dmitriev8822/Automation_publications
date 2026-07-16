# Модуль ai

`app/ai.py` задаёт интерфейс `AIClient` и каркас `OpenRouterAIClient`.

Реальные HTTP-вызовы OpenRouter будут реализованы отдельной задачей. Сейчас остальные модули могут опираться на методы `find_fresh_news()`, `generate_post()` и `generate_image()`.
