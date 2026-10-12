"""GA-02 D2-C C0: isolated, NON-AUTHORITATIVE catalog diagnostics.

No Registry lookup, publisher, DomainBinding, filesystem, tools or runtime consumers.
The only entry takes test-owned primitive metadata; hashes authenticate no issuer.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, NoReturn, cast

_ID = re.compile(r"[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*\Z", re.ASCII)
_VER = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\Z", re.ASCII)
_SHA = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_KIND = {
    "action",
    "strategy",
    "skill",
    "tool",
    "workflow",
    "capability",
    "prompt",
    "rule",
    "schema",
    "knowledge",
    "state",
    "eval",
}
_REG = {
    "action": "action",
    "strategy": "strategy",
    "skill": "skill",
    "tool": "tool",
    "workflow": "workflow",
    "capability": "capability",
    "prompt": "prompt",
    "rule": "policy",
    "schema": "schema",
}
_TYPES = {
    "action": ("ActionDefinition", "action_id", True),
    "strategy": ("StrategyDefinition", "strategy_id", True),
    "skill": ("SkillDefinition", "skill_id", True),
    "tool": ("ToolDefinition", "tool_id", True),
    "workflow": ("WorkflowDefinition", "workflow_id", True),
    "capability": ("CapabilityDefinition", "capability_id", False),
    "prompt": ("PromptDefinition", "prompt_id", False),
    "policy": ("PolicyDefinition", "rule_id", True),
    "schema": ("SchemaDefinition", "schema_id", False),
    "domain": ("DomainManifest", "domain_id", True),
}
# Field codes: s string, b strict bool, i strict int, l ordered strings,
# ? nullable, e:<members> enum string, L:<members> enum list.
_FIELDS = {
    "ActionDefinition": "action_id:s version:s category:s description:s intrusiveness_level:e:VERY_LOW,LOW,MEDIUM,HIGH requires_confirmation:b required_capability:s? allowed_planning_modes:L:FORCED,DETERMINISTIC,AGENT_PLANNED,DEGRADED enabled:b",
    "StrategyDefinition": "strategy_id:s version:s description:s preferred_goals:l preferred_needs:l compatible_emotions:l required_conditions:l avoid_conditions:l default_actions:l intrusiveness_level:e:VERY_LOW,LOW,MEDIUM,HIGH enabled:b",
    "SkillDefinition": "skill_id:s version:s enabled:b supported_actions:l? required_tools:l? optional_tools:l? allowed_states:l? input_schema:s? output_schema:s? timeout_policy:s? retry_policy:s? idempotency_policy:s? side_effect_level:s?",
    "WorkflowDefinition": "workflow_id:s version:s enabled:b states:l? entry_conditions:l? exit_conditions:l? supported_events:l? allowed_states:l? checkpoint_enabled:b? timeout_policy:s? resume_policy:s? required_tools:l? optional_tools:l?",
    "ToolDefinition": "tool_id:s version:s enabled:b description:s? input_schema:s? output_schema:s? timeout_policy:s? retry_policy:s? idempotency_mode:s? side_effect_level:s? required_permissions:l? resource_locks:l?",
    "PolicyDefinition": "rule_id:s version:s priority:i scope:s trigger:s? effect:s? enabled:b",
    "PromptDefinition": "prompt_id:s version:s layer:e:RUNTIME_BASE,DOMAIN,TASK,CONSTRAINT domain:s? stage:s? model_constraints:s? schema_contract:s?",
    "DomainManifest": "domain_id:s name:s version:s enabled:b runtime_compatibility:s? required_core_schemas:l? registered_schemas:l? registered_intents:l? registered_workflows:l? registered_capabilities:l? registered_skills:l? registered_tools:l? knowledge_domains:l? prompt_packages:l? state_schema:s? eval_packages:l? feature_flags:l?",
    "SchemaDefinition": "schema_id:s version:s scope:e:CORE,DOMAIN namespace:s? schema_reference:s?",
    "CapabilityDefinition": "capability_id:s version:s domain:s? implementation_type:s? status:s? business_taxonomy_ref:s? intents:l? entities:l? needs:l? skills:l? workflows:l? tools:l? knowledge_dependencies:l? state_dependencies:l? policy_dependencies:l? validation_dependencies:l? eval_cases:l?",
}
_REL = {
    ("action", "required_capability"): (
        "capability",
        "action.required_capability",
        False,
    ),
    ("strategy", "default_actions"): ("action", "strategy.default_actions", False),
    ("skill", "supported_actions"): ("action", "skill.supported_actions", False),
    ("skill", "required_tools"): ("tool", "skill.required_tools", False),
    ("skill", "optional_tools"): ("tool", "skill.optional_tools", True),
    ("workflow", "required_tools"): ("tool", "workflow.required_tools", False),
    ("workflow", "optional_tools"): ("tool", "workflow.optional_tools", True),
    ("capability", "skills"): ("skill", "capability.skills", False),
    ("capability", "workflows"): ("workflow", "capability.workflows", False),
    ("capability", "tools"): ("tool", "capability.tools", False),
}
_ALLOWED_MODE = {"REGISTRY_EXACT", "INERT_ONLY"}
_KEY = tuple[str, str, str, str]


class D2CCode(str, Enum):
    D2C_UNTRUSTED_CATALOG_SOURCE = "D2C_UNTRUSTED_CATALOG_SOURCE"
    D2C_CATALOG_GENERATION_MISMATCH = "D2C_CATALOG_GENERATION_MISMATCH"
    D2C_CATALOG_SNAPSHOT_UNSTABLE = "D2C_CATALOG_SNAPSHOT_UNSTABLE"
    D2C_CANONICAL_DEFINITION_INVALID = "D2C_CANONICAL_DEFINITION_INVALID"
    D2C_DEFINITION_HASH_MISMATCH = "D2C_DEFINITION_HASH_MISMATCH"
    D2C_EDGE_CATALOG_INVALID = "D2C_EDGE_CATALOG_INVALID"
    D2C_EXACT_DEPENDENCY_MISSING = "D2C_EXACT_DEPENDENCY_MISSING"
    D2C_DEPENDENCY_CYCLE = "D2C_DEPENDENCY_CYCLE"
    D2C_DEPENDENCY_DISABLED = "D2C_DEPENDENCY_DISABLED"
    D2C_HOST_ADAPTER_MISMATCH = "D2C_HOST_ADAPTER_MISMATCH"
    D2C_RESOURCE_LIMIT = "D2C_RESOURCE_LIMIT"
    D2C_RESOLUTION_UNSTABLE = "D2C_RESOLUTION_UNSTABLE"


class D2CResolutionError(ValueError):
    def __init__(self, code: D2CCode) -> None:
        self.code = code
        super().__init__(code.value)


def _deny(code: D2CCode) -> NoReturn:
    raise D2CResolutionError(code)


@dataclass(frozen=True, slots=True)
class DiagnosticAssetRefV1:
    kind: str
    namespace: str
    id: str
    version: str
    sha256: str
    relative_path: str


@dataclass(frozen=True, slots=True)
class DiagnosticCoreSchemaKeyV1:
    id: str
    version: str


@dataclass(frozen=True, slots=True)
class DiagnosticRegistryEntryV1:
    registry_kind: str
    namespace: str
    id: str
    version: str
    definition_type: str
    fields: dict[str, Any]
    definition_sha256: str
    record_enabled: bool
    intrinsic_enabled: bool | None


@dataclass(frozen=True, slots=True)
class DiagnosticEdgeOccurrenceV1:
    source_kind: str
    source_namespace: str
    source_id: str
    source_version: str
    relation_id: str
    ordinal: int
    declared_target_id: str
    outcome: str
    target_kind: str | None
    target_namespace: str | None
    target_id: str | None
    target_version: str | None


@dataclass(frozen=True, slots=True)
class DiagnosticAdapterEntryV1:
    registry_kind: str
    namespace: str
    id: str
    version: str
    status: str
    adapter_key: str | None
    adapter_generation: str | None
    tenant_scope_allowlist_id: str | None
    domain_scope: str | None
    host_registration_digest: str | None


@dataclass(frozen=True, slots=True)
class DiagnosticCatalogInputV1:
    profile: str
    domain_id: str
    domain_version: str
    runtime_profile: str
    manifest_sha256: str
    source_generation: str
    host_catalog_generation: str
    host_policy_id: str
    host_policy_generation: str
    prompt_mode: str
    rule_mode: str
    asset_refs: tuple[DiagnosticAssetRefV1, ...]
    approved_core_schema_keys: tuple[DiagnosticCoreSchemaKeyV1, ...]
    registry_entries: tuple[DiagnosticRegistryEntryV1, ...]
    edge_occurrences: tuple[DiagnosticEdgeOccurrenceV1, ...]
    adapter_entries: tuple[DiagnosticAdapterEntryV1, ...]


@dataclass(frozen=True, slots=True)
class DiagnosticResolutionSnapshotV1:
    observation_role: str
    graph_completeness: str
    operational_readiness: str
    seed_keys: tuple[_KEY, ...]
    dependency_keys: tuple[_KEY, ...]
    edge_occurrences: tuple[tuple[tuple[str, Any], ...], ...]
    definition_hashes: tuple[tuple[_KEY, str], ...]
    adapter_evidence: tuple[tuple[tuple[str, Any], ...], ...]
    edge_digest: str
    host_catalog_digest: str
    closure_digest: str
    unresolved_non_graph_metadata: bool


@dataclass(frozen=True, slots=True)
class _OwnedDiagnosticInputV1:
    value: DiagnosticCatalogInputV1
    primitive_element_count: int
    canonical_input_bytes: int = 0


def _string(value: object, *, identifier: bool = False, version: bool = False) -> bool:
    if type(value) is not str or len(value) > 1024 or not value:
        return False
    if unicodedata.normalize("NFC", value) != value:
        return False
    if any(unicodedata.category(c) in {"Cc", "Cs"} for c in value):
        return False
    if identifier:
        return len(value) <= 80 and bool(_ID.fullmatch(value))
    if version:
        return len(value) <= 32 and bool(_VER.fullmatch(value))
    return True


def _json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8", "strict")


def _digest(profile: str | None, value: Any) -> str:
    prefix = (profile.encode("utf-8") + b"\0") if profile is not None else b""
    return hashlib.sha256(prefix + _json(value)).hexdigest()


def _record(value: object, klass: type[Any], counter: list[int]) -> dict[str, Any]:
    if type(value) is not klass:
        _deny(D2CCode.D2C_RESOLUTION_UNSTABLE)
    result: dict[str, Any] = {}
    for field in fields(cast(Any, klass)):
        counter[0] += 1
        if counter[0] > 4096:
            _deny(D2CCode.D2C_RESOURCE_LIMIT)
        v = object.__getattribute__(value, field.name)
        if field.name == "fields":
            result[field.name] = _copy_fields(v, counter)
        elif type(v) in (str, bool, int, type(None)):
            if type(v) is str and not _string(v):
                _deny(D2CCode.D2C_RESOLUTION_UNSTABLE)
            result[field.name] = v
        else:
            _deny(D2CCode.D2C_RESOLUTION_UNSTABLE)
    return result


def _copy_fields(value: object, counter: list[int]) -> dict[str, Any]:
    if type(value) is not dict:
        _deny(D2CCode.D2C_RESOLUTION_UNSTABLE)
    # Explicit iterative stack; only exact builtins, no hostile iterators.
    root: dict[str, Any] = {}
    stack: list[tuple[object, Any, int, frozenset[int]]] = [
        (value, root, 0, frozenset())
    ]
    while stack:
        node, target, depth, ancestors = stack.pop()
        if depth > 12:
            _deny(D2CCode.D2C_RESOURCE_LIMIT)
        if id(node) in ancestors:
            _deny(D2CCode.D2C_RESOLUTION_UNSTABLE)
        if type(node) not in (dict, list):
            _deny(D2CCode.D2C_RESOLUTION_UNSTABLE)
        ancestors = ancestors | {id(node)}
        if type(node) is dict:
            for k, v in node.items():
                if not _string(k):
                    _deny(D2CCode.D2C_RESOLUTION_UNSTABLE)
                counter[0] += 1
                if counter[0] > 4096:
                    _deny(D2CCode.D2C_RESOURCE_LIMIT)
                if type(v) in (dict, list):
                    child: dict[str, Any] | list[Any] = {} if type(v) is dict else []
                    target[k] = child
                    stack.append((v, child, depth + 1, ancestors))
                elif type(v) in (str, bool, int, type(None)):
                    if type(v) is str and not _string(v):
                        _deny(D2CCode.D2C_CANONICAL_DEFINITION_INVALID)
                    target[k] = v
                else:
                    _deny(D2CCode.D2C_RESOLUTION_UNSTABLE)
        else:
            list_node = cast(list[Any], node)
            if len(list_node) > 256:
                _deny(D2CCode.D2C_RESOURCE_LIMIT)
            for v in list_node:
                counter[0] += 1
                if counter[0] > 4096:
                    _deny(D2CCode.D2C_RESOURCE_LIMIT)
                if type(v) in (dict, list):
                    child = {} if type(v) is dict else []
                    target.append(child)
                    stack.append((v, child, depth + 1, ancestors))
                elif type(v) in (str, bool, int, type(None)):
                    if type(v) is str and not _string(v):
                        _deny(D2CCode.D2C_CANONICAL_DEFINITION_INVALID)
                    target.append(v)
                else:
                    _deny(D2CCode.D2C_RESOLUTION_UNSTABLE)
    return root


_CARRIERS = {
    "asset_refs": DiagnosticAssetRefV1,
    "approved_core_schema_keys": DiagnosticCoreSchemaKeyV1,
    "registry_entries": DiagnosticRegistryEntryV1,
    "edge_occurrences": DiagnosticEdgeOccurrenceV1,
    "adapter_entries": DiagnosticAdapterEntryV1,
}


def _admit_and_copy_diagnostic_input(
    input: DiagnosticCatalogInputV1,
) -> _OwnedDiagnosticInputV1:
    if type(input) is not DiagnosticCatalogInputV1:
        _deny(D2CCode.D2C_RESOLUTION_UNSTABLE)
    count = [1]
    data: dict[str, Any] = {}
    for field in fields(DiagnosticCatalogInputV1):
        count[0] += 1
        if field.name in _CARRIERS:
            original = object.__getattribute__(input, field.name)
            if type(original) is not tuple:
                _deny(D2CCode.D2C_RESOLUTION_UNSTABLE)
            if field.name == "asset_refs" and len(original) > 256:
                _deny(D2CCode.D2C_RESOURCE_LIMIT)
            copied = []
            for v in original:
                count[0] += 1
                if count[0] > 4096:
                    _deny(D2CCode.D2C_RESOURCE_LIMIT)
                props = _record(v, _CARRIERS[field.name], count)
                copied.append(_CARRIERS[field.name](**props))
            data[field.name] = tuple(copied)
        else:
            v = object.__getattribute__(input, field.name)
            if type(v) is not str or not _string(v):
                _deny(D2CCode.D2C_RESOLUTION_UNSTABLE)
            data[field.name] = v
    if count[0] > 4096:
        _deny(D2CCode.D2C_RESOURCE_LIMIT)
    owned = DiagnosticCatalogInputV1(**data)
    if owned.profile != "GA02-D2C-C0-INPUT-1" or owned.runtime_profile != "GA02-D1-1":
        _deny(D2CCode.D2C_RESOLUTION_UNSTABLE)
    if owned.prompt_mode not in _ALLOWED_MODE or owned.rule_mode not in _ALLOWED_MODE:
        _deny(D2CCode.D2C_RESOLUTION_UNSTABLE)
    if not (
        _string(owned.domain_id, identifier=True)
        and _string(owned.domain_version, version=True)
        and bool(_SHA.fullmatch(owned.manifest_sha256))
    ):
        _deny(D2CCode.D2C_RESOLUTION_UNSTABLE)
    canonical_size = _input_canonical_size(owned)
    if canonical_size > 2097152:
        _deny(D2CCode.D2C_RESOURCE_LIMIT)
    return _OwnedDiagnosticInputV1(owned, count[0], canonical_size)


def _input_canonical_size(value: DiagnosticCatalogInputV1) -> int:
    """Count exact copied canonical input bytes, not only derived evidence.

    All fields have already been defensively copied to primitive owned values.
    """
    payload: dict[str, Any] = {}
    for field in fields(DiagnosticCatalogInputV1):
        item = object.__getattribute__(value, field.name)
        if field.name in _CARRIERS:
            payload[field.name] = [
                {
                    part.name: object.__getattribute__(record, part.name)
                    for part in fields(_CARRIERS[field.name])
                }
                for record in item
            ]
        else:
            payload[field.name] = item
    return len(_json(payload))


def _canonical_definition(entry: DiagnosticRegistryEntryV1) -> bytes:
    schema = _FIELDS.get(entry.definition_type)
    if schema is None or type(entry.fields) is not dict:
        _deny(D2CCode.D2C_CANONICAL_DEFINITION_INVALID)
    spec: dict[str, str] = {}
    for token in schema.split():
        name, _, kind_tag = token.partition(":")
        spec[name] = kind_tag
    if set(entry.fields) != set(spec):
        _deny(D2CCode.D2C_CANONICAL_DEFINITION_INVALID)
    for key, tag in spec.items():
        v = entry.fields[key]
        nullable = tag.endswith("?")
        if nullable:
            tag = tag[:-1]
        if v is None and nullable:
            continue
        if tag == "s":
            good = _string(v)
        elif tag == "b":
            good = type(v) is bool
        elif tag == "i":
            good = type(v) is int
        elif tag == "l":
            good = type(v) is list and all(_string(x) for x in v)
        elif tag.startswith("L:"):
            good = type(v) is list and all(
                type(x) is str and x in tag[2:].split(",") for x in v
            )
        elif tag.startswith("e:"):
            good = type(v) is str and v in tag[2:].split(",")
        else:
            good = False
        if not good:
            _deny(D2CCode.D2C_CANONICAL_DEFINITION_INVALID)
    payload = _json(entry.fields)
    if len(payload) > 10240:
        _deny(D2CCode.D2C_RESOURCE_LIMIT)
    return payload


def _key(
    kind: str | None, ns: str | None, item: str | None, version: str | None
) -> _KEY:
    if not all(type(value) is str for value in (kind, ns, item, version)):
        _deny(D2CCode.D2C_EDGE_CATALOG_INVALID)
    return cast(str, kind), cast(str, ns), cast(str, item), cast(str, version)


def _edge_obj(edge: DiagnosticEdgeOccurrenceV1) -> dict[str, Any]:
    return {
        field.name: object.__getattribute__(edge, field.name)
        for field in fields(DiagnosticEdgeOccurrenceV1)
    }


def _adapter_obj(adapter: DiagnosticAdapterEntryV1) -> dict[str, Any]:
    return {
        field.name: object.__getattribute__(adapter, field.name)
        for field in fields(DiagnosticAdapterEntryV1)
    }


def _key_obj(key: _KEY) -> dict[str, str]:
    return {
        "registry_kind": key[0],
        "namespace": key[1],
        "id": key[2],
        "version": key[3],
    }


def _asset_kind(kind: str, prompt: str, rule: str) -> str | None:
    if kind not in _REG:
        return None
    if (kind == "prompt" and prompt == "INERT_ONLY") or (
        kind == "rule" and rule == "INERT_ONLY"
    ):
        return None
    return _REG[kind]


def _resolve_owned_diagnostic_graph(
    owned: _OwnedDiagnosticInputV1,
) -> DiagnosticResolutionSnapshotV1:
    if type(owned) is not _OwnedDiagnosticInputV1:
        _deny(D2CCode.D2C_RESOLUTION_UNSTABLE)
    x = owned.value
    assetkeys: set[_KEY] = set()
    active: set[_KEY] = set()
    seen_assets: set[tuple[str, str, str, str]] = set()
    for asset_ref in x.asset_refs:
        if (
            not _string(asset_ref.kind)
            or not _string(asset_ref.namespace)
            or not _string(asset_ref.sha256)
            or asset_ref.kind not in _KIND
            or not (
                _string(asset_ref.id, identifier=True)
                and _string(asset_ref.version, version=True)
            )
            or not _SHA.fullmatch(asset_ref.sha256)
        ):
            _deny(D2CCode.D2C_RESOLUTION_UNSTABLE)
        if asset_ref.namespace != x.domain_id and not (
            asset_ref.kind == "schema" and asset_ref.namespace == "CORE"
        ):
            _deny(D2CCode.D2C_EXACT_DEPENDENCY_MISSING)
        if (
            asset_ref.kind,
            asset_ref.namespace,
            asset_ref.id,
            asset_ref.version,
        ) in seen_assets:
            _deny(D2CCode.D2C_RESOLUTION_UNSTABLE)
        if (
            not _string(asset_ref.relative_path)
            or len(asset_ref.relative_path.encode("utf-8")) > 512
            or any(p in {"", ".", ".."} for p in asset_ref.relative_path.split("/"))
            or any(c in asset_ref.relative_path for c in ("\\", ":", "%"))
            or asset_ref.relative_path.startswith("/")
        ):
            _deny(D2CCode.D2C_RESOLUTION_UNSTABLE)
        seen_assets.add(
            (asset_ref.kind, asset_ref.namespace, asset_ref.id, asset_ref.version)
        )
        kind = _asset_kind(asset_ref.kind, x.prompt_mode, x.rule_mode)
        if kind is not None:
            k = _key(kind, asset_ref.namespace, asset_ref.id, asset_ref.version)
            if asset_ref.namespace == "CORE" and (
                asset_ref.kind != "schema"
                or (asset_ref.id, asset_ref.version)
                not in {(v.id, v.version) for v in x.approved_core_schema_keys}
            ):
                _deny(D2CCode.D2C_EXACT_DEPENDENCY_MISSING)
            active.add(k)
        assetkeys.add(
            _key(asset_ref.kind, asset_ref.namespace, asset_ref.id, asset_ref.version)
        )
    if len(active) > 256:
        _deny(D2CCode.D2C_RESOURCE_LIMIT)
    records: dict[_KEY, DiagnosticRegistryEntryV1] = {}
    definition_hashes: dict[_KEY, str] = {}
    domain_key = _key("domain", x.domain_id, x.domain_id, x.domain_version)
    for registry_entry in x.registry_entries:
        k = _key(
            registry_entry.registry_kind,
            registry_entry.namespace,
            registry_entry.id,
            registry_entry.version,
        )
        if k in records or registry_entry.registry_kind not in _TYPES:
            _deny(D2CCode.D2C_RESOLUTION_UNSTABLE)
        cls, id_field, intrinsic = _TYPES[registry_entry.registry_kind]
        if (
            registry_entry.definition_type != cls
            or registry_entry.fields.get(id_field) != registry_entry.id
            or registry_entry.fields.get("version") != registry_entry.version
        ):
            _deny(D2CCode.D2C_CANONICAL_DEFINITION_INVALID)
        if registry_entry.registry_kind == "schema":
            scope = registry_entry.fields.get("scope")
            declared_namespace = registry_entry.fields.get("namespace")
            required_scope = "CORE" if registry_entry.namespace == "CORE" else "DOMAIN"
            if (
                scope != required_scope
                or declared_namespace != registry_entry.namespace
            ):
                _deny(D2CCode.D2C_EXACT_DEPENDENCY_MISSING)
        raw = _canonical_definition(registry_entry)
        actual = hashlib.sha256(raw).hexdigest()
        if (
            type(registry_entry.definition_sha256) is not str
            or actual != registry_entry.definition_sha256
        ):
            _deny(D2CCode.D2C_DEFINITION_HASH_MISMATCH)
        if type(registry_entry.record_enabled) is not bool or type(
            registry_entry.intrinsic_enabled
        ) not in (
            bool,
            type(None),
        ):
            _deny(D2CCode.D2C_CANONICAL_DEFINITION_INVALID)
        if intrinsic and type(registry_entry.intrinsic_enabled) is not bool:
            _deny(D2CCode.D2C_CANONICAL_DEFINITION_INVALID)
        if not intrinsic and registry_entry.intrinsic_enabled is not None:
            _deny(D2CCode.D2C_CANONICAL_DEFINITION_INVALID)
        if (
            intrinsic
            and registry_entry.fields["enabled"] != registry_entry.intrinsic_enabled
        ):
            _deny(D2CCode.D2C_CANONICAL_DEFINITION_INVALID)
        records[k] = registry_entry
        definition_hashes[k] = actual
    if domain_key not in records:
        _deny(D2CCode.D2C_EXACT_DEPENDENCY_MISSING)
    manifest = records[domain_key]
    if (
        manifest.fields["runtime_compatibility"] != x.runtime_profile
        or manifest.fields["domain_id"] != x.domain_id
        or manifest.fields["version"] != x.domain_version
    ):
        _deny(D2CCode.D2C_CATALOG_GENERATION_MISMATCH)
    expected: dict[tuple[_KEY, str, int], tuple[str, str, bool]] = {}
    for k, entry in sorted(records.items()):
        if k not in active:
            continue
        for (kind, field), (targetkind, relation, optional) in _REL.items():
            if kind != k[0]:
                continue
            refs = entry.fields[field]
            vals = (
                [refs]
                if field == "required_capability" and refs is not None
                else []
                if refs is None
                else refs
            )
            for ordinal, target in enumerate(vals):
                expected[(k, relation, ordinal)] = (targetkind, target, optional)
    edges: dict[tuple[_KEY, str, int], DiagnosticEdgeOccurrenceV1] = {}
    for e in x.edge_occurrences:
        source = _key(e.source_kind, e.source_namespace, e.source_id, e.source_version)
        ek = (source, e.relation_id, e.ordinal)
        if (
            type(e.ordinal) is not int
            or e.ordinal < 0
            or ek in edges
            or ek not in expected
        ):
            _deny(D2CCode.D2C_EDGE_CATALOG_INVALID)
        tk, tid, optional = expected[ek]
        if e.declared_target_id != tid:
            _deny(D2CCode.D2C_EDGE_CATALOG_INVALID)
        if e.outcome == "OPTIONAL_ABSENT":
            if not optional or any(
                v is not None
                for v in (
                    e.target_kind,
                    e.target_namespace,
                    e.target_id,
                    e.target_version,
                )
            ):
                _deny(D2CCode.D2C_EDGE_CATALOG_INVALID)
        elif (
            e.outcome != "PINNED"
            or e.target_kind != tk
            or e.target_id != tid
            or not (type(e.target_namespace) is str and type(e.target_version) is str)
        ):
            _deny(D2CCode.D2C_EDGE_CATALOG_INVALID)
        edges[ek] = e
    if set(edges) != set(expected):
        _deny(D2CCode.D2C_EDGE_CATALOG_INVALID)
    if len(edges) > 1024:
        _deny(D2CCode.D2C_RESOURCE_LIMIT)
    adjacency: dict[_KEY, list[_KEY]] = {k: [] for k in active}
    for e in edges.values():
        if e.outcome != "PINNED":
            continue
        target = _key(e.target_kind, e.target_namespace, e.target_id, e.target_version)
        if (
            target not in active
            or e.target_namespace not in {x.domain_id, "CORE"}
            or (e.target_namespace == "CORE" and e.target_kind != "schema")
        ):
            _deny(D2CCode.D2C_EXACT_DEPENDENCY_MISSING)
        adjacency[
            _key(e.source_kind, e.source_namespace, e.source_id, e.source_version)
        ].append(target)
    if set(records) != active | {domain_key}:
        if any(k not in records for k in active):
            _deny(D2CCode.D2C_EXACT_DEPENDENCY_MISSING)
        _deny(D2CCode.D2C_RESOLUTION_UNSTABLE)
    for k in sorted(records):
        item = records[k]
        if not item.record_enabled or item.intrinsic_enabled is False:
            _deny(D2CCode.D2C_DEPENDENCY_DISABLED)
    adapter_objects = []
    seen_adapter: set[_KEY] = set()
    for a in x.adapter_entries:
        k = _key(a.registry_kind, a.namespace, a.id, a.version)
        values = (
            a.adapter_key,
            a.adapter_generation,
            a.tenant_scope_allowlist_id,
            a.domain_scope,
            a.host_registration_digest,
        )
        if k in seen_adapter or k not in active:
            _deny(D2CCode.D2C_HOST_ADAPTER_MISMATCH)
        seen_adapter.add(k)
        if a.status in {"NOT_REQUIRED_BY_DIAGNOSTIC_PROFILE", "ABSENT_UNVERIFIED"}:
            valid = all(v is None for v in values)
        elif a.status == "DECLARED_NON_AUTHORITATIVE":
            valid = all(_string(v) for v in values) and (
                type(a.host_registration_digest) is str
                and bool(_SHA.fullmatch(a.host_registration_digest))
            )
        else:
            valid = False
        if not valid:
            _deny(D2CCode.D2C_HOST_ADAPTER_MISMATCH)
        adapter_objects.append(_adapter_obj(a))
    # One color-marked DFS for cycle detection, then longest DAG path from
    # every seed. Global DONE never masks a long path through a shared node.
    completed: set[_KEY] = set()
    longest_depth: dict[_KEY, int] = {}
    for root in sorted(active):
        if root in completed:
            continue
        stack: list[tuple[_KEY, bool]] = [(root, False)]
        visiting: set[_KEY] = set()
        while stack:
            node, finished = stack.pop()
            if finished:
                visiting.discard(node)
                longest_depth[node] = max(
                    (longest_depth[child] + 1 for child in set(adjacency[node])),
                    default=0,
                )
                completed.add(node)
                continue
            if node in visiting:
                _deny(D2CCode.D2C_DEPENDENCY_CYCLE)
            if node in completed:
                continue
            visiting.add(node)
            stack.append((node, True))
            for child in sorted(set(adjacency[node]), reverse=True):
                if child in visiting:
                    _deny(D2CCode.D2C_DEPENDENCY_CYCLE)
                if child not in completed:
                    stack.append((child, False))
    if longest_depth and max(longest_depth.values()) > 32:
        _deny(D2CCode.D2C_RESOURCE_LIMIT)
    sorted_keys = sorted(active)
    edgeobjs = [
        _edge_obj(e)
        for e in sorted(
            edges.values(),
            key=lambda e: (
                e.source_kind,
                e.source_namespace,
                e.source_id,
                e.source_version,
                e.relation_id,
                e.ordinal,
            ),
        )
    ]
    adapter_objects.sort(
        key=lambda v: (v["registry_kind"], v["namespace"], v["id"], v["version"])
    )
    edge_envelope = {
        "profile": "GA02-D2C-EDGES-1",
        "host_catalog_generation": x.host_catalog_generation,
        "edges": edgeobjs,
    }
    edge_digest = _digest("GA02-D2C-EDGES-1", edge_envelope)
    catalog_entries = [
        {
            "registry_kind": k[0],
            "namespace": k[1],
            "id": k[2],
            "version": k[3],
            "definition_type": v.definition_type,
            "definition_sha256": definition_hashes[k],
            "record_enabled": v.record_enabled,
            "intrinsic_enabled": v.intrinsic_enabled,
        }
        for k, v in sorted(records.items())
    ]
    catalog = {
        "profile": "GA02-D2C-CATALOG-2",
        "domain_id": x.domain_id,
        "domain_version": x.domain_version,
        "runtime_profile": x.runtime_profile,
        "manifest_sha256": x.manifest_sha256,
        "publisher_generation": x.source_generation,
        "host_catalog_generation": x.host_catalog_generation,
        "host_policy_id": x.host_policy_id,
        "host_policy_generation": x.host_policy_generation,
        "prompt_mode": x.prompt_mode,
        "rule_mode": x.rule_mode,
        "approved_core_schema_keys": [
            {"id": v.id, "version": v.version} for v in x.approved_core_schema_keys
        ],
        "registry_entries": catalog_entries,
        "adapter_entries": adapter_objects,
        "edge_digest": edge_digest,
    }
    catalog_digest = _digest("GA02-D2C-CATALOG-2", catalog)
    hashes = [
        {
            "registry_kind": k[0],
            "namespace": k[1],
            "id": k[2],
            "version": k[3],
            "definition_sha256": definition_hashes[k],
        }
        for k in sorted_keys
    ]
    closure = {
        "profile": "GA02-D2C-CLOSURE-1",
        "host_catalog_generation": x.host_catalog_generation,
        "manifest_sha256": x.manifest_sha256,
        "graph_completeness": "SUPPORTED_RELATIONS_ONLY",
        "operational_readiness": "NOT_ASSESSED",
        "seed_keys": [_key_obj(k) for k in sorted_keys],
        "dependency_keys": [_key_obj(k) for k in sorted_keys],
        "edges": edgeobjs,
        "definition_hashes": hashes,
        "adapter_evidence": adapter_objects,
    }
    if (
        owned.canonical_input_bytes
        + sum(len(_json(v)) for v in (edge_envelope, catalog, closure))
        > 2097152
    ):
        _deny(D2CCode.D2C_RESOURCE_LIMIT)
    closure_digest = _digest("GA02-D2C-CLOSURE-1", closure)
    return DiagnosticResolutionSnapshotV1(
        observation_role="UNTRUSTED_DIAGNOSTIC_ONLY",
        graph_completeness="SUPPORTED_RELATIONS_ONLY",
        operational_readiness="NOT_ASSESSED",
        seed_keys=tuple(sorted_keys),
        dependency_keys=tuple(sorted_keys),
        edge_occurrences=tuple(tuple(sorted(v.items())) for v in edgeobjs),
        definition_hashes=tuple((k, definition_hashes[k]) for k in sorted_keys),
        adapter_evidence=tuple(tuple(sorted(v.items())) for v in adapter_objects),
        edge_digest=edge_digest,
        host_catalog_digest=catalog_digest,
        closure_digest=closure_digest,
        unresolved_non_graph_metadata=True,
    )


def _resolve_untrusted_catalog_observation(
    input: DiagnosticCatalogInputV1,
) -> DiagnosticResolutionSnapshotV1:
    """The sole private C0 entry. Never yields a usable DomainBinding or permission."""
    try:
        owned = _admit_and_copy_diagnostic_input(input)
        return _resolve_owned_diagnostic_graph(owned)
    except D2CResolutionError:
        raise
    except Exception:  # noqa: BLE001 - hostile diagnostic data must fail closed
        raise D2CResolutionError(D2CCode.D2C_RESOLUTION_UNSTABLE) from None
