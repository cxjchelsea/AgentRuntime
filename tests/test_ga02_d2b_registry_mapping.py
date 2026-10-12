"""GA-02 D2-B: isolated metadata-only tests, never a trusted publisher."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from agent_core.domain_package_loader import (
    HostPackageRootIssuer, HostPublishedGeneration, LocalPackageLoader,
    TrustedPackageIdentity,
)
from agent_core.domain_registry_mapping import (
    D2BCode, D2BMappingError, InertAssetEvidenceV1,
    KindMappingPolicyV1, RegistryCatalogViewV1, RegistryMatchEvidenceV1,
    _map_untrusted_observation,
)
from runtime.contracts.enums import PlanningMode
from runtime.registries.action import ActionRegistry
from runtime.registries.domain import DomainRegistry
from runtime.registries.schema import SchemaRegistry
from runtime.registries.definitions import (
    ActionDefinition, DomainManifest, IntrusivenessLevel, SchemaDefinition, SchemaScope,
)

DOMAIN = "inventory.reconcile"
VERSION = "1.0.0"
PROFILE = "GA02-D1-1"
pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="D2-A Linux-only")


def _asset(kind: str, ident: str, path: str, data: bytes, namespace: str = DOMAIN):
    return ({"kind": kind, "namespace": namespace, "id": ident, "version": VERSION,
             "sha256": hashlib.sha256(data).hexdigest(), "relative_path": path}, data)


def _snapshot(tmp_path: Path, items):
    refs = sorted((ref for ref, _ in items),
                  key=lambda a: (a["kind"], a["namespace"], a["id"], a["version"], a["relative_path"]))
    for ref, data in items:
        target = tmp_path / ref["relative_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    unsigned = {"package_schema_version": "1", "domain_id": DOMAIN, "domain_version": VERSION,
                "name": "Inventory Reconciliation", "enabled": True,
                "runtime_compatibility": PROFILE, "asset_refs": refs}
    digest = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=False).encode()).hexdigest()
    (tmp_path / "package.json").write_text(json.dumps({**unsigned, "manifest_digest": digest}))
    identity = TrustedPackageIdentity("generation-1", DOMAIN, VERSION, PROFILE, digest)
    issuer = HostPackageRootIssuer(
        (HostPublishedGeneration(identity, str(tmp_path), True),),
        publication_verifier=lambda record: record.sealed is True and record.absolute_root == str(tmp_path),
    )  # Test-only; not a production trust root.
    with issuer.issue("generation-1") as lease:
        return LocalPackageLoader().load(lease, identity)


def _policy(s, mode="REGISTRY_MAPPING", approved=frozenset()):
    return KindMappingPolicyV1(
        "GA02-D2B-KIND-1", "test.host", "host-gen-1", DOMAIN, VERSION, PROFILE,
        s.expected_manifest_digest, s.generation_id, "INERT_ONLY", "INERT_ONLY",
        approved, mode,
    )


def _registries():
    domain = DomainRegistry()
    domain.register(DomainManifest(domain_id=DOMAIN, name="Inventory Reconciliation",
                                   version=VERSION, enabled=True, runtime_compatibility=PROFILE),
                    namespace=DOMAIN)
    action = ActionRegistry()
    action.register(ActionDefinition(
        action_id="stock.count", version=VERSION, category="inventory", description="count",
        intrusiveness_level=IntrusivenessLevel.LOW, requires_confirmation=False,
        required_capability=None, allowed_planning_modes=[PlanningMode.DETERMINISTIC],
    ), namespace=DOMAIN)
    return domain, action


def test_d2b_p01_exact_action_non_authoritative(tmp_path):
    s = _snapshot(tmp_path, [_asset("action", "stock.count", "actions/count.txt", b"count")])
    d, a = _registries()
    result = _map_untrusted_observation(s, policy=_policy(s), registries=RegistryCatalogViewV1(domain=d, action=a))
    assert result.observation_role == "NON_AUTHORITATIVE_AT_READ"
    assert len(result.evidence) == 1
    assert isinstance(result.evidence[0], RegistryMatchEvidenceV1)
    assert result.evidence[0].observed_namespace == DOMAIN
    assert not hasattr(result, "trusted")
    assert not hasattr(result, "runnable")


def test_d2b_p02_core_schema_allowlist(tmp_path):
    s = _snapshot(tmp_path, [_asset("schema", "shared.schema", "schemas/shared.json", b"{}", "CORE")])
    d, _ = _registries()
    schema = SchemaRegistry()
    schema.register(SchemaDefinition(schema_id="shared.schema", version=VERSION,
                                    scope=SchemaScope.CORE, namespace="CORE"), namespace="CORE")
    result = _map_untrusted_observation(s, policy=_policy(s, approved=frozenset({("shared.schema", VERSION)})),
                                       registries=RegistryCatalogViewV1(domain=d, schema=schema))
    assert isinstance(result.evidence[0], RegistryMatchEvidenceV1)


def test_d2b_p03_inert_knowledge(tmp_path):
    s = _snapshot(tmp_path, [_asset("knowledge", "catalog.notes", "knowledge/notes.txt", b"notes")])
    d, _ = _registries()
    result = _map_untrusted_observation(s, policy=_policy(s), registries=RegistryCatalogViewV1(domain=d))
    assert isinstance(result.evidence[0], InertAssetEvidenceV1)


def test_d2b_p04_inspection_never_reads_registry(tmp_path):
    s = _snapshot(tmp_path, [_asset("action", "stock.count", "actions/count.txt", b"count")])
    class Trap:
        def get(self, *args, **kwargs):
            raise AssertionError("registry must not be read")
    result = _map_untrusted_observation(
        s, policy=_policy(s, mode="INERT_INSPECTION"),
        registries=RegistryCatalogViewV1(domain=Trap(), action=Trap()))
    assert result.observation_role == "INERT_INSPECTION_ONLY"
    assert isinstance(result.evidence[0], InertAssetEvidenceV1)


def test_d2b_n01_missing_domain_is_atomic(tmp_path):
    s = _snapshot(tmp_path, [_asset("action", "stock.count", "actions/count.txt", b"count")])
    with pytest.raises(D2BMappingError) as exc:
        _map_untrusted_observation(s, policy=_policy(s), registries=RegistryCatalogViewV1(domain=DomainRegistry()))
    assert exc.value.code is D2BCode.D2B_EXACT_DEPENDENCY_NOT_FOUND
    assert str(exc.value) == exc.value.code.value


def test_d2b_n02_wrong_generation_before_read(tmp_path):
    s = _snapshot(tmp_path, [_asset("action", "stock.count", "actions/count.txt", b"count")])
    from dataclasses import replace
    with pytest.raises(D2BMappingError) as exc:
        _map_untrusted_observation(s, policy=replace(_policy(s), expected_publication_generation_id="wrong"),
                                   registries=RegistryCatalogViewV1())
    assert exc.value.code is D2BCode.D2B_TRUSTED_CATALOG_INVALID


def test_d2b_n03_core_schema_needs_allowlist(tmp_path):
    s = _snapshot(tmp_path, [_asset("schema", "shared.schema", "schemas/shared.json", b"{}", "CORE")])
    d, _ = _registries()
    with pytest.raises(D2BMappingError) as exc:
        _map_untrusted_observation(s, policy=_policy(s), registries=RegistryCatalogViewV1(domain=d))
    assert exc.value.code is D2BCode.D2B_EXACT_NAMESPACE_MISMATCH


def test_d2b_n04_missing_registry_slot_fails_closed(tmp_path):
    s = _snapshot(tmp_path, [_asset("action", "stock.count", "actions/count.txt", b"count")])
    d, _ = _registries()
    with pytest.raises(D2BMappingError) as exc:
        _map_untrusted_observation(s, policy=_policy(s), registries=RegistryCatalogViewV1(domain=d))
    assert exc.value.code is D2BCode.D2B_TRUSTED_CATALOG_INVALID


def test_d2b_n05_no_public_trusted_entry():
    import agent_core.domain_registry_mapping as module
    assert not hasattr(module, "map_verified_package")
    assert not hasattr(module, "D2BTrustedAdmissionV1")
