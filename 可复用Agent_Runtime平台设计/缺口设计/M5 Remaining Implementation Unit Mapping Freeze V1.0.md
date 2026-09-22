# M5 Remaining Implementation Unit Mapping Freeze V1.0

> Baseline：M5-IU1～IU6 = PASSED。
> Purpose：冻结 M5 后半段 Implementation Unit 与 M5 V2.0 Step 9～12 的一一映射，避免后续 IU 编号、设计范围和执行顺序再次漂移。

## 1. Frozen mapping

~~~text
M5-IU7  = Step 9  Cancellation / Preemption
M5-IU8  = Step 10 Concurrency / Resource Lock
M5-IU9  = Step 11 Persistence / Checkpoint / Recovery
M5-IU10 = Step 12 Execution Aggregation
~~~

正式实施顺序：

~~~text
M5-IU6 Timeout / Retry / Idempotency        = PASSED
↓
M5-IU7 Cancellation / Preemption
↓
M5-IU8 Concurrency / Resource Lock
↓
M5-IU9 Persistence / Checkpoint / Recovery
↓
M5-IU10 Execution Aggregation
↓
M5 Closure Review
↓
M6 Validation
~~~

## 2. Mapping invariants

### 2.1 IU7 不拥有 IU6 authority

~~~text
IU7 consumes resolved control facts
!= recompute Timeout / Retry / Idempotency
~~~

如果 control reason 为 TIMEOUT，IU7 只消费已经形成的 execution-control fact，不重新解释 timeout_policy。

### 2.2 IU7 不提前进入 IU8

~~~text
Cancellation / Preemption
!= Resource Lock policy
~~~

IU7 可以请求 operation-local cleanup，但 session/resource lock acquisition/release policy 正式归 IU8。

### 2.3 IU8 不提前进入 IU9

~~~text
live concurrency / lock coordination
!= durable checkpoint / crash recovery
~~~

IU8 可使用注入式 live lock provider；durable lock recovery / persisted ownership 属于 IU9。

### 2.4 IU9 不提前进入 IU10

~~~text
Persistence / Checkpoint / Recovery
!= canonical ExecutionResult aggregation
~~~

IU9 只保证运行事实可恢复；不决定最终 plan_status / business aggregation。

### 2.5 IU10 才进入 canonical ExecutionResult aggregation

只有 IU10 可以正式把：

~~~text
Step lifecycle
Step attempt observations
Skill / Workflow / Tool evidence
control evidence
reliability evidence
checkpoint/recovery evidence
~~~

聚合为 canonical ExecutionResult，并把结果交给 M6。

## 3. Deferred debt ownership

此前明确后置的债务正式归属：

~~~text
Workflow WAITING durability     -> M5-IU9
Workflow resume / recovery      -> M5-IU9
durable attempt history         -> M5-IU9
Crash Recovery                  -> M5-IU9
Resource Lock                   -> M5-IU8
Cancellation / Preemption       -> M5-IU7
canonical ExecutionResult       -> M5-IU10
M6 handoff                      -> after M5-IU10 / M5 Closure
~~~

## 4. Frozen status

~~~text
M5 REMAINING IU MAPPING = FROZEN

M5-IU7  = STEP 9
M5-IU8  = STEP 10
M5-IU9  = STEP 11
M5-IU10 = STEP 12

NEXT = M5-IU7 Implementation Design + Readiness Review
~~~