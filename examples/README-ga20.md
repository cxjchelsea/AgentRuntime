# GA-20 — Operator-Pinned Read-Only Agent Application (Linux Sandbox)

The executable CLI uses the **application-owned** `ReadOnlyApplicationStep`
with the existing M1 input normalizer, M2 safety/policy/constraint evaluation,
the composed M3 RuntimeUnderstandingEngine with injected deterministic domain rules, M4 plan/validate/recheck, GA-09 read-only dispatcher,
and evidence-bound business answer. The executable has **no imports from
`tests/`**.

This is a local sandbox integration, not a production M6 grant. M3 uses only domain-owned deterministic text rules for this bounded demo.
Requests with no supported deterministic interpretation have no deep-model fallback. The local host configuration is self-pinned,
not independently authenticated as a production publisher. Only previously
existing SQLite business data are read; no purchase, stock modification,
or task mutation is performed.

Prerequisites: Linux, Python 3.11 and project dependencies, an approved
OpenAI-compatible model endpoint (default Ollama `qwen2.5:3b`).

```bash
python -m examples.ga20_sandbox_cli \
  --operator-config /absolute/path/inventory.json \
  --domain inventory \
  --question "请查询库存并计算需要补货多少件"
```

The JSON contains exactly these properties:

```json
{
  "domain": "inventory.reconcile",
  "package_root": "/absolute/published/package",
  "generation_id": "sandbox-gen-1",
  "domain_version": "1.0.0",
  "runtime_profile": "GA02-D1-1",
  "manifest_digest": "64 lowercase hex characters from the pinned manifest",
  "database_file": "/absolute/data/business.sqlite",
  "step_keys": {"step-1": "sku-1"}
}
```

For `--domain learning` use a `learning.plan` package and provide every
workflow step key. The existing `business_records` SQLite table needs
domain_id, binding_fingerprint, record_key, value and sha256 columns.
Changing package/DB without updating pinned values is rejected.

Only the **test** command below creates synthetic business data:

```bash
python -m tests.ga20_fixture_prepare --output-dir /tmp/ga20-business-fixtures
python -m examples.ga20_sandbox_cli \
  --operator-config /tmp/ga20-business-fixtures/inventory.json \
  --domain inventory --question "查询库存需要补货多少"
```

The CLI will reject missing operator configuration and unsupported questions.
Each invocation is independent; GA-21 will address multi-turn state/continuation.
Run IDs and local identities are intentionally fixed to the isolated sandbox
profile and **must not** be reused as production tenant/session identity.

## GA-20 trust and deployment boundary

The operator JSON pins bytes and domain identities, but its in-process equality
verifier **does not prove independent publisher identity**. This application is
restricted to a trusted local operator, read-only data, and sandbox tool handlers.
A production host must supply independently authenticated publication evidence,
permissioned execution, and durable identity/session management separately.
Do not classify this integration as production security authorization.
