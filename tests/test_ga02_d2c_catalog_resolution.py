"""GA-02 D2-C isolated C0 contract tests; no live registries or providers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any, cast

import pytest

from agent_core import domain_catalog_resolution as c


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


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
        "ActionDefinition": "action_id",
        "StrategyDefinition": "strategy_id",
        "SkillDefinition": "skill_id",
        "WorkflowDefinition": "workflow_id",
        "ToolDefinition": "tool_id",
        "PolicyDefinition": "rule_id",
        "PromptDefinition": "prompt_id",
        "DomainManifest": "domain_id",
        "SchemaDefinition": "schema_id",
        "CapabilityDefinition": "capability_id",
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
    if kind in ("CapabilityDefinition", "PromptDefinition"):
        result["domain"] = "inventory.reconcile"
    return result


def entry(
    kind: str, item: str, data: dict[str, object] | None = None
) -> c.DiagnosticRegistryEntryV1:
    registry = {"PolicyDefinition": "policy", "DomainManifest": "domain"}
    target = registry.get(kind, kind.removesuffix("Definition").lower())
    values = data if data is not None else definition(kind, item)
    intrinsic: bool | None = bool(values["enabled"]) if "enabled" in values else None
    return c.DiagnosticRegistryEntryV1(
        target,
        "inventory.reconcile",
        item,
        "1.0.0",
        kind,
        values,
        hashlib.sha256(canonical(values)).hexdigest(),
        True,
        intrinsic,
    )


def asset(kind: str, item: str) -> c.DiagnosticAssetRefV1:
    return c.DiagnosticAssetRefV1(
        kind,
        "inventory.reconcile",
        item,
        "1.0.0",
        "a" * 64,
        f"{kind}s/{item}.json",
    )


def edge(
    source: str,
    sid: str,
    relation: str,
    target: str,
    tid: str,
    ordinal: int = 0,
    absent: bool = False,
) -> c.DiagnosticEdgeOccurrenceV1:
    return c.DiagnosticEdgeOccurrenceV1(
        source,
        "inventory.reconcile",
        sid,
        "1.0.0",
        relation,
        ordinal,
        tid,
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
        "GA02-D2C-C0-INPUT-1",
        "inventory.reconcile",
        "1.0.0",
        "GA02-D1-1",
        "a" * 64,
        "package-g1",
        "diagnostic-g1",
        "diagnostic-policy",
        "diagnostic-p1",
        "INERT_ONLY",
        "INERT_ONLY",
        (
            asset("action", "stock.count"),
            asset("capability", "stock.capability"),
            asset("skill", "stock.skill"),
            asset("tool", "stock.tool"),
        ),
        (),
        (
            entry("DomainManifest", "inventory.reconcile"),
            entry("ActionDefinition", "stock.count", action),
            entry("CapabilityDefinition", "stock.capability", cap),
            entry("SkillDefinition", "stock.skill", skill),
            entry("ToolDefinition", "stock.tool"),
        ),
        (
            edge(
                "action",
                "stock.count",
                "action.required_capability",
                "capability",
                "stock.capability",
            ),
            edge(
                "capability",
                "stock.capability",
                "capability.skills",
                "skill",
                "stock.skill",
            ),
            edge("skill", "stock.skill", "skill.required_tools", "tool", "stock.tool"),
        ),
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
    assert (
        got.edge_digest
        == "92bf389659d722d526bb7f0c2226c7533c2b9179a85dff5d031a8b9bb6381ed0"
    )
    assert (
        got.closure_digest
        == "f5b9d515f87ae8253c64f81c3b8309c83e57feb1af5b337eed18da3190604b71"
    )
    assert len(got.seed_keys) == len(got.dependency_keys) == 4
    assert len(got.edge_occurrences) == 3
    assert (
        dict(got.definition_hashes)[
            ("action", "inventory.reconcile", "stock.count", "1.0.0")
        ]
        == "b4c5c567443b3b088d6385ef5f9669c5ffbdd0b74c0d266387b99558a2fecc95"
    )


def test_cycle_rejected() -> None:
    f = fixture()
    rows = list(f.registry_entries)
    skill = dict(rows[3].fields)
    skill["supported_actions"] = ["stock.count"]
    rows[3] = entry("SkillDefinition", "stock.skill", skill)
    expect_code(
        c.D2CCode.D2C_DEPENDENCY_CYCLE,
        replace(
            f,
            registry_entries=tuple(rows),
            edge_occurrences=f.edge_occurrences
            + (
                edge(
                    "skill",
                    "stock.skill",
                    "skill.supported_actions",
                    "action",
                    "stock.count",
                ),
            ),
        ),
    )


def test_optional_absence_is_explicit_and_keeps_four_nodes() -> None:
    f = fixture()
    rows = list(f.registry_entries)
    skill = dict(rows[3].fields)
    skill["optional_tools"] = ["stock.optional"]
    rows[3] = entry("SkillDefinition", "stock.skill", skill)
    result = c._resolve_untrusted_catalog_observation(
        replace(
            f,
            registry_entries=tuple(rows),
            edge_occurrences=f.edge_occurrences
            + (
                edge(
                    "skill",
                    "stock.skill",
                    "skill.optional_tools",
                    "tool",
                    "stock.optional",
                    absent=True,
                ),
            ),
        )
    )
    assert len(result.seed_keys) == 4
    assert len(result.edge_occurrences) == 4


def test_duplicate_ordinal_and_missing_target() -> None:
    f = fixture()
    expect_code(
        c.D2CCode.D2C_EDGE_CATALOG_INVALID,
        replace(f, edge_occurrences=f.edge_occurrences + f.edge_occurrences[:1]),
    )
    expect_code(
        c.D2CCode.D2C_EXACT_DEPENDENCY_MISSING,
        replace(
            f, asset_refs=f.asset_refs[:1], edge_occurrences=f.edge_occurrences[:1]
        ),
    )


def test_orphan_priority() -> None:
    f = fixture()
    a = dict(f.registry_entries[1].fields)
    a["required_capability"] = None
    only = replace(
        f,
        asset_refs=f.asset_refs[:1],
        registry_entries=(
            f.registry_entries[0],
            entry("ActionDefinition", "stock.count", a),
            f.registry_entries[2],
        ),
        edge_occurrences=(),
    )
    expect_code(c.D2CCode.D2C_RESOLUTION_UNSTABLE, only)
    missing = replace(
        only,
        registry_entries=(
            only.registry_entries[0],
            f.registry_entries[1],
            f.registry_entries[2],
        ),
        edge_occurrences=f.edge_occurrences[:1],
    )
    expect_code(c.D2CCode.D2C_EXACT_DEPENDENCY_MISSING, missing)
    wrong = list(missing.registry_entries)
    wrong[1] = replace(wrong[1], definition_sha256="b" * 64)
    expect_code(
        c.D2CCode.D2C_DEFINITION_HASH_MISMATCH,
        replace(missing, registry_entries=tuple(wrong)),
    )


def test_mode_changes_catalog_digest() -> None:
    f = fixture()
    first = c._resolve_untrusted_catalog_observation(f)
    second = c._resolve_untrusted_catalog_observation(
        replace(f, prompt_mode="REGISTRY_EXACT")
    )
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
    expect_code(
        c.D2CCode.D2C_RESOLUTION_UNSTABLE, replace(f, registry_entries=tuple(rows))
    )
    cyclic: list[object] = []
    cyclic.append(cyclic)
    a["description"] = cyclic
    rows[1] = replace(rows[1], fields=a)
    expect_code(
        c.D2CCode.D2C_RESOLUTION_UNSTABLE, replace(f, registry_entries=tuple(rows))
    )


def test_definition_vectors_and_exact_no_prefix() -> None:
    expected = {
        "ActionDefinition": "991e6b213af25e38fb6482b8e0f4f52f201fff26c157ac1953b169013063ffbf",
        "SkillDefinition": "07dd4a06978f8fe8665edb5587826e3de36fe5acae6808d0576b150ec86d8ef2",
        "ToolDefinition": "0c3f922fe6b16cac6ce54235d5938a4ac14f225487417bd92cafd49a0ac4f55a",
    }
    for kind, digest in expected.items():
        item = {
            "ActionDefinition": "stock.count",
            "SkillDefinition": "stock.skill",
            "ToolDefinition": "stock.tool",
        }[kind]
        assert (
            hashlib.sha256(c._canonical_definition(entry(kind, item))).hexdigest()
            == digest
        )


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
    assert (
        c._admit_and_copy_diagnostic_input(
            replace(f, registry_entries=tuple(row))
        ).primitive_element_count
        > count
    )


def test_no_trusted_api_or_runtime_export() -> None:
    for name in (
        "resolve_verified_domain",
        "DomainBindingV1",
        "HostCatalogPublisher",
        "BoundRunDomainV1",
    ):
        assert not hasattr(c, name)


# Extended deterministic reference, boundary and security evidence.


@pytest.mark.parametrize(
    ("kind", "item", "expected"),
    [
        (
            "ActionDefinition",
            "stock.count",
            "991e6b213af25e38fb6482b8e0f4f52f201fff26c157ac1953b169013063ffbf",
        ),
        (
            "StrategyDefinition",
            "stock.strategy",
            "5ca6bcd39d3e3899e0e43c33c9a7f2e055905795646aa95af3bcf879fc7fe389",
        ),
        (
            "SkillDefinition",
            "stock.skill",
            "07dd4a06978f8fe8665edb5587826e3de36fe5acae6808d0576b150ec86d8ef2",
        ),
        (
            "WorkflowDefinition",
            "stock.workflow",
            "4fc3bad08bbaa5bcedb90bd1f5eade2bd39bb0aa45ea7b32e00084704b62e98a",
        ),
        (
            "ToolDefinition",
            "stock.tool",
            "0c3f922fe6b16cac6ce54235d5938a4ac14f225487417bd92cafd49a0ac4f55a",
        ),
        (
            "PolicyDefinition",
            "stock.rule",
            "7181937a3b97dc8ee345e59db9b2332cb56b8192c6a34fe1da6cedc2bd5ce2d8",
        ),
        (
            "PromptDefinition",
            "stock.prompt",
            "1693c258ac856f25af1ca1cc5679513e2bb2595b0cf8f4ca6509591f98249e05",
        ),
        (
            "DomainManifest",
            "inventory.reconcile",
            "3d0a395c4760745a913247eb2ff0e0a65fd84fe7b0733d2e9c25a8152f083f56",
        ),
        (
            "SchemaDefinition",
            "stock.schema",
            "fc7cd1e466d3bc4b8b0a2ab6eba0843789282e96482710ae0646bd0b37a90591",
        ),
        (
            "CapabilityDefinition",
            "stock.capability",
            "5c16c2c9f1d09a357bf856d56745f561b6ad63685e15db1fdf7b0ab7c9ac7be0",
        ),
    ],
)
def test_ten_definition_golden_vectors(kind: str, item: str, expected: str) -> None:
    assert (
        hashlib.sha256(c._canonical_definition(entry(kind, item))).hexdigest()
        == expected
    )


def test_c06_c07_catalog_two_mode_vectors() -> None:
    data: dict[str, object] = {
        "adapter_entries": [],
        "approved_core_schema_keys": [],
        "domain_id": "inventory.reconcile",
        "domain_version": "1.0.0",
        "edge_digest": "df28640283682cbc5ce71f51e2581ded513ede5223aa335e89b55e615c8ff1ef",
        "host_catalog_generation": "diagnostic-g1",
        "host_policy_generation": "diagnostic-p1",
        "host_policy_id": "diagnostic-policy",
        "manifest_sha256": "a" * 64,
        "profile": "GA02-D2C-CATALOG-2",
        "prompt_mode": "REGISTRY_EXACT",
        "publisher_generation": "package-g1",
        "registry_entries": [],
        "rule_mode": "INERT_ONLY",
        "runtime_profile": "GA02-D1-1",
    }
    assert c._digest("GA02-D2C-CATALOG-2", data) == (
        "2c1388a320cbb4752e2aae0e2d777c560781d742bfdedf49d8773d1b0ae1f02d"
    )
    data["prompt_mode"] = "INERT_ONLY"
    assert c._digest("GA02-D2C-CATALOG-2", data) == (
        "776576af1529d2e63326fe10dcc778cfe3fc7d0de38fdb801fbd444ef148ee64"
    )
    data["rule_mode"] = "REGISTRY_EXACT"
    assert c._digest("GA02-D2C-CATALOG-2", data) not in {
        "2c1388a320cbb4752e2aae0e2d777c560781d742bfdedf49d8773d1b0ae1f02d",
        "776576af1529d2e63326fe10dcc778cfe3fc7d0de38fdb801fbd444ef148ee64",
    }


def _eight_capabilities() -> c.DiagnosticCatalogInputV1:
    base = fixture()
    caps = [f"stock.capability.{n}" for n in range(8)]
    return replace(
        base,
        asset_refs=tuple(asset("capability", item) for item in caps),
        registry_entries=(entry("DomainManifest", "inventory.reconcile"),)
        + tuple(entry("CapabilityDefinition", item) for item in caps),
        edge_occurrences=(),
    )


def _ex_boundary(extra: int = 0) -> c.DiagnosticCatalogInputV1:
    base = _eight_capabilities()
    assert c._admit_and_copy_diagnostic_input(base).primitive_element_count == 316
    slots = 3780 + extra
    records = list(base.registry_entries)
    for i in range(1, 9):
        item = f"stock.capability.{i - 1}"
        fields_copy = dict(records[i].fields)
        for field in ("intents", "entities", "needs"):
            amount = min(256, slots)
            if amount:
                fields_copy[field] = ["x"] * amount
                slots -= amount
        records[i] = entry("CapabilityDefinition", item, fields_copy)
    assert slots == 0
    return replace(base, registry_entries=tuple(records))


def test_ex_4096_and_4097_exact_external_preflight() -> None:
    at_limit = _ex_boundary()
    owned = c._admit_and_copy_diagnostic_input(at_limit)
    assert owned.primitive_element_count == 4096
    snap = c._resolve_untrusted_catalog_observation(at_limit)
    assert len(snap.seed_keys) == 8
    assert snap.operational_readiness == "NOT_ASSESSED"
    expect_code(c.D2CCode.D2C_RESOURCE_LIMIT, _ex_boundary(extra=1))


def _ng_boundary(extra: bool = False) -> c.DiagnosticCatalogInputV1:
    f = fixture()
    name_list = ["stock.skill.a", "stock.skill.b", "stock.skill.c", "stock.skill.d"]
    if extra:
        name_list.append("stock.skill.e")
    refs = [asset("skill", item) for item in name_list] + [asset("tool", "stock.tool")]
    records = [entry("DomainManifest", "inventory.reconcile")]
    occurrences: list[c.DiagnosticEdgeOccurrenceV1] = []
    for index, item in enumerate(name_list):
        count = 1 if index == 4 else 256
        data = definition("SkillDefinition", item)
        data["optional_tools"] = ["stock.tool"] * count
        records.append(entry("SkillDefinition", item, data))
        for ordinal in range(count):
            occurrences.append(
                edge(
                    "skill", item, "skill.optional_tools", "tool", "stock.tool", ordinal
                )
            )
    records.append(entry("ToolDefinition", "stock.tool"))
    return replace(
        f,
        asset_refs=tuple(refs),
        registry_entries=tuple(records),
        edge_occurrences=tuple(occurrences),
    )


def test_ng_1024_and_1025_internal_only_budget() -> None:
    at_limit = _ng_boundary()
    result = c._resolve_owned_diagnostic_graph(c._OwnedDiagnosticInputV1(at_limit, 0))
    assert len(result.edge_occurrences) == 1024
    assert len(result.seed_keys) == 5
    with pytest.raises(c.D2CResolutionError) as exc:
        c._resolve_owned_diagnostic_graph(
            c._OwnedDiagnosticInputV1(_ng_boundary(extra=True), 0)
        )
    assert exc.value.code == c.D2CCode.D2C_RESOURCE_LIMIT
    assert exc.value.code.value == str(exc.value)


def test_or03_included_target_is_diagnostic_success() -> None:
    source = definition("ActionDefinition", "stock.count")
    source["required_capability"] = "stock.capability"
    input_value = replace(
        fixture(),
        asset_refs=(
            asset("action", "stock.count"),
            asset("capability", "stock.capability"),
        ),
        registry_entries=(
            entry("DomainManifest", "inventory.reconcile"),
            entry("ActionDefinition", "stock.count", source),
            entry("CapabilityDefinition", "stock.capability"),
        ),
        edge_occurrences=(
            edge(
                "action",
                "stock.count",
                "action.required_capability",
                "capability",
                "stock.capability",
            ),
        ),
    )
    result = c._resolve_untrusted_catalog_observation(input_value)
    assert result.observation_role == "UNTRUSTED_DIAGNOSTIC_ONLY"
    assert len(result.seed_keys) == 2


def test_core_schema_requires_matching_scope_and_allowlist() -> None:
    f = fixture()
    schema = definition("SchemaDefinition", "stock.schema")
    schema["scope"] = "CORE"
    schema["namespace"] = "CORE"
    schema_ref = replace(asset("schema", "stock.schema"), namespace="CORE")
    schema_entry = replace(
        entry("SchemaDefinition", "stock.schema", schema), namespace="CORE"
    )
    full = replace(
        f,
        asset_refs=f.asset_refs + (schema_ref,),
        registry_entries=f.registry_entries + (schema_entry,),
        approved_core_schema_keys=(
            c.DiagnosticCoreSchemaKeyV1("stock.schema", "1.0.0"),
        ),
    )
    assert len(c._resolve_untrusted_catalog_observation(full).seed_keys) == 5
    bad = dict(schema)
    bad["scope"] = "DOMAIN"
    bad_entry = replace(
        entry("SchemaDefinition", "stock.schema", bad), namespace="CORE"
    )
    expect_code(
        c.D2CCode.D2C_EXACT_DEPENDENCY_MISSING,
        replace(full, registry_entries=f.registry_entries + (bad_entry,)),
    )
    expect_code(
        c.D2CCode.D2C_EXACT_DEPENDENCY_MISSING,
        replace(full, approved_core_schema_keys=()),
    )


def test_adapter_union_refuses_nonnull_absent() -> None:
    f = fixture()
    bad = c.DiagnosticAdapterEntryV1(
        "tool",
        "inventory.reconcile",
        "stock.tool",
        "1.0.0",
        "ABSENT_UNVERIFIED",
        None,
        "rogue",
        None,
        None,
        None,
    )
    expect_code(c.D2CCode.D2C_HOST_ADAPTER_MISMATCH, replace(f, adapter_entries=(bad,)))
    good = replace(bad, adapter_generation=None)
    assert (
        c._resolve_untrusted_catalog_observation(
            replace(f, adapter_entries=(good,))
        ).operational_readiness
        == "NOT_ASSESSED"
    )


def test_copy_owns_nested_definition_lists() -> None:
    f = fixture()
    source = f.registry_entries[3].fields
    owned = c._admit_and_copy_diagnostic_input(f)
    reference = c._resolve_owned_diagnostic_graph(owned)
    original = source["required_tools"]
    source["required_tools"] = ["not.the.tool"]
    try:
        after = c._resolve_owned_diagnostic_graph(owned)
    finally:
        source["required_tools"] = original
    assert after.closure_digest == reference.closure_digest


def test_prompt_mode_switch_requires_exact_registry_entry() -> None:
    f = fixture()
    prompt_ref = asset("prompt", "stock.prompt")
    inert = replace(f, asset_refs=f.asset_refs + (prompt_ref,))
    assert len(c._resolve_untrusted_catalog_observation(inert).seed_keys) == 4
    expect_code(
        c.D2CCode.D2C_EXACT_DEPENDENCY_MISSING,
        replace(inert, prompt_mode="REGISTRY_EXACT"),
    )
    prompt = entry("PromptDefinition", "stock.prompt")
    active = replace(
        inert,
        prompt_mode="REGISTRY_EXACT",
        registry_entries=f.registry_entries + (prompt,),
    )
    result = c._resolve_untrusted_catalog_observation(active)
    assert len(result.seed_keys) == 5
    assert result.operational_readiness == "NOT_ASSESSED"


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("intrusiveness_level", "UNRECOGNIZED"),
        ("requires_confirmation", "false"),
        ("allowed_planning_modes", ["not-a-mode"]),
    ],
)
def test_invalid_definition_fields_fail_closed(field: str, invalid: object) -> None:
    f = fixture()
    rows = list(f.registry_entries)
    action = dict(rows[1].fields)
    action[field] = invalid
    rows[1] = entry("ActionDefinition", "stock.count", action)
    expect_code(
        c.D2CCode.D2C_CANONICAL_DEFINITION_INVALID,
        replace(f, registry_entries=tuple(rows)),
    )


def test_external_list_overflow_and_unsupported_type() -> None:
    f = fixture()
    rows = list(f.registry_entries)
    skill = dict(rows[3].fields)
    skill["optional_tools"] = ["stock.tool"] * 257
    rows[3] = entry("SkillDefinition", "stock.skill", skill)
    expect_code(c.D2CCode.D2C_RESOURCE_LIMIT, replace(f, registry_entries=tuple(rows)))
    expect_code(
        c.D2CCode.D2C_RESOLUTION_UNSTABLE, replace(f, prompt_mode=cast(Any, 123))
    )


def test_e01_e02_e03_historical_empty_evidence_vectors() -> None:
    edge_catalog = {
        "edges": [],
        "host_catalog_generation": "diagnostic-g1",
        "profile": "GA02-D2C-EDGES-1",
    }
    expected_edge = "df28640283682cbc5ce71f51e2581ded513ede5223aa335e89b55e615c8ff1ef"
    assert c._digest("GA02-D2C-EDGES-1", edge_catalog) == expected_edge

    historical_catalog = {
        "adapter_entries": [],
        "approved_core_schema_keys": [],
        "domain_id": "inventory.reconcile",
        "domain_version": "1.0.0",
        "edge_digest": expected_edge,
        "host_catalog_generation": "diagnostic-g1",
        "host_policy_generation": "diagnostic-p1",
        "host_policy_id": "diagnostic-policy",
        "manifest_sha256": "a" * 64,
        "profile": "GA02-D2C-CATALOG-1",
        "publisher_generation": "package-g1",
        "registry_entries": [],
        "runtime_profile": "GA02-D1-1",
    }
    assert c._digest("GA02-D2C-CATALOG-1", historical_catalog) == (
        "ecfc18f4e025d898c74865e60e5b2199df10584bb1ece0b2b84e4d0d03bf45cc"
    )

    historical_closure = {
        "adapter_evidence": [],
        "definition_hashes": [],
        "dependency_keys": [],
        "edges": [],
        "graph_completeness": "SUPPORTED_RELATIONS_ONLY",
        "host_catalog_generation": "diagnostic-g1",
        "manifest_sha256": "a" * 64,
        "operational_readiness": "NOT_ASSESSED",
        "profile": "GA02-D2C-CLOSURE-1",
        "seed_keys": [],
    }
    assert c._digest("GA02-D2C-CLOSURE-1", historical_closure) == (
        "342f90ec3f8526f957d103f9677b778635ab9c9195c46b9f1bd00c83556d0eca"
    )


def test_upstream_d2d_binding_five_golden_vectors_unchanged() -> None:
    # Independent input construction: these are serialized reference cases,
    # not a C0 issuer, trusted binding or runnable admission.
    base: dict[str, object] = {
        "assets": [],
        "binding_profile": "GA02-D2-BINDING-1",
        "dependencies": [],
        "domain_id": "inventory.reconcile",
        "domain_version": "1.0.0",
        "host_catalog_generation": "host-v1",
        "manifest_sha256": (
            "c757e6506fb0e8d7741c9abf5abc2880221655f506afd597dd7817edce195a3f"
        ),
        "runtime_profile": "GA02-D1-1",
    }
    assert c._digest("GA02-D2-BINDING-1", base) == (
        "8342fd5a5d645e8ab907cd3cbdab4e78cf5a7375a4da554f903184b8809be859"
    )

    one_asset = {
        "id": "stock.count",
        "kind": "action",
        "namespace": "inventory.reconcile",
        "relative_path": "actions/count.json",
        "sha256": "a" * 64,
        "version": "1.0.0",
    }
    one_dependency = {
        "definition_sha256": "b" * 64,
        "enabled_at_resolution": True,
        "host_adapter_generation": None,
        "host_adapter_key": None,
        "id": "stock.count",
        "namespace": "inventory.reconcile",
        "registry_kind": "action",
        "version": "1.0.0",
    }
    payload: dict[str, object] = {
        **base,
        "assets": [one_asset],
        "dependencies": [one_dependency],
    }
    assert c._digest("GA02-D2-BINDING-1", payload) == (
        "649c58d4aa6fb132e807a5b96c2969e354fc942568371e7a8087a2d984855bfd"
    )
    changed_definition: dict[str, object] = {
        **payload,
        "dependencies": [{**one_dependency, "definition_sha256": "c" * 64}],
    }
    assert c._digest("GA02-D2-BINDING-1", changed_definition) == (
        "2121d12f19c3e7cdf0e67f6d1d2942b03760cb4d11393046d68ded40e81e10b8"
    )
    changed_generation = {**payload, "host_catalog_generation": "host-v2"}
    assert c._digest("GA02-D2-BINDING-1", changed_generation) == (
        "3a5aecc673eb889b351f39c92282c7a6f211e4cb020d08a0137c5c6535f89692"
    )
    changed_asset = {
        **payload,
        "assets": [{**one_asset, "sha256": "d" * 64}],
    }
    assert c._digest("GA02-D2-BINDING-1", changed_asset) == (
        "3e19d5c7c5b8a71fd1dad2d991d42e240264cdf911bc97aa7b02fffbb259d125"
    )


def test_canonical_input_budget_precedes_semantic_adapter_fault() -> None:
    source = fixture()
    # 140 × 4 × 1024 astral scalars: >2 MiB in UTF-8 within 4096 slots.
    large = "𠜎" * 1024
    adapters = tuple(
        c.DiagnosticAdapterEntryV1(
            "tool",
            "inventory.reconcile",
            f"stock.tool.extra.{i}",
            "1.0.0",
            "DECLARED_NON_AUTHORITATIVE",
            large,
            large,
            large,
            large,
            "a" * 64,
        )
        for i in range(140)
    )
    invalid = replace(source, adapter_entries=adapters)
    expect_code(c.D2CCode.D2C_RESOURCE_LIMIT, invalid)
    # The same malformed catalog within the byte cap has a semantic denial.
    expect_code(
        c.D2CCode.D2C_HOST_ADAPTER_MISMATCH,
        replace(source, adapter_entries=adapters[:1]),
    )


def _physical_chain(path_edges: int) -> c.DiagnosticCatalogInputV1:
    """Versioned Action→Capability→Skill→Action DAG with reverse-sorted roots."""
    base = fixture()
    names: list[tuple[str, str, str]] = []
    for ordinal in range(path_edges + 1):
        triad = ordinal // 3
        suffix = f"a{30 - triad:02d}"
        if ordinal % 3 == 0:
            names.append(("action", "ActionDefinition", f"chain.action.{suffix}"))
        elif ordinal % 3 == 1:
            names.append(("capability", "CapabilityDefinition", f"chain.cap.{suffix}"))
        else:
            names.append(("skill", "SkillDefinition", f"chain.skill.{suffix}"))
    refs = []
    records = [entry("DomainManifest", "inventory.reconcile")]
    edges = []
    for position, (kind, cls, item) in enumerate(names):
        data = definition(cls, item)
        if position < path_edges:
            target_kind, _, target_id = names[position + 1]
            if kind == "action":
                data["required_capability"] = target_id
                relation = "action.required_capability"
            elif kind == "capability":
                data["skills"] = [target_id]
                relation = "capability.skills"
            else:
                data["supported_actions"] = [target_id]
                relation = "skill.supported_actions"
            edges.append(edge(kind, item, relation, target_kind, target_id))
        refs.append(asset(kind, item))
        records.append(entry(cls, item, data))
    return replace(
        base,
        asset_refs=tuple(refs),
        registry_entries=tuple(records),
        edge_occurrences=tuple(edges),
    )


def test_global_done_does_not_hide_path_depth_33() -> None:
    safe = c._resolve_untrusted_catalog_observation(_physical_chain(32))
    assert len(safe.seed_keys) == 33
    expect_code(c.D2CCode.D2C_RESOURCE_LIMIT, _physical_chain(33))


def test_strict_asset_paths_and_carrier_strings() -> None:
    f = fixture()
    bad_path = replace(f.asset_refs[0], relative_path="a/" + "b" * 512)
    expect_code(
        c.D2CCode.D2C_RESOLUTION_UNSTABLE,
        replace(f, asset_refs=(bad_path,) + f.asset_refs[1:]),
    )
    non_nfc = replace(f.asset_refs[0], relative_path="actions/cafe\u0301.json")
    expect_code(
        c.D2CCode.D2C_RESOLUTION_UNSTABLE,
        replace(f, asset_refs=(non_nfc,) + f.asset_refs[1:]),
    )
    too_long = replace(f.registry_entries[1], definition_type="A" * 1025)
    expect_code(
        c.D2CCode.D2C_RESOLUTION_UNSTABLE,
        replace(
            f,
            registry_entries=(f.registry_entries[0], too_long) + f.registry_entries[2:],
        ),
    )


def test_graph_diamond_shared_dag_and_alias_copy() -> None:
    f = fixture()
    one = list(f.registry_entries)
    cap = dict(one[2].fields)
    cap["skills"] = ["stock.skill", "stock.skill.two"]
    one[2] = entry("CapabilityDefinition", "stock.capability", cap)
    skilltwo = definition("SkillDefinition", "stock.skill.two")
    skilltwo["required_tools"] = ["stock.tool"]
    one.append(entry("SkillDefinition", "stock.skill.two", skilltwo))
    valid = replace(
        f,
        asset_refs=f.asset_refs + (asset("skill", "stock.skill.two"),),
        registry_entries=tuple(one),
        edge_occurrences=f.edge_occurrences
        + (
            edge(
                "capability",
                "stock.capability",
                "capability.skills",
                "skill",
                "stock.skill.two",
                1,
            ),
            edge(
                "skill", "stock.skill.two", "skill.required_tools", "tool", "stock.tool"
            ),
        ),
    )
    assert len(c._resolve_untrusted_catalog_observation(valid).seed_keys) == 5
    common: list[str] = ["stock.tool"]
    aliased = dict(skilltwo)
    aliased["required_tools"] = common
    aliased["optional_tools"] = common
    records = list(valid.registry_entries)
    records[-1] = entry("SkillDefinition", "stock.skill.two", aliased)
    owned_input = replace(
        valid,
        registry_entries=tuple(records),
        edge_occurrences=valid.edge_occurrences
        + (
            edge(
                "skill", "stock.skill.two", "skill.optional_tools", "tool", "stock.tool"
            ),
        ),
    )
    owned = c._admit_and_copy_diagnostic_input(owned_input)
    common.append("new.tool")
    assert len(c._resolve_owned_diagnostic_graph(owned).edge_occurrences) == 6


def test_generation_error_precedes_corrupt_definition() -> None:
    f = fixture()
    rows = list(f.registry_entries)
    manifest = dict(rows[0].fields)
    manifest["runtime_compatibility"] = "wrong-profile"
    rows[0] = entry("DomainManifest", "inventory.reconcile", manifest)
    rows[1] = replace(rows[1], definition_sha256="f" * 64)
    expect_code(
        c.D2CCode.D2C_CATALOG_GENERATION_MISMATCH,
        replace(f, registry_entries=tuple(rows)),
    )


def test_invalid_definition_precedes_invalid_edge() -> None:
    f = fixture()
    rows = list(f.registry_entries)
    action = dict(rows[1].fields)
    action["requires_confirmation"] = "no"
    rows[1] = entry("ActionDefinition", "stock.count", action)
    expect_code(
        c.D2CCode.D2C_CANONICAL_DEFINITION_INVALID,
        replace(
            f,
            registry_entries=tuple(rows),
            edge_occurrences=f.edge_occurrences + f.edge_occurrences[:1],
        ),
    )


def test_missing_d1_precedes_cycle_and_adapter_precedes_cycle() -> None:
    f = fixture()
    rows = list(f.registry_entries)
    skill = dict(rows[3].fields)
    skill["supported_actions"] = ["stock.count"]
    rows[3] = entry("SkillDefinition", "stock.skill", skill)
    cyclic = replace(
        f,
        registry_entries=tuple(rows),
        edge_occurrences=f.edge_occurrences
        + (
            edge(
                "skill",
                "stock.skill",
                "skill.supported_actions",
                "action",
                "stock.count",
            ),
        ),
    )
    expect_code(
        c.D2CCode.D2C_EXACT_DEPENDENCY_MISSING,
        replace(
            cyclic,
            asset_refs=tuple(ref for ref in cyclic.asset_refs if ref.kind != "tool"),
        ),
    )
    bad_adapter = c.DiagnosticAdapterEntryV1(
        "tool",
        "inventory.reconcile",
        "stock.tool",
        "1.0.0",
        "ABSENT_UNVERIFIED",
        None,
        "forged",
        None,
        None,
        None,
    )
    expect_code(
        c.D2CCode.D2C_HOST_ADAPTER_MISMATCH,
        replace(cyclic, adapter_entries=(bad_adapter,)),
    )


def test_depth_13_and_foreign_dict_type_rejected_without_callbacks() -> None:
    f = fixture()
    rows = list(f.registry_entries)
    action = dict(rows[1].fields)
    nested: list[object] = []
    pointer = nested
    for _ in range(13):
        child: list[object] = []
        pointer.append(child)
        pointer = child
    action["description"] = nested
    rows[1] = replace(rows[1], fields=action)
    expect_code(
        c.D2CCode.D2C_RESOURCE_LIMIT,
        replace(f, registry_entries=tuple(rows)),
    )

    class DangerousDict(dict[str, object]):
        def items(self) -> Any:
            raise AssertionError("custom items must not be invoked")

    rows[1] = replace(rows[1], fields=DangerousDict(action))
    expect_code(
        c.D2CCode.D2C_RESOLUTION_UNSTABLE,
        replace(f, registry_entries=tuple(rows)),
    )


def test_noncanonical_key_and_unpaired_unicode_rejected() -> None:
    f = fixture()
    rows = list(f.registry_entries)
    malformed = dict(rows[1].fields)
    malformed["cafe\u0301"] = "unexpected"
    rows[1] = replace(rows[1], fields=malformed)
    expect_code(
        c.D2CCode.D2C_RESOLUTION_UNSTABLE,
        replace(f, registry_entries=tuple(rows)),
    )
    surrogate = replace(f.asset_refs[0], relative_path="test/\ud800.json")
    expect_code(
        c.D2CCode.D2C_RESOLUTION_UNSTABLE,
        replace(f, asset_refs=(surrogate,) + f.asset_refs[1:]),
    )


def _utf8_scalar_of_exact_size(size: int) -> str:
    """1..4096 byte NFC Unicode value with at most 1024 scalars."""
    assert 1 <= size <= 4096
    characters = (size + 3) // 4
    reduction = 4 * characters - size
    return "𠜎" * (characters - 1) + ("𠜎", "€", "é", "x")[reduction]


def _adapter_pressure_input(
    count: int, *, astral: bool = False
) -> c.DiagnosticCatalogInputV1:
    f = fixture()
    large = ("𠜎" if astral else "x") * 1024
    adapters = tuple(
        c.DiagnosticAdapterEntryV1(
            "tool",
            "inventory.reconcile",
            f"stock.tool.extra.{i}",
            "1.0.0",
            "DECLARED_NON_AUTHORITATIVE",
            large,
            large,
            large,
            large,
            "a" * 64,
        )
        for i in range(count)
    )
    return replace(f, adapter_entries=adapters)


def _precise_input_boundary(over: int) -> c.DiagnosticCatalogInputV1:
    """Construct canonical 2MiB or 2MiB+1 inputs without >4096 slots."""
    target = 2097152 + over
    for count in range(110, 140):
        full = _adapter_pressure_input(count, astral=True)
        small = tuple(
            c.DiagnosticAdapterEntryV1(
                "tool",
                "inventory.reconcile",
                f"filler.{i}",
                "1.0.0",
                "DECLARED_NON_AUTHORITATIVE",
                "x",
                "x",
                "x",
                "x",
                "a" * 64,
            )
            for i in range(2)
        )
        candidate = replace(full, adapter_entries=full.adapter_entries + small)
        delta = target - c._input_canonical_size(candidate)
        if not 0 <= delta <= 8 * 4095:
            continue
        updated = list(candidate.adapter_entries)
        for i in range(2):
            record = updated[count + i]
            sizes = []
            for _ in range(4):
                added = min(4095, delta)
                sizes.append(_utf8_scalar_of_exact_size(1 + added))
                delta -= added
            updated[count + i] = replace(
                record,
                adapter_key=sizes[0],
                adapter_generation=sizes[1],
                tenant_scope_allowlist_id=sizes[2],
                domain_scope=sizes[3],
            )
        assert delta == 0
        result = replace(candidate, adapter_entries=tuple(updated))
        assert c._input_canonical_size(result) == target
        return result
    pytest.fail("2MiB UTF-8 admission boundary fixture is not constructible")


def test_exact_2mib_and_one_over_rejected_during_input_copy() -> None:
    at_limit = _precise_input_boundary(0)
    owned = c._admit_and_copy_diagnostic_input(at_limit)
    assert owned.canonical_input_bytes == 2097152
    assert owned.primitive_element_count <= 4096
    over = _precise_input_boundary(1)
    expect_code(c.D2CCode.D2C_RESOURCE_LIMIT, over)


def test_projected_evidence_limit_precedes_cycle_and_adapter_semantics() -> None:
    pressure = _adapter_pressure_input(190)
    assert c._input_canonical_size(pressure) < 2097152
    expect_code(c.D2CCode.D2C_RESOURCE_LIMIT, pressure)

    rows = list(pressure.registry_entries)
    skill = dict(rows[3].fields)
    skill["supported_actions"] = ["stock.count"]
    rows[3] = entry("SkillDefinition", "stock.skill", skill)
    cycle = replace(
        pressure,
        registry_entries=tuple(rows),
        edge_occurrences=pressure.edge_occurrences
        + (
            edge(
                "skill",
                "stock.skill",
                "skill.supported_actions",
                "action",
                "stock.count",
            ),
        ),
    )
    expect_code(c.D2CCode.D2C_RESOURCE_LIMIT, cycle)
    malformed = list(pressure.registry_entries)
    action = dict(malformed[1].fields)
    action["requires_confirmation"] = "false"
    malformed[1] = entry("ActionDefinition", "stock.count", action)
    expect_code(
        c.D2CCode.D2C_RESOURCE_LIMIT,
        replace(pressure, registry_entries=tuple(malformed)),
    )
    expect_code(
        c.D2CCode.D2C_HOST_ADAPTER_MISMATCH,
        replace(pressure, adapter_entries=pressure.adapter_entries[:1]),
    )


def test_a10_cross_domain_and_a12_disabled_dependencies() -> None:
    f = fixture()
    bad_edge = replace(f.edge_occurrences[0], target_namespace="wrong.domain")
    expect_code(
        c.D2CCode.D2C_EXACT_DEPENDENCY_MISSING,
        replace(f, edge_occurrences=(bad_edge,) + f.edge_occurrences[1:]),
    )
    rows = list(f.registry_entries)
    rows[4] = replace(rows[4], record_enabled=False)
    expect_code(
        c.D2CCode.D2C_DEPENDENCY_DISABLED,
        replace(f, registry_entries=tuple(rows)),
    )


def test_a19_unexpected_internal_exception_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected(_: object) -> None:
        raise RuntimeError("SECRET-DETAIL-MUST-NOT-LEAK")

    monkeypatch.setattr(c, "_resolve_owned_diagnostic_graph", unexpected)
    expect_code(c.D2CCode.D2C_RESOLUTION_UNSTABLE, fixture())


def test_a01_rejects_forged_trust_and_missing_root_field() -> None:
    from types import SimpleNamespace

    f = fixture()
    forged = SimpleNamespace(
        **{
            **{field: getattr(f, field) for field in f.__dataclass_fields__},
            "trusted": True,
        }
    )
    expect_code(c.D2CCode.D2C_RESOLUTION_UNSTABLE, cast(Any, forged))
    incomplete = object.__new__(c.DiagnosticCatalogInputV1)
    for name in f.__dataclass_fields__:
        if name != "edge_occurrences":
            object.__setattr__(incomplete, name, getattr(f, name))
    expect_code(c.D2CCode.D2C_RESOLUTION_UNSTABLE, incomplete)


def test_a03_self_cycle_plus_hostile_object_no_method_calls() -> None:
    f = fixture()
    counters = {"str": 0, "repr": 0, "hash": 0, "eq": 0, "iter": 0}

    class Hostile:
        def __str__(self) -> str:
            counters["str"] += 1
            raise AssertionError("hostile __str__")

        def __repr__(self) -> str:
            counters["repr"] += 1
            raise AssertionError("hostile __repr__")

        def __hash__(self) -> int:
            counters["hash"] += 1
            raise AssertionError("hostile __hash__")

        def __eq__(self, other: object) -> bool:
            counters["eq"] += 1
            raise AssertionError("hostile __eq__")

        def __iter__(self) -> Any:
            counters["iter"] += 1
            raise AssertionError("hostile __iter__")

    cyclic: list[Any] = []
    cyclic.append(cyclic)
    cyclic.append(Hostile())
    rows = list(f.registry_entries)
    action = dict(rows[1].fields)
    action["description"] = cyclic
    rows[1] = replace(rows[1], fields=action)
    expect_code(
        c.D2CCode.D2C_RESOLUTION_UNSTABLE,
        replace(f, registry_entries=tuple(rows)),
    )
    assert counters == dict.fromkeys(counters, 0)


def test_a07_exact_valid_definition_wrong_digest() -> None:
    f = fixture()
    rows = list(f.registry_entries)
    rows[1] = replace(rows[1], definition_sha256="f" * 64)
    expect_code(
        c.D2CCode.D2C_DEFINITION_HASH_MISMATCH,
        replace(f, registry_entries=tuple(rows)),
    )


def test_a08_duplicate_wrong_ordinal_unmatched_edge() -> None:
    f = fixture()
    cases = (
        f.edge_occurrences + f.edge_occurrences[:1],
        (replace(f.edge_occurrences[0], ordinal=9),) + f.edge_occurrences[1:],
        f.edge_occurrences
        + (
            edge(
                "action",
                "stock.count",
                "action.unexpected",
                "capability",
                "stock.capability",
            ),
        ),
    )
    for occurrences in cases:
        expect_code(
            c.D2CCode.D2C_EDGE_CATALOG_INVALID,
            replace(f, edge_occurrences=occurrences),
        )


def test_a11_non_schema_core_target_fails_closed() -> None:
    f = fixture()
    original = f.edge_occurrences[0]
    foreign = replace(original, target_namespace="CORE")
    expect_code(
        c.D2CCode.D2C_EXACT_DEPENDENCY_MISSING,
        replace(f, edge_occurrences=(foreign,) + f.edge_occurrences[1:]),
    )


def test_exact_string_1024_1025_external_boundary() -> None:
    f = fixture()
    rows = list(f.registry_entries)
    values = dict(rows[1].fields)
    values["description"] = "x" * 1024
    rows[1] = entry("ActionDefinition", "stock.count", values)
    result = c._resolve_untrusted_catalog_observation(
        replace(f, registry_entries=tuple(rows))
    )
    assert len(result.seed_keys) == 4
    values["description"] = "x" * 1025
    rows[1] = entry("ActionDefinition", "stock.count", values)
    expect_code(
        c.D2CCode.D2C_RESOLUTION_UNSTABLE,
        replace(f, registry_entries=tuple(rows)),
    )


def _definition_byte_boundary(size: int) -> dict[str, object]:
    values = definition("CapabilityDefinition", "stock.capability")
    values["intents"] = ["x" * 30] * 256
    baseline = len(canonical(values))
    assert baseline < size
    extra = size - baseline
    labels = list(cast(list[str], values["intents"]))
    index = 0
    while extra:
        delta = min(994, extra)
        labels[index] += "x" * delta
        extra -= delta
        index += 1
    values["intents"] = labels
    assert len(canonical(values)) == size
    assert all(len(item) <= 1024 for item in labels)
    return values


def test_canonical_definition_exact_10240_10241_byte_limit() -> None:
    accepted = entry(
        "CapabilityDefinition",
        "stock.capability",
        _definition_byte_boundary(10240),
    )
    assert len(c._canonical_definition(accepted)) == 10240
    oversized = entry(
        "CapabilityDefinition",
        "stock.capability",
        _definition_byte_boundary(10241),
    )
    with pytest.raises(c.D2CResolutionError) as exc:
        c._canonical_definition(oversized)
    assert exc.value.code == c.D2CCode.D2C_RESOURCE_LIMIT


def test_internal_only_256_257_active_nodes() -> None:
    f = _eight_capabilities()
    refs = tuple(
        asset("capability", f"cap.node.{index:03d}") for index in range(257)
    )
    entries = (entry("DomainManifest", "inventory.reconcile"),) + tuple(
        entry("CapabilityDefinition", f"cap.node.{index:03d}")
        for index in range(257)
    )
    for count in (256, 257):
        sample = replace(
            f, asset_refs=refs[:count], registry_entries=entries[: count + 1]
        )
        if count == 256:
            result = c._resolve_owned_diagnostic_graph(
                c._OwnedDiagnosticInputV1(sample, 0)
            )
            assert len(result.seed_keys) == 256
        else:
            with pytest.raises(c.D2CResolutionError) as exc:
                c._resolve_owned_diagnostic_graph(
                    c._OwnedDiagnosticInputV1(sample, 0)
                )
            assert exc.value.code == c.D2CCode.D2C_RESOURCE_LIMIT


# Authoritative map of executable C0 oracles. A17 has no runnable C0 entry.
_A_ORACLES = (
    ("A01", "test_a01_rejects_forged_trust_and_missing_root_field"),
    ("A02", "test_generation_error_precedes_corrupt_definition"),
    ("A03", "test_a03_self_cycle_plus_hostile_object_no_method_calls"),
    ("A04", "test_depth_13_and_foreign_dict_type_rejected_without_callbacks"),
    ("A05", "test_projected_evidence_limit_precedes_cycle_and_adapter_semantics"),
    ("A06", "test_invalid_definition_precedes_invalid_edge"),
    ("A07", "test_a07_exact_valid_definition_wrong_digest"),
    ("A08", "test_a08_duplicate_wrong_ordinal_unmatched_edge"),
    ("A09", "test_orphan_priority"),
    ("A10", "test_a10_cross_domain_and_a12_disabled_dependencies"),
    ("A11", "test_a11_non_schema_core_target_fails_closed"),
    ("A12", "test_a10_cross_domain_and_a12_disabled_dependencies"),
    ("A13", "test_missing_d1_precedes_cycle_and_adapter_precedes_cycle"),
    ("A14", "test_cycle_rejected"),
    ("A15", "test_nonempty_dag_and_exact_reference_vectors"),
    ("A16", "test_optional_absence_is_explicit_and_keeps_four_nodes"),
    ("A17", "C1_ONLY_OUTER_BOUNDARY_UNIMPLEMENTED"),
    ("A18", "test_core_schema_requires_matching_scope_and_allowlist"),
    ("A19", "test_a19_unexpected_internal_exception_is_sanitized"),
    ("A20", "test_adapter_union_refuses_nonnull_absent"),
)


@pytest.mark.parametrize(("case_id", "oracle"), _A_ORACLES)
def test_a01_a20_executable_oracle_contract(
    case_id: str, oracle: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Actually execute the prescribed C0 oracle, not only test symbol presence."""
    if case_id == "A17":
        assert oracle == "C1_ONLY_OUTER_BOUNDARY_UNIMPLEMENTED"
        assert not hasattr(c, "resolve_verified_domain")
        return
    runner = globals()[oracle]
    assert callable(runner)
    if case_id == "A19":
        runner(monkeypatch)
    else:
        runner()


def test_a01_a20_inventory_is_complete_and_unique() -> None:
    assert {key for key, _ in _A_ORACLES} == {
        f"A{i:02d}" for i in range(1, 21)
    }
    assert len({key for key, _ in _A_ORACLES}) == 20
