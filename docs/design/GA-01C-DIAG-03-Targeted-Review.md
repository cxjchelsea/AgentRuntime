# GA-01C DIAG-03 Targeted Independent Review — Typed Consumer

## Review baseline

- Stacked original PR #101, exact review base HEAD `430a179fd8d5511414a3aea59702354b087efd43`.
- Original M4 request has optional `planning_observation`; DIAG-03 test's outbound model payload omits the old `last_agent_action`.
- M4 StrategyEligibilityRule still ran through DIAG-01's JSON-in-`last_agent_action` internally, even though model input had migrated. That is a material incomplete consumer migration.
- `StrategyModelRequestBuilder` originally invoked a zero-argument projection callback, without supplying current request ID. This is an insufficiently bound opt-in read-side extension; it does not by itself establish trust.

## Narrow remediation

1. Test-only DIAG-03 `TrustedTypedEligibility` reads the **same projected context object** as the model, populated exclusively by DIAG-02 initial-state admission or SandboxObservationProjector-verified executions. It no longer parses DIAG-01's legacy JSON for the M4 decision. Only the collection strategy is declined with admitted `AVAILABLE_UNVERIFIED`, and the existing M4 Policy/Recheck remains authoritative.
2. M4 optional `observation_provider` callback receives `request_id`; the sandbox binding guard refuses foreign request IDs. Existing **no-provider** consumers are unchanged. This is a compatibility adjustment to an experimental PR #101 opt-in interface, not a production security token.
3. Negative tests reject cross-Run model reads and prevent forged user-text JSON from triggering eligibility restrictions.

## Important unsolved risks

- The schema still has only `source_scope` and evidence reference strings; no complete immutable run/subject/tenant scope binding in the DTO itself. Test assembly holds a per-Run binding; **production composition still not authorized**.
- Private in-process evidence projector ownership prevents user text from acting as authority in this sandbox. It is not a signed or durable proof and does not protect arbitrary dependency injection or malicious plugin code.
- The optional M4 request-builder API signature change requires external consumers to adapt if they already supplied their own experimental callback. Run full mypy/pytest gates.
- Qwen3B can emit invalid JSON/strategy despite a correct contract. Re-run real model E2E and report intermittent failures; do not lower the validator or scoring thresholds.

## Acceptance gates

- All normal pytest/mypy/Ruff at exact branch HEAD.
- Actual local Qwen3B DIAG-03 twelve-task E2E (not skipped), original thresholds 10/12 completed, at least 90% action correctness, zero unclassified model errors.
- PR stays Draft and stacked, without actual Tool execution, M6 positive grant or main merge.
