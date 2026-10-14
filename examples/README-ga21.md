# GA-21 — Multi-Turn Context & Goal Continuation

This is a **bounded in-process application feature**, built on the GA-20
real-model / M4 approved / read-only SQLite tool path. It is not durable memory,
production identity, or multi-agent orchestration.

Run with a trusted, previously published sandbox package and SQLite data:

```bash
python -m examples.ga21_cli --domain inventory --operator-config /absolute/path/inventory.json
```

Example interaction: `请查询库存` (verified tool run), `刚才结果`
(replays the previous grounded answer with a visible cached-data label, **no
tool execution**), `再查一次` (fresh approved GA-20 read-only run),
`取消` (terminate and clear the session goal).

The session is restricted to one selected domain, a fixed maximum number of
turns, and one process. The application never treats old tool observations as
fresh; refresh must execute a new run. Unsupported new tasks do not inherit
the previous goal or permissions. An error does not overwrite the last verified
result. No network side effect or tool-write path is enabled.

Current limitation: this supports explicit recall/refresh of a completed
goal, not arbitrary semantic follow-ups, paused workflow continuation, or
durable checkpoints. Those require separate evidence-backed capabilities.
