"""Тесты генератора локального HTTPS-сертификата (offline; без запуска openssl)."""

from pathlib import Path

import pytest

from app.scripts import setup_local_https as sl


def test_build_openssl_cmd_has_san_and_paths(tmp_path: Path) -> None:
    cert = tmp_path / "localhost-cert.pem"
    key = tmp_path / "localhost-key.pem"
    cmd = sl.build_openssl_cmd(cert, key)
    assert cmd[0] == "openssl"
    assert "-x509" in cmd and "-nodes" in cmd
    # SAN обязателен: DNS:localhost и IP:127.0.0.1.
    assert "subjectAltName=DNS:localhost,IP:127.0.0.1" in cmd
    assert str(cert) in cmd and str(key) in cmd


def test_generate_cert_creates_dir_and_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    certs_dir = tmp_path / "certs"
    calls: dict[str, object] = {}

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls["cmd"] = cmd
        # Эмулируем openssl: создаём файлы.
        Path(cmd[cmd.index("-out") + 1]).write_text("CERT", encoding="utf-8")
        Path(cmd[cmd.index("-keyout") + 1]).write_text("KEY", encoding="utf-8")

        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr(sl, "openssl_available", lambda: True)
    monkeypatch.setattr(sl.subprocess, "run", fake_run)

    cert_path, key_path = sl.generate_cert(certs_dir)
    assert certs_dir.exists()
    assert cert_path.exists() and key_path.exists()
    assert cert_path.name == "localhost-cert.pem" and key_path.name == "localhost-key.pem"
    assert "openssl" in calls["cmd"]  # type: ignore[operator]


def test_generate_cert_without_openssl_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sl, "openssl_available", lambda: False)
    with pytest.raises(sl.OpensslNotFoundError):
        sl.generate_cert(tmp_path / "certs")


def test_main_reports_no_openssl_without_crash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sl, "openssl_available", lambda: False)
    sl.main()
    out = capsys.readouterr().out
    assert "openssl не найден" in out
    # Секретов/ключей в выводе нет.
    assert "BEGIN" not in out
