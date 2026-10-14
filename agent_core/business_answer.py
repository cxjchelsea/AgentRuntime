"""GA-14 bounded user-facing answers grounded in completed Agent observations.

This is an application-layer answer renderer, NOT M8 RuntimeResponse,
medical advice or an LLM's unsupervised free-text answer. It never claims
that replenishment or study tasks were physically executed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from agent_core.domain_execution_catalog import (
    DomainExecutionCatalog,
    WorkflowStepEvidence,
)
from agent_core.readonly_business_tools import _business_facts
from agent_core.readonly_domain_lookup import ReadOnlyDomainLookup
from agent_core.runner import RunBoundaryError, RunKind, RunOutcome


@dataclass(frozen=True, slots=True)
class BusinessAnswer:
    run_id: str
    domain_id: str
    question: str
    text: str
    source_digests: tuple[str, ...]


def _question_scope(question: str, operation: str) -> bool:
    normalized = question.lower()
    if operation == "inventory_replenishment":
        return any(
            term in normalized
            for term in ("库存", "补货", "采购", "stock", "reorder", "inventory")
        )
    if operation == "learning_progress":
        return any(
            term in normalized
            for term in ("学习", "进度", "任务", "完成", "study", "progress", "lesson")
        )
    return False


def render_business_answer(
    *,
    question: str,
    outcome: RunOutcome,
    lookup: ReadOnlyDomainLookup,
    operation: str,
) -> BusinessAnswer:
    """Render a grounded response only after all declared steps complete.

    Recompute domain metrics from the frozen snapshot; the Agent's observation
    MUST match the computed facts. Never interpret GOAL_SATISFIED as proof of a
    real-world replenishment, shipment or study activity.
    """
    if (
        type(question) is not str
        or not 1 <= len(question.strip()) <= 1000
        or type(outcome) is not RunOutcome
        or type(lookup) is not ReadOnlyDomainLookup
        or type(operation) is not str
        or not _question_scope(question, operation)
    ):
        raise RunBoundaryError("unsupported business answer request")
    catalog: DomainExecutionCatalog = lookup.catalog
    if (
        outcome.kind is not RunKind.FINISH
        or not outcome.run_id
        or outcome.executions != len(catalog.workflow.steps)
        or len(outcome.observations) != len(catalog.workflow.steps)
        or not catalog.completion_from_observations(
            run_id=outcome.run_id,
            observations=tuple(
                WorkflowStepEvidence(step.step_id, observed)
                for step, observed in zip(
                    catalog.workflow.steps, outcome.observations, strict=True
                )
            ),
        )
    ):
        raise RunBoundaryError("business answer requires completed correlated workflow")

    digests: list[str] = []
    for step, observed in zip(
        catalog.workflow.steps, outcome.observations, strict=True
    ):
        record = lookup.records[lookup.step_keys[step.step_id]]
        digest = hashlib.sha256(record.value.encode("utf-8")).hexdigest()
        if (
            record.domain_id != catalog.domain_id
            or record.binding_fingerprint != catalog.binding_fingerprint
            or record.sha256 != digest
        ):
            raise RunBoundaryError("business answer source mismatch")
        evidence = "RECORD_SHA256_" + digest
        expected = _business_facts(operation, record.value)
        if (
            evidence not in observed.facts
            or any(fact not in observed.facts for fact in expected)
            or step.completion_fact not in observed.facts
        ):
            raise RunBoundaryError("business answer observation does not match source")
        digests.append(digest)

    # The last step is the latest computed business status for this task.
    final_record = lookup.records[lookup.step_keys[catalog.workflow.steps[-1].step_id]]
    last_facts = _business_facts(operation, final_record.value)
    if operation == "inventory_replenishment":
        available = next(
            f.split("_")[-1] for f in last_facts if f.startswith("AVAILABLE_")
        )
        quantity = next(
            f.removeprefix("REPLENISH_QTY_")
            for f in last_facts
            if f.startswith("REPLENISH_QTY_")
        )
        if quantity == "0":
            text = f"当前可用库存为 {available} 件，按设定目标计算，暂不需要补货。本次只完成查询与计算，没有执行采购或库存修改。"
        else:
            text = f"当前可用库存为 {available} 件，按设定目标建议补货 {quantity} 件。本次只完成查询与计算，尚未执行采购或库存修改。"
    elif operation == "learning_progress":
        progress = next(
            f.removeprefix("PROGRESS_PERCENT_")
            for f in last_facts
            if f.startswith("PROGRESS_PERCENT_")
        )
        remaining = next(
            f.removeprefix("REMAINING_TASKS_")
            for f in last_facts
            if f.startswith("REMAINING_TASKS_")
        )
        text = (
            f"按当前记录，学习任务完成进度为 {progress}%，剩余 {remaining} 项。"
            "本次只完成进度查询与计算，没有替你完成任何学习任务。"
        )
    else:
        raise RunBoundaryError("unsupported business answer operation")
    return BusinessAnswer(
        run_id=outcome.run_id,
        domain_id=catalog.domain_id,
        question=question,
        text=text,
        source_digests=tuple(digests),
    )
