"""GA-03 test-only content assembly: prompt, rule, knowledge, and M4 assets.

Assets are bounded, inert and hash checked; this is NOT RAG retrieval, a
production PromptBuilder, M2 policy permission, nor trusted C1 admission.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any

from agent_core.sandbox_domain_assembly import SandboxAssemblyError, SandboxDomainBinding
from tests.ga02_d4_domain_m4_assembly import SandboxM4Domain, assemble_sandbox_m4


def _asset_dict(raw: bytes, keys: set[str]) -> dict[str, str]:
    if type(raw) is not bytes or len(raw) > 4096:
        raise SandboxAssemblyError("invalid domain extension asset")

    def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SandboxAssemblyError("duplicate domain extension field")
            result[key] = value
        return result

    try:
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
    except (ValueError, UnicodeError) as exc:
        raise SandboxAssemblyError("malformed domain extension JSON") from exc
    if (
        type(decoded) is not dict
        or decoded.keys() != keys
        or any(type(v) is not str or not v or len(v) > 256 for v in decoded.values())
    ):
        raise SandboxAssemblyError("domain extension schema mismatch")
    return decoded


@dataclass(frozen=True, slots=True)
class SandboxDomainKnowledge:
    m4: SandboxM4Domain
    prompt_focus: str
    rule_required_key: str
    completion_after: str
    knowledge_key: str
    knowledge_fact: str

    def admitted_knowledge(self, *, available: frozenset[str]) -> tuple[str, ...]:
        """Inert exact-key lookup; does not infer evidence from a prompt or LLM."""
        if self.rule_required_key not in available:
            return ()
        return (self.knowledge_fact,)


def assemble_ga03_domain(binding: SandboxDomainBinding) -> SandboxDomainKnowledge:
    if type(binding) is not SandboxDomainBinding or binding.role != (
        "SANDBOX_NON_AUTHORITATIVE_DOMAIN_BINDING"
    ):
        raise SandboxAssemblyError("invalid GA03 sandbox binding")

    additional: dict[str, dict[str, str]] = {}
    base_assets = []
    for asset in binding.assets:
        if (
            type(asset.content_bytes) is not bytes
            or hashlib.sha256(asset.content_bytes).hexdigest() != asset.sha256
            or asset.namespace != binding.domain_id
            or asset.version != "1.0.0"
        ):
            raise SandboxAssemblyError("GA03 asset digest or namespace mismatch")
        if asset.kind in {"action", "strategy"}:
            base_assets.append(asset)
            continue
        schemas = {
            "prompt": {"focus"},
            "rule": {"required_knowledge", "completion_after"},
            "knowledge": {"key", "fact"},
        }
        if asset.kind not in schemas or asset.kind in additional:
            raise SandboxAssemblyError("unknown or duplicate GA03 asset")
        additional[asset.kind] = _asset_dict(
            asset.content_bytes, schemas[asset.kind]
        )

    if set(additional) != {"prompt", "rule", "knowledge"}:
        raise SandboxAssemblyError("missing GA03 domain asset")
    rule = additional["rule"]
    knowledge = additional["knowledge"]
    if (
        rule["required_knowledge"] != knowledge["key"]
        or rule["completion_after"] not in {"collect", "verify"}
    ):
        raise SandboxAssemblyError("GA03 rule/knowledge mismatch")

    # D4 knows Action/Strategy only. Preserve the original full identity and
    # run fingerprint; this projected view never creates a trusted Host claim.
    projected = replace(binding, assets=tuple(base_assets))
    m4 = assemble_sandbox_m4(projected)
    m4 = replace(m4, binding=binding)
    return SandboxDomainKnowledge(
        m4=m4,
        prompt_focus=additional["prompt"]["focus"],
        rule_required_key=rule["required_knowledge"],
        completion_after=rule["completion_after"],
        knowledge_key=knowledge["key"],
        knowledge_fact=knowledge["fact"],
    )
