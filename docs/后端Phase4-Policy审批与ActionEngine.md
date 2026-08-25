# 后端 Phase 4：Policy、审批与 Action Engine

> 状态：已完成开发、安全回归与 Phase 4 总 Review  
> 冻结版本：Alembic `20260814_0032`

## 目标

把当前只读调查链路扩展为受控执行链路，同时保持默认拒绝、审批不可绕过、执行幂等、资源互斥和审计先行。

## 开发顺序

| 优先级 | 模块 | 验收要点 | 状态 |
|---|---|---|---|
| P0 | Policy Engine MVP | 环境隔离、风险/自治级别/Capability/资源匹配、首条高优先级规则生效、无匹配默认拒绝、Dry Run 解释 | 已完成 |
| P0 | Policy 完整治理 | 启停与修改、维护窗口、执行次数限制、策略版本与决策快照 | 已完成 |
| P0 | Approval | 创建、批准/拒绝、有效期、有限参数编辑、执行前二次校验、超时 | 已完成 |
| P0 | Action Request | ActionProposal 转换、Idempotency Key、状态机、审计先行 | 已完成 |
| P0 | Resource Lock | 同一资源互斥、租约、Fencing Token、崩溃恢复 | 已完成 |
| P1 | Action Dispatcher | Runner 派发、白名单 Connector、超时进入 UNKNOWN、先对账再重试 | 已完成控制面、Runner 协议与首批 Connector |
| P1 | Verification/Compensation | 硬指标验证、失败停止、补偿/回滚接口、人工接管 | 已完成首个安全闭环 |
| P1 | Agent HITL | 持久化 Wait、审批/补偿决议恢复、SSE 事件与 Checkpoint 一致性 | 已完成首个闭环 |
| P1 | Agent Action Proposal | graph-v2、服务端范围校验、Policy/Approval/Action 转换 | 已完成 |

## 已实现的 Policy 契约

规则属于单一 Environment，并可限制：

- `autonomyLevels`：`L0` 至 `L4`；
- `riskLevels`：`read_only`、`low`、`medium`、`high`；
- `capabilities`：精确 Capability 白名单；
- `resourceIds`：精确资源范围；
- `effect`：`allow` 或 `deny`；
- `approvalRequired`：允许后是否必须进入审批；
- `priority`：数值越大越先匹配。
- `maintenanceDays` + 起止分钟：UTC 维护窗口，星期一为 `0`；
- `maxExecutionsPerIncident`：单条规则对单个 Incident 的正式授权上限；
- `version`：规则修改使用乐观锁，防止覆盖并发更新。

空条件列表表示该维度不限制。决策按优先级查找第一条完全匹配的启用规则；没有规则匹配时必须拒绝。Dry Run 不创建 Action、Approval 或 RunnerTask。

## API

```text
POST /api/v1/policies
GET  /api/v1/policies?environmentId={id}
PUT  /api/v1/policies/{policyId}
POST /api/v1/policies/dry-run
POST /api/v1/policies/evaluate
POST /api/v1/approvals
GET  /api/v1/approvals?incidentId={id}&status={status}
POST /api/v1/approvals/{approvalId}/decision
POST /api/v1/actions
GET  /api/v1/actions?incidentId={id}&status={status}
POST /api/v1/actions/{actionId}/cancel
GET  /api/v1/resource-locks
POST /api/v1/actions/{actionId}/dispatch
GET  /api/v1/actions/{actionId}/execution
GET  /api/v1/actions/{actionId}/verification
POST /api/v1/actions/{actionId}/reconcile
POST /api/v1/actions/{actionId}/compensation
GET  /api/v1/compensations?incidentId={id}
POST /api/v1/compensations/{compensationId}/decision
POST /api/v1/compensations/{compensationId}/dispatch
GET  /api/v1/compensations/{compensationId}/execution
POST /api/v1/compensations/{compensationId}/escalate
```

- 创建和修改规则：仅 Admin；
- 查询规则：Admin、Operator、Viewer，受 Environment Scope 限制；
- Dry Run：Admin、Operator，受 Environment Scope 和资源归属限制；
- Evaluate：Admin、Operator，必须绑定 Incident，生成不可变 Decision Snapshot；
- 所有写操作继续由统一中间件写入 Actor 审计。

维护窗口不允许跨 UTC 午夜。正式 Evaluate 会锁定匹配规则、重新核对版本和启用状态，然后检查单 Incident 上限并写入快照。允许快照会保守占用一次授权额度，避免后续并发 Action 越过限制；Action Engine 落地后必须引用该 `snapshotId`，且派发前仍需使用最新规则再次判定。

## Approval 契约

- 只有 `allowed=true` 且 `approvalRequired=true` 的正式 Decision Snapshot 可以创建审批；
- 一个 Decision Snapshot 最多创建一个审批，防止重复审批分叉；
- 状态为 `pending`、`approved`、`rejected`、`expired`；
- 决议携带 `expectedVersion`，并发或重复决议返回冲突；
- 参数只允许标量 JSON 值，且审批人只能修改 `editableParameterKeys` 中声明的键；
- 批准前按 Snapshot 中的目标、Capability、自治级别和风险重新运行当前 Policy；
- 当前规则拒绝、停用、维护窗口关闭或不再要求审批时，批准 Fail Closed；
- 到期后的决议会把审批落为 `expired`，绝不会自动通过；GET 查询仅投影到期状态，不产生隐藏写操作；
- 创建和决议分别发布 `approval.requested`、`approval.resolved` SSE/Outbox 事件。

## Action Request 契约

- Action Request 必须引用一个允许的正式 Policy Decision Snapshot；
- Snapshot 要求审批时，必须绑定同一 Snapshot 的 `approved` Approval，且 Approval 仍在有效期内；
- Action 参数必须与审批后的参数完全一致，防止批准后替换目标或扩大影响；
- Snapshot 不要求审批时禁止附带 Approval，避免制造虚假的授权链；
- 创建前再次按当前 Policy 复核，旧 Snapshot 不能绕过规则停用、拒绝或维护窗口；
- `idempotencyKey` 在 Environment 内唯一，同键同载荷返回原 Action 并标记 `replayed=true`；
- 同键不同载荷返回 `ACTION_IDEMPOTENCY_CONFLICT`，并发唯一键竞争也走相同幂等语义；
- 新建 Action 状态为 `ready`；执行链路使用 `dispatching/running/applied/verifying/succeeded/failed/verification_failed/unknown` 状态；
- 参数 JSON 最大 16 KiB，必须提供至少一条硬验证标准；
- 创建与取消分别发布 `action.requested`、`action.cancelled` SSE/Outbox 事件；
- 本批不执行任何远端变更，Runner Dispatcher 和 Resource Lock 完成前 `ready` 仅代表通过控制面授权检查。

## Resource Lock 契约

- 每个 Resource 永久保留一条锁记录，释放时不删除；
- 第一次获取 Token 为 `1`，每次释放后重获或租约过期接管都严格递增；
- 同一 Action 在有效租约内重复获取返回原锁并标记 `duplicate=true`；
- 其他 Action 在租约有效时收到 `RESOURCE_LOCK_CONFLICT`；
- acquire/renew/release 仅存在于 Admin/Internal API；普通控制面不能人工操作运行锁；
- renew/release 必须同时匹配 Action ID 和 Fencing Token；旧 Token 无法续租或释放新所有者的锁，运行中状态禁止人工释放；
- Action 派发时由服务端原子获取锁，并再次校验最新 Policy、Approval 有效期及批准参数，作为派发前 Fail Closed 门槛；客户端不提交 Resource Fencing Token；
- Action 取消会在同一事务中释放其锁并发布事件；
- 默认租约为 120 秒，可通过 `OPSPILOT_RESOURCE_LOCK_LEASE_SECONDS` 配置；
- `resource_lock.acquired`、`resource_lock.released` 进入 Incident SSE/Outbox；续租不产生高频业务事件；
- Dispatcher/Runner 内部协议强制携带 Fencing Token；面向控制面的 Action 派发接口不接收或暴露该 Token。

## Action Dispatcher 契约

- Dispatcher 只选择在线、Environment 匹配且明确声明目标 Action Capability 的 Runner；
- 服务端动作白名单当前仅包含 `container.restart`、`service.reload`、`traffic_probe.pause/resume` 和 `health.check`，每个动作使用精确单字段参数 Schema，不提供任意 Shell；
- Runner claim 同时校验 Runner Fencing Token，并收到 Execution 与 Resource 两个 Fencing Token；
- renew 同时延长 Action Execution Lease 和 Resource Lock Lease；
- complete 必须携带两个 Token 和幂等 `completionId`；动作失败会释放锁，动作成功进入 `applied/verifying` 并继续冻结资源锁；
- Execution Lease 超时不会自动重试，而是把 Action/Execution 置为 `unknown`，锁进入 `reconciliationRequired` 冻结状态；
- UNKNOWN 时其他 Action 无法接管同一资源，必须调用 reconcile，根据目标系统实际状态落为 succeeded/failed 后才能释放；
- 用户控制面 API 与 Runner 专用 `/runner/v1` API 保持隔离，Runner 使用自身可轮换 Token；
- 发布 `action.dispatched`、`action.started`、`action.applied/failed`、`action.unknown` 和 `action.reconciled` SSE/Outbox 事件。

## Verification 契约

Runner 现已消费 Action claim，并实现 `container.restart` 与 `health.check` 两个固定参数、无 Shell 的 Docker Action Connector。执行期间会并行维护 Runner 心跳、Action Execution Lease 和 Resource Lock Lease；过期 Fencing Token 会终止本地进程并停止回传，完成重试复用同一个 `completionId`。`health.check.target` 当前明确表示 Docker 容器 ID 或名称。

- Action 成功应用后，服务端根据受信任的 Capability/参数映射生成只读 RunnerTask，不解析或执行用户输入的自然语言；
- `container.restart` 和 `health.check` 当前都映射为 `docker.container_health`，目标参数由服务端转换；
- 派发 Runner 必须同时声明 Action Capability 与对应只读验证 Operation，否则 Dispatcher 拒绝派发；
- Verification Task 最多执行三次，失败期间 Action 保持 `verifying`，Resource Lock 保持冻结；
- 验证通过会生成 Evidence、把 Action/Execution 置为 `succeeded` 并释放锁；
- 连续失败会置为 `verification_failed`，继续冻结锁；存在 `rollbackCapability` 时返回 `compensationRequired=true`；
- `verificationCriteria` 作为审批和审计快照保留，不被解释成命令、查询或表达式，避免注入和权限扩张；
- 发布 `action.verification_queued/passed/failed` SSE/Outbox 事件。

## Compensation 契约

- 只有 `verification_failed` 且 Verification 明确返回 `compensationRequired=true` 的 Action 可以创建补偿；
- Compensation Request 使用 Environment 内幂等键，同键同载荷返回原记录，同键异载荷冲突；
- 补偿拥有独立的 `pending/approved/rejected` 决议记录、有效期、Actor 和审计事件，创建后绝不会自动执行；
- 批准时再次校验当前 Policy，策略已拒绝或失效时 Fail Closed；
- 当前可执行补偿严格限制为与原 Action 相同的 Capability 和已批准参数，跨 Capability 补偿尚未启用；
- Compensation 派发请求不接收 Resource Fencing Token；服务端在事务内读取并使用冻结锁的当前 Token；
- Runner 复用 Action Worker 协议，但 claim 明确返回 `executionKind=compensation` 和 `compensationId`；
- 补偿执行继续使用 Execution Lease、Resource Lock Lease、双 Fencing Token 与幂等 `completionId`；
- 成功后原 Action 进入 `compensated` 并释放锁；失败或执行结果未知时进入 `escalated/unknown`，锁继续冻结等待人工接管；
- 发布 `compensation.requested/resolved/dispatched/started/succeeded/escalated/unknown` SSE/Outbox 事件。

## 下一批后端开发

Phase 4 已冻结，后续仅接受安全修复和兼容性修复。当前进入 Phase 5 故障实验室，先补齐 Agent 自动选择只读 Observation、服务端可信参数编译、持久化 RunnerTask 等待/恢复，再实现 SQLite/Qdrant Connector 与可复现故障案例。跨 Capability 补偿需要独立 Policy Decision 与参数映射，在该模型落地前保持禁用。

## Agent Action Proposal 闭环

- `graph-v1` 保持冻结，继续支持旧 Run 的 Checkpoint 恢复；
- `graph-v2` 在 Evidence 评估后增加 `propose_action` 节点，新 Run 默认使用该版本；
- 模型最多输出一个结构化 Proposal，不能直接调用 Runner 或执行动作；
- 后端校验 Proposal 必须属于当前 Incident Resource 和正在运行的 remediation/experiment PlanStep；
- Capability 必须同时命中服务器 Action 白名单和 PlanStep 白名单，风险必须与 PlanStep 一致；
- Policy 默认拒绝时 Proposal 进入 `denied`，不会创建 Approval 或 Action；
- Policy 要求审批时 Proposal 进入 `awaiting_approval`，Checkpoint 与 HITL Wait 原子暂停；
- 批准后后端使用批准参数创建 Action Request，Proposal 进入 `action_ready`，Run 自动重新入队；
- 拒绝或过期时 Proposal 进入 `rejected`，Run 恢复后由 Agent 做结束或升级判断；
- 恢复后的 Replanner 只接收服务器生成的 `hitlDecision`（Wait、对象和结果），不接收浏览器拼装的决议文本；
- `propose_action` Checkpoint 关联当前 remediation/experiment PlanStep，便于恢复与审计核对；
- Policy 不要求审批时，后端直接创建 `ready` Action Request，但仍不会绕过后续 Resource Lock、Runner Lease、Verification 和 Compensation；
- 跨 Capability rollback 在 Action 创建阶段即被拒绝，避免到补偿阶段才暴露不可执行配置；
- `(runId, nodeExecutionId)` 保证 Proposal 幂等，重复节点不能生成第二个 Action。

公开只读接口：

```text
GET /api/v1/action-proposals?incident_id={incident_id}&status={status}
```

SSE/Outbox 新增：

```text
action.proposal_created
action.proposal_resolved
```

## 前端边界

Policy 页面只负责规则管理和 Dry Run 展示。前端不得自行计算是否允许执行，也不得把 Dry Run 结果当成执行授权；最终授权始终由后端在 Action 派发前重新判定。
