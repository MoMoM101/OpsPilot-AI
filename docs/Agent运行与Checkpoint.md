# Agent 运行与 Checkpoint

> 状态：Phase 3 LangGraph、PydanticAI Provider、恢复 Worker 与模型预算已实现  
> 更新时间：2026-08-11

## 1. 目标

InvestigationRun 是一次可暂停、可恢复的 Agent 调查执行。它把执行事实保存在 PostgreSQL，
避免 Control Plane 重启后只能从头开始，也避免依靠进程内对象判断节点是否已经完成。

当前实现提供运行状态、稳定 Thread ID、图版本、迭代上限、乐观锁、结构化 Checkpoint 和
LangGraph 节点调度。PydanticAI 通过 OpenAI-compatible 接口提供 Planner、Investigator 和 Replanner
结构化输出；后台 Worker 默认关闭，只有显式配置模型后才允许开启。

## 2. Graph 版本与节点注册表

当前发布版本是 `graph-v1` 和 `graph-v2`，新 Run 默认使用 `graph-v2`。Run 创建和从暂停恢复到运行时，后端都会确认该版本仍在注册表中；
未知或已经下线的版本返回 `INVESTIGATION_GRAPH_VERSION_UNAVAILABLE`，不会用新代码猜测旧图的执行语义。

`graph-v1` 按稳定 key 注册以下节点：

```text
load_incident
load_topology
load_recent_changes
classify_complexity
create_plan
select_next_step
run_investigator
assess_evidence
maybe_replan
escalate_or_finish
```

`graph-v2` 保留上述稳定节点，并在 `assess_evidence` 与 `maybe_replan` 之间增加
`propose_action`。`graph-v1` 不修改，确保已有 Checkpoint 可继续按原图恢复。

Checkpoint 的 `node` 必须存在于 Run 对应的 Graph；`completedNodeKeys` 必须采用
`<node>:<iteration>` 格式，并引用同一 Graph 中的节点。节点顺序、调查循环和停止分支由 LangGraph
执行器负责。

## 3. 状态机

```text
queued -> running -> paused -> running
                  -> completed
                  -> failed
                  -> cancelled
queued --------------------> cancelled
paused --------------------> failed/cancelled
```

终态不可重新打开。需要重新调查时创建新的 Run，新 Run 会获得新的 `threadId`。

## 4. Checkpoint 内容

每个 Checkpoint 保存：

- 单调递增的 `sequence`；
- 节点幂等键 `nodeExecutionId`；
- `node`、`graphVersion` 和迭代次数；
- 当前 PlanStep 引用；
- Hypothesis 和 Evidence ID 引用；
- 已完成节点键；
- 无进展计数；
- 本节点是否取得进展以及持久化的下一步动作；
- 本节点模型请求数、输入 Token 和输出 Token；
- 最多 2000 字符的结果摘要。

Checkpoint 不保存隐藏思维链、完整 Prompt、完整模型消息或大段 Evidence 内容。业务事实仍以
Incident、Plan、Hypothesis、Evidence 和 RunnerTask 表为准，Checkpoint 只保存恢复所需引用。

## 5. 幂等和并发

- Run 创建使用 `idempotencyKey`；相同参数重放返回原 Run；
- 同一个 Incident 同时只允许一个 `queued`、`running` 或 `paused` Run；
- Checkpoint 使用 `(runId, nodeExecutionId)` 保证节点幂等；
- 相同节点执行键和相同内容重放不会增加 sequence 或 Run version；
- 相同执行键携带不同内容返回 `CHECKPOINT_IDEMPOTENCY_CONFLICT`；
- 新 Checkpoint 必须携带 `expectedRunVersion`，防止并发覆盖；
- iteration 只能单调前进且不能超过 `maxIterations`。

## 6. Worker 领取与恢复

- Worker 使用数据库行锁和 `runtimeLeaseExpiresAt` 领取 `queued` Run；
- 首次领取把状态推进为 `running` 并发送 `investigation.status_changed`；
- 每个节点执行前续租，写 Checkpoint 前再次验证 Owner，防止失去租约的 Worker 覆盖结果；
- Control Plane 崩溃后，新 Worker 可以领取租约过期的 `running` Run；
- 恢复时根据最后一个 Checkpoint 的 `completedNodeKeys`、迭代、无进展计数和下一步动作跳过已完成节点；
- 恢复领取发送 `investigation.runtime_recovered`；
- 连续无进展达到阈值或达到最大迭代次数时，Run 自动进入 `paused`，等待人工判断。

有副作用的 Provider 必须使用收到的稳定 `nodeExecutionId` 做下游幂等。Checkpoint 能防止恢复后再次
调度已确认完成的节点，但无法撤销“下游副作用成功、Checkpoint 写入前进程崩溃”的窗口。

## 7. 引用边界

Checkpoint 中的 PlanStep、Hypothesis 和 Evidence 必须属于 Run 对应的 Incident。跨 Incident
引用和不存在的 ID 会被拒绝。这样恢复后不会把其他故障的证据带入当前调查。

## 8. API

```text
GET  /api/v1/investigation-graphs
GET  /api/v1/investigation-graphs/{graph_version}
POST /api/v1/incidents/{incident_id}/investigation-runs
GET  /api/v1/incidents/{incident_id}/investigation-runs
GET  /api/v1/investigation-runs/{run_id}
GET  /api/v1/investigation-runs/{run_id}/checkpoints
GET  /api/v1/investigation-runs/{run_id}/hitl-waits
```

用户面只提供 Run 创建、查询、Checkpoint 只读和单用途取消。Runtime 写接口位于独立内部面：

```text
POST /internal/v1/investigation-runs/{run_id}/transitions
POST /internal/v1/investigation-runs/{run_id}/checkpoints
POST /internal/v1/investigation-runs/{run_id}/hitl-waits
```

内部面不进入用户 OpenAPI，必须使用 `kind=service`、`role=runtime` 的 Principal Bearer Token。
Admin、Operator、Viewer 和浏览器均不能调用；进程内 Agent Runtime 继续直接调用 Service，不需要
经 HTTP 绕行。

SSE 事件：

```text
investigation.run_created
investigation.status_changed
investigation.checkpointed
investigation.runtime_recovered
investigation.hitl_wait_started
investigation.hitl_wait_resolved
```

HITL Wait 把 Run、最后一个 Checkpoint 与待决议的 Approval 或 Compensation 绑定。创建 Wait 与
`running -> paused` 在同一事务提交；人工决议时，决议记录、Wait 结果与 `paused -> queued` 也在
同一事务提交。Worker 再次领取后写入 `resumedAt`，并把 `waitId`、对象类型、对象 ID 和决议结果
放入节点执行上下文；Replanner 使用这份服务器生成的结构化 `hitlDecision`，而不是浏览器拼装的
自由文本。重复创建同一 Wait 或重复领取不会产生第二次恢复。取消 Run 会同时把仍在等待的
Wait 标记为 `cancelled`，后续对象决议不会重新打开已取消的 Run。

## 9. 运行配置

```text
OPSPILOT_AGENT_RUNTIME_ENABLED=false
OPSPILOT_AGENT_RUNTIME_POLL_INTERVAL_SECONDS=2
OPSPILOT_AGENT_RUNTIME_LEASE_SECONDS=60
OPSPILOT_AGENT_RUNTIME_NO_PROGRESS_LIMIT=3
OPSPILOT_AGENT_MODEL_NAME=
OPSPILOT_AGENT_MODEL_API_KEY=
OPSPILOT_AGENT_MODEL_BASE_URL=
OPSPILOT_AGENT_MODEL_REQUEST_LIMIT=2
OPSPILOT_AGENT_MODEL_INPUT_TOKENS_LIMIT=16000
OPSPILOT_AGENT_MODEL_OUTPUT_TOKENS_LIMIT=4000
```

开启运行时必须同时配置模型名和 API Key。`baseUrl` 为空时使用 OpenAI 默认地址；配置本地
Ollama/vLLM 或其他兼容服务时填写其 OpenAI-compatible 地址。Provider 只接收 Incident 的必要字段、
资源 ID、Evidence ID/类型/短摘要和剩余预算，不发送 Evidence 原始大字段或隐藏推理。

每个 Run 的 `maxModelRequests` 默认是 20。Checkpoint 在同一数据库事务内累计
`modelRequestsUsed`、`modelInputTokensUsed` 和 `modelOutputTokensUsed`；超过请求预算返回
`MODEL_REQUEST_BUDGET_EXHAUSTED`。PydanticAI 同时限制单节点请求数及输入、输出 Token。

## 10. 后续接入顺序

1. 让 Investigator 根据 PlanStep 创建受控 RunnerTask，并在 Evidence 返回后自动恢复 Run；
2. 增加最大墙钟运行时长和按金额计算的成本预算；
3. 增加模型 Profile、Prompt version 与评测门禁；
4. 增加旧 Graph version 的长期回归样本。
