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
