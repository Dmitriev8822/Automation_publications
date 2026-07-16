from app.schemas import GeneratedPost, News, PostStatus
from app.service import create_and_publish_post


class FakeAIClient:
    def __init__(self, news_items):
        self.news_items = news_items

    def find_fresh_news(self):
        return self.news_items

    def generate_post(self, news):
        return GeneratedPost(
            title=news.title,
            text="Generated text",
            image_prompt="Image prompt",
            source_url=news.source_url,
        )

    def generate_image(self, post):
        return None


class FakeTelegramPublisher:
    def __init__(self):
        self.calls = 0

    def publish_post(self, post, image=None):
        self.calls += 1
        return 42


class FakeRepository:
    def __init__(self, published=None):
        self.published = set(published or [])
        self.saved = []

    def is_news_published(self, source_url):
        return source_url in self.published

    def save_post(self, post, status, telegram_message_id=None, error_message=None):
        saved = {
            "post": post,
            "status": status,
            "telegram_message_id": telegram_message_id,
            "error_message": error_message,
        }
        self.saved.append(saved)
        return saved


def test_create_and_publish_post_publishes_first_unpublished_news():
    news = News(
        title="News",
        source_url="https://example.com/news",
        source_name="Example",
        summary="Summary",
    )
    repository = FakeRepository()
    publisher = FakeTelegramPublisher()

    result = create_and_publish_post(FakeAIClient([news]), publisher, repository)

    assert result["status"] == PostStatus.PUBLISHED
    assert result["telegram_message_id"] == 42
    assert publisher.calls == 1


def test_create_and_publish_post_returns_none_when_all_news_published():
    news = News(
        title="News",
        source_url="https://example.com/news",
        source_name="Example",
        summary="Summary",
    )
    repository = FakeRepository(published={"https://example.com/news"})
    publisher = FakeTelegramPublisher()

    result = create_and_publish_post(FakeAIClient([news]), publisher, repository)

    assert result is None
    assert publisher.calls == 0
