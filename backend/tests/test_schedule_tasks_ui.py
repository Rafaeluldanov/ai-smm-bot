"""Тесты UI задач расписания (offline, TestClient).

Проверяют, что расписания показываются как отдельные задачи с днями/временем/тегом/
статусом/стоимостью/следующей датой, кнопки Изменить/Удалить/Пауза/Preview видны и
не выполняют разрушительных действий, publish-due нет.
"""

from fastapi.testclient import TestClient

SCHEDULE_PAGE = "/ui/projects/1/platforms/telegram/schedule"
PLATFORM_PAGE = "/ui/projects/1/platforms/telegram"


def test_schedule_task_card_template_present(client: TestClient) -> None:
    body = client.get(SCHEDULE_PAGE).text
    # Рендер задач как отдельных карточек.
    assert "Задачи расписания" in body
    assert "schedTaskCard" in body
    assert "sched-task" in body
    assert "renderSchedTasks(" in body
    # Поля карточки задачи.
    for field in (
        "Платформа",
        "Категория/тег",
        "Дни недели",
        "Время",
        "Период",
        "Режим",
        "Стоимость публикации",
        "Следующая публикация",
    ):
        assert field in body, field


def test_schedule_task_action_buttons_visible(client: TestClient) -> None:
    body = client.get(SCHEDULE_PAGE).text
    for label in ("Изменить", "Удалить", "Пауза/Возобновить", "Preview ближайших постов"):
        assert label in body, label
    # Обработчики есть, но они безопасные (без разрушительных вызовов API).
    for fn in ("editTask(", "deleteTask(", "pauseTask(", "previewTask("):
        assert fn in body, fn
    # Удаление подтверждается и не бьёт по боту.
    assert "confirm(" in body
    assert "разрушительные действия не выполняются" in body


def test_schedule_cost_and_next_run_visible(client: TestClient) -> None:
    body = client.get(SCHEDULE_PAGE).text
    assert "units" in body  # стоимость публикации в units
    assert "cost_per_post_units" in body
    assert "nextRun(" in body  # расчёт следующей публикации


def test_schedule_tasks_also_on_platform_workspace(client: TestClient) -> None:
    body = client.get(PLATFORM_PAGE).text
    # На странице платформы задачи расписания живут во вкладке «Расписание».
    assert "pane-schedule" in body
    assert "renderSchedTasks(" in body
    assert "schedTaskCard" in body


def test_schedule_ui_has_no_publish_due(client: TestClient) -> None:
    for path in (SCHEDULE_PAGE, PLATFORM_PAGE):
        body = client.get(path).text
        assert "publish-due" not in body
        assert "publish_due" not in body
