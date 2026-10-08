# CA-M5-IU4-01 Execution Ownership + Core-controlled Invocation Boundary V1.0

> Baseline: M5-IU3 = PASSED @ `1018d707`
> Target: close M5-IU4 readiness blockers only.
> This amendment does **not** implement real Skill / Workflow / Tool invocation.

## 1. Blockers addressed

```text
B-M5-IU4-001 CAPABILITY_EXECUTION_OWNER_NOT_FROZEN
B-M5-IU4-002 CORE_CONTROLLED_TOOL_INVOCATION_BOUNDARY_MISSING
B-M5-IU4-003 TOOL_INVOCATION_VALIDATION_CONTRACT_MISSING
B-M5-IU4-004 CAPABILITY_INVOCATION_IDENTIFIER_FACTORY_MISSING
B-M5-IU4-005 WORKFLOW_TOOL_AUTHORITY_NOT_REPRESENTABLE
```

## 2. Approval-time execution owner

M4 internal `CapabilityBinding` adds an optional compatibility field at the end:

```text
execution_owner = SKILL | WORKFLOW | NONE
```

Formal planning path normalizes and freezes it before Draft assembly.

Rules:

```text
skill only            -> SKILL
forced workflow       -> WORKFLOW
workflow only         -> WORKFLOW
skill + workflow rule -> explicit owner required
no capability         -> NONE
```

Assembler writes:

```text
capability_plan.bindings[].execution_owner
```

PlanValidator requires owner presence and owner/reference consistency.

Canonical `ActionStep`, top-level `ApprovedActionPlan`, and `PolicyDecision` are unchanged.

## 3. Workflow Tool authority

`WorkflowDefinition` now supports backward-compatible optional metadata:

```text
required_tools
optional_tools
```

M4 ToolPlan adds:

```text
tool_calls[].required_by_workflows
```

ToolPlanner derives Tool authority from the **execution owner**:

```text
SKILL owner
-> SkillDefinition.required_tools / optional_tools
-> required_by_skills

WORKFLOW owner
-> WorkflowDefinition.required_tools / optional_tools
-> required_by_workflows

NONE owner
-> no owner Tool authority
```

SequencePlanner projects `ActionStep.tool_requirement` from the same owner-specific provenance.

## 4. PlanValidator owner/provenance integrity

Validator now checks:

```text
required_by_skills     -> owner Skills only
required_by_workflows  -> owner Workflows only

owner provenance
== exact Definition.required_tools
```

This prevents both omission and expansion of owner-required Tool authority.

Optional Tool calls may remain provenance-free in this amendment because optional Tool invocation is still disabled by `TD-M5-IU3-04`.

## 5. IU3 controlled amendment

IU3 `ApprovedStepCapabilityProjector` now consumes frozen `execution_owner`.

`ResolvedStepCapabilities` carries:

```text
execution_owner
```

Tool projection is owner-specific:

```text
SKILL    -> required_by_skills
WORKFLOW -> required_by_workflows
NONE     -> no owner Tool projection
```

A Step-level `tool_requirement` inconsistent with owner provenance fails closed.

### 5.1 Only the execution owner is runtime-gated

When an Approved binding contains both Skill and Workflow, IU3 no longer resolves/state-gates the non-owner capability.

Example:

```text
skill_id = S
workflow_id = W
execution_owner = WORKFLOW
```

Runtime gating applies to:

```text
W + W's approved Tool set
```

Current Skill Registry drift or Skill allowed_state cannot block W because S will not execute.

The non-owner reference remains ApprovedPlan metadata and still must be structurally pinned/consistent.

## 6. Core-controlled invocation contracts

New internal module:

```text
runtime/execution/invocation.py
```

Freezes:

```text
ApprovedToolInvoker
ToolInvocationJournalReader
ToolInvocationJournalEntry

ToolPayloadValidationStatus
ToolPayloadValidationDecision
ToolInputValidator
ToolOutputValidator

CapabilityInvocationIdentifierFactory
```

No concrete Tool invocation occurs in the amendment.

## 7. Skill / Workflow protocol amendment

```python
SkillImplementation.execute(
    request,
    execution_context,
    tool_invoker,
)

WorkflowImplementation.start(
    request,
    execution_context,
    tool_invoker,
)

WorkflowImplementation.resume(
    request,
    execution_context,
    tool_invoker,
)
```

The later IU4 executor must supply the Core-owned invoker.

This amendment defines the authorized path but does not claim that arbitrary Python Domain code is sandboxed from making unrelated external calls. Domain packages must conform to the Runtime implementation contract; real Tool truth recognized by Core can only come from the Core gateway/journal.

## 8. Authoritative Tool journal

The Core invocation journal binds:

```text
tool_call_id
tool_id
approved tool_version
permission status
input validation status
output validation status
final M5ToolResult
```

Domain-returned nested `tool_results` are not independent truth. Later IU4 execution must reconcile them against the gateway journal.

## 9. Validation boundary

Input/output validation contracts are now injectable.

The actual IU4 implementation must enforce:

```text
Input INVALID / UNKNOWN
-> do not invoke Tool

Tool non-success
-> validator must never upgrade to SUCCESS

Tool SUCCESS + invalid/unknown output
-> fail closed / preserve possible side-effect ambiguity
```

Schema resolution must not silently choose a latest version. Ambiguous schema references must fail closed in the injected validator.

## 10. Invocation IDs

`CapabilityInvocationIdentifierFactory` owns:

```text
new_tool_call_id(...)
new_workflow_instance_id(...)
```

No UUID/random policy is hardcoded into Core.

## 11. Explicitly still out of scope

```text
real Skill.execute invocation
real Workflow.start/resume invocation
real Tool.invoke invocation
Retry
Timeout enforcement
Idempotency
Resource Lock
Cancellation / Preemption side effects
Workflow resume routing
Checkpoint / Recovery
Execution aggregation
M6
Response
State / Memory update
```

## 12. Regression coverage added/updated

Coverage includes:

```text
auto Skill owner freeze
forced Workflow owner freeze
skill+workflow rule requires explicit owner
Workflow Tool provenance
owner-specific SequencePlanner tool_requirement
Draft owner preservation
PlanValidator owner/provenance integrity
Approval owner/provenance preservation
IU3 missing-owner fail closed
IU3 Workflow owner cannot inherit Skill Tool
IU3 only runtime-gates current owner
Workflow metadata backward compatibility
invocation validation/ID/journal contracts
Canonical contracts remain unchanged
```

## 13. Current amendment status

Verified HEAD before documentation-only closure update:

```text
2fa430fac88502c59cbc33ae263bf83822c2eb5e
```

Verification evidence:

```text
pytest = PASSED (529 passed)
mypy = PASSED (166 files)
ruff check = PASSED
ruff format --check = PASSED (166 files)
```

Formal closure:

```text
B-M5-IU4-001 = CLOSED
B-M5-IU4-002 = CLOSED
B-M5-IU4-003 = CLOSED
B-M5-IU4-004 = CLOSED
B-M5-IU4-005 = CLOSED

CA-M5-IU4-01 TARGETED AMENDMENT REVIEW = PASSED
CA-M5-IU4-01 VERIFICATION = PASSED
CA-M5-IU4-01 = PASSED

M5-IU4 IMPLEMENTATION READINESS = READY
M5 = IN PROGRESS
```
