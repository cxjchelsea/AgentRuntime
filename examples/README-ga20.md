# GA-20 — Operator-Pinned Read-Only Agent Application (Linux Sandbox)

The executable CLI uses the **application-owned** `ReadOnlyApplicationStep`
with the existing M1 input normalizer, M2 safety/policy/constraint evaluation,
M3 understanding contract, M4 plan/validate/recheck, GA-09 read-only dispatcher,
and evidence-bound business answer. The executable has **no imports from
`tests/`**.

This is a local sandbox integration, not a production M6 grant. The current
M3 understanding is a limited explicit domain-goal declaration rather than
general intent understanding. The local host configuration is self-pinned,
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
