"""M3-IU3 structured deep-understanding model boundary.

The boundary exposes only selected Runtime context and accepts Understanding-only
structured output. It does not provide policy, planning, execution, response, or
state-mutation authority to a model.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from runtime.contracts import RuntimeContext, RuntimeInput
from runtime.understanding.deterministic import RuleParseResult
from runtime.understanding.errors import (
    ModelInputBoundaryError,
    ModelOutputBoundaryError,
)
from runtime.understanding.routing import UnderstandingRouteDecision

_ALLOWED_OUTPUT_FIELDS = frozenset(
    {
        "semantic",
        "intents",
        "goal",
        "emotion",
        "needs",
        "interaction",
        "references",
        "risk_signals",
        "uncertainty",
        "evidence",
    }
)

_FORBIDDEN_MODEL_KEYS = frozenset(
    {
        "action_plan",
        "approved_action_plan",
        "policy_decision",
        "final_response",
        "response",
        "runtime_response",
        "state_update",
        "memory_update",
        "memory_write",
        "tool_call",
        "tool_calls",
        "workflow_call",
        "execute",
        "execution_result",
    }
)


@dataclass(frozen=True, slots=True)
class ModelContextSelectionPolicy:
    """Controls which generic Runtime facts may be exposed to deep understanding."""

    max_recent_turns: int = 6
    max_memories: int = 4
    include_memory: bool = True
    include_task: bool = True

    def __post_init__(self) -> None:
        if self.max_recent_turns < 0:
            raise ModelInputBoundaryError("max_recent_turns must be non-negative")
        if self.max_memories < 0:
            raise ModelInputBoundaryError("max_memories must be non-negative")


@dataclass(frozen=True, slots=True)
class SelectedModelContext:
    """Explicit allow-list view of RuntimeContext for M3 deep understanding."""

    session_id: str
    current_runtime_state: str
    active_task_id: str | None
    active_workflow_id: str | None
    pending_question: str | None
    current_topic: str | None
    recent_turns: tuple[dict[str, Any], ...]
    relevant_memories: tuple[dict[str, Any], ...]


class DefaultModelContextSelector:
    """Project RuntimeContext into a minimal generic model-visible view."""

    def __init__(self, policy: ModelContextSelectionPolicy | None = None) -> None:
        self._policy = policy or ModelContextSelectionPolicy()

    def select(self, runtime_context: RuntimeContext) -> SelectedModelContext:
        conversation = runtime_context.conversation_context
        task = runtime_context.task_context
        memory = runtime_context.memory_context

        recent_turns: tuple[dict[str, Any], ...] = ()
        if (
            self._policy.max_recent_turns > 0
            and conversation is not None
            and conversation.recent_turns
        ):
            selected_turns = conversation.recent_turns[-self._policy.max_recent_turns :]
            recent_turns = tuple(
                deepcopy(selected_turn) for selected_turn in selected_turns
            )

        relevant_memories: tuple[dict[str, Any], ...] = ()
        if (
            self._policy.include_memory
            and self._policy.max_memories > 0
            and memory is not None
            and memory.retrieved_memories
        ):
            selected_memories = memory.retrieved_memories[: self._policy.max_memories]
            relevant_memories = tuple(
                deepcopy(selected_memory) for selected_memory in selected_memories
            )

        active_task_id = None
        if self._policy.include_task:
            active_task_id = runtime_context.runtime_state_context.active_task_id
            if active_task_id is None and task is not None:
                active_task_id = task.task_id

        active_workflow_id = (
            runtime_context.runtime_state_context.active_workflow_id
            if self._policy.include_task
            else None
        )

        pending_question = None
        if conversation is not None and conversation.pending_question:
            pending_question = conversation.pending_question

        current_topic = None
        if conversation is not None:
            current_topic = conversation.current_topic
        if current_topic is None:
            current_topic = runtime_context.session_context.current_topic

        return SelectedModelContext(
            session_id=runtime_context.session_context.session_id,
            current_runtime_state=runtime_context.runtime_state_context.current_state.value,
            active_task_id=active_task_id,
            active_workflow_id=active_workflow_id,
            pending_question=pending_question,
            current_topic=current_topic,
            recent_turns=recent_turns,
            relevant_memories=relevant_memories,
        )


@dataclass(frozen=True, slots=True)
class DeepUnderstandingRequest:
    """Only data a deep-understanding model is allowed to receive in IU3."""

    request_id: str
    text: str
    context: SelectedModelContext
    deterministic_result: RuleParseResult


class DeepUnderstandingRequestBuilder:
    """Build a model request while enforcing turn/identity continuity."""

    def __init__(self, context_selector: DefaultModelContextSelector) -> None:
        self._context_selector = context_selector

    def build(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
        route: UnderstandingRouteDecision,
    ) -> DeepUnderstandingRequest:
        if not route.requires_model:
            raise ModelInputBoundaryError(
                "FAST_PATH must not build a deep-understanding model request"
            )
        if runtime_input.text is None or not runtime_input.text.strip():
            raise ModelInputBoundaryError(
                "deep-understanding text input must not be blank"
            )
        if runtime_input.session_id != runtime_context.session_context.session_id:
            raise ModelInputBoundaryError("session_id mismatch at model boundary")
        if runtime_input.subject_id != runtime_context.identity_context.subject_id:
            raise ModelInputBoundaryError("subject_id mismatch at model boundary")
        if (
            runtime_input.identity_scope
            != runtime_context.identity_context.identity_scope
        ):
            raise ModelInputBoundaryError("identity_scope mismatch at model boundary")

        return DeepUnderstandingRequest(
            request_id=runtime_input.request_id,
            text=runtime_input.text,
            context=self._context_selector.select(runtime_context),
            deterministic_result=route.deterministic_result,
        )


@dataclass(frozen=True, slots=True)
class ModelUnderstandingResult:
    """Internal Understanding-only model result; not a Canonical Contract."""

    semantic: dict[str, Any] | None = None
    intents: tuple[dict[str, Any], ...] = ()
    goal: dict[str, Any] | None = None
    emotion: dict[str, Any] | None = None
    needs: tuple[dict[str, Any], ...] = ()
    interaction: dict[str, Any] | None = None
    references: tuple[dict[str, Any], ...] = ()
    risk_signals: tuple[dict[str, Any], ...] = ()
    uncertainty: dict[str, Any] | None = None
    evidence: tuple[dict[str, Any], ...] = ()


class ModelUnderstandingOutputValidator:
    """Reject any model output outside the frozen M3 understanding task."""

    def validate(self, payload: Mapping[str, Any]) -> ModelUnderstandingResult:
        unknown_fields = set(payload) - _ALLOWED_OUTPUT_FIELDS
        if unknown_fields:
            raise ModelOutputBoundaryError(
                "model output contains fields outside the Understanding boundary"
            )
        self._reject_forbidden_keys(payload)

        return ModelUnderstandingResult(
            semantic=_optional_dict(payload, "semantic"),
            intents=_tuple_of_dicts(payload, "intents"),
            goal=_optional_dict(payload, "goal"),
            emotion=_optional_dict(payload, "emotion"),
            needs=_tuple_of_dicts(payload, "needs"),
            interaction=_optional_dict(payload, "interaction"),
            references=_tuple_of_dicts(payload, "references"),
            risk_signals=_tuple_of_dicts(payload, "risk_signals"),
            uncertainty=_optional_dict(payload, "uncertainty"),
            evidence=_tuple_of_dicts(payload, "evidence"),
        )

    def _reject_forbidden_keys(self, value: object) -> None:
        if isinstance(value, Mapping):
            for key, nested_value in value.items():
                if isinstance(key, str) and key.casefold() in _FORBIDDEN_MODEL_KEYS:
                    raise ModelOutputBoundaryError(
                        "model output attempted to cross the Understanding boundary"
                    )
                self._reject_forbidden_keys(nested_value)
        elif isinstance(value, (list, tuple)):
            for nested_value in value:
                self._reject_forbidden_keys(nested_value)


class StructuredUnderstandingModel(Protocol):
    """Provider-neutral deep-understanding model adapter boundary."""

    async def infer(
        self,
        request: DeepUnderstandingRequest,
    ) -> Mapping[str, Any]:
        """Return structured Understanding-only data; no side effects are allowed."""
        ...


def _optional_dict(
    payload: Mapping[str, Any], field_name: str
) -> dict[str, Any] | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ModelOutputBoundaryError(f"{field_name} must be an object")
    return deepcopy(dict(value))


def _tuple_of_dicts(
    payload: Mapping[str, Any],
    field_name: str,
) -> tuple[dict[str, Any], ...]:
    value = payload.get(field_name)
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ModelOutputBoundaryError(f"{field_name} must be an array")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ModelOutputBoundaryError(f"{field_name} items must be objects")
        result.append(deepcopy(dict(item)))
    return tuple(result)
