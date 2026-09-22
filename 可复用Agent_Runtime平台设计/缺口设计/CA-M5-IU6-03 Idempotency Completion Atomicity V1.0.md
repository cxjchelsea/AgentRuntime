# CA-M5-IU6-03 Idempotency Completion Atomicity V1.0

> Purpose：关闭 Formal Implementation 阶段新发现的 B-M5-IU6-007。
> Baseline：CA-M5-IU6-01 = PASSED，CA-M5-IU6-02 = PASSED。
> 本 Amendment 只补齐 KEY_BASED Tool 成功后的原子 completion authority；不实现 Retry loop、Tool invoke orchestration、Step retry、finish_step、Aggregation 或 M6。

## 1. Blocker

~~~text
B-M5-IU6-007
IDEMPOTENCY_COMPLETED_RESULT_RECORDING_AUTHORITY_MISSING
~~~

CA-02 已冻结：

~~~text
IdempotencyResultResolver.resolve_completed(record)
~~~

但没有 authority 负责首次成功时原子完成：

~~~text
可信保存 M5ToolResult
+
生成 result_reference
+
RESERVED -> COMPLETED
~~~

如果拆成 result persistence 与 mark_completed 两步，会形成 crash window，导致 record 与可恢复结果不一致。

## 2. 新增合同

新增：

~~~text
IdempotencyCompletionStatus
- COMPLETED
- CONFLICT
- UNKNOWN

IdempotencyCompletionDecision
- status
- reason_codes
- completed_record?

IdempotencyCompletionAuthority.complete(...)
~~~

## 3. Completion Authority

正式接口：

~~~text
complete(
  reserved_record: IdempotencyRecord,
  result: M5ToolResult
)
-> IdempotencyCompletionDecision
~~~

唯一职责：

~~~text
atomic {
  persist trusted result
  generate opaque recoverable result_reference
  verify exact RESERVED provenance
  transition RESERVED -> COMPLETED
}
~~~

它不得：

~~~text
调用 Tool
决定 Retry
改变 Tool/version/operation provenance
重新生成业务结果
修改 Step lifecycle
进入 M6
~~~

## 4. COMPLETED decision

只有成功完成整个原子操作才能返回：

~~~text
status = COMPLETED
completed_record.status = COMPLETED
~~~

Formal Implementation caller 还必须验证：

~~~text
completed_record.key == reserved_record.key
completed_record.execution_id == reserved_record.execution_id
completed_record.step_id == reserved_record.step_id
completed_record.step_execution_id == reserved_record.step_execution_id
completed_record.tool_id == reserved_record.tool_id
completed_record.tool_version == reserved_record.tool_version
completed_record.operation_key == reserved_record.operation_key
completed_record.operation_fingerprint == reserved_record.operation_fingerprint
completed_record.tool_call_id == result.tool_call_id
completed_record.result_reference 非空
~~~

任一不一致必须 fail closed，不能接受为 COMPLETED。

## 5. CONFLICT / UNKNOWN

~~~text
CONFLICT
→ another state/provenance won the atomic transition
→ 不得携带 completed_record

UNKNOWN
→ completion outcome 无法可信确认
→ 不得携带 completed_record
→ 不得假设可 Retry
~~~

UNKNOWN completion 必须进入 replay-safety / recovery 路径，不能重新 reserve 或盲目 invoke。

## 6. 与现有 IdempotencyStore 的关系

现有：

~~~text
mark_completed(key, tool_call_id, result_reference)
~~~

保留兼容，不作为 IU6 KEY_BASED production completion 的首选 authority。

IU6 Formal Implementation 使用：

~~~text
IdempotencyCompletionAuthority
~~~

以避免“结果存储”和“状态提交”由两个无原子性的组件分别执行。

## 7. Explicit non-goals

本 Amendment 不实现：

~~~text
Tool retry coordinator
Timeout runner wiring
Idempotency preflight execution
Tool operation correlation execution
Step attempt retry
Step finalization execution
Workflow auto-retry
finish_step
Aggregation
M6
~~~

## 8. Blocker closure rule

B-M5-IU6-007 只有以下全部满足后才可 CLOSED：

~~~text
1. atomic completion contract exists
2. COMPLETED requires completed record
3. CONFLICT / UNKNOWN cannot expose completed record
4. exact provenance/result identity validation is required by caller
5. Targeted Amendment Review = PASSED
6. four local gates = GREEN
7. no Retry/Tool invoke/lifecycle/M6 authority leaked into CA-03
~~~

## 9. Current status

~~~text
CA-M5-IU6-03 = CODE COMPLETE
CA-M5-IU6-03 TARGETED AMENDMENT REVIEW = PENDING
CA-M5-IU6-03 VERIFICATION = PENDING FOUR LOCAL GATES

B-M5-IU6-007 = FIX_IMPLEMENTED_PENDING_REVIEW_AND_GATES

M5-IU6 IMPLEMENTATION READINESS = NOT_READY
M5-IU6 FORMAL IMPLEMENTATION = PAUSED
M5 = IN PROGRESS
~~~