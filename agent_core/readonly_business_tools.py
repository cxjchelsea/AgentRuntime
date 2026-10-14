"""GA-12 deterministic business decisions over verified in-process records.

Inventory replenishment and study progress intentionally share the unchanged
M4 / GA-09 Agent Loop but have different data schemas and domain rules.
Application-owned operation assignments are not model-supplied. Sandbox only:
no write, network, database access, M6 grant or external execution authority.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from agent_core.readonly_domain_lookup import ReadOnlyDomainLookup, ReadOnlyToolHandler
from agent_core.runner import RunBoundaryError

_RULES = frozenset({"inventory_replenishment", "learning_progress"})


def _strict_json(raw: str, *, expected: frozenset[str]) -> dict[str, int]:
    if type(raw) is not str or not 1 <= len(raw) <= 2048:
        raise RunBoundaryError("invalid business record")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            if key in output:
                raise ValueError("duplicate field")
            output[key] = value
        return output

    try:
        parsed = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, RecursionError) as exc:
        raise RunBoundaryError("invalid business record") from exc
    if type(parsed) is not dict or parsed.keys() != expected:
        raise RunBoundaryError("business record schema mismatch")
    if any(type(value) is not int or not 0 <= value <= 100_000 for value in parsed.values()):
        raise RunBoundaryError("invalid business quantity")
    return parsed


def _business_facts(operation: str, value: str) -> tuple[str, ...]:
    if operation == "inventory_replenishment":
        data = _strict_json(
            value, expected=frozenset({"on_hand", "reserved", "target"})
        )
        if data["reserved"] > data["on_hand"]:
            raise RunBoundaryError("reserved quantity exceeds stock")
        available = data["on_hand"] - data["reserved"]
        deficit = max(0, data["target"] - available)
        return (
            f"AVAILABLE_{available}",
            f"REPLENISH_QTY_{deficit}",
            "REPLENISH_REQUIRED" if deficit else "REPLENISH_NOT_REQUIRED",
        )
    if operation == "learning_progress":
        data = _strict_json(
            value, expected=frozenset({"completed", "total"})
        )
        if not 1 <= data["total"] or data["completed"] > data["total"]:
            raise RunBoundaryError("invalid learning progress")
        percent = 100 * data["completed"] // data["total"]
        return (
            f"PROGRESS_PERCENT_{percent}",
            f"REMAINING_TASKS_{data['total'] - data['completed']}",
            "LEARNING_COMPLETE"
            if data["completed"] == data["total"]
            else "LEARNING_INCOMPLETE",
        )
    raise RunBoundaryError("unregistered business rule")


@dataclass(frozen=True, slots=True)
class ReadOnlyBusinessTools:
    """Bind each verified workflow step to one allowlisted domain calculation."""

    lookup: ReadOnlyDomainLookup
    step_operations: Mapping[str, str]
    _handlers: Mapping[str, ReadOnlyToolHandler] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.lookup) is not ReadOnlyDomainLookup:
            raise RunBoundaryError("invalid business lookup")
        steps = self.lookup.catalog.workflow.steps
        if (
            type(self.step_operations) is not dict
            or set(self.step_operations) != {step.step_id for step in steps}
            or any(
                type(op) is not str or op not in _RULES
                for op in self.step_operations.values()
            )
        ):
            raise RunBoundaryError("invalid business operation map")
        object.__setattr__(
            self, "step_operations", MappingProxyType(dict(self.step_operations))
        )
        verified_handlers = self.lookup.handlers()

        async def calculate(step_id: str, tool_id: str) -> tuple[str, ...]:
            step = next(
                (
                    entry
                    for entry in steps
                    if entry.step_id == step_id and entry.tool_id == tool_id
                ),
                None,
            )
            if step is None:
                raise RunBoundaryError("business tool step not bound")
            evidence = await verified_handlers[tool_id](step_id, tool_id)
            record = self.lookup.records[self.lookup.step_keys[step_id]]
            digest = "RECORD_SHA256_" + record.sha256
            if digest not in evidence or step.completion_fact not in evidence:
                raise RunBoundaryError("business source evidence mismatch")
            facts = _business_facts(self.step_operations[step_id], record.value)
            return (
                digest,
                *facts,
                *tuple(fact for fact in evidence if fact != digest),
            )

        object.__setattr__(
            self,
            "_handlers",
            MappingProxyType(
                {tool_id: calculate for tool_id in self.lookup.catalog.tool_ids}
            ),
        )

    def handlers(self) -> dict[str, ReadOnlyToolHandler]:
        """Inject into an application-owned GA-09 dispatcher."""
        return dict(self._handlers)
