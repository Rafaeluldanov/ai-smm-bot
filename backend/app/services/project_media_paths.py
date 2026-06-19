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


# --- Публичная папка SMM (Этап: публичная ссылка) ---

# Какие папки публичной SMM разрешены проекту (имена + синонимы).
# КРИТИЧНОЕ ПРАВИЛО ДОСТУПА:
#   teeon — ТОЛЬКО «Тион»; нельзя брать из «Фабрика сувениров».
#   fabric-souvenirs — своя «Фабрика сувениров» И «Тион».
_PUBLIC_ALLOWED_FOLDERS: dict[str, list[str]] = {
    "teeon": ["Тион", "TEEON", "teeon", "Tion"],
    "fabric-souvenirs": [
        "Фабрика сувениров",
        "fabric-souvenirs",
        "Фабрика",
        "Тион",
        "TEEON",
        "teeon",
        "Tion",
    ],
}

# Канонические папки-источники проекта (для построения путей сканирования).
_PUBLIC_CANONICAL_FOLDERS: dict[str, list[str]] = {
    "teeon": ["Тион"],
    "fabric-souvenirs": ["Тион", "Фабрика сувениров"],
}

# ЗАПРЕЩЁННЫЕ проекту папки (чужие проектные папки). Если такое имя встречается
# в ЛЮБОМ сегменте пути файла — файл недоступен проекту. Защита от утечки, когда
# чужая проектная папка вложена в разрешённую (например, «Фабрика сувениров»
# внутри «Тион»): teeon НИКОГДА не берёт медиа из «Фабрика сувениров».
_PUBLIC_FORBIDDEN_FOLDERS: dict[str, list[str]] = {
    "teeon": ["Фабрика сувениров", "fabric-souvenirs", "Фабрика"],
    "fabric-souvenirs": [],
}


def _normalize_folder_name(value: str) -> str:
    """Нормализовать имя папки: берём последний сегмент пути, ё→е, нижний
    регистр, убираем пробелы/дефисы/подчёркивания/слэши."""
    last_segment = value.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    lowered = last_segment.lower().replace("ё", "е")
    for char in (" ", "-", "_"):
        lowered = lowered.replace(char, "")
    return lowered


def get_public_project_folder_names(project_slug: str) -> list[str]:
    """Вернуть список разрешённых имён папок публичной SMM для проекта."""
    return list(_PUBLIC_ALLOWED_FOLDERS.get(project_slug, []))


def get_public_scan_roots(project_slug: str, root_folder: str | None = None) -> list[str]:
    """Вернуть канонические пути папок-источников внутри публичного ресурса.

    >>> get_public_scan_roots("teeon", root_folder="SMM")
    ['/SMM/Тион']
    """
    base = root_folder if root_folder is not None else get_settings().yandex_disk_public_root_folder
    base = base.strip("/")
    prefix = f"/{base}" if base else ""
    return [f"{prefix}/{name}" for name in _PUBLIC_CANONICAL_FOLDERS.get(project_slug, [])]


def is_public_folder_allowed_for_project(project_slug: str, folder_name_or_path: str) -> bool:
    """Разрешена ли проекту папка верхнего уровня (по имени или пути).

    Сравнение по нормализованному имени последнего сегмента — устойчиво к
    регистру, ё/е, пробелам и дефисам. teeon НЕ имеет доступа к «Фабрика сувениров».
    """
    target = _normalize_folder_name(folder_name_or_path)
    allowed = {
        _normalize_folder_name(name) for name in _PUBLIC_ALLOWED_FOLDERS.get(project_slug, [])
    }
    return target in allowed


def is_public_path_allowed_for_project(project_slug: str, path: str) -> bool:
    """Допустим ли проекту ПОЛНЫЙ путь файла (проверка всех сегментов).

    Возвращает False, если любой сегмент пути нормализуется в запрещённую проекту
    папку. Это закрывает утечку, когда чужая проектная папка вложена в
    разрешённую (например, файл в «/SMM/Тион/Фабрика сувениров/...» для teeon).
    """
    forbidden = {
        _normalize_folder_name(name) for name in _PUBLIC_FORBIDDEN_FOLDERS.get(project_slug, [])
    }
    if not forbidden:
        return True
    segments = [segment for segment in path.replace("\\", "/").split("/") if segment]
    return not any(_normalize_folder_name(segment) in forbidden for segment in segments)
