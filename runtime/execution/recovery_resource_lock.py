"""M5-IU9 CA-03 durable ResourceLock recovery and fencing contracts.

This module upgrades the IU8 lock / operation-binding mechanisms with crash-surviving
records and recovery-time reclaim authority. It deliberately does not orchestrate the
whole execution recovery flow; CA-M5-IU9-04 owns RecoveryDisposition ordering.

Safety invariant:

    worker/process disappeared != external Tool stopped

A Tool resource lease may be reclaimed only from exact terminal operation evidence
or from provider fencing that proves the prior operation can no longer commit its
side effect. TTL, heartbeat expiry, PID loss, or recovery-epoch takeover alone never
authorize Tool lock reclaim.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol

from runtime.execution.control_application import InFlightOperationHandle
from runtime.execution.recovery import (
    ExecutionRecoveryClaim,
    InMemoryRecoveryClaimAuthority,
    RecoveryClaimAuthority,
    RecoveryEpochValidationStatus,
)
from runtime.execution.recovery_evidence import (
    DurableInFlightEvidenceStore,
    DurableInFlightOperationObservation,
    InFlightEvidenceState,
)
from runtime.execution.resource_lock import (
    ResourceLockAcquireDecision,
    ResourceLockAcquireRequest,
    ResourceLockAcquireStatus,
    ResourceLockAuthority,
    ResourceLockLease,
    ResourceLockReleaseDecision,
    ResourceLockReleaseStatus,
)
from runtime.execution.resource_lock_lifecycle import (
    OperationResourceLeaseBinding,
    OperationResourceLeaseRegistry,
)


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_claim_execution(
    claim: ExecutionRecoveryClaim,
    execution_id: str,
) -> None:
    if claim.execution_id != execution_id:
        raise ValueError("recovery claim execution_id mismatch")


class DurableResourceLockState(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


@dataclass(frozen=True, slots=True)
class DurableResourceLockRecord:
    lease: ResourceLockLease
    state: DurableResourceLockState
    revision: int
    updated_at: datetime
    writer_recovery_epoch: int
    released_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, DurableResourceLockState):
            raise TypeError("state must be DurableResourceLockState")
        if self.revision < 1:
            raise ValueError("revision must be >= 1")
        if self.writer_recovery_epoch < 1:
            raise ValueError("writer_recovery_epoch must be >= 1")
        _require_aware(self.updated_at, "updated_at")
        if self.state is DurableResourceLockState.ACTIVE:
            if self.released_at is not None:
                raise ValueError("ACTIVE durable lock cannot carry released_at")
        else:
            if self.released_at is None:
                raise ValueError("RELEASED durable lock requires released_at")
            _require_aware(self.released_at, "released_at")
            if self.released_at < self.lease.acquired_at:
                raise ValueError("released_at cannot precede acquired_at")


class DurableResourceLockReadStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class DurableResourceLockReadDecision:
    status: DurableResourceLockReadStatus
    reason_codes: tuple[str, ...]
    record: DurableResourceLockRecord | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, DurableResourceLockReadStatus):
            raise TypeError("status must be DurableResourceLockReadStatus")
        if not self.reason_codes or any(not item.strip() for item in self.reason_codes):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status in {
            DurableResourceLockReadStatus.ACTIVE,
            DurableResourceLockReadStatus.RELEASED,
        }:
            if self.record is None:
                raise ValueError("ACTIVE/RELEASED read requires record")
            expected = (
                DurableResourceLockState.ACTIVE
                if self.status is DurableResourceLockReadStatus.ACTIVE
                else DurableResourceLockState.RELEASED
            )
            if self.record.state is not expected:
                raise ValueError("durable lock read status/record mismatch")
        elif self.record is not None:
            raise ValueError("NONE/UNKNOWN durable lock read cannot carry record")


class DurableResourceLockStore(Protocol):
    async def acquire(
        self,
        request: ResourceLockAcquireRequest,
        *,
        required_claim: ExecutionRecoveryClaim,
    ) -> ResourceLockAcquireDecision:
        """Atomically fence recovery epoch and persist exact IU8 acquisition."""

    async def release(
        self,
        lease: ResourceLockLease,
        *,
        released_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> ResourceLockReleaseDecision:
        """Atomically fence recovery epoch and persist exact release tombstone."""

    async def read_by_acquisition(
        self,
        acquisition_id: str,
    ) -> DurableResourceLockReadDecision:
        """Read durable acquisition history without collapsing uncertainty."""

    async def active_for_owner(
        self,
        owner_id: str,
    ) -> tuple[DurableResourceLockRecord, ...]:
        """Return active leases for one exact IU8 owner identity."""


class DurableResourceLockAuthority(ResourceLockAuthority):
    """IU8 ResourceLockAuthority backed by an IU9 durable store.

    The recovery claim is captured by the adapter so existing IU8 coordinators can
    keep their frozen ResourceLockAuthority protocol unchanged.
    """

    def __init__(
        self,
        *,
        store: DurableResourceLockStore,
        recovery_claim: ExecutionRecoveryClaim,
    ) -> None:
        self._store = store
        self._claim = recovery_claim

    async def acquire(
        self,
        request: ResourceLockAcquireRequest,
    ) -> ResourceLockAcquireDecision:
        if request.owner.execution_id != self._claim.execution_id:
            return ResourceLockAcquireDecision(
                status=ResourceLockAcquireStatus.UNKNOWN,
                reason_codes=("LOCK_RECOVERY_CLAIM_EXECUTION_MISMATCH",),
            )
        return await self._store.acquire(
            request,
            required_claim=self._claim,
        )

    async def release(
        self,
        lease: ResourceLockLease,
        *,
        released_at: datetime,
    ) -> ResourceLockReleaseDecision:
        if lease.owner.execution_id != self._claim.execution_id:
            return ResourceLockReleaseDecision(
                status=ResourceLockReleaseStatus.UNKNOWN,
                reason_codes=("LOCK_RECOVERY_CLAIM_EXECUTION_MISMATCH",),
                lease=lease,
            )
        return await self._store.release(
            lease,
            released_at=released_at,
            required_claim=self._claim,
        )


class OperationRecoveryStatus(str, Enum):
    RUNNING_CONFIRMED = "RUNNING_CONFIRMED"
    COMPLETED_CONFIRMED = "COMPLETED_CONFIRMED"
    STOPPED_CONFIRMED = "STOPPED_CONFIRMED"
    NOT_FOUND_WITH_PROOF = "NOT_FOUND_WITH_PROOF"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class OperationRecoveryDecision:
    status: OperationRecoveryStatus
    reason_codes: tuple[str, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.status, OperationRecoveryStatus):
            raise TypeError("status must be OperationRecoveryStatus")
        if not self.reason_codes or any(not item.strip() for item in self.reason_codes):
            raise ValueError("reason_codes must contain non-blank values")
        _require_aware(self.observed_at, "observed_at")


class OperationRecoveryProbe(Protocol):
    async def probe(
        self,
        *,
        handle: InFlightOperationHandle,
    ) -> OperationRecoveryDecision:
        """Ask the exact external provider/adapter about one operation identity.

        NOT_FOUND_WITH_PROOF is strong only when the provider proves that the exact
        identity cannot still execute or later commit a side effect. Ordinary 404,
        lookup failure, or local task absence must return UNKNOWN.
        """


class ProviderFenceStatus(str, Enum):
    ESTABLISHED = "ESTABLISHED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ProviderFenceEvidence:
    operation_handle_id: str
    fencing_token: str
    established_at: datetime
    recovery_epoch: int

    def __post_init__(self) -> None:
        _require_non_blank(self.operation_handle_id, "operation_handle_id")
        _require_non_blank(self.fencing_token, "fencing_token")
        _require_aware(self.established_at, "established_at")
        if self.recovery_epoch < 1:
            raise ValueError("recovery_epoch must be >= 1")


@dataclass(frozen=True, slots=True)
class ProviderFenceDecision:
    status: ProviderFenceStatus
    reason_codes: tuple[str, ...]
    evidence: ProviderFenceEvidence | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ProviderFenceStatus):
            raise TypeError("status must be ProviderFenceStatus")
        if not self.reason_codes or any(not item.strip() for item in self.reason_codes):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status is ProviderFenceStatus.ESTABLISHED:
            if self.evidence is None:
                raise ValueError("ESTABLISHED provider fence requires evidence")
        elif self.evidence is not None:
            raise ValueError("UNSUPPORTED/UNKNOWN provider fence cannot carry evidence")


class ProviderFencingAuthority(Protocol):
    async def establish_fence(
        self,
        *,
        binding: OperationResourceLeaseBinding,
        recovery_claim: ExecutionRecoveryClaim,
        requested_at: datetime,
    ) -> ProviderFenceDecision:
        """Fence the exact provider operation so older work cannot commit effects."""


class DurableOperationResourceBindingState(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


@dataclass(frozen=True, slots=True)
class DurableOperationResourceBindingRecord:
    binding: OperationResourceLeaseBinding
    state: DurableOperationResourceBindingState
    revision: int
    updated_at: datetime
    writer_recovery_epoch: int
    released_at: datetime | None = None
    release_basis: str | None = None
    provider_fence: ProviderFenceEvidence | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, DurableOperationResourceBindingState):
            raise TypeError("state must be DurableOperationResourceBindingState")
        if self.revision < 1:
            raise ValueError("revision must be >= 1")
        if self.writer_recovery_epoch < 1:
            raise ValueError("writer_recovery_epoch must be >= 1")
        _require_aware(self.updated_at, "updated_at")
        if self.state is DurableOperationResourceBindingState.ACTIVE:
            if (
                self.released_at is not None
                or self.release_basis is not None
                or self.provider_fence is not None
            ):
                raise ValueError(
                    "ACTIVE operation-resource binding cannot carry release evidence"
                )
        else:
            if self.released_at is None or self.release_basis is None:
                raise ValueError(
                    "RELEASED operation-resource binding requires release evidence"
                )
            _require_aware(self.released_at, "released_at")
            _require_non_blank(self.release_basis, "release_basis")
            if self.released_at < self.binding.handle.started_at:
                raise ValueError("binding released_at cannot precede operation start")
        if self.provider_fence is not None:
            if (
                self.provider_fence.operation_handle_id
                != self.binding.handle.operation_handle_id
            ):
                raise ValueError("provider fence operation identity mismatch")


class DurableOperationResourceBindingReadStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class DurableOperationResourceBindingReadDecision:
    status: DurableOperationResourceBindingReadStatus
    reason_codes: tuple[str, ...]
    record: DurableOperationResourceBindingRecord | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, DurableOperationResourceBindingReadStatus):
            raise TypeError("status must be DurableOperationResourceBindingReadStatus")
        if not self.reason_codes or any(not item.strip() for item in self.reason_codes):
            raise ValueError("reason_codes must contain non-blank values")
        if self.status in {
            DurableOperationResourceBindingReadStatus.ACTIVE,
            DurableOperationResourceBindingReadStatus.RELEASED,
        }:
            if self.record is None:
                raise ValueError("ACTIVE/RELEASED binding read requires record")
            expected = (
                DurableOperationResourceBindingState.ACTIVE
                if self.status is DurableOperationResourceBindingReadStatus.ACTIVE
                else DurableOperationResourceBindingState.RELEASED
            )
            if self.record.state is not expected:
                raise ValueError("binding read status/record mismatch")
        elif self.record is not None:
            raise ValueError("NONE/UNKNOWN binding read cannot carry record")


class DurableOperationResourceBindingStore(Protocol):
    async def register(
        self,
        binding: OperationResourceLeaseBinding,
        *,
        registered_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> bool:
        """Persist an exact active operation-resource binding without rebinding."""

    async def read(
        self,
        operation_handle_id: str,
    ) -> DurableOperationResourceBindingReadDecision:
        """Read active/released binding history fail-closed."""

    async def mark_released(
        self,
        binding: OperationResourceLeaseBinding,
        *,
        released_at: datetime,
        release_basis: str,
        required_claim: ExecutionRecoveryClaim,
        provider_fence: ProviderFenceEvidence | None = None,
    ) -> bool:
        """Persist release tombstone for an exact binding."""

    async def active_for_execution(
        self,
        execution_id: str,
    ) -> tuple[DurableOperationResourceBindingRecord, ...]:
        """Return all active bindings for one execution."""


class DurableOperationResourceLeaseRegistry(OperationResourceLeaseRegistry):
    """IU8 registry adapter backed by crash-surviving binding history."""

    def __init__(
        self,
        *,
        store: DurableOperationResourceBindingStore,
        recovery_claim: ExecutionRecoveryClaim,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._claim = recovery_claim
        self._clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise TypeError("binding registry clock returned invalid time")
        _require_aware(value, "binding registry clock")
        return value

    async def register(self, binding: OperationResourceLeaseBinding) -> bool:
        if binding.handle.execution_id != self._claim.execution_id:
            raise RuntimeError("OPERATION_BINDING_RECOVERY_CLAIM_MISMATCH")
        return await self._store.register(
            binding,
            registered_at=self._now(),
            required_claim=self._claim,
        )

    async def get(
        self,
        operation_handle_id: str,
    ) -> OperationResourceLeaseBinding | None:
        decision = await self._store.read(operation_handle_id)
        if decision.status is DurableOperationResourceBindingReadStatus.UNKNOWN:
            raise RuntimeError(decision.reason_codes[0])
        if decision.status is DurableOperationResourceBindingReadStatus.NONE:
            return None
        if decision.record is None:
            raise RuntimeError("DURABLE_OPERATION_BINDING_READ_INVALID")
        if decision.status is DurableOperationResourceBindingReadStatus.RELEASED:
            return None
        return decision.record.binding

    async def remove(self, binding: OperationResourceLeaseBinding) -> bool:
        if binding.handle.execution_id != self._claim.execution_id:
            raise RuntimeError("OPERATION_BINDING_RECOVERY_CLAIM_MISMATCH")
        return await self._store.mark_released(
            binding,
            released_at=self._now(),
            release_basis="LIVE_OPERATION_TERMINAL_RELEASE",
            required_claim=self._claim,
        )


class ResourceRecoveryStatus(str, Enum):
    RECLAIMED = "RECLAIMED"
    ALREADY_RECLAIMED = "ALREADY_RECLAIMED"
    NO_RESOURCE_LOCKS = "NO_RESOURCE_LOCKS"
    RETAINED = "RETAINED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ResourceRecoveryDecision:
    status: ResourceRecoveryStatus
    reason_codes: tuple[str, ...]
    operation_handle_id: str
    released_leases: tuple[ResourceLockLease, ...] = ()
    retained_leases: tuple[ResourceLockLease, ...] = ()
    operation_recovery: OperationRecoveryDecision | None = None
    provider_fence: ProviderFenceEvidence | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ResourceRecoveryStatus):
            raise TypeError("status must be ResourceRecoveryStatus")
        _require_non_blank(self.operation_handle_id, "operation_handle_id")
        if not self.reason_codes or any(not item.strip() for item in self.reason_codes):
            raise ValueError("reason_codes must contain non-blank values")
        released = {item.acquisition_id for item in self.released_leases}
        retained = {item.acquisition_id for item in self.retained_leases}
        if released & retained:
            raise ValueError("released and retained recovery leases must be disjoint")
        if self.status is ResourceRecoveryStatus.RECLAIMED and self.retained_leases:
            raise ValueError("RECLAIMED cannot carry retained leases")
        if self.status is ResourceRecoveryStatus.RETAINED and not self.retained_leases:
            raise ValueError("RETAINED requires retained leases")
        if self.status in {
            ResourceRecoveryStatus.ALREADY_RECLAIMED,
            ResourceRecoveryStatus.NO_RESOURCE_LOCKS,
        } and (self.released_leases or self.retained_leases):
            raise ValueError("no-op recovery status cannot carry lease mutations")


class ToolResourceRecoveryCoordinator:
    """Safely reclaim one crashed Tool operation's exact resource leases."""

    _STRONG_RECOVERY = frozenset(
        {
            OperationRecoveryStatus.COMPLETED_CONFIRMED,
            OperationRecoveryStatus.STOPPED_CONFIRMED,
            OperationRecoveryStatus.NOT_FOUND_WITH_PROOF,
        }
    )

    def __init__(
        self,
        *,
        claim_authority: RecoveryClaimAuthority,
        lock_store: DurableResourceLockStore,
        binding_store: DurableOperationResourceBindingStore,
        inflight_store: DurableInFlightEvidenceStore,
        operation_probe: OperationRecoveryProbe | None = None,
        provider_fencing: ProviderFencingAuthority | None = None,
    ) -> None:
        self._claim_authority = claim_authority
        self._lock_store = lock_store
        self._binding_store = binding_store
        self._inflight_store = inflight_store
        self._operation_probe = operation_probe
        self._provider_fencing = provider_fencing

    async def recover(
        self,
        *,
        operation_handle_id: str,
        recovery_claim: ExecutionRecoveryClaim,
        recovered_at: datetime,
    ) -> ResourceRecoveryDecision:
        _require_non_blank(operation_handle_id, "operation_handle_id")
        _require_aware(recovered_at, "recovered_at")

        epoch = await self._claim_authority.validate_current(recovery_claim)
        if epoch.status is not RecoveryEpochValidationStatus.CURRENT:
            return ResourceRecoveryDecision(
                status=ResourceRecoveryStatus.UNKNOWN,
                reason_codes=(
                    "RESOURCE_RECOVERY_STALE_EPOCH"
                    if epoch.status is RecoveryEpochValidationStatus.STALE
                    else "RESOURCE_RECOVERY_EPOCH_UNKNOWN",
                ),
                operation_handle_id=operation_handle_id,
            )

        binding_read = await self._binding_store.read(operation_handle_id)
        if binding_read.status is DurableOperationResourceBindingReadStatus.UNKNOWN:
            return ResourceRecoveryDecision(
                status=ResourceRecoveryStatus.UNKNOWN,
                reason_codes=binding_read.reason_codes,
                operation_handle_id=operation_handle_id,
            )
        if binding_read.status is DurableOperationResourceBindingReadStatus.RELEASED:
            return ResourceRecoveryDecision(
                status=ResourceRecoveryStatus.ALREADY_RECLAIMED,
                reason_codes=("RESOURCE_BINDING_ALREADY_RELEASED",),
                operation_handle_id=operation_handle_id,
            )
        if binding_read.status is DurableOperationResourceBindingReadStatus.NONE:
            active = await self._lock_store.active_for_owner(operation_handle_id)
            if active:
                return ResourceRecoveryDecision(
                    status=ResourceRecoveryStatus.RETAINED,
                    reason_codes=("UNBOUND_ACTIVE_RESOURCE_LEASES_REQUIRE_RECONCILIATION",),
                    operation_handle_id=operation_handle_id,
                    retained_leases=tuple(item.lease for item in active),
                )
            return ResourceRecoveryDecision(
                status=ResourceRecoveryStatus.NO_RESOURCE_LOCKS,
                reason_codes=("NO_OPERATION_RESOURCE_BINDING_OR_ACTIVE_LEASE",),
                operation_handle_id=operation_handle_id,
            )

        record = binding_read.record
        if record is None:
            return ResourceRecoveryDecision(
                status=ResourceRecoveryStatus.UNKNOWN,
                reason_codes=("RESOURCE_BINDING_READ_INVALID",),
                operation_handle_id=operation_handle_id,
            )
        binding = record.binding
        handle = binding.handle
        if handle.operation_handle_id != operation_handle_id:
            return self._retained(
                binding=binding,
                operation_handle_id=operation_handle_id,
                reason="RESOURCE_BINDING_OPERATION_IDENTITY_MISMATCH",
            )
        if handle.execution_id != recovery_claim.execution_id:
            return self._retained(
                binding=binding,
                operation_handle_id=operation_handle_id,
                reason="RESOURCE_BINDING_RECOVERY_EXECUTION_MISMATCH",
            )
        if recovered_at < handle.started_at or any(
            recovered_at < lease.acquired_at for lease in binding.leases
        ):
            return self._retained(
                binding=binding,
                operation_handle_id=operation_handle_id,
                reason="RESOURCE_RECOVERY_TIME_PRECEDES_OPERATION_EVIDENCE",
            )

        observations = await self._inflight_store.load_inflight(
            execution_id=handle.execution_id,
            step_execution_id=handle.step_execution_id,
        )
        matching = tuple(
            item
            for item in observations
            if item.handle.operation_handle_id == operation_handle_id
        )
        if len(matching) != 1:
            return self._retained(
                binding=binding,
                operation_handle_id=operation_handle_id,
                reason=(
                    "RESOURCE_RECOVERY_INFLIGHT_EVIDENCE_MISSING"
                    if not matching
                    else "RESOURCE_RECOVERY_INFLIGHT_EVIDENCE_AMBIGUOUS"
                ),
            )
        observation = matching[0]
        if observation.handle != handle:
            return self._retained(
                binding=binding,
                operation_handle_id=operation_handle_id,
                reason="RESOURCE_RECOVERY_INFLIGHT_HANDLE_MISMATCH",
            )

        strong_basis: str | None = None
        operation_recovery: OperationRecoveryDecision | None = None
        provider_fence: ProviderFenceEvidence | None = None

        if observation.state is InFlightEvidenceState.COMPLETED:
            strong_basis = "DURABLE_INFLIGHT_COMPLETED"
        elif observation.state is InFlightEvidenceState.CONFIRMED_STOPPED:
            strong_basis = "DURABLE_INFLIGHT_CONFIRMED_STOPPED"
        else:
            operation_recovery = await self._probe(handle)
            if operation_recovery is not None and (
                operation_recovery.status in self._STRONG_RECOVERY
            ):
                if operation_recovery.observed_at < handle.started_at:
                    return self._retained(
                        binding=binding,
                        operation_handle_id=operation_handle_id,
                        reason="OPERATION_RECOVERY_OBSERVATION_PRECEDES_START",
                        operation_recovery=operation_recovery,
                    )
                strong_basis = f"PROBE_{operation_recovery.status.value}"

        if strong_basis is None:
            fence_decision = await self._fence(
                binding=binding,
                recovery_claim=recovery_claim,
                requested_at=recovered_at,
            )
            if fence_decision is not None:
                if fence_decision.status is ProviderFenceStatus.ESTABLISHED:
                    evidence = fence_decision.evidence
                    if (
                        evidence is None
                        or evidence.operation_handle_id != operation_handle_id
                        or evidence.recovery_epoch != recovery_claim.recovery_epoch
                        or evidence.established_at < handle.started_at
                        or evidence.established_at > recovered_at
                    ):
                        return self._retained(
                            binding=binding,
                            operation_handle_id=operation_handle_id,
                            reason="PROVIDER_FENCE_EVIDENCE_INVALID",
                            operation_recovery=operation_recovery,
                        )
                    provider_fence = evidence
                    strong_basis = "PROVIDER_FENCE_ESTABLISHED"
                elif fence_decision.status is ProviderFenceStatus.UNKNOWN:
                    return self._retained(
                        binding=binding,
                        operation_handle_id=operation_handle_id,
                        reason="PROVIDER_FENCE_UNKNOWN_RESOURCE_RETAINED",
                        operation_recovery=operation_recovery,
                    )

        if strong_basis is None:
            reason = "RESOURCE_RECONCILIATION_REQUIRED"
            if (
                operation_recovery is not None
                and operation_recovery.status is OperationRecoveryStatus.RUNNING_CONFIRMED
            ):
                reason = "OPERATION_RUNNING_RESOURCE_RETAINED"
            return self._retained(
                binding=binding,
                operation_handle_id=operation_handle_id,
                reason=reason,
                operation_recovery=operation_recovery,
            )

        released: list[ResourceLockLease] = []
        retained: list[ResourceLockLease] = []
        for lease in reversed(binding.leases):
            decision = await self._lock_store.release(
                lease,
                released_at=recovered_at,
                required_claim=recovery_claim,
            )
            if (
                decision.lease == lease
                and decision.status
                in {
                    ResourceLockReleaseStatus.RELEASED,
                    ResourceLockReleaseStatus.ALREADY_RELEASED,
                }
            ):
                released.append(lease)
            else:
                retained.append(lease)

        released.reverse()
        retained.reverse()
        if retained:
            return ResourceRecoveryDecision(
                status=ResourceRecoveryStatus.UNKNOWN,
                reason_codes=("RESOURCE_RECLAIM_RELEASE_UNCERTAIN",),
                operation_handle_id=operation_handle_id,
                released_leases=tuple(released),
                retained_leases=tuple(retained),
                operation_recovery=operation_recovery,
                provider_fence=provider_fence,
            )

        marked = await self._binding_store.mark_released(
            binding,
            released_at=recovered_at,
            release_basis=strong_basis,
            required_claim=recovery_claim,
            provider_fence=provider_fence,
        )
        if not marked:
            return ResourceRecoveryDecision(
                status=ResourceRecoveryStatus.UNKNOWN,
                reason_codes=("RESOURCE_RECLAIM_BINDING_TOMBSTONE_UNKNOWN",),
                operation_handle_id=operation_handle_id,
                released_leases=tuple(released),
                operation_recovery=operation_recovery,
                provider_fence=provider_fence,
            )

        return ResourceRecoveryDecision(
            status=ResourceRecoveryStatus.RECLAIMED,
            reason_codes=(strong_basis, "RESOURCE_LEASES_RECLAIMED"),
            operation_handle_id=operation_handle_id,
            released_leases=tuple(released),
            operation_recovery=operation_recovery,
            provider_fence=provider_fence,
        )

    async def _probe(
        self,
        handle: InFlightOperationHandle,
    ) -> OperationRecoveryDecision | None:
        if self._operation_probe is None:
            return None
        try:
            decision = await self._operation_probe.probe(handle=handle)
        except Exception:  # noqa: BLE001
            return OperationRecoveryDecision(
                status=OperationRecoveryStatus.UNKNOWN,
                reason_codes=("OPERATION_RECOVERY_PROBE_EXCEPTION",),
                observed_at=handle.started_at,
            )
        if not isinstance(decision, OperationRecoveryDecision):
            return OperationRecoveryDecision(
                status=OperationRecoveryStatus.UNKNOWN,
                reason_codes=("OPERATION_RECOVERY_PROBE_INVALID_DECISION",),
                observed_at=handle.started_at,
            )
        return decision

    async def _fence(
        self,
        *,
        binding: OperationResourceLeaseBinding,
        recovery_claim: ExecutionRecoveryClaim,
        requested_at: datetime,
    ) -> ProviderFenceDecision | None:
        if self._provider_fencing is None:
            return None
        try:
            decision = await self._provider_fencing.establish_fence(
                binding=binding,
                recovery_claim=recovery_claim,
                requested_at=requested_at,
            )
        except Exception:  # noqa: BLE001
            return ProviderFenceDecision(
                status=ProviderFenceStatus.UNKNOWN,
                reason_codes=("PROVIDER_FENCE_EXCEPTION",),
            )
        if not isinstance(decision, ProviderFenceDecision):
            return ProviderFenceDecision(
                status=ProviderFenceStatus.UNKNOWN,
                reason_codes=("PROVIDER_FENCE_INVALID_DECISION",),
            )
        return decision

    @staticmethod
    def _retained(
        *,
        binding: OperationResourceLeaseBinding,
        operation_handle_id: str,
        reason: str,
        operation_recovery: OperationRecoveryDecision | None = None,
    ) -> ResourceRecoveryDecision:
        return ResourceRecoveryDecision(
            status=ResourceRecoveryStatus.RETAINED,
            reason_codes=(reason,),
            operation_handle_id=operation_handle_id,
            retained_leases=binding.leases,
            operation_recovery=operation_recovery,
        )


class InMemoryDurableResourceRecoveryStore(
    DurableResourceLockStore,
    DurableOperationResourceBindingStore,
):
    """Reference crash-surviving lock/binding ledger for CA-03 contract tests.

    Sharing this object across recreated adapters simulates restart. It is not a
    production persistence implementation. Production stores must validate the
    recovery fence and mutate the durable record in one transaction/CAS boundary.
    """

    def __init__(
        self,
        *,
        claim_authority: InMemoryRecoveryClaimAuthority,
    ) -> None:
        self._claim_authority = claim_authority
        self._lock = asyncio.Lock()
        self._lock_by_acquisition: dict[str, DurableResourceLockRecord] = {}
        self._active_acquisition_by_key: dict[str, str] = {}
        self._binding_by_handle: dict[
            str,
            DurableOperationResourceBindingRecord,
        ] = {}

    def _fence_status(
        self,
        claim: ExecutionRecoveryClaim,
    ) -> RecoveryEpochValidationStatus:
        return self._claim_authority._validate_current_sync(claim).status

    async def acquire(
        self,
        request: ResourceLockAcquireRequest,
        *,
        required_claim: ExecutionRecoveryClaim,
    ) -> ResourceLockAcquireDecision:
        _require_claim_execution(required_claim, request.owner.execution_id)
        async with self._lock:
            if self._fence_status(required_claim) is not RecoveryEpochValidationStatus.CURRENT:
                return ResourceLockAcquireDecision(
                    status=ResourceLockAcquireStatus.UNKNOWN,
                    reason_codes=("DURABLE_LOCK_RECOVERY_EPOCH_NOT_CURRENT",),
                )

            indexed = self._lock_by_acquisition.get(request.acquisition_id)
            if indexed is not None:
                exact = (
                    indexed.lease.lock_key == request.lock_key
                    and indexed.lease.owner == request.owner
                )
                if not exact:
                    return ResourceLockAcquireDecision(
                        status=ResourceLockAcquireStatus.UNKNOWN,
                        reason_codes=("DURABLE_LOCK_ACQUISITION_IDENTITY_CONFLICT",),
                    )
                if indexed.state is DurableResourceLockState.ACTIVE:
                    return ResourceLockAcquireDecision(
                        status=ResourceLockAcquireStatus.ALREADY_ACQUIRED,
                        reason_codes=("DURABLE_LOCK_EXACT_ACQUIRE_REPLAY",),
                        lease=deepcopy(indexed.lease),
                    )
                return ResourceLockAcquireDecision(
                    status=ResourceLockAcquireStatus.UNKNOWN,
                    reason_codes=("DURABLE_LOCK_ACQUISITION_ALREADY_RELEASED",),
                )

            active_id = self._active_acquisition_by_key.get(request.lock_key)
            if active_id is not None:
                active = self._lock_by_acquisition[active_id]
                if active.state is DurableResourceLockState.ACTIVE:
                    return ResourceLockAcquireDecision(
                        status=ResourceLockAcquireStatus.BUSY,
                        reason_codes=("DURABLE_LOCK_HELD_BY_ANOTHER_ACQUISITION",),
                    )
                self._active_acquisition_by_key.pop(request.lock_key, None)

            lease = ResourceLockLease(
                lock_key=request.lock_key,
                owner=request.owner,
                acquisition_id=request.acquisition_id,
                acquired_at=request.requested_at,
            )
            record = DurableResourceLockRecord(
                lease=lease,
                state=DurableResourceLockState.ACTIVE,
                revision=1,
                updated_at=request.requested_at,
                writer_recovery_epoch=required_claim.recovery_epoch,
            )
            self._lock_by_acquisition[request.acquisition_id] = record
            self._active_acquisition_by_key[request.lock_key] = request.acquisition_id
            return ResourceLockAcquireDecision(
                status=ResourceLockAcquireStatus.ACQUIRED,
                reason_codes=("DURABLE_LOCK_ACQUIRED",),
                lease=deepcopy(lease),
            )

    async def release(
        self,
        lease: ResourceLockLease,
        *,
        released_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> ResourceLockReleaseDecision:
        _require_aware(released_at, "released_at")
        _require_claim_execution(required_claim, lease.owner.execution_id)
        if released_at < lease.acquired_at:
            raise ValueError("released_at cannot precede acquired_at")
        async with self._lock:
            if self._fence_status(required_claim) is not RecoveryEpochValidationStatus.CURRENT:
                return ResourceLockReleaseDecision(
                    status=ResourceLockReleaseStatus.UNKNOWN,
                    reason_codes=("DURABLE_LOCK_RELEASE_RECOVERY_EPOCH_NOT_CURRENT",),
                    lease=lease,
                )

            indexed = self._lock_by_acquisition.get(lease.acquisition_id)
            if indexed is None or indexed.lease != lease:
                return ResourceLockReleaseDecision(
                    status=ResourceLockReleaseStatus.NOT_OWNER,
                    reason_codes=("DURABLE_LOCK_RELEASE_ACQUISITION_NOT_OWNED",),
                    lease=lease,
                )
            if indexed.state is DurableResourceLockState.RELEASED:
                return ResourceLockReleaseDecision(
                    status=ResourceLockReleaseStatus.ALREADY_RELEASED,
                    reason_codes=("DURABLE_LOCK_EXACT_RELEASE_REPLAY",),
                    lease=lease,
                )

            active_id = self._active_acquisition_by_key.get(lease.lock_key)
            if active_id != lease.acquisition_id:
                return ResourceLockReleaseDecision(
                    status=ResourceLockReleaseStatus.NOT_OWNER,
                    reason_codes=("DURABLE_LOCK_ACTIVE_LEASE_MISMATCH",),
                    lease=lease,
                )

            released = replace(
                indexed,
                state=DurableResourceLockState.RELEASED,
                revision=indexed.revision + 1,
                updated_at=released_at,
                writer_recovery_epoch=required_claim.recovery_epoch,
                released_at=released_at,
            )
            self._lock_by_acquisition[lease.acquisition_id] = released
            self._active_acquisition_by_key.pop(lease.lock_key, None)
            return ResourceLockReleaseDecision(
                status=ResourceLockReleaseStatus.RELEASED,
                reason_codes=("DURABLE_LOCK_RELEASED",),
                lease=lease,
            )

    async def read_by_acquisition(
        self,
        acquisition_id: str,
    ) -> DurableResourceLockReadDecision:
        _require_non_blank(acquisition_id, "acquisition_id")
        async with self._lock:
            record = self._lock_by_acquisition.get(acquisition_id)
            if record is None:
                return DurableResourceLockReadDecision(
                    status=DurableResourceLockReadStatus.NONE,
                    reason_codes=("DURABLE_LOCK_ACQUISITION_NOT_FOUND",),
                )
            status = (
                DurableResourceLockReadStatus.ACTIVE
                if record.state is DurableResourceLockState.ACTIVE
                else DurableResourceLockReadStatus.RELEASED
            )
            return DurableResourceLockReadDecision(
                status=status,
                reason_codes=(f"DURABLE_LOCK_{status.value}",),
                record=deepcopy(record),
            )

    async def active_for_owner(
        self,
        owner_id: str,
    ) -> tuple[DurableResourceLockRecord, ...]:
        _require_non_blank(owner_id, "owner_id")
        async with self._lock:
            return deepcopy(
                tuple(
                    record
                    for record in self._lock_by_acquisition.values()
                    if record.state is DurableResourceLockState.ACTIVE
                    and record.lease.owner.owner_id == owner_id
                )
            )

    async def register(
        self,
        binding: OperationResourceLeaseBinding,
        *,
        registered_at: datetime,
        required_claim: ExecutionRecoveryClaim,
    ) -> bool:
        _require_aware(registered_at, "registered_at")
        _require_claim_execution(required_claim, binding.handle.execution_id)
        if registered_at < binding.handle.started_at:
            raise ValueError("registered_at cannot precede operation started_at")
        async with self._lock:
            if self._fence_status(required_claim) is not RecoveryEpochValidationStatus.CURRENT:
                raise RuntimeError("DURABLE_BINDING_RECOVERY_EPOCH_NOT_CURRENT")
            for lease in binding.leases:
                record = self._lock_by_acquisition.get(lease.acquisition_id)
                if (
                    record is None
                    or record.state is not DurableResourceLockState.ACTIVE
                    or record.lease != lease
                ):
                    raise RuntimeError("DURABLE_BINDING_LEASE_NOT_ACTIVE")

            key = binding.handle.operation_handle_id
            existing = self._binding_by_handle.get(key)
            if existing is not None:
                if (
                    existing.binding == binding
                    and existing.state is DurableOperationResourceBindingState.ACTIVE
                ):
                    return False
                raise ValueError("operation_handle_id resource binding cannot be rebound")
            self._binding_by_handle[key] = DurableOperationResourceBindingRecord(
                binding=deepcopy(binding),
                state=DurableOperationResourceBindingState.ACTIVE,
                revision=1,
                updated_at=registered_at,
                writer_recovery_epoch=required_claim.recovery_epoch,
            )
            return True

    async def read(
        self,
        operation_handle_id: str,
    ) -> DurableOperationResourceBindingReadDecision:
        _require_non_blank(operation_handle_id, "operation_handle_id")
        async with self._lock:
            record = self._binding_by_handle.get(operation_handle_id)
            if record is None:
                return DurableOperationResourceBindingReadDecision(
                    status=DurableOperationResourceBindingReadStatus.NONE,
                    reason_codes=("DURABLE_OPERATION_BINDING_NOT_FOUND",),
                )
            status = (
                DurableOperationResourceBindingReadStatus.ACTIVE
                if record.state is DurableOperationResourceBindingState.ACTIVE
                else DurableOperationResourceBindingReadStatus.RELEASED
            )
            return DurableOperationResourceBindingReadDecision(
                status=status,
                reason_codes=(f"DURABLE_OPERATION_BINDING_{status.value}",),
                record=deepcopy(record),
            )

    async def mark_released(
        self,
        binding: OperationResourceLeaseBinding,
        *,
        released_at: datetime,
        release_basis: str,
        required_claim: ExecutionRecoveryClaim,
        provider_fence: ProviderFenceEvidence | None = None,
    ) -> bool:
        _require_aware(released_at, "released_at")
        _require_non_blank(release_basis, "release_basis")
        _require_claim_execution(required_claim, binding.handle.execution_id)
        async with self._lock:
            if self._fence_status(required_claim) is not RecoveryEpochValidationStatus.CURRENT:
                raise RuntimeError("DURABLE_BINDING_RELEASE_RECOVERY_EPOCH_NOT_CURRENT")
            key = binding.handle.operation_handle_id
            existing = self._binding_by_handle.get(key)
            if existing is None:
                return False
            if existing.binding != binding:
                raise ValueError("operation resource binding identity mismatch")
            if existing.state is DurableOperationResourceBindingState.RELEASED:
                return (
                    existing.released_at == released_at
                    and existing.release_basis == release_basis
                    and existing.provider_fence == provider_fence
                )
            if any(
                (
                    record := self._lock_by_acquisition.get(lease.acquisition_id)
                ) is None
                or record.state is not DurableResourceLockState.RELEASED
                or record.lease != lease
                for lease in binding.leases
            ):
                raise RuntimeError("DURABLE_BINDING_RELEASE_BEFORE_LEASE_RELEASE")
            self._binding_by_handle[key] = replace(
                existing,
                state=DurableOperationResourceBindingState.RELEASED,
                revision=existing.revision + 1,
                updated_at=released_at,
                writer_recovery_epoch=required_claim.recovery_epoch,
                released_at=released_at,
                release_basis=release_basis,
                provider_fence=deepcopy(provider_fence),
            )
            return True

    async def active_for_execution(
        self,
        execution_id: str,
    ) -> tuple[DurableOperationResourceBindingRecord, ...]:
        _require_non_blank(execution_id, "execution_id")
        async with self._lock:
            return deepcopy(
                tuple(
                    record
                    for record in self._binding_by_handle.values()
                    if record.state is DurableOperationResourceBindingState.ACTIVE
                    and record.binding.handle.execution_id == execution_id
                )
            )
