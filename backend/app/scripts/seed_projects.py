"""Seed-скрипт: создаёт базовые проекты компании.

Идемпотентен: повторный запуск не создаёт дубликаты, а сообщает,
что проект уже существует. Запуск: ``make seed-projects``.
"""

from app.db.session import get_sessionmaker
from app.repositories import project_repository as repo
from app.schemas.project import ProjectCreate

SEED_PROJECTS: list[ProjectCreate] = [
    ProjectCreate(
        name="TEEON",
        slug="teeon",
        website_url="https://teeon.ru",
        description=(
            "TEEON — проект по пошиву корпоративной одежды, промо-одежды и мерча. "
            "Основные направления: футболки, худи, свитшоты, лонгсливы, поло, жилеты, "
            "сумки, промо-одежда, корпоративная одежда, шелкография, DTF, DTG, "
            "вышивка, жаккард, бирки и брендированные элементы."
        ),
    ),
    ProjectCreate(
        name="Фабрика сувениров",
        slug="fabric-souvenirs",
        website_url=None,
        description=(
            "Фабрика сувениров — проект по производству и брендированию сувенирной "
            "продукции. Основные направления: шелкография, УФ-печать, тампопечать, "
            "гравировка, кружки, ручки, текстиль, пакеты, корпоративные подарки, "
            "мерч и промо-продукция."
        ),
    ),
]


def seed_projects() -> None:
    """Создать недостающие seed-проекты и напечатать отчёт."""
    factory = get_sessionmaker()
    created = 0
    skipped = 0
    with factory() as db:
        for data in SEED_PROJECTS:
            existing = repo.get_project_by_slug(db, data.slug)
            if existing is not None:
                print(f"[=] Проект '{data.slug}' уже существует (id={existing.id})")
                skipped += 1
                continue
            project = repo.create_project(db, data)
            print(f"[+] Создан проект '{project.slug}' (id={project.id})")
            created += 1

    print(f"Готово. Создано: {created}, уже существовало: {skipped}.")


if __name__ == "__main__":
    seed_projects()
