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
- `medical.chronic_management`: longitudinal metrics and follow-up workflows.
- `medical.mental_wellbeing`: wellbeing conversations and separately governed
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

## Required gates before claiming a usable medical Agent

| Gate | Required evidence | Phase 1 |
| --- | --- | --- |
| Package switch and Core reuse | Two different medical packages without Core changes | Implemented synthetic test |
| Cross-domain isolation | Both illegal action directions denied before execution | Implemented synthetic test |
| Real medical knowledge retrieval | Pinned sources, citations, freshness, contradiction handling | Not implemented |
| Clinical policies | Red-flag triage, human escalation, no unsafe automated advice | Not implemented |
| Domain state, consent and identity | Authorized per-person isolation and explicit cross-domain data access | Not implemented |
| Multi-turn medical goal change | Verified medical domain context, state changes, and reapproval | Not implemented |
| Predictive model | Validated input schema, model version and clinical calibration | Not implemented |
| Actual model and realistic E2E | Frozen mixed-domain scenario matrix and independent grading | Not implemented |

## Next practical integration experiment

Build two small read-only *medical* domain packages on de-identified or fully
synthetic fixtures with distinct knowledge retrieval and tools. Run mixed
domain-specific tasks across both with unchanged Agent Core, report per-domain
task completion, factual grounding, cross-domain leakage, red-flag escalation,
and failure behaviour. Keep professional clinical review as an independent gate.
