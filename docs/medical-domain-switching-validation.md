# Medical Domain Switching — Phase 1 Architecture Acceptance

Baseline: AgentRuntime main `7be7c34a8038b733b678b11b5e701944476e9a05`.
This validation deliberately does not build or evaluate clinical decision support.

## Intended product boundary

One reusable Agent Core hosts multiple *medical subdomains* via pinned domain
packages. A package owns domain-specific prompts, knowledge access, capabilities,
tools, state semantics, rules and evaluation criteria. Clinical safety decisions,
privileges and user-data access are enforced separately and must not be inferred
from a domain package or LLM recommendation alone.

Initial domains:
- `medical.chronic-management`: longitudinal metrics and follow-up workflows.
- `medical.mental-wellbeing`: wellbeing conversations and separately governed
  risk triage. No autonomous crisis evaluation is asserted here.
- Later: `medical.risk_prediction`: independently validated predictive model
  adapters and versioned input/output contracts, not free-form LLM diagnosis.

## Evidence now implemented

`tests/test_medical_domain_switching.py` assembles two *synthetic* medical
subdomains using the same verified package issuer, real M4 planning and existing
Agent coordinator. It asserts distinct identity/fingerprints/actions/strategies,
two approved sandbox actions per domain and bidirectional cross-domain tool
denial *before* execution. There are **no Core or Runtime changes** in this PR.

The package fixtures use inert collect/verify facts, not medical knowledge bases,
patient records, real disease prediction or actual mental-health assessments.
The deterministic model test double is NOT a real LLM test.

## Knowledge and Rule Switching Evidence (synthetic)

The two pinned medical packages now contain different, hash-verified knowledge,
prompt and rule JSON assets, with domain-specific required-knowledge keys.
`tests/test_medical_knowledge_rule_switching.py` checks these exact package
assets, separate per-domain admitted retrieval, role-separated model messages,
foreign-domain rejection and a known prompt injection pattern. Its FTS5
case uses a real in-memory SQLite full-text index but only synthetic content.
It does **not** prove medical guideline quality, clinical safety enforcement,
clinical triage, or model performance. Policy rule identifiers in model
contexts are illustrative; no production policy engine is switched by this test.

## Rule-driven Agent decision E2E (synthetic)

`tests/test_medical_rule_decision_e2e.py` uses the existing compatible GA03
verified medical content-package assembly, M4 and AgentRunCoordinator.
A *synthetic* chronic package sets `completion_after=verify` and performs two
approved mock steps; a *synthetic* wellbeing package sets
`completion_after=collect` and performs one approved mock step. Missing
package-required knowledge produces WAIT without invoking M4 or a tool.
These are intentionally different artificial completion rules used solely to
show the same Core follows selected domain-owned rule/knowledge gates.
The test transport deterministically selects actions: this does NOT establish
that a real LLM can autonomously choose correct medical workflow, and neither
rule represents appropriate clinical practice. The GA03 adapter supports
content-only packages; it is distinct from the mixed tool-workflow package
used by the SQLite test. Combining both representations into a deployable
medical business package still requires an integration contract.

## Required gates before claiming a usable medical Agent

| Gate | Required evidence | Phase 1 |
| --- | --- | --- |
| Package switch and Core reuse | Two different medical packages without Core changes | Implemented synthetic test |
| Cross-domain isolation | Both illegal action directions denied before execution | Implemented synthetic test |
| Real medical knowledge retrieval | Pinned sources, citations, freshness, contradiction handling | Not implemented; inert knowledge assets only |
| Clinical policies | Red-flag triage, human escalation, no unsafe automated advice | Not implemented |
| Domain state, consent and identity | Authorized per-person isolation and explicit cross-domain data access | Domain/fingerprint isolation tested; actual patient identity and consent NOT implemented |
| Multi-turn medical goal change | Verified medical domain context, state changes, and reapproval | Not implemented |
| Predictive model | Validated input schema, model version and clinical calibration | Not implemented |
| Actual model and realistic E2E | Frozen mixed-domain scenario matrix and independent grading | Not implemented |

## Next practical integration experiment

Build two small read-only *medical* domain packages on de-identified or fully
synthetic fixtures with distinct knowledge retrieval and tools. Run mixed
domain-specific tasks across both with unchanged Agent Core, report per-domain
task completion, factual grounding, cross-domain leakage, red-flag escalation,
and failure behaviour. Keep professional clinical review as an independent gate.
