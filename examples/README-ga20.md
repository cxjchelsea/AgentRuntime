# GA-20 Interactive Business Agent Sandbox

A **Linux-only experimental** entry point wrapping the existing GA-15 read-only
Qwen → M4 → sandbox dispatcher → SQLite observation → verified answer chain.
It deliberately imports existing test fixture package publishers and generates
**synthetic SQLite data** for each run. It is **not yet** a general-purpose
production Agent, an external business connector, or a persisted conversation.

Prerequisites: Python 3.11, `pip install -e '.[test]'`, an accessible
OpenAI-compatible model endpoint (for local Ollama, pull `qwen2.5:3b`).

```bash
python -m examples.ga20_sandbox_cli --domain inventory --question '请帮我查库存并计算需要补货多少件'
python -m examples.ga20_sandbox_cli --domain learning --question '请帮我查学习进度与剩余学习任务'
```

Configure `GA01C_LLM_URL`, `GA01C_LLM_MODEL` and (for remote HTTPS)
`GA01C_LLM_API_KEY` if the default local Ollama endpoint is not used.
Omit `--question` to type one task interactively. There is no multi-turn
memory. Unsupported requests are rejected. The inventory example uses
8 on hand / 3 reserved / target 12; the study example uses 2/5 completed.

This slice proves an interactive entry path only. Before claiming domain
portability, GA-20 must replace fixture dependency with a supported installed
Domain Package and external read-only source, demonstrate real-model CLI E2E,
and add a governed session boundary. Never interpret computed replenishment
as a real inventory mutation.

## Operator-pinned external data (Linux sandbox)

The CLI additionally supports an **existing** verified package directory and
an **existing** SQLite `business_records` table, without generating fixture
records. Set `--operator-config /absolute/path/source.json`. The JSON must
contain exactly:

```json
{
  "domain": "inventory.reconcile",
  "package_root": "/absolute/published/package",
  "generation_id": "sandbox-gen-1",
  "domain_version": "1.0.0",
  "runtime_profile": "GA02-D1-1",
  "manifest_digest": "64 lowercase hex characters from the pinned package manifest",
  "database_file": "/absolute/data/business.sqlite",
  "step_keys": {"step-1": "sku-1"}
}
```

For the learning CLI, the package domain is `learning.plan` and
`step_keys` must match all workflow steps. Package and database must
already exist, with matching domain ID, package binding fingerprint, source
records and sha256. A record key maps to one SQLite row. There is no
auto-import, write operation, or model-supplied SQL.

**Trust limitation:** the configuration and verifier are under the same
local operator's control. The CLI does **not** authenticate independent
publication or grant physical host execution authority. It still reuses
the test-only `ModelDrivenSandboxTurn` and runtime-input fixture.
This external-source option demonstrates application wiring, not production
readiness or general natural-language task classification.
