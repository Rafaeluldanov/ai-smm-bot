"""Сервис генерации постов из тем (Этап 5).

Превращает выбранную тему (``Topic``) в черновик поста: собирает тексты под
Telegram, VK и Instagram по детерминированным шаблонам формата, добавляет CTA,
SEO-ключи и хэштеги, подбирает медиа-актив. Реального AI и сети здесь нет —
тексты формируются из таксономии форматов и помощников текста.

Если подходящего медиа нет, пост помечается статусом ``needs_media``, иначе —
``draft``. Публикация и согласование на этом этапе не выполняются.
"""

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.project import Project
from app.models.topic import Topic
from app.repositories import post_repository, project_repository, topic_repository
from app.repositories.topic_repository import TopicNotFoundError
from app.schemas.post import (
    PostCreate,
    PostGenerationRequest,
    PostGenerationResult,
    PostRead,
    WeeklyPostGenerationRequest,
    WeeklyPostGenerationResult,
)
from app.schemas.topic import TopicSelectionRequest
from app.services import topic_taxonomy
from app.services.post_media_selection_service import PostMediaSelectionService
from app.services.post_template_taxonomy import get_available_formats, infer_format_from_topic
from app.services.post_text_helpers import build_cta, build_hashtags, get_brand_name, shorten_text
from app.services.topic_selection_service import TopicSelectionService
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError

logger = get_logger(__name__)

# Предел длины «крючка» для Instagram (формат короче и визуальнее).
_INSTAGRAM_HOOK_LEN = 200


class PostGenerationService:
    """Собирает черновики постов из тем (без AI и публикации)."""

    def __init__(
        self,
        media_selection_service: PostMediaSelectionService,
        topic_selection_service: TopicSelectionService,
    ) -> None:
        self._media = media_selection_service
        self._topic_selection = topic_selection_service

    # --- Публичные методы ---

    def generate_post_for_topic(
        self, db: Session, topic_id: int, request: PostGenerationRequest | None = None
    ) -> PostGenerationResult:
        """Сгенерировать пост по id темы. 404 (TopicNotFoundError), если темы нет."""
        topic = topic_repository.get_topic_by_id(db, topic_id)
        if topic is None:
            raise TopicNotFoundError(topic_id)
        recommended_format = request.recommended_format if request else None
        return self.generate_post_from_topic_object(db, topic, recommended_format)

    def generate_post_from_topic_object(
        self, db: Session, topic: Topic, recommended_format: str | None = None
    ) -> PostGenerationResult:
        """Сгенерировать пост по объекту темы и сохранить его в БД."""
        project = project_repository.get_project_by_id(db, topic.project_id)
        if project is None:
            raise ProjectNotFoundError(topic.project_id)

        notes: list[str] = []
        fmt = self._resolve_format(topic, recommended_format)
        notes.append(f"Формат поста: {fmt}")

        media_asset, warnings = self._media.select_media_for_topic(db, topic)

        cta = build_cta(project.slug, fmt)
        texts = self.generate_platform_texts(project.slug, topic, fmt, cta)
        seo_keywords = list(topic.seo_keywords or [])
        hashtags = build_hashtags(project.slug, topic.title, topic.cluster or "", seo_keywords)

        needs_media = media_asset is None
        status = "needs_media" if needs_media else "draft"
        if media_asset is not None:
            notes.append(f"Подобрано медиа id={media_asset.id}")
        else:
            notes.append("Медиа не найдено — пост помечен needs_media")

        post = post_repository.create_post(
            db,
            PostCreate(
                project_id=topic.project_id,
                topic_id=topic.id,
                media_asset_id=media_asset.id if media_asset is not None else None,
                title=topic.title,
                telegram_text=texts["telegram_text"],
                vk_text=texts["vk_text"],
                instagram_text=texts["instagram_text"],
                hashtags=hashtags,
                seo_keywords=seo_keywords,
                status=status,
            ),
        )
        logger.info(
            "Сгенерирован пост id=%s по теме '%s' (формат=%s, статус=%s)",
            post.id,
            topic.title,
            fmt,
            status,
        )
        if needs_media:
            notes.append(
                "Можно подобрать внешнее изображение (Этап 9): "
                f"POST /external-images/search/post/{post.id}"
            )

        return PostGenerationResult(
            post=PostRead.model_validate(post),
            selected_media_asset_id=media_asset.id if media_asset is not None else None,
            needs_media=needs_media,
            warnings=warnings,
            generation_notes=notes,
        )

    def generate_weekly_posts(
        self, db: Session, request: WeeklyPostGenerationRequest
    ) -> WeeklyPostGenerationResult:
        """Сгенерировать посты на неделю(и) из рекомендованных тем проекта."""
        project = self._resolve_project(db, request.project_id, request.project_slug)
        warnings: list[str] = []
        need = max(request.weeks, 1) * max(request.posts_per_week, 1)

        selection = self._topic_selection.select_topics_for_project(
            db,
            project.id,
            TopicSelectionRequest(
                business_priorities=request.business_priorities,
                weeks=request.weeks,
                posts_per_week=request.posts_per_week,
            ),
        )
        warnings.extend(selection.warnings)

        topics = topic_repository.list_topics(
            db, project_id=project.id, status="recommended", limit=1000
        )
        chosen = topics[:need]
        if len(chosen) < need:
            warnings.append("Рекомендованных тем меньше, чем требуется постов в плане")

        posts: list[PostRead] = []
        for topic in chosen:
            result = self.generate_post_from_topic_object(db, topic)
            posts.append(result.post)
            warnings.extend(result.warnings)

        return WeeklyPostGenerationResult(
            project_id=project.id,
            project_slug=project.slug,
            generated_count=len(posts),
            posts=posts,
            warnings=list(dict.fromkeys(warnings)),
        )

    def generate_platform_texts(
        self, project_slug: str, topic: Topic, format_name: str, cta: str
    ) -> dict[str, str]:
        """Собрать тексты под Telegram, VK и Instagram для темы и формата."""
        brand = get_brand_name(project_slug)
        cluster = topic.cluster or ""
        blocks = self._body_blocks(brand, topic.title, cluster, format_name)
        hashtags = build_hashtags(
            project_slug, topic.title, cluster, list(topic.seo_keywords or [])
        )

        telegram_text = "\n\n".join([*blocks, cta])

        cluster_label = cluster.strip() or "наших изделий"
        bullets = [
            f"— подберём подходящее изделие в категории «{cluster_label}»;",
            "— поможем с макетом и нанесением логотипа;",
            "— рассчитаем тираж, стоимость и сроки;",
            "— учтём задачу: мероприятие, мерч для команды или подарки клиентам.",
        ]
        vk_text = "\n\n".join([blocks[0], "Чем поможем:\n" + "\n".join(bullets), cta])

        instagram_hook = shorten_text(blocks[0], _INSTAGRAM_HOOK_LEN)
        instagram_text = "\n\n".join([instagram_hook, cta, " ".join(hashtags)])

        return {
            "telegram_text": telegram_text,
            "vk_text": vk_text,
            "instagram_text": instagram_text,
        }

    # --- Внутренняя логика ---

    def _resolve_format(self, topic: Topic, recommended_format: str | None) -> str:
        """Определить формат: из запроса → из профиля кластера → по ключевым словам."""
        if recommended_format and recommended_format in get_available_formats():
            return recommended_format
        profile_formats: list[str] = []
        if topic.cluster:
            profile = topic_taxonomy.get_cluster_profile(topic.cluster)
            profile_formats = list(profile.get("recommended_formats", []))
        return infer_format_from_topic(topic.title, topic.cluster or "", profile_formats)

    def _resolve_project(
        self, db: Session, project_id: int | None, project_slug: str | None
    ) -> Project:
        """Найти проект по id или slug. ProjectNotFoundError, если не найден."""
        if project_id is not None:
            project = project_repository.get_project_by_id(db, project_id)
            if project is None:
                raise ProjectNotFoundError(project_id)
            return project
        if project_slug:
            project = project_repository.get_project_by_slug(db, project_slug)
            if project is None:
                raise ProjectNotFoundError(project_slug)
            return project
        raise ProjectNotFoundError("не задан project_id или project_slug")

    def _body_blocks(self, brand: str, title: str, cluster: str, fmt: str) -> list[str]:
        """Сформировать абзацы «тела» поста под формат (без CTA)."""
        cluster_label = cluster.strip() or "наших изделий"
        if fmt == "expert":
            return [
                f"{title} — тема, в которой стоит разобраться заранее, чтобы не "
                "переплатить и получить нужный результат.",
                "Итог зависит от материала, тиража и технологии нанесения: под "
                "разные задачи подходят разные решения, и узкие места видны заранее.",
                f"Если планируете заказ, специалисты {brand} помогут выбрать "
                "подходящий вариант и рассчитать стоимость.",
            ]
        if fmt == "technology":
            return [
                f"{title} — разберём, как это работает и когда технология действительно уместна.",
                "У каждого способа нанесения свои сильные стороны: один выигрывает "
                "на тираже, другой — на детализации и стойкости. Выбор зависит от "
                "изделия, макета и бюджета.",
                f"В {brand} подскажут, какая технология подойдёт под ваш макет и тираж.",
            ]
        if fmt == "case":
            return [
                f"{title} — короткий разбор того, как такая задача решается на практике.",
                "Обычно всё начинается с задачи клиента: изделие, макет, тираж и "
                "сроки. Дальше подбираются материал и технология нанесения, "
                "согласуется образец и запускается производство.",
                f"Похожую задачу можно решить и для вашей компании — в {brand} "
                "помогут собрать решение под цель и бюджет.",
            ]
        if fmt == "faq":
            return [
                f"{title}. Собрали короткие ответы на вопросы, которые задают чаще всего.",
                "Что важно учесть: изделие и материал, технологию нанесения, тираж и "
                "сроки. От этих параметров зависят и стоимость, и итоговый вид.",
                f"Остались вопросы — специалисты {brand} подскажут вариант под вашу задачу.",
            ]
        if fmt == "selling":
            return [
                f"{title} — поможем подобрать решение под вашу задачу, тираж и бюджет.",
                "Подберём изделие и технологию нанесения, рассчитаем стоимость и "
                "сроки. Работаем и с небольшими партиями, и с крупными заказами.",
                f"{brand} ведёт заказ от макета до готовой партии.",
            ]
        # product — формат по умолчанию.
        return [
            f"{title} — один из самых востребованных вариантов в категории «{cluster_label}».",
            "Такие изделия заказывают для мероприятий, команд, промоакций, "
            "welcome-наборов и подарков клиентам. До запуска стоит определиться с "
            "материалом, тиражом и способом нанесения логотипа.",
            f"В {brand} можно собрать решение под задачу компании — от небольшого "
            "пробного тиража до крупной партии.",
        ]
