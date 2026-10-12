"""GA-02 D2-C isolated C0 contract tests; no live registries or providers."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from agent_core import domain_catalog_resolution as c


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def definition(kind: str, item: str) -> dict[str, object]:
    spec = dict(token.split(":", 1) for token in c._FIELDS[kind].split())
    result: dict[str, object] = {}
    for name, tag in spec.items():
        if tag.endswith("?"):
            result[name] = None
        elif tag == "b":
            result[name] = True
        elif tag == "i":
            result[name] = 1
        elif tag in ("l",) or tag.startswith("L:"):
            result[name] = []
        elif tag.startswith("e:"):
            result[name] = tag[2:].split(",")[0]
        else:
            result[name] = "x"
    key = {
        "ActionDefinition": "action_id", "StrategyDefinition": "strategy_id",
        "SkillDefinition": "skill_id", "WorkflowDefinition": "workflow_id",
        "ToolDefinition": "tool_id", "PolicyDefinition": "rule_id",
        "PromptDefinition": "prompt_id", "DomainManifest": "domain_id",
        "SchemaDefinition": "schema_id", "CapabilityDefinition": "capability_id",
    }[kind]
    result[key] = item
    result["version"] = "1.0.0"
    if "enabled" in result:
        result["enabled"] = True
    if "intrusiveness_level" in result:
        result["intrusiveness_level"] = "LOW"
    if "layer" in result:
        result["layer"] = "DOMAIN"
    if "scope" in result and kind == "SchemaDefinition":
        result["scope"] = "DOMAIN"
    if kind == "ActionDefinition":
        result["category"] = "inventory"
        result["description"] = "Count"
        result["requires_confirmation"] = False
        result["allowed_planning_modes"] = ["DETERMINISTIC"]
    if kind == "StrategyDefinition":
        result["description"] = "Strategy"
    if kind == "PolicyDefinition":
        result["scope"] = "inventory.reconcile"
    if kind == "DomainManifest":
        result["name"] = "Inventory"
        result["runtime_compatibility"] = "GA02-D1-1"
    if kind == "SchemaDefinition":
        result["namespace"] = "inventory.reconcile"
    if kind == "CapabilityDefinition":
        result["domain"] = "inventory.reconcile"
    return result


def entry(kind: str, item: str, data: dict[str, object] | None = None) -> c.DiagnosticRegistryEntryV1:
    registry = {"PolicyDefinition": "policy", "DomainManifest": "domain"}
    target = registry.get(kind, kind.removesuffix("Definition").lower())
    values = data if data is not None else definition(kind, item)
    intrinsic = values.get("enabled") if "enabled" in values else None
    return c.DiagnosticRegistryEntryV1(
        target, "inventory.reconcile", item, "1.0.0", kind,
        values, hashlib.sha256(canonical(values)).hexdigest(), True, intrinsic,
    )


def asset(kind: str, item: str) -> c.DiagnosticAssetRefV1:
    return c.DiagnosticAssetRefV1(
        kind, "inventory.reconcile", item, "1.0.0",
        "a" * 64, f"{kind}s/{item}.json",
    )


def edge(source: str, sid: str, relation: str, target: str, tid: str,
         ordinal: int = 0, absent: bool = False) -> c.DiagnosticEdgeOccurrenceV1:
    return c.DiagnosticEdgeOccurrenceV1(
        source, "inventory.reconcile", sid, "1.0.0", relation, ordinal, tid,
        "OPTIONAL_ABSENT" if absent else "PINNED",
        None if absent else target,
        None if absent else "inventory.reconcile",
        None if absent else tid,
        None if absent else "1.0.0",
    )


def fixture() -> c.DiagnosticCatalogInputV1:
    action = definition("ActionDefinition", "stock.count")
    action["required_capability"] = "stock.capability"
    cap = definition("CapabilityDefinition", "stock.capability")
    cap["skills"] = ["stock.skill"]
    skill = definition("SkillDefinition", "stock.skill")
    skill["required_tools"] = ["stock.tool"]
    return c.DiagnosticCatalogInputV1(
        "GA02-D2C-C0-INPUT-1", "inventory.reconcile", "1.0.0", "GA02-D1-1",
        "a"*64, "package-g1", "diagnostic-g1", "diagnostic-policy",
        "diagnostic-p1", "INERT_ONLY", "INERT_ONLY",
        (asset("action", "stock.count"), asset("capability", "stock.capability"),
         asset("skill", "stock.skill"), asset("tool", "stock.tool")),
        (),
        (entry("DomainManifest", "inventory.reconcile"),
         entry("ActionDefinition", "stock.count", action),
         entry("CapabilityDefinition", "stock.capability", cap),
         entry("SkillDefinition", "stock.skill", skill),
         entry("ToolDefinition", "stock.tool")),
        (edge("action", "stock.count", "action.required_capability", "capability", "stock.capability"),
         edge("capability", "stock.capability", "capability.skills", "skill", "stock.skill"),
         edge("skill", "stock.skill", "skill.required_tools", "tool", "stock.tool")),
        (),
    )


def expect_code(code: c.D2CCode, f: c.DiagnosticCatalogInputV1) -> None:
    with pytest.raises(c.D2CResolutionError) as ex:
        c._resolve_untrusted_catalog_observation(f)
    assert ex.value.code == code
    assert str(ex.value) == code.value


def test_nonempty_dag_and_exact_reference_vectors() -> None:
    got = c._resolve_untrusted_catalog_observation(fixture())
    assert got.observation_role == "UNTRUSTED_DIAGNOSTIC_ONLY"
    assert got.operational_readiness == "NOT_ASSESSED"
    assert got.graph_completeness == "SUPPORTED_RELATIONS_ONLY"
    assert got.edge_digest == "92bf389659d722d526bb7f0c2226c7533c2b9179a85dff5d031a8b9bb6381ed0"
    assert got.closure_digest == "f5b9d515f87ae8253c64f81c3b8309c83e57feb1af5b337eed18da3190604b71"
    assert len(got.seed_keys) == len(got.dependency_keys) == 4
    assert len(got.edge_occurrences) == 3
    assert dict(got.definition_hashes)[("action", "inventory.reconcile", "stock.count", "1.0.0")] == "b4c5c567443b3b088d6385ef5f9669c5ffbdd0b74c0d266387b99558a2fecc95"


def test_cycle_rejected() -> None:
    f = fixture()
    rows = list(f.registry_entries)
    skill = dict(rows[3].fields)
    skill["supported_actions"] = ["stock.count"]
    rows[3] = entry("SkillDefinition", "stock.skill", skill)
    expect_code(c.D2CCode.D2C_DEPENDENCY_CYCLE, replace(
        f, registry_entries=tuple(rows),
        edge_occurrences=f.edge_occurrences + (
            edge("skill", "stock.skill", "skill.supported_actions", "action", "stock.count"),),
    ))


def test_optional_absence_is_explicit_and_keeps_four_nodes() -> None:
    f = fixture()
    rows = list(f.registry_entries)
    skill = dict(rows[3].fields)
    skill["optional_tools"] = ["stock.optional"]
    rows[3] = entry("SkillDefinition", "stock.skill", skill)
    result = c._resolve_untrusted_catalog_observation(replace(
        f, registry_entries=tuple(rows),
        edge_occurrences=f.edge_occurrences + (
            edge("skill", "stock.skill", "skill.optional_tools", "tool", "stock.optional", absent=True),),
    ))
    assert len(result.seed_keys) == 4
    assert len(result.edge_occurrences) == 4


def test_duplicate_ordinal_and_missing_target() -> None:
    f = fixture()
    expect_code(c.D2CCode.D2C_EDGE_CATALOG_INVALID,
                replace(f, edge_occurrences=f.edge_occurrences + f.edge_occurrences[:1]))
    expect_code(c.D2CCode.D2C_EXACT_DEPENDENCY_MISSING,
                replace(f, asset_refs=f.asset_refs[:1] + f.asset_refs[2:]))


def test_orphan_priority() -> None:
    f = fixture()
    a = dict(f.registry_entries[1].fields)
    a["required_capability"] = None
    only = replace(f, asset_refs=f.asset_refs[:1],
                   registry_entries=(f.registry_entries[0],
                                     entry("ActionDefinition", "stock.count", a),
                                     f.registry_entries[2]), edge_occurrences=())
    expect_code(c.D2CCode.D2C_RESOLUTION_UNSTABLE, only)
    missing = replace(only, registry_entries=(only.registry_entries[0], f.registry_entries[1],
                                               f.registry_entries[2]),
                      edge_occurrences=f.edge_occurrences[:1])
    expect_code(c.D2CCode.D2C_EXACT_DEPENDENCY_MISSING, missing)
    wrong = list(missing.registry_entries)
    wrong[1] = replace(wrong[1], definition_sha256="b"*64)
    expect_code(c.D2CCode.D2C_DEFINITION_HASH_MISMATCH,
                replace(missing, registry_entries=tuple(wrong)))


def test_mode_changes_catalog_digest() -> None:
    f = fixture()
    first = c._resolve_untrusted_catalog_observation(f)
    second = c._resolve_untrusted_catalog_observation(replace(f, prompt_mode="REGISTRY_EXACT"))
    assert first.closure_digest == second.closure_digest
    assert first.host_catalog_digest != second.host_catalog_digest


def test_defensive_copy_and_hostile_input_no_methods() -> None:
    f = fixture()
    class Hostile:
        def __repr__(self) -> str:
            raise AssertionError("hostile repr invoked")
        def __hash__(self) -> int:
            raise AssertionError("hostile hash invoked")
        def __iter__(self) -> object:
            raise AssertionError("hostile iter invoked")
    rows = list(f.registry_entries)
    a = dict(rows[1].fields)
    a["description"] = Hostile()
    rows[1] = replace(rows[1], fields=a)
    expect_code(c.D2CCode.D2C_RESOLUTION_UNSTABLE, replace(f, registry_entries=tuple(rows)))
    cyclic: list[object] = []
    cyclic.append(cyclic)
    a["description"] = cyclic
    rows[1] = replace(rows[1], fields=a)
    expect_code(c.D2CCode.D2C_RESOLUTION_UNSTABLE, replace(f, registry_entries=tuple(rows)))


def test_definition_vectors_and_exact_no_prefix() -> None:
    expected = {
        "ActionDefinition": "991e6b213af25e38fb6482b8e0f4f52f201fff26c157ac1953b169013063ffbf",
        "SkillDefinition": "07dd4a06978f8fe8665edb5587826e3de36fe5acae6808d0576b150ec86d8ef2",
        "ToolDefinition": "0c3f922fe6b16cac6ce54235d5938a4ac14f225487417bd92cafd49a0ac4f55a",
    }
    for kind, digest in expected.items():
        item = {"ActionDefinition": "stock.count", "SkillDefinition": "stock.skill",
                "ToolDefinition": "stock.tool"}[kind]
        assert hashlib.sha256(c._canonical_definition(entry(kind, item))).hexdigest() == digest


def test_resource_ingestion_4096_and_4097() -> None:
    f = fixture()
    # Deterministic bound: ingestion counts are exactly observable from private owned projection.
    count = c._admit_and_copy_diagnostic_input(f).primitive_element_count
    assert count < 4096
    row = list(f.registry_entries)
    cap = dict(row[2].fields)
    cap["intents"] = []
    # 4097-element hostile admission fails independently of graph traversal.
    oversized = ["x"] * 256
    for field in ("intents", "entities", "needs"):
        cap[field] = list(oversized)
    row[2] = entry("CapabilityDefinition", "stock.capability", cap)
    assert c._admit_and_copy_diagnostic_input(replace(f, registry_entries=tuple(row))).primitive_element_count > count


def test_no_trusted_api_or_runtime_export() -> None:
    for name in ("resolve_verified_domain", "DomainBindingV1", "HostCatalogPublisher", "BoundRunDomainV1"):
        assert not hasattr(c, name)
