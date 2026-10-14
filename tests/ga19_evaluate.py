"""GA-19 fixed multi-scenario acceptance matrix, separate offline/live evidence.

Runs existing *actual* Agent/SQLite/Qwen tests (never mocks a successful result).
Requires all mandatory scenarios to pass and explicitly rejects skips/zero tests.
Outputs machine-readable + human-readable evidence tied to one checkout SHA.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

_PASS = re.compile(r"(?<!\d)(\d+) passed(?:,| in )")
_SKIP = re.compile(r"(?<!\d)(\d+) skipped(?:,| in )")
_MAX_LOG = 2400


@dataclass(frozen=True, slots=True)
class Scenario:
    scenario_id: str
    dimension: str
    target: str
    expression: str = ""
    min_passed: int = 1


OFFLINE = (
    Scenario("O01", "grounding", "tests/test_ga14_business_answer.py"),
    Scenario("O02", "data_integrity", "tests/test_ga13_sqlite_business_intake.py"),
    Scenario(
        "O03", "tool_choice", "tests/test_ga16_dynamic_business_task.py",
        "test_dynamic_model_tool_choice_and_replanning and False", 3,
    ),
    Scenario(
        "O04", "authorization", "tests/test_ga16_dynamic_business_task.py",
        "test_dynamic_task_rejects_foreign_and_replayed_steps",
    ),
    Scenario(
        "O05", "planning", "tests/test_ga17_goal_driven_plan.py",
        "test_goal_model_plan_rejects_unsafe_proposals", 8,
    ),
    Scenario(
        "O06", "replanning", "tests/test_ga17_goal_driven_plan.py",
        "test_goal_replanning_preserves_executed_evidence",
    ),
    Scenario(
        "O07", "goal_evaluation", "tests/test_ga18_adaptive_goal.py",
        "test_adaptive_replan_from_business_observation_to_verified_goal and False",
    ),
    Scenario(
        "O08", "failure_safety", "tests/test_ga18_adaptive_goal.py",
        "test_replan_requires_trigger_preserves_evidence_and_has_budget",
    ),
)
LIVE = (
    Scenario(
        "L01", "grounding", "tests/test_ga15_live_business_agent.py",
        "test_real_model_drives_business_actions_and_grounded_answer", 2,
    ),
    Scenario(
        "L02", "tool_choice", "tests/test_ga16_dynamic_business_task.py",
        "test_dynamic_model_tool_choice_and_replanning and True",
    ),
    Scenario(
        "L03", "planning", "tests/test_ga17_goal_driven_plan.py",
        "test_goal_plan_to_m4_dynamic_sqlite_agent_e2e and True",
    ),
    Scenario(
        "L04", "replanning", "tests/test_ga18_adaptive_goal.py",
        "test_adaptive_replan_from_business_observation_to_verified_goal and True",
    ),
)


def classify(returncode: int, output: str, minimum: int) -> tuple[bool, int, int]:
    """No unobserved, skipped or zero-test success can count as a PASS."""
    passed = sum(int(value) for value in _PASS.findall(output))
    skipped = sum(int(value) for value in _SKIP.findall(output))
    return returncode == 0 and passed >= minimum and skipped == 0, passed, skipped


def build_report(tier: str, results: list[dict[str, object]], *, sha: str) -> dict[str, object]:
    if tier not in ("offline", "live") or not sha:
        raise ValueError("invalid evaluation provenance")
    required = OFFLINE if tier == "offline" else LIVE
    names = [str(row.get("scenario_id")) for row in results]
    if names != [scenario.scenario_id for scenario in required]:
        raise ValueError("missing, reordered or unexpected evaluation scenario")
    by_dimension: dict[str, dict[str, int]] = {}
    for entry in results:
        dimension = str(entry["dimension"])
        bucket = by_dimension.setdefault(dimension, {"passed": 0, "total": 0})
        bucket["total"] += 1
        bucket["passed"] += int(entry["status"] == "PASS")
    all_pass = all(row["status"] == "PASS" for row in results)
    return {
        "schema_version": "ga19-evaluation-v1",
        "tier": tier,
        "checkout_sha": sha,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "model": os.environ.get("GA01C_LLM_MODEL", "") if tier == "live" else None,
        "scenario_count": len(results),
        "scenario_passed": sum(row["status"] == "PASS" for row in results),
        "acceptance": "PASS" if all_pass else "FAIL",
        "dimensions": by_dimension,
        "scenarios": results,
        "limitations": (
            "Test-backed constrained sandbox evidence, not independent human "
            "grading, unrestricted agent autonomy or production side-effect safety."
        ),
    }


def evaluate(tier: str, output_dir: Path) -> int:
    scenarios = OFFLINE if tier == "offline" else LIVE
    if tier == "live" and any(
        os.environ.get(key) != "1"
        for key in ("GA15_LIVE_OPT_IN", "GA16_LIVE_OPT_IN",
                    "GA17_LIVE_OPT_IN", "GA18_LIVE_OPT_IN")
    ):
        raise ValueError("all four real-provider opt-ins are required")
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    for case in scenarios:
        command = [sys.executable, "-m", "pytest", case.target, "-q", "-rs"]
        if case.expression:
            command.extend(["-k", case.expression])
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=180,
                check=False,
            )
            output = completed.stdout + "\n" + completed.stderr
            valid, passed, skipped = classify(
                completed.returncode, output, case.min_passed
            )
            code = completed.returncode
        except subprocess.TimeoutExpired as error:
            output = f"pytest timed out: {error}"
            valid, passed, skipped, code = False, 0, 0, -1
        status = "PASS" if valid else "FAIL"
        results.append({
            "scenario_id": case.scenario_id,
            "dimension": case.dimension,
            "status": status,
            "test_target": case.target,
            "selector": case.expression,
            "minimum_passed": case.min_passed,
            "tests_passed": passed,
            "tests_skipped": skipped,
            "returncode": code,
            "log_tail": output[-_MAX_LOG:],
        })
        print(f"GA19_SCENARIO={case.scenario_id} DIMENSION={case.dimension} "
              f"STATUS={status} PASSED={passed} SKIPPED={skipped}", flush=True)
    sha = os.environ.get("GITHUB_SHA") or "local-unattested"
    report = build_report(tier, results, sha=sha)
    (output_dir / f"ga19-{tier}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    rows = [
        f"# GA-19 {tier.title()} Multi-Scenario Evaluation",
        "",
        f"- Checkout: \`{sha}\`",
        f"- Acceptance: **{report['acceptance']}**",
        f"- Scenarios: {report['scenario_passed']}/{report['scenario_count']}",
        "",
        "| ID | Dimension | Outcome | Tests passed | Skipped |",
        "|---|---|---|---:|---:|",
    ]
    for item in results:
        rows.append(
            f"| {item['scenario_id']} | {item['dimension']} | "
            f"{item['status']} | {item['tests_passed']} | "
            f"{item['tests_skipped']} |"
        )
    rows.extend(["", str(report["limitations"])])
    (output_dir / f"ga19-{tier}.md").write_text(
        "\n".join(rows) + "\n", encoding="utf-8"
    )
    print(f"GA19_TIER={tier} ACCEPTANCE={report['acceptance']} "
          f"SHA={sha}", flush=True)
    return 0 if report["acceptance"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", choices=("offline", "live"), required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    return evaluate(args.tier, args.out_dir)


if __name__ == "__main__":
    raise SystemExit(main())
