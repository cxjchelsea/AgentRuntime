"""GA-19 evaluation matrix fail-closed scoring, provenance and coverage tests."""

from __future__ import annotations

import pytest

from tests.ga19_evaluate import LIVE, OFFLINE, build_report, classify


@pytest.mark.parametrize(
    ("returncode", "stdout", "minimum", "expected"),
    [
        (0, "2 passed in 1.2s", 2, True),
        (0, "1 passed in 1.2s", 2, False),
        (0, "2 passed, 1 skipped in 1.2s", 2, False),
        (1, "2 passed, 1 failed in 1.2s", 2, False),
        (0, "no tests ran in 0.2s", 1, False),
        (5, "1 skipped in 0.2s", 1, False),
    ],
)
def test_evaluation_never_infers_success_from_missing_or_skipped_tests(
    returncode: int, stdout: str, minimum: int, expected: bool
) -> None:
    assert classify(returncode, stdout, minimum)[0] is expected


def test_ga19_fixed_suite_distinguishes_live_and_offline_dimensions() -> None:
    assert len(OFFLINE) == 8
    assert len(LIVE) == 4
    assert len({case.scenario_id for case in (*OFFLINE, *LIVE)}) == 12
    assert {item.dimension for item in OFFLINE} >= {
        "grounding", "data_integrity", "tool_choice",
        "authorization", "planning", "replanning",
        "goal_evaluation", "failure_safety",
    }
    assert {item.dimension for item in LIVE} == {
        "grounding", "tool_choice", "planning", "replanning"
    }
    assert all(item.min_passed > 0 for item in (*OFFLINE, *LIVE))


def test_report_rejects_missing_scenarios_and_false_passes() -> None:
    with pytest.raises(ValueError, match="missing"):
        build_report("offline", [], sha="sha")
    with pytest.raises(ValueError, match="provenance"):
        build_report("offline", [], sha="")
    rows: list[dict[str, object]] = [
        {"scenario_id": case.scenario_id, "dimension": case.dimension,
         "status": "PASS"}
        for case in OFFLINE
    ]
    assert build_report("offline", rows, sha="exact-head")["acceptance"] == "PASS"
    rows[-1]["status"] = "FAIL"
    report = build_report("offline", rows, sha="exact-head")
    assert report["acceptance"] == "FAIL"
    assert report["scenario_passed"] == 7
