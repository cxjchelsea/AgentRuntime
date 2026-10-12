"""GA-02 D2-B isolated, non-authoritative registry metadata observation.

This module has NO trusted host admission, binding, execution, or production consumer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from agent_core.domain_descriptor import (
    PROFILE,
    PackageDescriptorError,
    descriptor_to_domain_manifest,
)
from agent_core.domain_package_loader import VerifiedPackageSnapshotV1
from runtime.registries.base import RegistryKey
from runtime.registries.definitions import (
    ActionDefinition,
    CapabilityDefinition,
    DomainManifest,
    PolicyDefinition,
    PromptDefinition,
    SchemaDefinition,
    SchemaScope,
    SkillDefinition,
    StrategyDefinition,
    ToolDefinition,
    WorkflowDefinition,
)
from runtime.registries.errors import RegistryError, RegistryItemNotFoundError

_TYPES: dict[str, tuple[str, type[Any], str, bool]] = {
    "action": ("action", ActionDefinition, "action_id", True),
    "strategy": ("strategy", StrategyDefinition, "strategy_id", True),
    "skill": ("skill", SkillDefinition, "skill_id", True),
    "tool": ("tool", ToolDefinition, "tool_id", True),
    "workflow": ("workflow", WorkflowDefinition, "workflow_id", True),
    "capability": ("capability", CapabilityDefinition, "capability_id", False),
    "prompt": ("prompt", PromptDefinition, "prompt_id", False),
    "rule": ("policy", PolicyDefinition, "rule_id", True),
    "schema": ("schema", SchemaDefinition, "schema_id", False),
}
_INERT = frozenset({"knowledge", "state", "eval"})
_SHA = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_ID = re.compile(r"[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*\Z", re.ASCII)
_VERSION = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z", re.ASCII
)


class D2BCode(str, Enum):
    D2B_TRUSTED_CATALOG_INVALID = "D2B_TRUSTED_CATALOG_INVALID"
    D2B_UNKNOWN_KIND_OR_POLICY = "D2B_UNKNOWN_KIND_OR_POLICY"
    D2B_EXACT_NAMESPACE_MISMATCH = "D2B_EXACT_NAMESPACE_MISMATCH"
    D2B_UNSUPPORTED_ACTIVE_KIND = "D2B_UNSUPPORTED_ACTIVE_KIND"
    D2B_EXACT_DEPENDENCY_NOT_FOUND = "D2B_EXACT_DEPENDENCY_NOT_FOUND"
    D2B_REGISTRY_DEFINITION_MISMATCH = "D2B_REGISTRY_DEFINITION_MISMATCH"
    D2B_REGISTRY_DISABLED = "D2B_REGISTRY_DISABLED"
    D2B_REGISTRY_OBSERVATION_UNSTABLE = "D2B_REGISTRY_OBSERVATION_UNSTABLE"


class D2BMappingError(ValueError):
    def __init__(self, code: D2BCode) -> None:
        self.code = code
        super().__init__(code.value)


def _deny(code: D2BCode) -> None:
    raise D2BMappingError(code)


@dataclass(frozen=True, slots=True)
class KindMappingPolicyV1:
    profile: str
    host_policy_id: str
    host_policy_generation: str
    admitted_domain_id: str
    admitted_domain_version: str
    runtime_profile: str
    expected_manifest_digest: str
    expected_publication_generation_id: str
    prompt_mode: str
    rule_mode: str
    approved_core_schema_keys: frozenset[tuple[str, str]]
    admission_mode: str


@dataclass(frozen=True, slots=True)
class RegistryCatalogViewV1:
    domain: Any = None
    action: Any = None
    strategy: Any = None
    skill: Any = None
    tool: Any = None
    workflow: Any = None
    capability: Any = None
    prompt: Any = None
    policy: Any = None
    schema: Any = None


@dataclass(frozen=True, slots=True)
class AssetClassificationV1:
    kind: str
    namespace: str
    id: str
    version: str
    classification: str


@dataclass(frozen=True, slots=True)
class RegistryMatchEvidenceV1:
    asset: AssetClassificationV1
    registry_kind: str
    observed_id: str
    observed_version: str
    observed_namespace: str
    definition_type: str
    record_enabled: bool
    definition_enabled: bool | None
    observation_role: str = "NON_AUTHORITATIVE_AT_READ"


@dataclass(frozen=True, slots=True)
class InertAssetEvidenceV1:
    asset: AssetClassificationV1
    sha256: str
    relative_path: str
    observation_role: str = "INERT_INSPECTION_ONLY"


@dataclass(frozen=True, slots=True)
class RegistryKindMappingSnapshotV1:
    host_policy_id: str
    host_policy_generation: str
    domain_id: str
    domain_version: str
    publication_generation_id: str
    admission_mode: str
    observation_role: str
    evidence: tuple[RegistryMatchEvidenceV1 | InertAssetEvidenceV1, ...]


def _valid_policy(policy: object, snapshot: object, registries: object) -> bool:
    if (
        type(policy) is not KindMappingPolicyV1
        or type(snapshot) is not VerifiedPackageSnapshotV1
        or type(registries) is not RegistryCatalogViewV1
    ):
        return False
    p = policy
    d = snapshot.descriptor
    if type(p.approved_core_schema_keys) is not frozenset or not all(
        type(x) is tuple
        and len(x) == 2
        and type(x[0]) is str
        and bool(_ID.fullmatch(x[0]))
        and type(x[1]) is str
        and bool(_VERSION.fullmatch(x[1]))
        for x in p.approved_core_schema_keys
    ):
        return False
    if not all(
        type(v) is str and bool(v)
        for v in (
            p.host_policy_id,
            p.host_policy_generation,
            p.expected_publication_generation_id,
        )
    ):
        return False
    return (
        p.profile == "GA02-D2B-KIND-1"
        and p.runtime_profile == PROFILE
        and p.prompt_mode in {"REGISTRY_EXACT", "INERT_ONLY"}
        and p.rule_mode in {"REGISTRY_EXACT", "INERT_ONLY"}
        and p.admission_mode in {"INERT_INSPECTION", "REGISTRY_MAPPING"}
        and type(d.manifest_digest) is str
        and type(p.expected_manifest_digest) is str
        and bool(_SHA.fullmatch(p.expected_manifest_digest))
        and p.admitted_domain_id == d.domain_id
        and p.admitted_domain_version == d.domain_version
        and p.runtime_profile == d.runtime_compatibility
        and p.expected_manifest_digest
        == d.manifest_digest
        == snapshot.expected_manifest_digest
        and p.expected_publication_generation_id == snapshot.generation_id
    )


def _read(registry: Any, item: str, version: str, namespace: str) -> Any:
    if registry is None:
        _deny(D2BCode.D2B_TRUSTED_CATALOG_INVALID)
    try:
        return registry.get(item, version, namespace=namespace)
    except RegistryItemNotFoundError:
        raise D2BMappingError(D2BCode.D2B_EXACT_DEPENDENCY_NOT_FOUND) from None
    except RegistryError:
        raise D2BMappingError(D2BCode.D2B_REGISTRY_OBSERVATION_UNSTABLE) from None
    except Exception:  # noqa: BLE001 - untrusted Registry read must fail closed
        raise D2BMappingError(D2BCode.D2B_REGISTRY_OBSERVATION_UNSTABLE) from None


def _check_record(
    record: Any,
    item: str,
    version: str,
    namespace: str,
    definition_type: type[Any],
    id_field: str,
    intrinsic: bool,
) -> tuple[bool, bool | None]:
    try:
        key, definition = record.key, record.definition
        if type(key) is not RegistryKey or (
            key.item_id,
            key.version,
            key.namespace,
        ) != (item, version, namespace):
            _deny(D2BCode.D2B_REGISTRY_DEFINITION_MISMATCH)
        if (
            type(definition) is not definition_type
            or getattr(definition, id_field) != item
            or definition.version != version
        ):
            _deny(D2BCode.D2B_REGISTRY_DEFINITION_MISMATCH)
        enabled = record.enabled
        intrinsic_enabled = definition.enabled if intrinsic else None
        if type(enabled) is not bool or (
            intrinsic and type(intrinsic_enabled) is not bool
        ):
            _deny(D2BCode.D2B_REGISTRY_OBSERVATION_UNSTABLE)
        if enabled is not True or (intrinsic and intrinsic_enabled is not True):
            _deny(D2BCode.D2B_REGISTRY_DISABLED)
        return True, intrinsic_enabled
    except D2BMappingError:
        raise
    except Exception:  # noqa: BLE001 - untrusted Registry read must fail closed
        raise D2BMappingError(D2BCode.D2B_REGISTRY_OBSERVATION_UNSTABLE) from None


def _map_untrusted_observation(
    snapshot: VerifiedPackageSnapshotV1,
    *,
    policy: KindMappingPolicyV1,
    registries: RegistryCatalogViewV1,
) -> RegistryKindMappingSnapshotV1:
    """Pure metadata read. The returned object is NEVER trusted admission."""
    if not _valid_policy(policy, snapshot, registries):
        _deny(D2BCode.D2B_TRUSTED_CATALOG_INVALID)
    try:
        descriptor_to_domain_manifest(snapshot.descriptor)
        d = snapshot.descriptor
        if (
            type(snapshot.assets) is not tuple
            or tuple(a.ref for a in snapshot.assets) != d.asset_refs
        ):
            _deny(D2BCode.D2B_TRUSTED_CATALOG_INVALID)
    except (PackageDescriptorError, AttributeError, TypeError, ValueError):
        _deny(D2BCode.D2B_TRUSTED_CATALOG_INVALID)

    if policy.admission_mode == "REGISTRY_MAPPING":
        if d.enabled is not True:
            _deny(D2BCode.D2B_REGISTRY_DISABLED)
        domain_rec = _read(
            registries.domain, d.domain_id, d.domain_version, d.domain_id
        )
        _check_record(
            domain_rec,
            d.domain_id,
            d.domain_version,
            d.domain_id,
            DomainManifest,
            "domain_id",
            True,
        )
        try:
            if domain_rec.definition.runtime_compatibility != d.runtime_compatibility:
                _deny(D2BCode.D2B_REGISTRY_DEFINITION_MISMATCH)
        except D2BMappingError:
            raise
        except Exception:  # noqa: BLE001 - untrusted Registry read must fail closed
            raise D2BMappingError(D2BCode.D2B_REGISTRY_OBSERVATION_UNSTABLE) from None

    output: list[RegistryMatchEvidenceV1 | InertAssetEvidenceV1] = []
    for asset_ref in d.asset_refs:
        kind = asset_ref.kind
        if kind not in _TYPES and kind not in _INERT:
            _deny(D2BCode.D2B_UNKNOWN_KIND_OR_POLICY)
        ns = asset_ref.namespace
        if ns != d.domain_id and not (kind == "schema" and ns == "CORE"):
            _deny(D2BCode.D2B_EXACT_NAMESPACE_MISMATCH)
        if (
            ns == "CORE"
            and (asset_ref.id, asset_ref.version)
            not in policy.approved_core_schema_keys
        ):
            _deny(D2BCode.D2B_EXACT_NAMESPACE_MISMATCH)
        inactive = (
            policy.admission_mode == "INERT_INSPECTION"
            or kind in _INERT
            or (kind == "prompt" and policy.prompt_mode == "INERT_ONLY")
            or (kind == "rule" and policy.rule_mode == "INERT_ONLY")
        )
        classification = AssetClassificationV1(
            kind,
            ns,
            asset_ref.id,
            asset_ref.version,
            "INERT_ONLY" if inactive else "REGISTRY_EXACT",
        )
        if inactive:
            output.append(
                InertAssetEvidenceV1(
                    classification, asset_ref.sha256, asset_ref.relative_path
                )
            )
            continue
        registry_name, expected, id_field, intrinsic = _TYPES[kind]
        record = _read(
            getattr(registries, registry_name), asset_ref.id, asset_ref.version, ns
        )
        enabled, definition_enabled = _check_record(
            record, asset_ref.id, asset_ref.version, ns, expected, id_field, intrinsic
        )
        if kind == "schema":
            try:
                definition = record.definition
                scope = SchemaScope.CORE if ns == "CORE" else SchemaScope.DOMAIN
                if definition.namespace != ns or definition.scope is not scope:
                    _deny(D2BCode.D2B_EXACT_NAMESPACE_MISMATCH)
            except D2BMappingError:
                raise
            except Exception:  # noqa: BLE001 - untrusted Registry read must fail closed
                raise D2BMappingError(D2BCode.D2B_REGISTRY_OBSERVATION_UNSTABLE) from None
        output.append(
            RegistryMatchEvidenceV1(
                classification,
                registry_name,
                asset_ref.id,
                asset_ref.version,
                ns,
                expected.__name__,
                enabled,
                definition_enabled,
            )
        )
    return RegistryKindMappingSnapshotV1(
        policy.host_policy_id,
        policy.host_policy_generation,
        d.domain_id,
        d.domain_version,
        snapshot.generation_id,
        policy.admission_mode,
        (
            "INERT_INSPECTION_ONLY"
            if policy.admission_mode == "INERT_INSPECTION"
            else "NON_AUTHORITATIVE_AT_READ"
        ),
        tuple(output),
    )
