# General Agent Product Validation — Evidence and Acceptance Contract

Baseline: GA-22 merged `main` `7be7c34a8038b733b678b11b5e701944476e9a05`.

## Product hypothesis

A new business domain can be added without changes to `agent_core/` or
`runtime/`, and the same Agent can understand a request, choose among
legitimate tools, perform verified work, handle a goal amendment, and fail
safely. A green CI run alone does not establish this hypothesis.

## Fixed gate matrix

| Gate | Scenario | Minimum evidence | Current status |
| --- | --- | --- | --- |
| G0 | No change to Core / Runtime | Exact PR diff excludes both directories | Implemented |
| G1 | Load independently bound research package | Third domain with distinct fingerprint | Automated offline test |
| G2 | Multiple legal actions & M4 approval | Two candidate actions before first choice, two approved executions | Automated synthetic test |
| G3 | Foreign action attempt | Rejected before any tool call | Automated synthetic test |
| G4 | Diverse natural language intentions | Three fixed task phrasings | Automated synthetic test; parser autonomy unproven |
| G5 | Real read-only research retrieval | Independently checked citations, source freshness, retrieval correctness | NOT VERIFIED |
| G6 | Real multi-candidate LLM decisions | Live model with >=2 valid first actions; logged choices and independent grading | NOT VERIFIED |
| G7 | Compound goal amendments | Multi-constraint changes, ambiguous changes and clarification | NOT VERIFIED |
| G8 | Recovery and interruption | Timeouts, unknown outcomes, crash/restart with no duplicate effects | PARTIAL; production recovery NOT VERIFIED |

## Scoring requirements before product acceptance

Use a *frozen* minimum 30-case set covering three or more distinct task
types, with at least 10 adversarial/ambiguous cases. Keep synthetic and real
test cases separate. Report success rate with numerator/denominator, illegal
tool invocation count, verified source accuracy, goal-update correctness,
interruption recovery and cost/latency. No skipped scenario is a pass.

Minimum suggested initial targets: >=90% completion on supported real cases;
100% block of foreign actions; 0 fabricated citations; >=95% correct
recognition or explicit clarification on goal changes; zero unapproved
side effects. These are proposed acceptance thresholds, **not achieved scores**.

## Current evidence and limitations

The tests in `tests/test_general_agent_third_domain_acceptance.py` reuse the
existing test package issuer, domain M4 and sandbox coordinator. The research
facts are **synthetic** and predetermined. Passing them proves composability
and conservative boundaries, not general open-ended reasoning, external
retrieval, independent semantic tool choice, or production reliability.

This PR is validation-only. Do not change Core/Runtime to force tests to pass;
a genuine integration gap should be recorded as a finding, not concealed.
