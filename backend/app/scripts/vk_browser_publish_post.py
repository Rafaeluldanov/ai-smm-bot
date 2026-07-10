"""VK browser publisher fallback (dev/local): пост с картинками через веб VK, без API-токена.

Зачем: ключ сообщества VK не может загрузить фото (``photos.getWallUploadServer`` →
error 27), а официальный OAuth user-token для текущего VK ID приложения недоступен.
Пока — локальный fallback: автоматизация браузера. Владелец аккаунта логинится в VK
ВРУЧНУЮ (скрипт НЕ хранит логин/пароль), скрипт готовит текст+картинки поста и
прикрепляет их в форму создания записи группы. По умолчанию dry-run: публикация НЕ
нажимается. Реальная публикация — только с ``--confirm-live true``.

НЕ использует VK API-токены, НЕ делает live API-вызовов VK, НЕ печатает секретов.
Это dev/local инструмент, НЕ SaaS production flow. Playwright — опциональная dev-
зависимость (ставится ``make vk-browser-install``); модуль импортируется и без неё
(браузер поднимается лениво).

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.vk_browser_publish_post \\
      --post-id 123 --group-url "https://vk.com/club240102732" --dry-run true
"""

import argparse
import contextlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.api.deps import get_image_enhancement_processor, get_media_download_service
from app.config import get_settings
from app.db.session import get_sessionmaker
from app.integrations import media_attachments as ma
from app.models.post import Post
from app.repositories import post_publication_repository, post_repository
from app.schemas.post_publication import PostPublicationCreate, PostPublicationUpdate

VK_BASE = "https://vk.com"
UPLOADS_ROOT = Path("tmp/vk_browser_uploads")
DEFAULT_PROFILE_DIR = "tmp/vk_browser_profile"
PLAYWRIGHT_MISSING_MESSAGE = (
    "Установите Playwright: pip install playwright && python -m playwright install chromium"
)
# Селекторы-кандидаты для VK web (DOM VK меняется — пробуем несколько, best-effort).
_COMPOSER_SELECTORS = (
    "text=Что у вас нового?",
    "[placeholder='Что у вас нового?']",
    "div.wall_post_text",
    "[data-testid='posting_open']",
)
_PUBLISH_SELECTORS = (
    "button:has-text('Опубликовать')",
    "text=Опубликовать",
    "[data-testid='posting_submit']",
)


class PlaywrightNotInstalledError(RuntimeError):
    """Playwright не установлен (см. ``make vk-browser-install``)."""


def _parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


# --------------------------------------------------------------------------- #
# Чистые функции (юнит-тестируемы без браузера/сети)                          #
# --------------------------------------------------------------------------- #


def build_group_url_from_group_id(group_id: str | None) -> str | None:
    """Собрать ``https://vk.com/club{id}`` из group_id (или None, если пусто)."""
    if not group_id:
        return None
    gid = str(group_id).strip().lstrip("-")
    for prefix in ("club", "public"):
        if gid.startswith(prefix) and gid[len(prefix) :].isdigit():
            gid = gid[len(prefix) :]
    if not gid:
        return None
    return f"{VK_BASE}/club{gid}"


def select_vk_text(post: Post) -> str:
    """Текст поста для VK: vk_text → telegram_text → title (первый непустой)."""
    for attr in ("vk_text", "telegram_text", "title"):
        value = getattr(post, attr, None)
        if value and str(value).strip():
            return str(value)
    return ""


def _is_image_item(item: dict[str, Any]) -> bool:
    kind = str(item.get("media_kind") or "").lower()
    if kind == "image":
        return True
    if kind == "video":
        return False
    return ma.is_image(str(item.get("file_name") or ""))


def extract_image_media_files(
    generation_notes: dict[str, Any], max_images: int
) -> list[dict[str, Any]]:
    """Отобрать только image из ``generation_notes.media_files`` (с лимитом)."""
    files = generation_notes.get("media_files") or []
    images = [f for f in files if isinstance(f, dict) and _is_image_item(f)]
    if max_images and max_images > 0:
        images = images[:max_images]
    return images


def needs_heic_conversion(file_name: str) -> bool:
    """HEIC/HEIF-файл, который VK web upload может не принять без конвертации в JPEG."""
    return ma.extension(file_name) in ma.HEIC_EXTENSIONS


def text_source(post: Post) -> str:
    """Из какого поля взят текст (для безопасного отчёта, без самого текста)."""
    if post.vk_text and str(post.vk_text).strip():
        return "vk_text"
    if post.telegram_text and str(post.telegram_text).strip():
        return "telegram_text"
    if post.title and str(post.title).strip():
        return "title"
    return "—"


def prepare_images(
    items: list[dict[str, Any]],
    downloader: ma.SupportsPublicMediaDownload | None,
    processor: ma.SupportsImageConversion | None,
    out_dir: Path,
) -> tuple[list[Path], list[str]]:
    """Скачать/сконвертировать картинки во временную папку. Вернуть (пути, предупреждения).

    Приоритет — локальная enhanced-копия (``media_path``); иначе публичная папка
    Яндекс Диска. HEIC/HEIF → JPEG (если есть конвертер); иначе предупреждение, что
    VK web upload может не принять файл. Токены/секреты нигде не используются.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    warnings: list[str] = []
    for index, item in enumerate(items):
        content, file_name = ma.load_item_bytes(item, downloader)
        if content is None:
            warnings.append(f"медиа недоступно, пропущено: {file_name}")
            continue
        content, file_name, _ctype = ma.maybe_convert_heic(content, file_name, processor)
        if needs_heic_conversion(file_name):
            warnings.append(
                f"HEIC/HEIF не сконвертирован ({file_name}) — VK web upload может не принять файл. "
                "Установите конвертер (Pillow/pillow-heif) или подготовьте JPEG вручную."
            )
        safe = ma.sanitize_filename(file_name)
        path = out_dir / f"{index:02d}_{safe}"
        path.write_bytes(content)
        paths.append(path)
    return paths, warnings


# --------------------------------------------------------------------------- #
# Браузерная часть (Playwright) — не тестируется в CI                          #
# --------------------------------------------------------------------------- #


def _import_sync_playwright() -> Any:
    try:
        # Playwright — опциональная dev-зависимость (не в prod requirements).
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover — зависит от локальной установки
        raise PlaywrightNotInstalledError(PLAYWRIGHT_MISSING_MESSAGE) from exc
    return sync_playwright


def _first_visible(page: Any, selectors: tuple[str, ...]) -> Any:  # pragma: no cover
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0:
                return locator
        except Exception:  # noqa: BLE001 — селектор мог не подойти, пробуем следующий
            continue
    return None


def browser_publish(  # pragma: no cover — реальный браузер, вне CI
    *,
    group_url: str,
    text: str,
    image_paths: list[Path],
    dry_run: bool,
    confirm_live: bool,
    headless: bool,
    profile_dir: Path,
    post_id: int,
    out_dir: Path,
) -> dict[str, Any]:
    """Открыть VK в браузере, подготовить пост и (только при confirm-live) опубликовать.

    Логин выполняет ПОЛЬЗОВАТЕЛЬ вручную; профиль браузера хранится в ``profile_dir``
    (пароли не сохраняются скриптом). Возвращает {published, external_url, external_post_id}.
    """
    sync_playwright = _import_sync_playwright()
    result: dict[str, Any] = {"published": False, "external_url": None, "external_post_id": None}
    profile_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile_dir), headless=headless, accept_downloads=False
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(group_url, wait_until="domcontentloaded")
        print(
            "В открывшемся браузере войдите в VK (если ещё не вошли), затем нажмите Enter "
            "в терминале."
        )
        input()

        composer = _first_visible(page, _COMPOSER_SELECTORS)
        if composer is None:
            shot = out_dir / "debug_vk_page.png"
            with contextlib.suppress(Exception):
                page.screenshot(path=str(shot))
            print(
                f"Не найдена область создания поста. Скриншот: {shot}. Создайте пост вручную "
                f"и прикрепите файлы из {out_dir}."
            )
            if dry_run:
                input("Dry-run: браузер оставлен открытым. Нажмите Enter, чтобы закрыть…")
            context.close()
            return result

        try:
            composer.click()
            page.keyboard.type(text)
        except Exception as exc:  # noqa: BLE001
            print(f"Не удалось вставить текст автоматически: {exc}. Вставьте вручную.")

        try:
            file_input = page.locator("input[type=file]").first
            file_input.set_input_files([str(p) for p in image_paths])
            print(f"Прикреплено файлов: {len(image_paths)}")
        except Exception as exc:  # noqa: BLE001
            print(f"Не удалось прикрепить файлы автоматически: {exc}. Прикрепите из {out_dir}.")

        if dry_run:
            print("Dry-run: пост подготовлен в браузере, проверьте вручную. Публикация не нажата.")
            input("Нажмите Enter, чтобы закрыть браузер…")
            context.close()
            return result

        if not confirm_live:  # страховка (run() уже проверяет)
            print("Для реальной публикации нужен --confirm-live true.")
            context.close()
            return result

        publish = _first_visible(page, _PUBLISH_SELECTORS)
        if publish is None:
            print("Кнопка «Опубликовать» не найдена — опубликуйте вручную.")
            context.close()
            return result
        publish.click()
        page.wait_for_timeout(3000)
        result["published"] = True
        try:
            link = page.locator("a[href*='/wall-']").first
            if link.count() > 0:
                href = link.get_attribute("href") or ""
                if href:
                    result["external_url"] = href if href.startswith("http") else f"{VK_BASE}{href}"
                    result["external_post_id"] = href.rstrip("/").split("wall")[-1] or None
        except Exception:  # noqa: BLE001
            pass
        print("Опубликовано (проверьте пост в группе).")
        context.close()
    return result


# --------------------------------------------------------------------------- #
# Оркестрация (тестируема с инъекцией browser_fn)                             #
# --------------------------------------------------------------------------- #


def _record_publication(db: Session, post: Post, group_url: str, result: dict[str, Any]) -> None:
    """Записать PostPublication (status=published) — только с внешними данными, если есть."""
    existing = post_publication_repository.get_publication_by_post_and_platform(db, post.id, "vk")
    now = datetime.now(UTC)
    if existing is None:
        post_publication_repository.create_publication(
            db,
            PostPublicationCreate(
                post_id=post.id,
                project_id=post.project_id,
                platform="vk",
                target_id=group_url,
                status="published",
                external_post_id=result.get("external_post_id"),
                external_url=result.get("external_url"),
                published_at=now,
                payload={"via": "browser_fallback"},
            ),
        )
    else:
        post_publication_repository.update_publication(
            db,
            existing,
            PostPublicationUpdate(
                status="published",
                external_post_id=result.get("external_post_id"),
                external_url=result.get("external_url"),
                published_at=now,
            ),
        )


def _print_next(post_id: int, dry_run: bool) -> None:
    print("\nСледующие шаги:")
    if dry_run:
        print("  Проверьте пост в открытом браузере вручную. Публикация НЕ нажата.")
        print(
            "  Реальная публикация (после проверки): "
            f"make vk-browser-publish-live post_id={post_id}"
        )
    else:
        print("  Публикация нажата (если кнопка найдена). Проверьте пост в группе VK.")


def run(
    db: Session,
    downloader: ma.SupportsPublicMediaDownload | None,
    processor: ma.SupportsImageConversion | None,
    settings: Any,
    args: argparse.Namespace,
    *,
    browser_fn: Any = browser_publish,
) -> dict[str, Any] | None:
    """Ядро: подготовить пост+картинки и (через browser_fn) подготовить/опубликовать."""
    dry_run = _parse_bool(args.dry_run)
    confirm_live = _parse_bool(args.confirm_live)
    headless = _parse_bool(args.headless)

    post = post_repository.get_post_by_id(db, args.post_id)
    if post is None:
        print(f"Ошибка: пост #{args.post_id} не найден.")
        return None

    text = select_vk_text(post)
    images = extract_image_media_files(post.generation_notes or {}, args.max_images)
    if not images:
        print(
            "Ошибка: у поста нет изображений (generation_notes.media_files) — публиковать нечего."
        )
        return {"created": False, "reason": "no_images", "post_id": post.id, "published": False}

    if not dry_run and not confirm_live:
        print("Для реальной публикации нужен --confirm-live true.")
        return {
            "created": False,
            "reason": "need_confirm_live",
            "post_id": post.id,
            "published": False,
        }

    group_url = (args.group_url or "").strip() or build_group_url_from_group_id(
        getattr(settings, "vk_default_group_id", None)
    )
    if not group_url:
        print("Ошибка: не задан --group-url и нет VK_DEFAULT_GROUP_ID.")
        return None

    out_dir = UPLOADS_ROOT / f"post_{post.id}"
    paths, warnings = prepare_images(images, downloader, processor, out_dir)
    for warning in warnings:
        print(f"  ! {warning}")
    if not paths:
        print("Ошибка: не удалось подготовить ни одного изображения.")
        return {
            "created": False,
            "reason": "no_prepared_images",
            "post_id": post.id,
            "published": False,
        }

    print(
        f"Пост #{post.id}: текст из {text_source(post)} ({len(text)} символов), "
        f"изображений {len(paths)} → {out_dir}"
    )
    print(f"Группа VK: {group_url}")
    print(f"Режим: {'dry-run (публикация не нажимается)' if dry_run else 'LIVE (confirm-live)'}")

    try:
        result = browser_fn(
            group_url=group_url,
            text=text,
            image_paths=paths,
            dry_run=dry_run,
            confirm_live=confirm_live,
            headless=headless,
            profile_dir=Path(args.browser_profile_dir),
            post_id=post.id,
            out_dir=out_dir,
        )
    except PlaywrightNotInstalledError as exc:
        print(f"Ошибка: {exc}")
        return {"created": False, "reason": "no_playwright", "post_id": post.id, "published": False}

    published = bool(result and result.get("published"))
    recorded = False
    if not dry_run and confirm_live and published:
        _record_publication(db, post, group_url, result or {})
        recorded = True
    _print_next(post.id, dry_run)
    return {
        "created": recorded,
        "reason": None,
        "post_id": post.id,
        "published": published,
        "images": len(paths),
        "dry_run": dry_run,
    }


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов VK browser publisher."""
    parser = argparse.ArgumentParser(description="VK browser publisher fallback (dev/local)")
    parser.add_argument("--post-id", type=int, required=True)
    parser.add_argument("--group-url", default=None)
    parser.add_argument("--browser-profile-dir", default=DEFAULT_PROFILE_DIR)
    parser.add_argument("--dry-run", default="true")
    parser.add_argument("--max-images", type=int, default=5)
    parser.add_argument("--headless", default="false")
    parser.add_argument("--confirm-live", default="false")
    return parser


def main() -> None:
    """Точка входа CLI (реальный браузер запускается лениво только при вызове)."""
    args = build_parser().parse_args()
    settings = get_settings()
    downloader = get_media_download_service()
    processor = get_image_enhancement_processor()
    factory = get_sessionmaker()
    with factory() as db:
        run(db, downloader, processor, settings, args)


if __name__ == "__main__":
    main()
