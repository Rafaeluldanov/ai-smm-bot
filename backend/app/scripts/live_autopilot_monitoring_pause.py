"""CLI стоп-крана автопилота (пауза/возобновление) — v0.6.1.

Запуск:
  make live-autopilot-monitoring-pause project_id=1 action=pause confirmation=PAUSE_AUTOPILOT
  make live-autopilot-monitoring-pause project_id=1 action=resume confirmation=RESUME_AUTOPILOT
  python -m app.scripts.live_autopilot_monitoring_pause --project-id 1 --action pause \
      --confirmation PAUSE_AUTOPILOT

Пауза мгновенно останавливает черновики и реальную публикацию (переключает состояние, которое
движок уже учитывает); глобальные live-флаги не трогает. Возобновление НЕ включает реальную
публикацию — её нужно включить отдельно через готовность. Требует подтверждения.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.live_autopilot_monitoring_service import (
    LiveAutopilotMonitoringError,
    get_live_autopilot_monitoring_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов стоп-крана."""
    parser = argparse.ArgumentParser(description="Стоп-кран автопилота (пауза/возобновление)")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--action", type=str, choices=("pause", "resume"), default="pause")
    parser.add_argument("--confirmation", type=str, default="")
    return parser


def main() -> None:
    """Точка входа CLI стоп-крана."""
    args = build_parser().parse_args()
    service = get_live_autopilot_monitoring_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            if args.action == "pause":
                result = service.pause_project_autopilot(
                    db, args.project_id, confirmation=args.confirmation
                )
            else:
                result = service.resume_project_autopilot(
                    db, args.project_id, confirmation=args.confirmation
                )
        except LiveAutopilotMonitoringError as exc:
            print(f"Отклонено: {exc}")
            return
    print(f"action:              {args.action}")
    print(f"ok:                  {result.get('ok')}")
    if args.action == "pause":
        print(f"autopilot_paused:    {result.get('autopilot_paused')}")
        print(f"project_live:        {result.get('project_live_enabled')}")
    else:
        print(f"autopilot_status:    {result.get('autopilot_status')}")
        print(f"live_re_enabled:     {result.get('live_re_enabled')}")
    print(result.get("note", ""))


if __name__ == "__main__":
    main()
