"""GA-08 inert Workflow/Tool/Capability catalogs and evidence-bound completion.

This catalog NEVER binds a live tool adapter, produces a grant, issues M6
permission, or interprets an observation as an authenticated external result.
The application supplies actual trusted execution separately.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from agent_core.domain_extension import DomainExtension, DomainExtensionError
from agent_core.domain_package_loader import VerifiedPackageSnapshotV1
from agent_core.runner import ObservedFact
from runtime.registries import (
    CapabilityDefinition,
    CapabilityRegistry,
    ToolDefinition,
    ToolRegistry,
    WorkflowDefinition,
    WorkflowRegistry,
)


@dataclass(frozen=True, slots=True)
class DomainStep:
    step_id: str
    tool_id: str
    completion_fact: str
    action_id: str
    goal_effect_keys: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class DomainWorkflow:
    workflow_id: str
    steps: tuple[DomainStep, ...]


@dataclass(frozen=True, slots=True)
class WorkflowStepEvidence:
    """Application-provided step correlation; no M6 execution authority."""

    step_id: str
    observation: ObservedFact


@dataclass(frozen=True, slots=True)
class DomainExecutionCatalog:
    domain_id: str
    binding_fingerprint: str
    workflow: DomainWorkflow
    capability_id: str
    tool_ids: tuple[str, ...]
    workflows: WorkflowRegistry
    tools: ToolRegistry
    capabilities: CapabilityRegistry

    def completion_from_observations(
        self, *, run_id: str, observations: tuple[WorkflowStepEvidence, ...]
    ) -> bool:
        """Require ordered, run-bound and separately correlated step evidence.

        Workflow step ID is NOT an execution-instance ID. No trusted execution
        attestation or positive M6 grant is implied by this sandbox gate.
        """
        if (
            type(run_id) is not str
            or not run_id
            or type(observations) is not tuple
            or len(observations) != len(self.workflow.steps)
        ):
            return False
        request_ids: set[str] = set()
        execution_ids: set[str] = set()
        plan_ids: set[str] = set()
        for step, evidence in zip(self.workflow.steps, observations, strict=True):
            if type(evidence) is not WorkflowStepEvidence:
                return False
            observed = evidence.observation
            if (
                type(observed) is not ObservedFact
                or evidence.step_id != step.step_id
                or observed.workflow_step_id != step.step_id
                or observed.tool_id != step.tool_id
                or observed.run_id != run_id
                or observed.domain_fingerprint != self.binding_fingerprint
                or not observed.request_id
                or not observed.execution_id
                or not observed.plan_id
                or step.completion_fact not in observed.facts
                or observed.execution_id in execution_ids
                or observed.plan_id in plan_ids
            ):
                return False
            request_ids.add(observed.request_id)
            execution_ids.add(observed.execution_id)
            plan_ids.add(observed.plan_id)
        # Each Agent iteration may have a distinct request ID under one run.
        # The Coordinator validates exact request/plan correlation per turn.
        return len(request_ids) in (1, len(observations))


def _data(raw: bytes, *, keys: frozenset[str]) -> dict[str, Any]:
    if type(raw) is not bytes or len(raw) > 8192:
        raise DomainExtensionError("invalid execution asset length")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, val in pairs:
            if key in output:
                raise DomainExtensionError("duplicate execution asset key")
            output[key] = val
        return output

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise DomainExtensionError("unparseable execution asset") from exc
    if type(value) is not dict or value.keys() != keys:
        raise DomainExtensionError("invalid execution asset schema")
    return value


def _name(value: object) -> str:
    if type(value) is not str or not 1 <= len(value) <= 96:
        raise DomainExtensionError("invalid execution identifier")
    if not all(char.isascii() and (char.isalnum() or char in "._-") for char in value):
        raise DomainExtensionError("unsupported execution identifier characters")
    return value


def assemble_execution_catalog(
    snapshot: VerifiedPackageSnapshotV1, extension: DomainExtension
) -> DomainExecutionCatalog:
    """Validate an optional capability and one small ordered workflow.

    A workflow is only a static proposal. Registries hold metadata, not
    executable implementations, workflow instances, or M6 permissions.
    """
    if (
        type(snapshot) is not VerifiedPackageSnapshotV1
        or type(extension) is not DomainExtension
        or snapshot.generation_id != extension.binding.generation_id
        or snapshot.descriptor.domain_id != extension.binding.domain_id
        or snapshot.descriptor.domain_version != extension.binding.domain_version
        or snapshot.descriptor.manifest_digest != extension.binding.manifest_digest
        or tuple(a.ref for a in snapshot.assets) != snapshot.descriptor.asset_refs
    ):
        raise DomainExtensionError("execution catalog package binding mismatch")
    found: dict[str, list[tuple[str, dict[str, Any]]]] = {
        "tool": [],
        "workflow": [],
        "capability": [],
    }
    for asset in snapshot.assets:
        kind = asset.ref.kind
        if kind not in found:
            continue
        if (
            asset.ref.namespace != extension.binding.domain_id
            or asset.ref.version != "1.0.0"
            or type(asset.content_bytes) is not bytes
            or hashlib.sha256(asset.content_bytes).hexdigest() != asset.ref.sha256
        ):
            raise DomainExtensionError("execution catalog asset integrity mismatch")
        schema = {
            "tool": frozenset({"description"}),
            "workflow": frozenset({"steps"}),
            "capability": frozenset({"workflow_id", "tool_ids"}),
        }[kind]
        found[kind].append((asset.ref.id, _data(asset.content_bytes, keys=schema)))
    if len(found["workflow"]) != 1 or len(found["capability"]) != 1:
        raise DomainExtensionError("requires exactly one workflow and capability")
    if not 1 <= len(found["tool"]) <= 8:
        raise DomainExtensionError("invalid tool catalog size")

    tools = ToolRegistry()
    workflows = WorkflowRegistry()
    capabilities = CapabilityRegistry()
    tool_ids: list[str] = []
    for tool_id, record in found["tool"]:
        _name(tool_id)
        if tool_id in tool_ids:
            raise DomainExtensionError("duplicate tool")
        desc = record["description"]
        if type(desc) is not str or not 1 <= len(desc) <= 128:
            raise DomainExtensionError("invalid tool metadata")
        tool_ids.append(tool_id)
        tools.register(
            ToolDefinition(
                tool_id=tool_id,
                version="1.0.0",
                description=desc,
                side_effect_level="NO_EXTERNAL_EXECUTION",
                required_permissions=[],
            ),
            namespace=extension.binding.domain_id,
        )
    workflow_id, raw_workflow = found["workflow"][0]
    capability_id, raw_capability = found["capability"][0]
    _name(workflow_id)
    _name(capability_id)
    steps = raw_workflow["steps"]
    if type(steps) is not list or not 1 <= len(steps) <= 6:
        raise DomainExtensionError("invalid workflow steps")
    parsed: list[DomainStep] = []
    for entry in steps:
        if type(entry) is not dict or not (
            entry.keys() == {"step_id", "tool_id", "completion_fact", "action_id"}
            or entry.keys() == {
                "step_id", "tool_id", "completion_fact", "action_id",
                "goal_effect_keys",
            }
        ):
            raise DomainExtensionError("invalid workflow step schema")
        step_id = _name(entry["step_id"])
        tool_id = _name(entry["tool_id"])
        fact = _name(entry["completion_fact"])
        action_id = _name(entry["action_id"])
        if (
            tool_id not in tool_ids
            or action_id not in extension.action_ids
            or step_id in {step.step_id for step in parsed}
        ):
            raise DomainExtensionError("unknown tool or duplicate workflow step")
        raw_effects = entry.get("goal_effect_keys")
        if raw_effects is None:
            # Legacy packages can run, but must never silently retain a step.
            effects = frozenset({"*"})
        elif (
            type(raw_effects) is not list
            or not 1 <= len(raw_effects) <= 8
            or any(type(key) is not str or not 1 <= len(key) <= 96 for key in raw_effects)
            or len(set(raw_effects)) != len(raw_effects)
        ):
            raise DomainExtensionError("invalid workflow goal effect keys")
        else:
            effects = frozenset(raw_effects)
        parsed.append(DomainStep(step_id, tool_id, fact, action_id, effects))
    allowed_tools = raw_capability["tool_ids"]
    if (
        raw_capability["workflow_id"] != workflow_id
        or type(allowed_tools) is not list
        or any(type(item) is not str for item in allowed_tools)
        or set(allowed_tools) != set(tool_ids)
        or len(allowed_tools) != len(tool_ids)
    ):
        raise DomainExtensionError("capability references inconsistent")
    workflows.register(
        WorkflowDefinition(
            workflow_id=workflow_id,
            version="1.0.0",
            states=[step.step_id for step in parsed],
            required_tools=list(dict.fromkeys(step.tool_id for step in parsed)),
            checkpoint_enabled=False,
        ),
        namespace=extension.binding.domain_id,
    )
    capabilities.register(
        CapabilityDefinition(
            capability_id=capability_id,
            version="1.0.0",
            domain=extension.binding.domain_id,
            status="SANDBOX_METADATA_ONLY",
            workflows=[workflow_id],
            tools=tool_ids,
        ),
        namespace=extension.binding.domain_id,
    )
    return DomainExecutionCatalog(
        extension.binding.domain_id,
        extension.binding.binding_fingerprint,
        DomainWorkflow(workflow_id, tuple(parsed)),
        capability_id,
        tuple(tool_ids),
        workflows,
        tools,
        capabilities,
    )
