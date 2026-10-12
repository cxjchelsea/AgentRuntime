"""GA-02 D2-B: isolated metadata-only tests, never a trusted publisher."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from agent_core.domain_package_loader import (
    HostPackageRootIssuer,
    HostPublishedGeneration,
    LocalPackageLoader,
    TrustedPackageIdentity,
)
from agent_core.domain_registry_mapping import (
    D2BCode,
    D2BMappingError,
    InertAssetEvidenceV1,
    KindMappingPolicyV1,
    RegistryCatalogViewV1,
    RegistryMatchEvidenceV1,
    _map_untrusted_observation,
)
from runtime.contracts.enums import PlanningMode
from runtime.registries.action import ActionRegistry
from runtime.registries.base import RegistryKey
from runtime.registries.definitions import (
    ActionDefinition,
    DomainManifest,
    IntrusivenessLevel,
    SchemaDefinition,
    SchemaScope,
)
from runtime.registries.domain import DomainRegistry
from runtime.registries.errors import RegistryError, RegistryItemNotFoundError
from runtime.registries.schema import SchemaRegistry

DOMAIN = "inventory.reconcile"
VERSION = "1.0.0"
PROFILE = "GA02-D1-1"
pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="D2-A Linux-only"
)


def _asset(kind: str, ident: str, path: str, data: bytes, namespace: str = DOMAIN):
    return (
        {
            "kind": kind,
            "namespace": namespace,
            "id": ident,
            "version": VERSION,
            "sha256": hashlib.sha256(data).hexdigest(),
            "relative_path": path,
        },
        data,
    )


def _snapshot(tmp_path: Path, items):
    refs = sorted(
        (ref for ref, _ in items),
        key=lambda a: (
            a["kind"],
            a["namespace"],
            a["id"],
            a["version"],
            a["relative_path"],
        ),
    )
    for ref, data in items:
        target = tmp_path / ref["relative_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    unsigned = {
        "package_schema_version": "1",
        "domain_id": DOMAIN,
        "domain_version": VERSION,
        "name": "Inventory Reconciliation",
        "enabled": True,
        "runtime_compatibility": PROFILE,
        "asset_refs": refs,
    }
    digest = hashlib.sha256(
        json.dumps(
            unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    (tmp_path / "package.json").write_text(
        json.dumps({**unsigned, "manifest_digest": digest})
    )
    identity = TrustedPackageIdentity("generation-1", DOMAIN, VERSION, PROFILE, digest)
    issuer = HostPackageRootIssuer(
        (HostPublishedGeneration(identity, str(tmp_path), True),),
        publication_verifier=lambda record: (
            record.sealed is True and record.absolute_root == str(tmp_path)
        ),
    )  # Test-only; not a production trust root.
    with issuer.issue("generation-1") as lease:
        return LocalPackageLoader().load(lease, identity)


def _policy(s, mode="REGISTRY_MAPPING", approved=frozenset()):
    return KindMappingPolicyV1(
        "GA02-D2B-KIND-1",
        "test.host",
        "host-gen-1",
        DOMAIN,
        VERSION,
        PROFILE,
        s.expected_manifest_digest,
        s.generation_id,
        "INERT_ONLY",
        "INERT_ONLY",
        approved,
        mode,
    )


def _registries():
    domain = DomainRegistry()
    domain.register(
        DomainManifest(
            domain_id=DOMAIN,
            name="Inventory Reconciliation",
            version=VERSION,
            enabled=True,
            runtime_compatibility=PROFILE,
        ),
        namespace=DOMAIN,
    )
    action = ActionRegistry()
    action.register(
        ActionDefinition(
            action_id="stock.count",
            version=VERSION,
            category="inventory",
            description="count",
            intrusiveness_level=IntrusivenessLevel.LOW,
            requires_confirmation=False,
            required_capability=None,
            allowed_planning_modes=[PlanningMode.DETERMINISTIC],
        ),
        namespace=DOMAIN,
    )
    return domain, action


def test_d2b_p01_exact_action_non_authoritative(tmp_path):
    s = _snapshot(
        tmp_path, [_asset("action", "stock.count", "actions/count.txt", b"count")]
    )
    d, a = _registries()
    result = _map_untrusted_observation(
        s, policy=_policy(s), registries=RegistryCatalogViewV1(domain=d, action=a)
    )
    assert result.observation_role == "NON_AUTHORITATIVE_AT_READ"
    assert len(result.evidence) == 1
    assert isinstance(result.evidence[0], RegistryMatchEvidenceV1)
    assert result.evidence[0].observed_namespace == DOMAIN
    assert not hasattr(result, "trusted")
    assert not hasattr(result, "runnable")


def test_d2b_p02_core_schema_allowlist(tmp_path):
    s = _snapshot(
        tmp_path,
        [_asset("schema", "shared.schema", "schemas/shared.json", b"{}", "CORE")],
    )
    d, _ = _registries()
    schema = SchemaRegistry()
    schema.register(
        SchemaDefinition(
            schema_id="shared.schema",
            version=VERSION,
            scope=SchemaScope.CORE,
            namespace="CORE",
        ),
        namespace="CORE",
    )
    result = _map_untrusted_observation(
        s,
        policy=_policy(s, approved=frozenset({("shared.schema", VERSION)})),
        registries=RegistryCatalogViewV1(domain=d, schema=schema),
    )
    assert isinstance(result.evidence[0], RegistryMatchEvidenceV1)


def test_d2b_p03_inert_knowledge(tmp_path):
    s = _snapshot(
        tmp_path,
        [_asset("knowledge", "catalog.notes", "knowledge/notes.txt", b"notes")],
    )
    d, _ = _registries()
    result = _map_untrusted_observation(
        s, policy=_policy(s), registries=RegistryCatalogViewV1(domain=d)
    )
    assert isinstance(result.evidence[0], InertAssetEvidenceV1)


def test_d2b_p04_inspection_never_reads_registry(tmp_path):
    s = _snapshot(
        tmp_path, [_asset("action", "stock.count", "actions/count.txt", b"count")]
    )

    class Trap:
        def get(self, *args, **kwargs):
            raise AssertionError("registry must not be read")

    result = _map_untrusted_observation(
        s,
        policy=_policy(s, mode="INERT_INSPECTION"),
        registries=RegistryCatalogViewV1(domain=Trap(), action=Trap()),
    )
    assert result.observation_role == "INERT_INSPECTION_ONLY"
    assert isinstance(result.evidence[0], InertAssetEvidenceV1)


def test_d2b_n01_missing_domain_is_atomic(tmp_path):
    s = _snapshot(
        tmp_path, [_asset("action", "stock.count", "actions/count.txt", b"count")]
    )
    with pytest.raises(D2BMappingError) as exc:
        _map_untrusted_observation(
            s,
            policy=_policy(s),
            registries=RegistryCatalogViewV1(domain=DomainRegistry()),
        )
    assert exc.value.code is D2BCode.D2B_EXACT_DEPENDENCY_NOT_FOUND
    assert str(exc.value) == exc.value.code.value


def test_d2b_n02_wrong_generation_before_read(tmp_path):
    s = _snapshot(
        tmp_path, [_asset("action", "stock.count", "actions/count.txt", b"count")]
    )
    with pytest.raises(D2BMappingError) as exc:
        _map_untrusted_observation(
            s,
            policy=replace(_policy(s), expected_publication_generation_id="wrong"),
            registries=RegistryCatalogViewV1(),
        )
    assert exc.value.code is D2BCode.D2B_TRUSTED_CATALOG_INVALID


def test_d2b_n03_core_schema_needs_allowlist(tmp_path):
    s = _snapshot(
        tmp_path,
        [_asset("schema", "shared.schema", "schemas/shared.json", b"{}", "CORE")],
    )
    d, _ = _registries()
    with pytest.raises(D2BMappingError) as exc:
        _map_untrusted_observation(
            s, policy=_policy(s), registries=RegistryCatalogViewV1(domain=d)
        )
    assert exc.value.code is D2BCode.D2B_EXACT_NAMESPACE_MISMATCH


def test_d2b_n04_missing_registry_slot_fails_closed(tmp_path):
    s = _snapshot(
        tmp_path, [_asset("action", "stock.count", "actions/count.txt", b"count")]
    )
    d, _ = _registries()
    with pytest.raises(D2BMappingError) as exc:
        _map_untrusted_observation(
            s, policy=_policy(s), registries=RegistryCatalogViewV1(domain=d)
        )
    assert exc.value.code is D2BCode.D2B_TRUSTED_CATALOG_INVALID


def test_d2b_n05_no_public_trusted_entry():
    import agent_core.domain_registry_mapping as module

    assert not hasattr(module, "map_verified_package")
    assert not hasattr(module, "D2BTrustedAdmissionV1")


class _FakeRegistry:
    """Test-only hostile exact-read adapter. Never used in production."""

    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error
        self.get_calls = 0

    def get(self, item, version, *, namespace):
        self.get_calls += 1
        if self.error is not None:
            raise self.error
        return self.value


def _action_record():
    _, registry = _registries()
    return registry.get("stock.count", VERSION, namespace=DOMAIN)


def _call_action(tmp_path, *, action=None, domain=None, policy_change=None):
    s = _snapshot(
        tmp_path, [_asset("action", "stock.count", "actions/count.txt", b"count")]
    )
    d, a = _registries()
    if action is not None:
        a = action
    if domain is not None:
        d = domain
    p = _policy(s)
    if policy_change:
        p = replace(p, **policy_change)
    return _map_untrusted_observation(
        s, policy=p, registries=RegistryCatalogViewV1(domain=d, action=a)
    )


@pytest.mark.parametrize(
    ("policy_change", "expected"),
    [
        ({"profile": "UNKNOWN"}, D2BCode.D2B_TRUSTED_CATALOG_INVALID),
        ({"expected_manifest_digest": "0" * 64}, D2BCode.D2B_TRUSTED_CATALOG_INVALID),
        ({"admitted_domain_id": "other.domain"}, D2BCode.D2B_TRUSTED_CATALOG_INVALID),
        ({"runtime_profile": "other"}, D2BCode.D2B_TRUSTED_CATALOG_INVALID),
        ({"prompt_mode": "EVAL"}, D2BCode.D2B_TRUSTED_CATALOG_INVALID),
        ({"rule_mode": "EVAL"}, D2BCode.D2B_TRUSTED_CATALOG_INVALID),
        ({"admission_mode": "RUN"}, D2BCode.D2B_TRUSTED_CATALOG_INVALID),
        (
            {"approved_core_schema_keys": {("shared.schema", VERSION)}},
            D2BCode.D2B_TRUSTED_CATALOG_INVALID,
        ),
    ],
)
def test_d2b_n06_invalid_policy_fails_closed(tmp_path, policy_change, expected):
    with pytest.raises(D2BMappingError) as exc:
        _call_action(tmp_path, policy_change=policy_change)
    assert exc.value.code is expected


def test_d2b_n07_legacy_none_namespace_domain_is_not_fallback(tmp_path):
    d = DomainRegistry()
    d.register(
        DomainManifest(
            domain_id=DOMAIN,
            name="Inventory Reconciliation",
            version=VERSION,
            enabled=True,
            runtime_compatibility=PROFILE,
        )
    )
    with pytest.raises(D2BMappingError) as exc:
        _call_action(tmp_path, domain=d)
    assert exc.value.code is D2BCode.D2B_EXACT_DEPENDENCY_NOT_FOUND


@pytest.mark.parametrize(
    ("tamper", "code"),
    [
        ("wrong_key", D2BCode.D2B_REGISTRY_DEFINITION_MISMATCH),
        ("wrong_definition", D2BCode.D2B_REGISTRY_DEFINITION_MISMATCH),
        ("disabled_record", D2BCode.D2B_REGISTRY_DISABLED),
        ("disabled_definition", D2BCode.D2B_REGISTRY_DISABLED),
    ],
)
def test_d2b_n08_registry_mismatch_or_disabled(tmp_path, tamper, code):
    rec = _action_record()
    if tamper == "wrong_key":
        rec.key = RegistryKey("other.action", VERSION, DOMAIN)
    elif tamper == "wrong_definition":
        rec.definition = rec.definition.model_copy(update={"action_id": "other.action"})
    elif tamper == "disabled_record":
        rec.enabled = False
    else:
        rec.definition.enabled = False
    with pytest.raises(D2BMappingError) as exc:
        _call_action(tmp_path, action=_FakeRegistry(value=rec))
    assert exc.value.code is code


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (
            RegistryItemNotFoundError("secret path"),
            D2BCode.D2B_EXACT_DEPENDENCY_NOT_FOUND,
        ),
        (RegistryError("secret path"), D2BCode.D2B_REGISTRY_OBSERVATION_UNSTABLE),
        (RuntimeError("secret path"), D2BCode.D2B_REGISTRY_OBSERVATION_UNSTABLE),
    ],
)
def test_d2b_n09_registry_exceptions_are_redacted(tmp_path, error, code):
    with pytest.raises(D2BMappingError) as exc:
        _call_action(tmp_path, action=_FakeRegistry(error=error))
    assert exc.value.code is code
    assert str(exc.value) == code.value
    assert "secret" not in str(exc.value)


def test_d2b_n10_hostile_implementation_is_not_touched(tmp_path):
    class Trap:
        calls = 0

        def __call__(self):
            self.calls += 1
            raise AssertionError("execution")

        def __repr__(self):
            self.calls += 1
            raise AssertionError("repr")

        def __str__(self):
            self.calls += 1
            raise AssertionError("str")

    trap = Trap()
    rec = _action_record()
    rec.implementation_ref = trap
    result = _call_action(tmp_path, action=_FakeRegistry(value=rec))
    assert result.evidence[0].observation_role == "NON_AUTHORITATIVE_AT_READ"
    assert trap.calls == 0
    assert not hasattr(result.evidence[0], "implementation_ref")


def test_d2b_n11_no_partial_output_on_late_failure(tmp_path):
    s = _snapshot(
        tmp_path,
        [
            _asset("action", "stock.count", "actions/count.txt", b"count"),
            _asset("schema", "stock.schema", "schemas/stock.json", b"{}"),
        ],
    )
    d, a = _registries()
    with pytest.raises(D2BMappingError) as exc:
        _map_untrusted_observation(
            s,
            policy=_policy(s),
            registries=RegistryCatalogViewV1(
                domain=d, action=a, schema=SchemaRegistry()
            ),
        )
    assert exc.value.code is D2BCode.D2B_EXACT_DEPENDENCY_NOT_FOUND


def test_d2b_n12_schema_namespace_and_scope_are_strict(tmp_path):
    s = _snapshot(
        tmp_path,
        [_asset("schema", "shared.schema", "schemas/shared.json", b"{}", "CORE")],
    )
    d, _ = _registries()
    schema = SchemaRegistry()
    schema.register(
        SchemaDefinition(
            schema_id="shared.schema",
            version=VERSION,
            scope=SchemaScope.DOMAIN,
            namespace="CORE",
        ),
        namespace="CORE",
    )
    with pytest.raises(D2BMappingError) as exc:
        _map_untrusted_observation(
            s,
            policy=_policy(s, approved=frozenset({("shared.schema", VERSION)})),
            registries=RegistryCatalogViewV1(domain=d, schema=schema),
        )
    assert exc.value.code is D2BCode.D2B_EXACT_NAMESPACE_MISMATCH


def test_d2b_n13_no_live_objects_or_mutability_escape(tmp_path):
    result = _call_action(tmp_path)
    assert type(result.evidence) is tuple
    with pytest.raises(FrozenInstanceError):
        result.evidence[0].registry_kind = "tool"
    assert isinstance(result.evidence[0], RegistryMatchEvidenceV1)


def test_d2b_n14_missing_newer_version_does_not_fallback(tmp_path):
    rec = _action_record()
    rec.key = RegistryKey("stock.count", "2.0.0", DOMAIN)
    with pytest.raises(D2BMappingError) as exc:
        _call_action(tmp_path, action=_FakeRegistry(value=rec))
    assert exc.value.code is D2BCode.D2B_REGISTRY_DEFINITION_MISMATCH


def test_d2b_n15_no_registry_lookup_for_inert_inspection(tmp_path):
    s = _snapshot(
        tmp_path, [_asset("knowledge", "catalog.notes", "knowledge/n.txt", b"notes")]
    )
    spy = _FakeRegistry(error=RuntimeError("must not call"))
    output = _map_untrusted_observation(
        s,
        policy=_policy(s, mode="INERT_INSPECTION"),
        registries=RegistryCatalogViewV1(domain=spy, action=spy),
    )
    assert spy.get_calls == 0
    assert all(isinstance(e, InertAssetEvidenceV1) for e in output.evidence)
