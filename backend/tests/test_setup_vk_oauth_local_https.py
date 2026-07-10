"""Тесты мастера VK OAuth для локального HTTPS (offline; секрет не печатается)."""

from pathlib import Path

import pytest

from app.scripts import setup_vk_oauth_local_https as vkl

SECRET = "vk-app-secret-DO-NOT-LEAK-999"


def _read(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, value = stripped.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def test_apply_setup_writes_local_https_redirect(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("EXISTING=keep\nVK_ACCESS_TOKEN=do-not-touch\n", encoding="utf-8")

    summary = vkl.apply_setup(env, SECRET)

    values = _read(env)
    assert values["VK_APP_ID"] == "54671660"
    assert (
        values["VK_OAUTH_REDIRECT_URI"] == "https://localhost:8443/integrations/vk/oauth/callback"
    )
    assert values["VK_APP_SECRET"] == SECRET
    assert values["VK_DEFAULT_GROUP_ID"] == "240102732"
    assert values["VK_LIVE_PUBLISHING_ENABLED"] == "false"
    # VK_ACCESS_TOKEN не тронут; прочие строки сохранены.
    assert values["VK_ACCESS_TOKEN"] == "do-not-touch"
    assert values["EXISTING"] == "keep"
    assert summary["VK_APP_SECRET"] == "present"


def test_apply_setup_keeps_existing_group_id(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("VK_DEFAULT_GROUP_ID=11112222\n", encoding="utf-8")
    vkl.apply_setup(env, SECRET)
    assert _read(env)["VK_DEFAULT_GROUP_ID"] == "11112222"  # не перезаписан


def test_never_enables_live(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("VK_LIVE_PUBLISHING_ENABLED=true\n", encoding="utf-8")
    vkl.apply_setup(env, SECRET)
    assert _read(env)["VK_LIVE_PUBLISHING_ENABLED"] == "false"


def test_report_has_vkid_instructions_no_secret(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    summary = vkl.apply_setup(env, SECRET)
    report = vkl.build_report(summary)
    assert "https://localhost:8443/integrations/vk/oauth/callback" in report
    assert "https://127.0.0.1:8443/integrations/vk/oauth/callback" in report  # запасной
    assert "localhost" in report
    assert "VK_APP_SECRET=present" in report
    assert SECRET not in report  # секрет не попадает в отчёт


def test_main_uses_getpass_and_hides_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    report = tmp_path / "report.txt"
    monkeypatch.setattr(vkl.getpass, "getpass", lambda *_a, **_k: SECRET)
    monkeypatch.setattr(vkl, "REPORT_PATH", report)

    vkl.main(env_path=env)

    out = capsys.readouterr().out
    assert SECRET not in out  # секрет не печатается
    assert "VK_APP_SECRET=present" in out
    assert "VK_LIVE_PUBLISHING_ENABLED=false" in out
    assert _read(env)["VK_APP_SECRET"] == SECRET
    # Отчёт создан и не содержит секрета.
    assert report.exists() and SECRET not in report.read_text(encoding="utf-8")
