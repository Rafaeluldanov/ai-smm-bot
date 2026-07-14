"""Тесты UI AI Learning Loop (v0.6.5): страница «AI обучение вашего бренда» рендерится."""

from fastapi.testclient import TestClient


def test_ai_learning_page_renders(client: TestClient) -> None:
    r = client.get("/ui/projects/1/ai-learning")
    assert r.status_code == 200
    html = r.text
    assert "AI обучение вашего бренда" in html
    # Ключевые блоки экрана присутствуют.
    assert "Что AI понял" in html
    assert "Рекомендации" in html
    assert "Как вам последние посты" in html


def test_ai_learning_page_has_feedback_buttons(client: TestClient) -> None:
    html = client.get("/ui/projects/1/ai-learning").text
    for label in ("Отлично", "Хорошо", "Нормально", "Не подходит"):
        assert label in html


def test_ai_learning_page_calls_learning_api(client: TestClient) -> None:
    html = client.get("/ui/projects/1/ai-learning").text
    # Экран ходит в новый API обучения (analyze/feedback), без публикаций/live.
    assert "/learning/analyze" in html
    assert "/learning/feedback" in html
    # JS экрана не вызывает публикацию/включение live.
    assert "publish_once_if_allowed" not in html
    assert "live_publishing" not in html
