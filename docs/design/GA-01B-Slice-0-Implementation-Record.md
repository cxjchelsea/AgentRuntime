# GA-01B Slice 0：实现记录与验证边界

- 父设计：PR #91 GA-01A，精确 HEAD `51619ea1f6f0123419f96cd145c2642adb50df11`。
- 实现范围：M2 shared admission 最小重构；内部 AgentRunBinding + IterationRef/Correlation；测试专用 Mock Executor / SandboxObservation；初步接口/隔离测试。
- **不包含**：Agent Loop Coordinator、第二轮模型决策、M6 正向 Grant、M7/M8 正式提交、生产 Tool。
- G01：共享判定逻辑已在源码中提取；须以真实 G2 回归证明未改动异常优先级。
- G02：构造 SYSTEM_EVENT 输入并用真实 DefaultInputProcessor 测试；还需真实 DefaultContextBuilder/M3/M4 集成测试，不能标称 G02 完整通过。
- G03：Mock 和 verifier 仅放 `tests/ga01/`，仅出 `SandboxObservation`；须进一步证明 G1/G2 deny-only 和生产 DI 不能获得测试权限。
- 本次通过 GitHub 直接提交修改；无法直接 `git clone` 到本地运行环境（网络 DNS），因此**没有真实 pytest/mypy/ruff 成功日志**；远端 CI 若无真实 job 证据，不得把它算作 VERIFIED。

## 待完成测试

1. `python -m pytest tests/test_m2_runtime_integration_gate.py tests/test_m6_iu1_b2_dual_runtime.py tests/test_ga01_slice0.py -q`
2. `python -m pytest tests -q`
3. `python -m mypy runtime agent_core tests`
4. `python -m ruff check runtime agent_core tests`
5. `python -m ruff format --check runtime agent_core tests`

正式 `GA-01B Slice 0 = PASSED` 只能基于同一 HEAD 的测试执行、格式与类型检查、G2/M6 negative parity 以及 G02 M3/Context 接线证明。现阶段标为 `IMPLEMENTED_UNVERIFIED`，而非 CLOSED。
