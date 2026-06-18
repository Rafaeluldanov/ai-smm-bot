"""Сопоставление проектов и папок на Яндекс Диске.

Структура хранилища::

    /SMM_BOT
      /01_TEEON
        /01_Входящие_на_разбор
        /02_Одобренные_фото
        /03_Видео
        /04_Внешние_картинки_из_интернета
        /05_Использовано_в_постах
        /06_Нужно_переснять
      /02_Фабрика_сувениров
        ... (аналогично)

Корень (``/SMM_BOT``) берётся из настроек (``YANDEX_DISK_ROOT_PATH``).
"""

from app.config import get_settings

# slug проекта -> имя его папки внутри корня хранилища.
_PROJECT_FOLDERS: dict[str, str] = {
    "teeon": "01_TEEON",
    "fabric-souvenirs": "02_Фабрика_сувениров",
}

# Папки, которые сканируются (относительно корня проекта).
# Папка 05_Использовано_в_постах НЕ сканируется (медиа уже отработано).
_DEFAULT_SCAN_SUBFOLDERS: list[str] = [
    "01_Входящие_на_разбор",
    "02_Одобренные_фото",
    "03_Видео",
    "04_Внешние_картинки_из_интернета",
    "06_Нужно_переснять",
]


class UnknownProjectError(Exception):
    """Для проекта не задана папка на Яндекс Диске."""

    def __init__(self, project_slug: str) -> None:
        self.project_slug = project_slug
        super().__init__(f"Для проекта '{project_slug}' не задана папка на Яндекс Диске")


def _root(root_path: str | None) -> str:
    base = root_path if root_path is not None else get_settings().yandex_disk_root_path
    return base.rstrip("/")


def get_project_disk_root(project_slug: str, root_path: str | None = None) -> str:
    """Вернуть корневую папку проекта на Яндекс Диске.

    >>> get_project_disk_root("teeon", root_path="/SMM_BOT")
    '/SMM_BOT/01_TEEON'
    """
    folder = _PROJECT_FOLDERS.get(project_slug)
    if folder is None:
        raise UnknownProjectError(project_slug)
    return f"{_root(root_path)}/{folder}"


def get_default_scan_folders(project_slug: str, root_path: str | None = None) -> list[str]:
    """Вернуть полные пути папок проекта, которые нужно сканировать."""
    project_root = get_project_disk_root(project_slug, root_path)
    return [f"{project_root}/{sub}" for sub in _DEFAULT_SCAN_SUBFOLDERS]
