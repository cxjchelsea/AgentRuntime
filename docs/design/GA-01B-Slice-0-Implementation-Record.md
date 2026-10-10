# GA-01B Slice 0｜实现与真实验证记录

> 当前基线：PR #92，stacked on PR #91 / GA-01A。本文证据对应**已验证代码 HEAD** `24eb304b50e9334c239f8aad0c5c23f9457647ca`。后续文档性提交不改变代码执行结果，但最终 PR 仍需基于新 HEAD 复核 GitHub Actions。
>
> **状态：SLICE_0_TARGETED_VERIFIED（仅 Slice 0）。不代表 Agent Loop 实现完成或获得 M6 生产授权。**

## 已实现

- G01：`runtime/orchestration/m2_admission.py` 唯一共享的 M2 增强 Admission，G2 的现有 Orchestrator 代理调用；保留 Policy blocked → incoming disposition → preemption 判定顺序。
- G02：`agent_core/iteration.py` 建立 `AgentRunBinding` / `IterationRef` 和执行结果结构关联；内部后续事件为 `SYSTEM_EVENT`，与原用户信息分开；真实 DefaultInputProcessor 和集成 M1/M2/M3/M4 fixture 测试。
- G03：MockExecutor / SandboxObservation 位于 `tests/ga01/`；不生成权威 `ValidatedResult`，检验 M6 结构一致性但不授予业务真相或生产权限；负测覆盖重入、未成功结果、跨域和假冒 plan/fingerprint。
- CI：`.github/workflows/ga01b-slice0.yml`，Python 3.11；显式包发现和 pytest-asyncio 解决运行环境问题。
- 原有 M2 源码位置敏感测试改为检查抽取后的真实公共组件；M5 原有 tool journal 仅做静态类型收窄，未改变执行语义；清理少量旧版 linter 指令与新增文件格式。

## 精确证据（运行完成）

- <https://github.com/cxjchelsea/AgentRuntime/actions/runs/38011840300>：push workflow SUCCESS。
- <https://github.com/cxjchelsea/AgentRuntime/actions/runs/38011843566>：PR workflow SUCCESS。
- 定向测试：**76 passed**（G01/G02/G03、M2、G1/G2 NoGrant）。
- 全量 pytest：**1162 passed, 1 warning**。
- mypy `runtime agent_core tests`：**Success, 239 source files**。
- ruff check：**All checks passed**。
- ruff format --check：**239 files already formatted**。

## 不得夸大范围

1. Slice 0 **没有** AgentRunCoordinator 多轮决策；观察驱动第二次行动属于后续 Slice。
2. G02 中真实 M1/M2/M3/M4 的 `SYSTEM_EVENT` 兼容由既有集成 fixture（含 RequestAwareUnderstandingEngine）验证，**不是证明所有真实模型 Provider 均支持**。
3. G03 目前证明测试型 Sandbox 与现有 G1/G2 隔离；生产 Composition Root 尚未装配，所以无法声称已证明生产 DI 否定用例。
4. M6 B3 正向授权仍未实现；任何 Mock SUCCESS 不能视为生产结果验证。
5. PR #91 仍为当前 stacked base；合并顺序需要先解决 PR #91，再处理 PR #92。

## 后续开发

下一小切片：正式 `AgentRunCoordinator` 的最小 Observe→Decide→Act→Observe→FINISH；使用原 M3/M4/M5 接口、沙箱证据与预算抑制，并保留 G2 NoGrant 的隔离。进入该切片后更新真实任务 E2E 证据，而不是继续建设更多 Runtime 子模块。
