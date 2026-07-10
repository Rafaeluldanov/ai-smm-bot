"""Локальный dev-мастер: поднять HTTPS-туннель (cloudflared) для VK OAuth callback.

Зачем: VK ID не принимает ``http://127.0.0.1`` как Trusted Redirect — нужен HTTPS.
Мастер поднимает приложение на ``127.0.0.1:8000``, запускает HTTPS-туннель и —
ВАЖНО — НЕ доверяет первому попавшемуся URL из лога, а реально проверяет, что
``<tunnel>/health`` отвечает 200 (QUIC/TCP/HTTP2 могут быть заблокированы сетью).
Только после проверки пишет в ``.env`` ``VK_OAUTH_REDIRECT_URI`` и печатает, что
вставить в VK ID.

Провайдеры (``--provider auto|cloudflared|ngrok``, по умолчанию ``auto``):
- сначала cloudflared quick tunnel (``*.trycloudflare.com``, http2 → default);
- если он не дал рабочий ``/health`` — fallback на ngrok (``*.ngrok-free.app``),
  читая ``NGROK_AUTHTOKEN`` из окружения (в контейнер — только по имени ``-e``,
  значение не попадает в ``ps``/логи). Нет токена — понятное сообщение, без Docker.

Безопасность:
- ``VK_APP_SECRET`` спрашивается через ``getpass`` и НИКОГДА не печатается/не логируется;
- ``VK_ACCESS_TOKEN`` / ``TELEGRAM_*`` не трогаются; live НЕ включается
  (``VK_LIVE_PUBLISHING_ENABLED=false``);
- отчёт ``tmp/vk_oauth_tunnel_wizard_report.txt`` пишется через ``redact_sensitive``
  (без секретов/токенов); ``.env`` не коммитится.

Это dev-инструмент: он запускает subprocess/Docker/сеть только в ``main()``.
Чистые функции (parse/build/update/redact/report) — юнит-тестируемы без сети.

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.dev_vk_oauth_tunnel_wizard
"""

import argparse
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from getpass import getpass
from pathlib import Path

# --- Константы окружения (dev) ---
VK_APP_ID_DEFAULT = "54671660"
VK_DEFAULT_GROUP_ID_DEFAULT = "240102732"
CALLBACK_PATH = "/integrations/vk/oauth/callback"
DEFAULT_ENV_PATH = Path(".env")
REPORT_PATH = Path("tmp/vk_oauth_tunnel_wizard_report.txt")

APP_HOST = "127.0.0.1"
APP_PORT = 8000
APP_HEALTH_URL = f"http://{APP_HOST}:{APP_PORT}/health"
UVICORN_MATCH = "uvicorn app.main:app"
COMPOSE_PROJECT = "ai_smm_bot"
CLOUDFLARED_IMAGE = "cloudflare/cloudflared:latest"
CLOUDFLARED_CONTAINER = "ai-smm-vk-cloudflared-tunnel"
DOCKER_INTERNAL_URL = f"http://host.docker.internal:{APP_PORT}"
DOCKER_INTERNAL_HOSTPORT = f"host.docker.internal:{APP_PORT}"

NGROK_IMAGE = "ngrok/ngrok:latest"
NGROK_CONTAINER = "ai-smm-vk-ngrok"

_TRYCLOUDFLARE_RE = re.compile(r"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com")
_NGROK_RE = re.compile(r"https://[a-z0-9][a-z0-9-]*\.ngrok(?:-free)?\.(?:app|io|dev)")
# Маркеры того, что cloudflared не смог поднять соединение (сеть блокирует порты).
_CLOUDFLARED_FAILURE_MARKERS = (
    "CONNECTIVITY PRE-CHECKS FAIL",
    "Environment has critical failures",
    "port 7844",
    "failed to dial",
    "failed to connect",
    "no more connections active",
)
# Маркеры того, что ngrok не смог поднять туннель (нет токена/сеть/лимит).
_NGROK_FAILURE_MARKERS = (
    "ERR_NGROK",
    "authentication failed",
    "failed to start tunnel",
    "The authtoken you specified",
    "account limited",
)
# Понятная причина при недоступном туннеле (используется и в тестах).
NETWORK_BLOCK_MESSAGE = (
    "Cloudflare tunnel URL was generated but not reachable. Network blocks Cloudflare "
    "tunnel ports. Use another network, VPN, mobile hotspot, or deploy backend to a "
    "public HTTPS host."
)
# Сообщение при отсутствии NGROK_AUTHTOKEN (fallback на ngrok).
NGROK_TOKEN_MISSING_MESSAGE = (
    "NGROK_AUTHTOKEN не задан. Получите токен в личном кабинете ngrok и запустите:\n"
    "  export NGROK_AUTHTOKEN=..."
)
FALLBACK_OPTIONS = (
    "1. попробовать другой интернет / мобильную точку;",
    "2. использовать ngrok, если пользователь даст NGROK_AUTHTOKEN;",
    "3. временно выложить backend на Render/Railway/VPS.",
)

# Ключи, значения которых нельзя показывать/писать в отчёт.
_SENSITIVE_KEY_RE = re.compile(
    r"(?im)^(\s*[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD)[A-Z0-9_]*\s*=)\s*(.+)$"
)
_INLINE_TOKEN_RE = re.compile(r"(?i)\b(access_token|client_secret|api_key|authtoken)=([^&\s\"']+)")


# --------------------------------------------------------------------------- #
# Чистые функции (юнит-тестируемы без сети/Docker)                            #
# --------------------------------------------------------------------------- #


def parse_tunnel_url(text: str) -> str | None:
    """Извлечь первый ``https://*.trycloudflare.com`` из текста логов (или None)."""
    match = _TRYCLOUDFLARE_RE.search(text or "")
    return match.group(0) if match else None


def parse_ngrok_url(text: str) -> str | None:
    """Извлечь первый ``https://*.ngrok(-free).app|io|dev`` из текста логов (или None)."""
    match = _NGROK_RE.search(text or "")
    return match.group(0) if match else None


def build_redirect_values(tunnel_url: str) -> dict[str, str]:
    """Собрать домен и redirect URL из URL туннеля."""
    base = tunnel_url.strip().rstrip("/")
    domain = base.split("://", 1)[-1]
    return {
        "tunnel_url": base,
        "domain": domain,
        "redirect_uri": f"{base}{CALLBACK_PATH}",
    }


def update_env_lines(lines: list[str], updates: dict[str, str]) -> list[str]:
    """Идемпотентно обновить/добавить ключи в строках ``.env`` (прочее — без изменений)."""
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            name = stripped.split("=", 1)[0].strip()
            if name in updates:
                out.append(f"{name}={updates[name]}")
                seen.add(name)
                continue
        out.append(line)
    for name, value in updates.items():
        if name not in seen:
            out.append(f"{name}={value}")
    return out


def read_env_value(lines: list[str], key: str) -> str | None:
    """Прочитать значение ключа из строк ``.env`` (или None)."""
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            name, value = stripped.split("=", 1)
            if name.strip() == key:
                return value.strip()
    return None


def redact_sensitive(text: str) -> str:
    """Замаскировать значения секретов/токенов (``*_SECRET/*_TOKEN/*_PASSWORD``, inline)."""
    redacted = _SENSITIVE_KEY_RE.sub(lambda m: f"{m.group(1)}***", text or "")
    redacted = _INLINE_TOKEN_RE.sub(lambda m: f"{m.group(1)}=***", redacted)
    return redacted


def build_env_updates(
    tunnel_url: str | None, secret: str | None, existing_group_id: str | None
) -> dict[str, str] | None:
    """Собрать VK OAuth-обновления ``.env`` ТОЛЬКО при проверенном туннеле.

    Возвращает None, если ``tunnel_url`` пуст (туннель не поднят/не проверен) —
    тогда ``VK_OAUTH_REDIRECT_URI`` НЕ записывается. Секрет добавляется только если
    передан. Live никогда не включается.
    """
    if not tunnel_url:
        return None
    values = build_redirect_values(tunnel_url)
    updates: dict[str, str] = {
        "VK_APP_ID": VK_APP_ID_DEFAULT,
        "VK_OAUTH_REDIRECT_URI": values["redirect_uri"],
        "VK_LIVE_PUBLISHING_ENABLED": "false",
    }
    if secret:
        updates["VK_APP_SECRET"] = secret
    if not existing_group_id:
        updates["VK_DEFAULT_GROUP_ID"] = VK_DEFAULT_GROUP_ID_DEFAULT
    return updates


def build_report(redirect_values: dict[str, str], *, secret_written: bool) -> str:
    """Собрать безопасный итог (без секретов) для печати и файла отчёта."""
    tunnel_url = redirect_values["tunnel_url"]
    sep = "=" * 40
    secret_line = (
        "VK_APP_SECRET записан (значение не показывается)"
        if secret_written
        else "VK_APP_SECRET не менялся"
    )
    return (
        "\n".join(
            [
                sep,
                "VK ID: что вставить",
                sep,
                "",
                "Базовый домен:",
                redirect_values["domain"],
                "",
                "Доверенный Redirect URL:",
                redirect_values["redirect_uri"],
                "",
                "Потом:",
                "1. VK ID → Приложение → Подключение авторизации",
                "2. Вставить базовый домен",
                "3. Вставить Redirect URL",
                "4. Сохранить",
                "5. Открыть:",
                f"   {tunnel_url}/ui/projects",
                "6. Проект TEEON → VK → Подключить VK",
                "7. После возврата нажать Проверить доступ",
                "",
                sep,
                "Безопасность",
                sep,
                "VK_LIVE_PUBLISHING_ENABLED=false",
                "publish-due не запускался",
                "секреты не печатались",
                secret_line,
            ]
        )
        + "\n"
    )


def build_failure_report(reason: str) -> str:
    """Собрать безопасный отчёт при неудаче туннеля (с fallback-вариантами)."""
    sep = "=" * 40
    return (
        "\n".join(
            [
                sep,
                "HTTPS-туннель не поднялся",
                sep,
                "",
                reason,
                "",
                NETWORK_BLOCK_MESSAGE,
                "",
                "Варианты:",
                *FALLBACK_OPTIONS,
                "",
                sep,
                "Безопасность",
                sep,
                "VK_OAUTH_REDIRECT_URI не записан (туннель не проверен)",
                "VK_LIVE_PUBLISHING_ENABLED=false",
                "publish-due не запускался",
                "секреты не печатались",
            ]
        )
        + "\n"
    )


def write_report(content: str, path: Path = REPORT_PATH) -> None:
    """Записать отчёт в файл (на всякий случай через ``redact_sensitive``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(redact_sensitive(content), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Импуртные шаги (subprocess/Docker/сеть) — только в main(), без тестов        #
# --------------------------------------------------------------------------- #


def _run(
    cmd: list[str], *, timeout: float = 60.0, check: bool = False
) -> subprocess.CompletedProcess[str]:
    """Запустить команду и вернуть результат (stdout+stderr перехвачены, редактированы)."""
    return subprocess.run(  # noqa: S603 — dev-инструмент, фиксированные команды
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


def http_status(url: str, timeout: float = 5.0) -> int | None:
    """GET url и вернуть HTTP-статус или None при ошибке (без исключений наружу)."""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "vk-oauth-wizard"})
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return int(response.status)
    except (urllib.error.URLError, OSError, ValueError):
        return None


def wait_for_health(url: str, timeout_seconds: float, interval: float = 2.0) -> bool:
    """Опрашивать ``url`` до 200 или до таймаута."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if http_status(url) == 200:
            return True
        time.sleep(interval)
    return False


def stop_old_processes() -> None:
    """Остановить старый uvicorn и старые cloudflared/ngrok-контейнеры (db/redis не трогать)."""
    _run(["pkill", "-f", UVICORN_MATCH], check=False)
    try:
        for image in (CLOUDFLARED_IMAGE, NGROK_IMAGE):
            found = _run(["docker", "ps", "-q", "--filter", f"ancestor={image}"])
            ids = [cid for cid in found.stdout.split() if cid]
            if ids:
                _run(["docker", "stop", *ids], check=False)
        _run(["docker", "rm", "-f", CLOUDFLARED_CONTAINER], check=False)
        _run(["docker", "rm", "-f", NGROK_CONTAINER], check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def start_db_redis() -> None:
    """Поднять db/redis через docker compose (без публикаций)."""
    _run(["docker", "compose", "-p", COMPOSE_PROJECT, "up", "-d", "db", "redis"], timeout=180.0)


def start_app() -> subprocess.Popen[str]:
    """Запустить uvicorn на 127.0.0.1:8000 (лог в PIPE)."""
    return subprocess.Popen(  # noqa: S603
        [
            ".venv/bin/uvicorn",
            "app.main:app",
            "--app-dir",
            "backend",
            "--host",
            APP_HOST,
            "--port",
            str(APP_PORT),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _run_tunnel_and_verify(
    cmd: list[str],
    container: str,
    parse_fn: Callable[[str], str | None],
    failure_markers: tuple[str, ...],
    timeout_seconds: float,
) -> tuple[str | None, str]:
    """Запустить туннель-контейнер и ПРОВЕРИТЬ ``<url>/health`` 200.

    Возвращает (verified_url | None, лог-причина, редактированная). URL не считается
    рабочим, пока ``/health`` реально не ответил 200 (не доверяем URL из лога).
    """
    _run(["docker", "rm", "-f", container], check=False)
    process = subprocess.Popen(  # noqa: S603
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    collected: list[str] = []
    tunnel_url: str | None = None
    deadline = time.monotonic() + timeout_seconds
    try:
        assert process.stdout is not None
        while time.monotonic() < deadline:
            line = process.stdout.readline()
            if not line:
                if process.poll() is not None:
                    break
                time.sleep(0.2)
                continue
            collected.append(line.rstrip())
            if tunnel_url is None:
                tunnel_url = parse_fn(line)
            if any(marker in line for marker in failure_markers):
                break
            if tunnel_url and http_status(f"{tunnel_url}/health") == 200:
                return tunnel_url, "ok"
        # Последняя попытка проверки, если URL уже найден.
        if tunnel_url and wait_for_health(
            f"{tunnel_url}/health", min(20.0, max(5.0, deadline - time.monotonic()))
        ):
            return tunnel_url, "ok"
    finally:
        _run(["docker", "rm", "-f", container], check=False)
        if process.poll() is None:
            process.terminate()
    return None, redact_sensitive("\n".join(collected[-20:]))


def try_cloudflared(protocol: str | None, timeout_seconds: float) -> tuple[str | None, str]:
    """Поднять cloudflared quick tunnel и проверить ``<url>/health`` 200."""
    cmd = [
        "docker",
        "run",
        "--rm",
        "--name",
        CLOUDFLARED_CONTAINER,
        CLOUDFLARED_IMAGE,
        "tunnel",
        "--no-autoupdate",
    ]
    if protocol:
        cmd += ["--protocol", protocol]
    cmd += ["--url", DOCKER_INTERNAL_URL]
    return _run_tunnel_and_verify(
        cmd, CLOUDFLARED_CONTAINER, parse_tunnel_url, _CLOUDFLARED_FAILURE_MARKERS, timeout_seconds
    )


def try_ngrok(timeout_seconds: float) -> tuple[str | None, str]:
    """Fallback: поднять ngrok HTTPS-туннель и проверить ``<url>/health`` 200.

    ``NGROK_AUTHTOKEN`` читается из окружения и передаётся в контейнер ТОЛЬКО по
    имени (``-e NGROK_AUTHTOKEN``) — значение не попадает в ``ps``/логи. Если токена
    нет — возвращает понятное сообщение (без запуска Docker).
    """
    token = os.environ.get("NGROK_AUTHTOKEN")
    if not token:
        return None, NGROK_TOKEN_MISSING_MESSAGE
    cmd = [
        "docker",
        "run",
        "--rm",
        "--name",
        NGROK_CONTAINER,
        "-e",
        "NGROK_AUTHTOKEN",  # значение наследуется из окружения, не пишется в командную строку
        NGROK_IMAGE,
        "http",
        DOCKER_INTERNAL_HOSTPORT,
        "--log",
        "stdout",
        "--log-format",
        "logfmt",
    ]
    return _run_tunnel_and_verify(
        cmd, NGROK_CONTAINER, parse_ngrok_url, _NGROK_FAILURE_MARKERS, timeout_seconds
    )


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов мастера туннеля."""
    parser = argparse.ArgumentParser(description="Dev-мастер HTTPS-туннеля для VK OAuth")
    parser.add_argument("--skip-secret", action="store_true", help="не спрашивать VK_APP_SECRET")
    parser.add_argument(
        "--no-write-env", action="store_true", help="не писать .env (только показать)"
    )
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--provider", default="auto", choices=["auto", "cloudflared", "ngrok"])
    return parser


def _fail(reason: str) -> None:
    """Печать безопасной неудачи + запись отчёта (без секретов)."""
    report = build_failure_report(reason)
    print(report)
    write_report(report)


def establish_tunnel(provider: str, timeout_seconds: float) -> tuple[str | None, str]:
    """Поднять проверенный HTTPS-туннель по стратегии provider.

    ``auto`` — сначала cloudflared (http2 → default), затем fallback на ngrok.
    Возвращает (verified_url | None, объединённая причина неудач). URL всегда уже
    проверен по ``/health`` внутри ``try_*``.
    """
    reasons: list[str] = []

    if provider in ("auto", "cloudflared"):
        print("→ Пробую HTTPS-туннель cloudflared (http2)…")
        _run(["docker", "pull", CLOUDFLARED_IMAGE], timeout=300.0, check=False)
        url, reason = try_cloudflared("http2", timeout_seconds)
        if not url:
            print("  http2 не прошёл, пробую протокол по умолчанию…")
            url, reason = try_cloudflared(None, timeout_seconds)
        if url:
            return url, "ok"
        reasons.append(f"cloudflared: {reason}")

    if provider in ("auto", "ngrok"):
        if not os.environ.get("NGROK_AUTHTOKEN"):
            print(NGROK_TOKEN_MISSING_MESSAGE)
            reasons.append(NGROK_TOKEN_MISSING_MESSAGE)
        else:
            print("→ Fallback: пробую HTTPS-туннель ngrok…")
            _run(["docker", "pull", NGROK_IMAGE], timeout=300.0, check=False)
            url, reason = try_ngrok(timeout_seconds)
            if url:
                return url, "ok"
            reasons.append(f"ngrok: {reason}")

    return None, "\n\n".join(reasons)


def main() -> None:
    """Точка входа мастера (subprocess/Docker/сеть). Пишет .env только при 200 на туннеле."""
    args = build_parser().parse_args()
    env_path = DEFAULT_ENV_PATH

    print("→ Останавливаю старые uvicorn/cloudflared…")
    stop_old_processes()
    print("→ Поднимаю db/redis (docker compose)…")
    try:
        start_db_redis()
    except (OSError, subprocess.SubprocessError) as exc:
        _fail(f"docker compose db/redis не поднялся: {redact_sensitive(str(exc))}")
        return

    print("→ Запускаю FastAPI на 127.0.0.1:8000…")
    app_proc = start_app()
    try:
        if not wait_for_health(APP_HEALTH_URL, timeout_seconds=40.0):
            tail = ""
            if app_proc.stdout is not None:
                try:
                    tail = redact_sensitive("".join(app_proc.stdout.readlines()[-20:]))
                except OSError:
                    tail = ""
            _fail(f"Приложение не ответило на {APP_HEALTH_URL}. Последние логи:\n{tail}")
            return
        print("  ✔ /health локально отвечает 200")

        tunnel_url, reason = establish_tunnel(args.provider, args.timeout_seconds)
        if not tunnel_url:
            _fail(f"HTTPS-туннель не поднялся (provider={args.provider}).\n{reason}")
            return
        print(f"  ✔ Туннель проверен по /health: {tunnel_url}")

        values = build_redirect_values(tunnel_url)
        secret = ""
        if not args.skip_secret:
            secret = getpass("Вставьте защищённый ключ VK приложения (не отображается): ").strip()

        secret_written = False
        if not args.no_write_env:
            lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
            existing_group = read_env_value(lines, "VK_DEFAULT_GROUP_ID")
            updates = build_env_updates(tunnel_url, secret or None, existing_group)
            if updates is not None:
                env_path.write_text(
                    "\n".join(update_env_lines(lines, updates)) + "\n", encoding="utf-8"
                )
                secret_written = bool(secret)

        report = build_report(values, secret_written=secret_written)
        print("\n" + report)
        write_report(report)
        print(f"Отчёт: {REPORT_PATH}")
    finally:
        if app_proc.poll() is None:
            app_proc.terminate()


if __name__ == "__main__":
    main()
