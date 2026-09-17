"""M2-IU1 双阶段 Safety Guard 的默认真实实现。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from uuid import uuid4

from runtime.contracts import (
    RuntimeContext,
    RuntimeInput,
    SafetyPhase,
    SafetyResult,
    SafetyRiskLevel,
    UnderstandingState,
)
from runtime.interfaces.safety import SafetyGuard
from runtime.safety.errors import (
    DuplicateSafetyRuleError,
    InvalidSafetyFindingError,
    SafetyGuardInvariantError,
    SafetyRuleConflictError,
    SafetyRuleExecutionError,
)
from runtime.safety.rules import SafetyFinding, SafetyRule

_RISK_ORDER = {
    SafetyRiskLevel.NONE: 0,
    SafetyRiskLevel.LOW: 1,
    SafetyRiskLevel.MEDIUM: 2,
    SafetyRiskLevel.HIGH: 3,
    SafetyRiskLevel.CRITICAL: 4,
}


class DefaultSafetyGuard(SafetyGuard):
    """执行可注入 Hard Safety Rules，并聚合为 Canonical ``SafetyResult``。

    Core 不硬编码任何医疗、陪护、金融或设备风险条件。具体风险条件来自
    ``SafetyRule``；本类只负责双阶段执行、最严格约束聚合、Early→Deep 单调继承、
    冲突检测和错误边界。
    """

    def __init__(
        self,
        rules: Iterable[SafetyRule] = (),
        *,
        clock: Callable[[], datetime] | None = None,
        result_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._rules: tuple[SafetyRule, ...] = tuple(rules)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._result_id_factory = result_id_factory or (lambda: str(uuid4()))
        seen: set[str] = set()
        for rule in self._rules:
            rule_id = rule.rule_id.strip()
            if not rule_id:
                raise InvalidSafetyFindingError("SafetyRule.rule_id must not be blank")
            if rule_id in seen:
                raise DuplicateSafetyRuleError(f"duplicate safety rule: {rule_id}")
            seen.add(rule_id)

    async def evaluate_early(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext | None = None,
    ) -> SafetyResult:
        """执行 M3 之前的确定性 Early Safety Rules。"""
        findings: list[SafetyFinding] = []
        for rule in self._rules:
            finding = await self._run_early_rule(rule, runtime_input, runtime_context)
            if finding is not None:
                findings.append(finding)
        return self._aggregate(
            phase=SafetyPhase.EARLY,
            runtime_input=runtime_input,
            findings=findings,
            inherited=None,
        )

    async def evaluate_deep(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        early_safety: SafetyResult,
    ) -> SafetyResult:
        """在 Understanding 之后重评估，且不得弱化 Early Safety 约束。"""
        self._validate_deep_inputs(runtime_input, understanding_state, early_safety)
        findings: list[SafetyFinding] = []
        for rule in self._rules:
            finding = await self._run_deep_rule(
                rule,
                runtime_input,
                runtime_context,
                understanding_state,
                early_safety,
            )
            if finding is not None:
                findings.append(finding)
        return self._aggregate(
            phase=SafetyPhase.DEEP,
            runtime_input=runtime_input,
            findings=findings,
            inherited=early_safety,
        )

    async def _run_early_rule(
        self,
        rule: SafetyRule,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext | None,
    ) -> SafetyFinding | None:
        try:
            finding = await rule.evaluate_early(runtime_input, runtime_context)
        except Exception as error:
            raise SafetyRuleExecutionError(
                rule.rule_id,
                SafetyPhase.EARLY,
                error,
            ) from error
        self._validate_finding(rule, finding)
        return finding

    async def _run_deep_rule(
        self,
        rule: SafetyRule,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
        understanding_state: UnderstandingState,
        early_safety: SafetyResult,
    ) -> SafetyFinding | None:
        try:
            finding = await rule.evaluate_deep(
                runtime_input,
                runtime_context,
                understanding_state,
                early_safety,
            )
        except Exception as error:
            raise SafetyRuleExecutionError(
                rule.rule_id,
                SafetyPhase.DEEP,
                error,
            ) from error
        self._validate_finding(rule, finding)
        return finding

    @staticmethod
    def _validate_finding(rule: SafetyRule, finding: SafetyFinding | None) -> None:
        if finding is None:
            return
        if not isinstance(finding, SafetyFinding):
            raise InvalidSafetyFindingError(
                f"rule {rule.rule_id} must return SafetyFinding or None"
            )
        if finding.rule_id != rule.rule_id:
            raise InvalidSafetyFindingError(
                f"finding.rule_id mismatch for rule {rule.rule_id}"
            )

    @staticmethod
    def _validate_deep_inputs(
        runtime_input: RuntimeInput,
        understanding_state: UnderstandingState,
        early_safety: SafetyResult,
    ) -> None:
        if early_safety.phase is not SafetyPhase.EARLY:
            raise SafetyGuardInvariantError("Deep Safety requires phase=EARLY baseline")
        if early_safety.request_id != runtime_input.request_id:
            raise SafetyGuardInvariantError(
                "Early Safety request_id must match RuntimeInput.request_id"
            )
        if understanding_state.metadata.request_id != runtime_input.request_id:
            raise SafetyGuardInvariantError(
                "UnderstandingState request_id must match RuntimeInput.request_id"
            )

    def _aggregate(
        self,
        *,
        phase: SafetyPhase,
        runtime_input: RuntimeInput,
        findings: list[SafetyFinding],
        inherited: SafetyResult | None,
    ) -> SafetyResult:
        risk_levels = [finding.risk_level for finding in findings]
        if inherited is not None:
            risk_levels.append(inherited.risk_level)
        risk_level = max(
            risk_levels, key=_RISK_ORDER.__getitem__, default=SafetyRiskLevel.NONE
        )

        reason_codes = self._dedupe(
            ([*inherited.reason_codes] if inherited is not None else [])
            + [code for finding in findings for code in finding.reason_codes]
        )
        if not reason_codes:
            reason_codes = ["NO_SAFETY_RULE_MATCH"]

        matched_rules = self._dedupe(
            ([*(inherited.matched_rules or [])] if inherited is not None else [])
            + [finding.rule_id for finding in findings]
        )
        risk_types = self._dedupe(
            ([*(inherited.risk_types or [])] if inherited is not None else [])
            + [risk_type for finding in findings for risk_type in finding.risk_types]
        )
        restricted_actions = self._dedupe(
            ([*(inherited.restricted_actions or [])] if inherited is not None else [])
            + [action for finding in findings for action in finding.restricted_actions]
        )

        force_workflows = self._dedupe(
            (
                [inherited.force_workflow]
                if inherited and inherited.force_workflow
                else []
            )
            + [
                finding.force_workflow
                for finding in findings
                if finding.force_workflow is not None
            ]
        )
        if len(force_workflows) > 1:
            raise SafetyRuleConflictError(
                "multiple safety rules require different forced workflows"
            )
        force_workflow = force_workflows[0] if force_workflows else None

        evidence: dict[str, object] = {}
        if inherited is not None and inherited.evidence is not None:
            evidence["early"] = inherited.evidence
        for finding in findings:
            if finding.evidence is not None:
                evidence[finding.rule_id] = finding.evidence

        confidence_values = [
            finding.confidence for finding in findings if finding.confidence is not None
        ]
        if inherited is not None and inherited.confidence is not None:
            confidence_values.append(inherited.confidence)

        inherited_allowed = (
            inherited.allowed_to_continue_normal_flow if inherited is not None else True
        )
        allowed_to_continue = inherited_allowed and all(
            finding.allowed_to_continue_normal_flow for finding in findings
        )

        return SafetyResult(
            safety_result_id=self._result_id_factory(),
            request_id=runtime_input.request_id,
            phase=phase,
            risk_detected=(inherited.risk_detected if inherited is not None else False)
            or any(
                finding.risk_level is not SafetyRiskLevel.NONE for finding in findings
            ),
            risk_level=risk_level,
            interrupt_current_task=(
                inherited.interrupt_current_task if inherited is not None else False
            )
            or any(finding.interrupt_current_task for finding in findings),
            allowed_to_continue_normal_flow=allowed_to_continue,
            safety_lock_required=(
                inherited.safety_lock_required if inherited is not None else False
            )
            or any(finding.safety_lock_required for finding in findings),
            reason_codes=reason_codes,
            created_at=self._clock(),
            risk_types=risk_types or None,
            matched_rules=matched_rules or None,
            evidence=evidence or None,
            confidence=max(confidence_values) if confidence_values else None,
            force_workflow=force_workflow,
            requires_immediate_action=(
                bool(inherited.requires_immediate_action)
                if inherited is not None
                else False
            )
            or any(finding.requires_immediate_action for finding in findings),
            restricted_actions=restricted_actions or None,
        )

    @staticmethod
    def _dedupe(values: Iterable[str]) -> list[str]:
        return list(dict.fromkeys(values))
