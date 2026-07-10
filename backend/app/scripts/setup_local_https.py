"""Локальный self-signed HTTPS-сертификат для VK OAuth callback (без туннелей).

Генерирует сертификат ``tmp/certs/localhost-cert.pem`` + ключ
``tmp/certs/localhost-key.pem`` с SAN ``DNS:localhost`` и ``IP:127.0.0.1`` — чтобы
поднять локальный HTTPS на ``https://localhost:8443`` (VK ID требует HTTPS
redirect; ``http://127.0.0.1`` не принимается).

Использует ``openssl`` через subprocess; при его отсутствии — понятная ошибка.
Артефакты кладутся в ``tmp/`` (в ``.gitignore``); в репозиторий не попадают.

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.setup_local_https
"""

import shutil
import subprocess
from pathlib import Path

CERTS_DIR = Path("tmp/certs")
CERT_PATH = CERTS_DIR / "localhost-cert.pem"
KEY_PATH = CERTS_DIR / "localhost-key.pem"
# SAN обязателен: без него браузеры/clients отвергают сертификат для localhost.
_SUBJECT = "/CN=localhost"
_SAN = "subjectAltName=DNS:localhost,IP:127.0.0.1"


class OpensslNotFoundError(RuntimeError):
    """openssl не найден в PATH."""


def openssl_available() -> bool:
    """Есть ли ``openssl`` в PATH."""
    return shutil.which("openssl") is not None


def build_openssl_cmd(cert_path: Path, key_path: Path) -> list[str]:
    """Собрать команду openssl для self-signed сертификата с SAN (чистая, тестируемая)."""
    return [
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(key_path),
        "-out",
        str(cert_path),
        "-days",
        "825",
        "-subj",
        _SUBJECT,
        "-addext",
        _SAN,
    ]


def generate_cert(certs_dir: Path = CERTS_DIR) -> tuple[Path, Path]:
    """Создать папку и сгенерировать сертификат+ключ. Вернуть (cert, key)."""
    if not openssl_available():
        raise OpensslNotFoundError(
            "openssl не найден. Установите его (macOS: `brew install openssl`, "
            "Debian/Ubuntu: `apt-get install openssl`) и повторите."
        )
    certs_dir.mkdir(parents=True, exist_ok=True)
    cert_path = certs_dir / "localhost-cert.pem"
    key_path = certs_dir / "localhost-key.pem"
    subprocess.run(  # noqa: S603 — фиксированная dev-команда, без пользовательского ввода
        build_openssl_cmd(cert_path, key_path),
        check=True,
        capture_output=True,
        text=True,
        timeout=60.0,
    )
    return cert_path, key_path


def main() -> None:
    """Точка входа: сгенерировать локальный HTTPS-сертификат и показать next steps."""
    try:
        cert_path, key_path = generate_cert()
    except OpensslNotFoundError as exc:
        print(f"Ошибка: {exc}")
        return
    except subprocess.CalledProcessError as exc:
        # stderr openssl не содержит секретов, но на всякий случай не печатаем ключ.
        print(f"Ошибка генерации сертификата (openssl вернул {exc.returncode}).")
        return

    print("Локальный HTTPS-сертификат создан (self-signed, SAN: DNS:localhost, IP:127.0.0.1):")
    print(f"  cert: {cert_path}")
    print(f"  key:  {key_path}")
    print("\nДалее:")
    print(
        "  make vk-oauth-local-https   # записать VK OAuth в .env (redirect https://localhost:8443)"
    )
    print("  make run-https-local        # поднять UI на https://localhost:8443")
    print("  открыть https://localhost:8443/ui/projects (принять предупреждение браузера)")


if __name__ == "__main__":
    main()
