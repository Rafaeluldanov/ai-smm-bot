"""Генерация одного черновика поста по теме (без сети и AI).

Запуск:
  make generate-post topic_id=1
  python -m app.scripts.generate_post --topic-id 1 --format product
"""

import argparse

from app.api.deps import get_post_generation_service
from app.db.session import get_sessionmaker
from app.repositories.topic_repository import TopicNotFoundError
from app.schemas.post import PostGenerationRequest
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError


def main() -> None:
    """Точка входа CLI генерации поста по теме."""
    parser = argparse.ArgumentParser(description="Генерация черновика поста по теме")
    parser.add_argument("--topic-id", type=int, required=True)
    parser.add_argument("--format", default=None, help="expert|product|technology|case|faq|selling")
    args = parser.parse_args()

    request = PostGenerationRequest(recommended_format=args.format)
    service = get_post_generation_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            result = service.generate_post_for_topic(db, args.topic_id, request)
        except (TopicNotFoundError, ProjectNotFoundError) as exc:
            print(f"Ошибка: {exc}")
            return

    post = result.post
    print(f"Пост id={post.id} | статус: {post.status} | тема: {post.title}")
    print(f"Медиа: {result.selected_media_asset_id} | needs_media: {result.needs_media}\n")
    print("[Telegram]\n" + (post.telegram_text or ""))
    print("\n[VK]\n" + (post.vk_text or ""))
    print("\n[Instagram]\n" + (post.instagram_text or ""))
    print("\nХэштеги: " + " ".join(post.hashtags))
    print("SEO: " + ", ".join(post.seo_keywords))
    for note in result.generation_notes:
        print(f"  · {note}")
    for warning in result.warnings:
        print(f"  ! {warning}")


if __name__ == "__main__":
    main()
