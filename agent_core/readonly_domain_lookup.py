"""GA-10 bounded read-only domain record lookup for sandbox Tool dispatch.

This is real deterministic lookup against immutable application-supplied data,
not a tool result fabricated by the test StepPort. No filesystem/network IO,
mutation, M6 permission, or authenticated external observation is implied.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from agent_core.domain_execution_catalog import DomainExecutionCatalog
from agent_core.runner import RunBoundaryError

ReadOnlyToolHandler = Callable[[str, str], Awaitable[tuple[str, ...]]]


@dataclass(frozen=True, slots=True)
class ReadOnlyRecord:
    domain_id: str
    binding_fingerprint: str
    key: str
    value: str
    sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.domain_id) is not str
            or not self.domain_id
            or type(self.binding_fingerprint) is not str
            or len(self.binding_fingerprint) != 64
            or type(self.key) is not str
            or not 1 <= len(self.key) <= 96
            or type(self.value) is not str
            or not 1 <= len(self.value) <= 2048
            or type(self.sha256) is not str
            or len(self.sha256) != 64
            or hashlib.sha256(self.value.encode("utf-8")).hexdigest() != self.sha256
        ):
            raise RunBoundaryError("invalid read-only record snapshot")


@dataclass(frozen=True, slots=True)
class ReadOnlyDomainLookup:
    """Exact-domain immutable records, with package-owned step lookup keys."""

    catalog: DomainExecutionCatalog
    records: Mapping[str, ReadOnlyRecord]
    step_keys: Mapping[str, str]
    _handlers: Mapping[str, ReadOnlyToolHandler] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.catalog) is not DomainExecutionCatalog:
            raise RunBoundaryError("invalid read-only catalog")
        if type(self.records) is not dict or type(self.step_keys) is not dict:
            raise RunBoundaryError("read-only lookup requires explicit snapshots")
        steps = self.catalog.workflow.steps
        if (
            not 1 <= len(self.records) <= 32
            or set(self.step_keys) != {step.step_id for step in steps}
            or any(
                type(key) is not str
                or type(rec) is not ReadOnlyRecord
                or key != rec.key
                or rec.domain_id != self.catalog.domain_id
                or rec.binding_fingerprint != self.catalog.binding_fingerprint
                for key, rec in self.records.items()
            )
            or any(key not in self.records for key in self.step_keys.values())
        ):
            raise RunBoundaryError("read-only lookup scope mismatch")
        records = MappingProxyType(dict(self.records))
        step_keys = MappingProxyType(dict(self.step_keys))
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "step_keys", step_keys)
        handlers: dict[str, ReadOnlyToolHandler] = {}
        for step in steps:
            if step.tool_id in handlers:
                # The same tool is allowed for distinct steps; one handler must
                # explicitly resolve the actual step, not capture a prior step.
                continue

            async def handle(step_id: str, tool_id: str) -> tuple[str, ...]:
                selected = next(
                    (
                        entry
                        for entry in self.catalog.workflow.steps
                        if entry.step_id == step_id and entry.tool_id == tool_id
                    ),
                    None,
                )
                if selected is None:
                    raise RunBoundaryError("read-only lookup step mismatch")
                key = self.step_keys[step_id]
                record = self.records[key]
                if (
                    record.key != key
                    or hashlib.sha256(record.value.encode("utf-8")).hexdigest()
                    != record.sha256
                ):
                    raise RunBoundaryError("read-only record integrity mismatch")
                digest_fact = "RECORD_SHA256_" + record.sha256
                if selected == self.catalog.workflow.steps[-1]:
                    return (digest_fact, selected.completion_fact, "GOAL_SATISFIED")
                return (digest_fact, selected.completion_fact)

            handlers[step.tool_id] = handle
        object.__setattr__(self, "_handlers", MappingProxyType(handlers))

    def handlers(self) -> dict[str, ReadOnlyToolHandler]:
        """Application composes these with its existing sandbox dispatcher."""
        return dict(self._handlers)
