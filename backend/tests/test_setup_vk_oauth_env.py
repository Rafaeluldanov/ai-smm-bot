"""Тесты локального мастера VK OAuth .env (offline; секрет не печатается)."""

from pathlib import Path

import pytest

from app.scripts import setup_vk_oauth_env as vkenv

SECRET = "vk-super-secret-value-XYZ"


def _read(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, value = stripped.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def test_apply_setup_writes_vk_oauth_fields(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("EXISTING=keep\nVK_ACCESS_TOKEN=do-not-touch\n", encoding="utf-8")

    summary = vkenv.apply_setup(env, SECRET)

    values = _read(env)
    assert values["VK_APP_ID"] == "54671660"
    assert values["VK_OAUTH_REDIRECT_URI"] == "http://127.0.0.1:8000/integrations/vk/oauth/callback"
    assert values["VK_APP_SECRET"] == SECRET
    assert values["VK_DEFAULT_GROUP_ID"] == "240102732"
    assert values["VK_LIVE_PUBLISHING_ENABLED"] == "false"
    # Прочие строки сохранены; VK_ACCESS_TOKEN не тронут.
    assert values["EXISTING"] == "keep"
    assert values["VK_ACCESS_TOKEN"] == "do-not-touch"
    # Сводка не содержит секрета (только маркер present).
    assert summary["VK_APP_SECRET"] == "present"


def test_apply_setup_keeps_existing_group_id(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("VK_DEFAULT_GROUP_ID=99999999\n", encoding="utf-8")
    vkenv.apply_setup(env, SECRET)
    assert _read(env)["VK_DEFAULT_GROUP_ID"] == "99999999"  # не перезаписан


def test_main_uses_getpass_and_hides_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setattr(vkenv.getpass, "getpass", lambda *_a, **_k: SECRET)

    vkenv.main(env_path=env)

    out = capsys.readouterr().out
    # Секрет НЕ печатается; live НЕ включён.
    assert SECRET not in out
    assert "VK_APP_SECRET=present" in out
    assert "VK_LIVE_PUBLISHING_ENABLED=false" in out
    assert _read(env)["VK_APP_SECRET"] == SECRET


def test_never_enables_live(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("VK_LIVE_PUBLISHING_ENABLED=true\n", encoding="utf-8")
    vkenv.apply_setup(env, SECRET)
    # Мастер принудительно ставит live=false, даже если было true.
    assert _read(env)["VK_LIVE_PUBLISHING_ENABLED"] == "false"
