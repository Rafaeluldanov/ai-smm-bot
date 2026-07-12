"""Тесты парсера упоминаний (@mentions) — v0.5.0. Offline; резолв только в пределах аккаунта."""

from sqlalchemy.orm import Session

from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services import mention_parser_service as mp


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(
        db, email=f"{slug}-owner@e.com", password_hash="x", full_name="Иван Петров"
    )
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    member = user_repository.create_user(db, email=f"{slug}-anna@e.com", password_hash="x")
    account_repository.create_membership(db, account.id, member.id, role="member")
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner, member


def test_extract_email_mention() -> None:
    out = mp.extract_mentions("привет @anna@example.com как дела")
    assert "anna@example.com" in out


def test_extract_username_mention() -> None:
    out = mp.extract_mentions("@ivan посмотри пожалуйста")
    assert "ivan" in out


def test_extract_user_id_mention() -> None:
    out = mp.extract_mentions("нужно согласовать @user_id:123")
    assert "user_id:123" in out


def test_extract_cyrillic_surrounding_text() -> None:
    # Упоминания корректно извлекаются из кириллического текста.
    text = "Привет, @anna@example.com! Посмотри задачу, спасибо большое."
    out = mp.extract_mentions(text)
    assert "anna@example.com" in out
    # И username между кириллицей.
    out2 = mp.extract_mentions("коллеги @ivan срочно нужно ревью медиатеки")
    assert "ivan" in out2


def test_extract_dedup_and_order() -> None:
    out = mp.extract_mentions("@ivan @ivan @user_id:1")
    assert out == ["ivan", "user_id:1"]


def test_resolve_email_same_account(db_session: Session) -> None:
    account, _project, _owner, member = _seed(db_session, "mp-email")
    user = mp.resolve_mention_to_user(db_session, account.id, member.email)
    assert user is not None and user.id == member.id


def test_resolve_user_id_same_account(db_session: Session) -> None:
    account, _project, owner, _member = _seed(db_session, "mp-uid")
    user = mp.resolve_mention_to_user(db_session, account.id, f"user_id:{owner.id}")
    assert user is not None and user.id == owner.id


def test_resolve_username_by_email_local(db_session: Session) -> None:
    account, _project, _owner, member = _seed(db_session, "mp-uname")
    # member email local part is "mp-uname-anna" → handle
    local = member.email.split("@", 1)[0]
    user = mp.resolve_mention_to_user(db_session, account.id, local)
    assert user is not None and user.id == member.id


def test_resolve_only_same_account(db_session: Session) -> None:
    account_a, _pa, _oa, _ma = _seed(db_session, "mp-iso-a")
    _account_b, _pb, owner_b, _mb = _seed(db_session, "mp-iso-b")
    # owner_b НЕ в account_a → не резолвится.
    user = mp.resolve_mention_to_user(db_session, account_a.id, owner_b.email)
    assert user is None


def test_unresolved_returns_none(db_session: Session) -> None:
    account, _project, _owner, _member = _seed(db_session, "mp-unres")
    assert mp.resolve_mention_to_user(db_session, account.id, "nobody@nowhere.com") is None
    assert mp.resolve_mention_to_user(db_session, account.id, "ghostuser") is None


def test_resolve_no_account_returns_none(db_session: Session) -> None:
    assert mp.resolve_mention_to_user(db_session, None, "anyone@example.com") is None
