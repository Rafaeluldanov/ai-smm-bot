"""Тесты флага --use-default-publication-vector автономного прогона."""

from app.scripts.autonomous_run import build_parser, build_request, resolve_business_priorities
from app.services.seo_content_sources import get_default_publication_vector


def _args(argv: list[str]):  # noqa: ANN202
    return build_parser().parse_args(argv)


def test_default_vector_applied_when_no_manual_priority() -> None:
    args = _args(["--project-slug", "teeon", "--use-default-publication-vector"])
    priorities = resolve_business_priorities(args)
    assert priorities == get_default_publication_vector("teeon")
    assert priorities["футболки"] == 100


def test_manual_priority_overrides_preset() -> None:
    args = _args(
        [
            "--project-slug",
            "teeon",
            "--use-default-publication-vector",
            "--business-priority",
            "футболки=50",
        ]
    )
    priorities = resolve_business_priorities(args)
    assert priorities == {"футболки": 50}


def test_no_flag_no_priority_is_none() -> None:
    args = _args(["--project-slug", "teeon"])
    assert resolve_business_priorities(args) is None


def test_build_request_carries_default_vector() -> None:
    args = _args(["--project-slug", "teeon", "--use-default-publication-vector"])
    request = build_request(args)
    assert request.business_priorities == get_default_publication_vector("teeon")


def test_default_vector_unknown_project_is_none() -> None:
    args = _args(["--project-slug", "no-such-project", "--use-default-publication-vector"])
    assert resolve_business_priorities(args) is None
