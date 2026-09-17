"""M2-IU2 Core Runtime State / Transition Engine。"""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from datetime import datetime

from runtime.contracts import RuntimeControlState, RuntimeInput
from runtime.contracts.context import RuntimeStateContext
from runtime.state_management.definitions import (
    RuntimeStateDefinition,
    RuntimeStateSnapshot,
    StateTransitionDecision,
)
from runtime.state_management.errors import (
    DuplicateStateDefinitionError,
    InvalidStateTransitionError,
    MissingStateDefinitionError,
    StateNotInitializedError,
    StateRevisionConflictError,
)
from runtime.state_management.store import RuntimeStateStore


class RuntimeStateEngine:
    """只管理 Core RuntimeControlState 的确定性状态机。

    不负责 DomainState、Safety 风险判断、Priority、Preemption 或 Policy。
    具体允许迁移图必须由装配层显式注入，避免 Core 自行发明业务流程。
    """

    def __init__(
        self,
        *,
        store: RuntimeStateStore,
        definitions: Iterable[RuntimeStateDefinition],
    ) -> None:
        self._store = store
        self._definitions: dict[RuntimeControlState, RuntimeStateDefinition] = {}
        for definition in definitions:
            if definition.state in self._definitions:
                raise DuplicateStateDefinitionError(
                    f"duplicate RuntimeStateDefinition for {definition.state.value}"
                )
            self._definitions[definition.state] = definition
        if not self._definitions:
            raise MissingStateDefinitionError(
                "at least one state definition is required"
            )
        self._validate_definition_graph()

    @staticmethod
    def scope_key(runtime_input: RuntimeInput) -> tuple[str, str]:
        """Core Runtime 状态按 identity_scope + session_id 隔离。"""
        return (runtime_input.identity_scope, runtime_input.session_id)

    def definition(self, state: RuntimeControlState) -> RuntimeStateDefinition:
        try:
            return self._definitions[state]
        except KeyError as error:
            raise MissingStateDefinitionError(
                f"missing RuntimeStateDefinition for {state.value}"
            ) from error

    async def initialize(
        self,
        scope_key: Hashable,
        *,
        initial_state: RuntimeControlState,
        entered_at: datetime,
    ) -> RuntimeStateSnapshot:
        """显式初始化一个新的状态 scope；已存在则返回现有快照。"""
        current = await self._store.load(scope_key)
        if current is not None:
            return current
        definition = self.definition(initial_state)
        snapshot = RuntimeStateSnapshot(
            current_state=initial_state,
            previous_state=None,
            entered_at=entered_at,
            interruptible=definition.interruptible,
            revision=0,
        )
        await self._store.compare_and_set(
            scope_key,
            expected_revision=None,
            snapshot=snapshot,
        )
        return snapshot

    async def load(self, scope_key: Hashable) -> RuntimeStateSnapshot:
        """读取已存在快照；不存在时不猜测默认状态。"""
        snapshot = await self._store.load(scope_key)
        if snapshot is None:
            raise StateNotInitializedError("runtime state snapshot is not initialized")
        return snapshot

    def evaluate_transition(
        self,
        snapshot: RuntimeStateSnapshot,
        target_state: RuntimeControlState,
    ) -> StateTransitionDecision:
        """确定性判断迁移是否合法，不产生副作用。"""
        current_definition = self.definition(snapshot.current_state)
        self.definition(target_state)

        if target_state is snapshot.current_state:
            return StateTransitionDecision(
                from_state=snapshot.current_state,
                to_state=target_state,
                allowed=True,
                no_op=True,
                reason_codes=("STATE_UNCHANGED",),
                expected_revision=snapshot.revision,
            )

        if target_state not in current_definition.allowed_transitions:
            return StateTransitionDecision(
                from_state=snapshot.current_state,
                to_state=target_state,
                allowed=False,
                no_op=False,
                reason_codes=("TRANSITION_NOT_ALLOWED",),
                expected_revision=snapshot.revision,
            )

        return StateTransitionDecision(
            from_state=snapshot.current_state,
            to_state=target_state,
            allowed=True,
            no_op=False,
            reason_codes=("TRANSITION_ALLOWED",),
            expected_revision=snapshot.revision,
        )

    async def transition(
        self,
        scope_key: Hashable,
        *,
        target_state: RuntimeControlState,
        entered_at: datetime,
        expected_revision: int | None = None,
    ) -> RuntimeStateSnapshot:
        """校验并用 CAS 提交一次 Core 状态迁移。"""
        snapshot = await self.load(scope_key)
        if expected_revision is not None and snapshot.revision != expected_revision:
            raise StateRevisionConflictError(
                "runtime state revision does not match caller expectation"
            )

        decision = self.evaluate_transition(snapshot, target_state)
        if not decision.allowed:
            raise InvalidStateTransitionError(
                f"transition {snapshot.current_state.value} -> {target_state.value} is not allowed"
            )
        if decision.no_op:
            return snapshot

        target_definition = self.definition(target_state)
        committed = RuntimeStateSnapshot(
            current_state=target_state,
            previous_state=snapshot.current_state,
            entered_at=entered_at,
            interruptible=target_definition.interruptible,
            revision=snapshot.revision + 1,
            active_task_id=snapshot.active_task_id,
            active_workflow_id=snapshot.active_workflow_id,
            interaction_mode=snapshot.interaction_mode,
            pending_question_id=snapshot.pending_question_id,
            runtime_flags=snapshot.runtime_flags,
        )
        await self._store.compare_and_set(
            scope_key,
            expected_revision=snapshot.revision,
            snapshot=committed,
        )
        return committed

    @staticmethod
    def to_context(snapshot: RuntimeStateSnapshot) -> RuntimeStateContext:
        """把内部状态快照投影为冻结的 RuntimeStateContext。"""
        return RuntimeStateContext(
            current_state=snapshot.current_state,
            previous_state=snapshot.previous_state,
            interruptible=snapshot.interruptible,
            entered_at=snapshot.entered_at,
            active_task_id=snapshot.active_task_id,
            active_workflow_id=snapshot.active_workflow_id,
            interaction_mode=snapshot.interaction_mode,
            pending_question_id=snapshot.pending_question_id,
            runtime_flags=list(snapshot.runtime_flags) or None,
        )

    def _validate_definition_graph(self) -> None:
        for definition in self._definitions.values():
            for target in definition.allowed_transitions:
                if target not in self._definitions:
                    raise MissingStateDefinitionError(
                        f"{definition.state.value} references undefined state {target.value}"
                    )
