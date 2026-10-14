"""GA-11 domain-configured, in-process read-only text tools.

Different domain packages can bind the same capability without modifying
the Agent loop or trusting model-selected operation names. Computations
run exclusively over verified GA-10 immutable record snapshots.
No network, filesystem, mutation, external execution or M6 grant.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from agent_core.readonly_domain_lookup import (
    ReadOnlyDomainLookup,
    ReadOnlyToolHandler,
)
from agent_core.runner import RunBoundaryError

_OPERATIONS = frozenset({"word_count", "character_count"})


@dataclass(frozen=True, slots=True)
class ReadOnlyTextTools:
    lookup: ReadOnlyDomainLookup
    step_operations: Mapping[str, str]
    _handlers: Mapping[str, ReadOnlyToolHandler] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.lookup) is not ReadOnlyDomainLookup:
            raise RunBoundaryError("invalid text tool lookup")
        steps = self.lookup.catalog.workflow.steps
        if (
            type(self.step_operations) is not dict
            or set(self.step_operations) != {step.step_id for step in steps}
            or any(
                type(operation) is not str or operation not in _OPERATIONS
                for operation in self.step_operations.values()
            )
        ):
            raise RunBoundaryError("invalid domain text tool operations")
        object.__setattr__(
            self, "step_operations", MappingProxyType(dict(self.step_operations))
        )
        source_handlers = self.lookup.handlers()

        async def evaluate(step_id: str, tool_id: str) -> tuple[str, ...]:
            step = next(
                (
                    item
                    for item in steps
                    if item.step_id == step_id and item.tool_id == tool_id
                ),
                None,
            )
            if step is None:
                raise RunBoundaryError("text tool step not bound to package")
            # The source handler performs an exact read and rechecks SHA256.
            evidence = await source_handlers[tool_id](step_id, tool_id)
            record = self.lookup.records[self.lookup.step_keys[step_id]]
            digest_fact = "RECORD_SHA256_" + record.sha256
            if (
                digest_fact not in evidence
                or step.completion_fact not in evidence
            ):
                raise RunBoundaryError("text tool record evidence mismatch")
            operation = self.step_operations[step_id]
            if operation == "word_count":
                metric = f"WORD_COUNT_{len(record.value.split())}"
            else:
                metric = f"CHARACTER_COUNT_{len(record.value)}"
            return (digest_fact, metric, *tuple(
                fact for fact in evidence if fact != digest_fact
            ))

        handlers = {tool_id: evaluate for tool_id in self.lookup.catalog.tool_ids}
        object.__setattr__(self, "_handlers", MappingProxyType(handlers))

    def handlers(self) -> dict[str, ReadOnlyToolHandler]:
        """Return handlers for application-owned GA-09 sandbox composition."""
        return dict(self._handlers)
