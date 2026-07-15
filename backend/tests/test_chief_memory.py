"""Тесты памяти решений AI Chief of Staff (v0.7.1).

Инварианты: решение сохраняется; одна активная запись на key; disable не удаляет;
контекст отражает решения (memory влияет на context); память НЕ меняет другие слои напрямую.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.ai_chief_of_staff_service import (
    AIChiefOfStaffError,
    AIChiefOfStaffService,
)

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIChiefOfStaffService:
    return AIChiefOfStaffService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> int:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id


def test_save_and_list_decision(db_session: Session) -> None:
    pid = _project(db_session, "chmem1")
    svc = _svc()
    d = svc.save_decision_memory(
        db_session,
        pid,
        decision_type="restriction",
        key="sales_style",
        value={"style": "soft"},
        reason="Не использовать агрессивные продажи",
    )
    assert d["decision_type"] == "restriction" and d["active"] is True
    decisions = svc.get_decisions(db_session, pid)
    assert len(decisions) == 1 and decisions[0]["key"] == "sales_style"


def test_decision_influences_context(db_session: Session) -> None:
    pid = _project(db_session, "chmem2")
    svc = _svc()
    svc.save_decision_memory(
        db_session, pid, decision_type="restriction", key="sales_style", value={"style": "soft"}
    )
    svc.save_decision_memory(
        db_session, pid, decision_type="strategy", key="content_focus", value={"focus": "cases"}
    )
    ctx = svc.build_decision_context(db_session, pid)
    assert ctx["by_key"]["sales_style"] == {"style": "soft"}
    assert any(r["key"] == "sales_style" for r in ctx["restrictions"])
    assert any(s["key"] == "content_focus" for s in ctx["strategies"])
    applied = svc.apply_decision_memory(db_session, pid)
    assert "content_strategy" in applied["applies_to"]
    assert applied["owner_context"]["by_key"]["content_focus"] == {"focus": "cases"}


def test_same_key_updates_single_active(db_session: Session) -> None:
    pid = _project(db_session, "chmem3")
    svc = _svc()
    svc.save_decision_memory(
        db_session, pid, decision_type="preference", key="main_channel", value={"channel": "vk"}
    )
    svc.save_decision_memory(
        db_session,
        pid,
        decision_type="preference",
        key="main_channel",
        value={"channel": "telegram"},
    )
    decisions = svc.get_decisions(db_session, pid)
    assert len(decisions) == 1
    assert decisions[0]["value"] == {"channel": "telegram"}


def test_disable_keeps_history(db_session: Session) -> None:
    pid = _project(db_session, "chmem4")
    svc = _svc()
    d = svc.save_decision_memory(
        db_session, pid, decision_type="approval", key="x", value={"ok": True}
    )
    svc.disable_decision(db_session, d["id"])
    assert svc.get_decisions(db_session, pid, active_only=True) == []
    # запись не удалена — видна среди всех
    assert len(svc.get_decisions(db_session, pid, active_only=False)) == 1


def test_unknown_decision_type_rejected(db_session: Session) -> None:
    pid = _project(db_session, "chmem5")
    with pytest.raises(AIChiefOfStaffError):
        _svc().save_decision_memory(db_session, pid, decision_type="bogus", key="k", value={})


def test_empty_key_rejected(db_session: Session) -> None:
    pid = _project(db_session, "chmem6")
    with pytest.raises(AIChiefOfStaffError):
        _svc().save_decision_memory(db_session, pid, decision_type="preference", key="  ", value={})


def test_decision_flows_into_briefing_context(db_session: Session) -> None:
    """Сохранённое решение попадает в briefing.business_state.owner_context (memory→context)."""
    pid = _project(db_session, "chmem7")
    svc = _svc()
    svc.save_decision_memory(
        db_session, pid, decision_type="restriction", key="sales_style", value={"style": "soft"}
    )
    out = svc.generate_daily_briefing(db_session, pid)
    oc = out["briefing"]["business_state"]["owner_context"]
    assert oc["by_key"]["sales_style"] == {"style": "soft"}
    assert any(r["key"] == "sales_style" for r in oc["restrictions"])
    assert "ограничени" in (out["briefing"]["summary"] or "").lower()


def test_one_active_after_disable_and_resave(db_session: Session) -> None:
    """disable + повторное сохранение того же key → ровно одна активная, история сохранена."""
    pid = _project(db_session, "chmem8")
    svc = _svc()
    d = svc.save_decision_memory(
        db_session, pid, decision_type="preference", key="main_channel", value={"c": "vk"}
    )
    svc.disable_decision(db_session, d["id"])
    svc.save_decision_memory(
        db_session, pid, decision_type="preference", key="main_channel", value={"c": "tg"}
    )
    active = [
        x
        for x in svc.get_decisions(db_session, pid, active_only=True)
        if x["key"] == "main_channel"
    ]
    assert len(active) == 1 and active[0]["value"] == {"c": "tg"}
    history = [
        x
        for x in svc.get_decisions(db_session, pid, active_only=False)
        if x["key"] == "main_channel"
    ]
    assert len(history) >= 2


def test_long_key_deduped_after_truncation(db_session: Session) -> None:
    """Ключ >80 символов не должен обходить «одна активная запись на key» (усечение согласовано)."""
    pid = _project(db_session, "chmem9")
    svc = _svc()
    long_key = "k" * 120
    svc.save_decision_memory(
        db_session, pid, decision_type="preference", key=long_key, value={"v": 1}
    )
    svc.save_decision_memory(
        db_session, pid, decision_type="preference", key=long_key, value={"v": 2}
    )
    active = svc.get_decisions(db_session, pid, active_only=True)
    assert len(active) == 1 and active[0]["value"] == {"v": 2}
    assert len(active[0]["key"]) == 80


def test_partial_unique_blocks_two_active_same_key(db_session: Session) -> None:
    """БД-инвариант: две активные записи на один (project_id, key) невозможны."""
    from sqlalchemy.exc import IntegrityError

    from app.models.business_decision_memory import BusinessDecisionMemory

    pid = _project(db_session, "chmem10")
    db_session.add(
        BusinessDecisionMemory(
            project_id=pid, decision_type="preference", key="k", value={}, active=True
        )
    )
    db_session.commit()
    db_session.add(
        BusinessDecisionMemory(
            project_id=pid, decision_type="preference", key="k", value={}, active=True
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    # active + inactive с тем же ключом — допустимо (нужно для disable→resave)
    db_session.add(
        BusinessDecisionMemory(
            project_id=pid, decision_type="preference", key="k", value={}, active=False
        )
    )
    db_session.commit()
