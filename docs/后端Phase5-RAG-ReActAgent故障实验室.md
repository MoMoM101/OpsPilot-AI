# 后端 Phase 5：RAG-ReActAgent 故障实验室

> 状态：开发中  
> 当前版本：Alembic `20260815_0033`

## 阶段目标

建立一套可由 `docker compose` 重复启动、注入、恢复和验证的 RAG 故障环境，并让现有 Incident、Agent、Runner、Evidence、Policy 和 Action 链路形成真实端到端闭环。

Phase 5 不扩大模型权限。模型只能从服务端给出的 Resource 和只读 Operation 白名单中选择观察目标；Connector 参数、网络地址、文件路径、查询语句和超时策略全部由服务端可信配置生成。

## 开发范围与顺序

| 批次 | 范围 | 交付门槛 | 状态 |
|---|---|---|---|
| 5.0 | Phase 4 基线冻结、Phase 5 技术设计、场景契约 | 文档与当前 API/迁移一致 | 已完成 |
| 5.1 | Agent Observation Proposal 与可信参数编译 | 模型不能提交参数；非法 Resource 配置 Fail Closed | 已完成基础契约 |
| 5.2 | 持久化 Observation 等待与恢复 | `run_investigator` 创建 RunnerTask 后暂停；成功或失败完成后幂等恢复 Run | 已完成 |
| 5.3 | SQLite/Qdrant/RAG 只读 Connector | 固定 Schema、无 Shell、输出限长与脱敏 | 已完成 |
| 5.4 | Lab Compose 与故障控制器 | 注入和清理幂等，不影响控制面数据 | 已完成 |
| 5.5 | 首批 5 个端到端案例 | 告警、调查、证据、恢复、审计可自动断言 | 实现完成，等待 Docker Runtime 实跑验收 |

## Agent Observation 契约

模型输出最多包含一个观察建议：

```json
{
  "action": "observe",
  "proposal": {
    "resourceId": "uuid",
    "operation": "http.probe",
    "purpose": "区分进程在线与业务就绪"
  },
  "reason": "当前证据不足"
}
```

模型不得输出 `parameters`、URL、文件路径、PromQL、SQL、凭据或命令。未知字段直接拒绝。`none` 表示无需新增观察，`escalate` 表示在当前安全边界内无法继续。

Resource 的可信配置由 Admin/部署清单维护：

```json
{
  "observability": {
    "runnerOperations": {
      "http.probe": {
        "parameters": {
          "url": "http://rag-api:8000/ready",
          "expectedStatuses": [200],
          "captureBody": true
        },
        "timeoutSeconds": 10,
        "maxAttempts": 2
      }
    }
  }
}
```

服务端编译后仍复用 `RunnerTaskCreate` 的 Connector 匹配、参数白名单、URL/时间范围、大小和重试上限校验。配置缺失或非法时 Fail Closed，不回退到模型参数。

## 持久化执行设计

`run_investigator` 不同步等待 Runner：

1. 读取当前运行中的 PlanStep、Incident Resource 和允许的只读 Operation；
2. 调用 Observation Provider，并进行 Resource、PlanStep、Operation 和预算校验；
3. 以 `(runId, nodeExecutionId)` 派生幂等键，在同一持久化流程中创建 RunnerTask；
4. 写入 Checkpoint 并把 InvestigationRun 置为 `paused`；
5. Runner 完成任务后生成成功或失败 Observation 记录，原子地把仍在等待该任务的 Run 重新置为 `queued`；
6. 恢复时依靠 completed node key 跳过重复派发，进入 `assess_evidence`。

Checkpoint、`investigation_observation_waits`、RunnerTask 和 Run 暂停在同一事务提交，避免任务先完成而 Run 后暂停的竞态。Runner 成功或失败完成时，等待记录解析和 Run 重新入队也与任务结果、Evidence 在同一事务提交。

失败、租约耗尽和 Runner 不可达不能静默消失。它们形成 `collectionStatus=failed` 的有界 Evidence，使 Replanner 能区分“目标系统故障”和“观测能力不可用”。Run 取消、Plan 替换或 Step 终止时同步取消尚未执行的 Observation Task/Wait；恢复依赖节点完成键，不能重复派发同一 Observation。

## 专属只读 Operation

计划增加以下 Operation，全部使用精确 Pydantic Schema：

- `sqlite.health`：只读打开、基础元数据和响应时间；
- `sqlite.lock_status`：WAL、busy/locked 状态和受限 pragma；
- `sqlite.integrity_check`：只执行只读完整性检查；
- `qdrant.health`：进程与 readiness；
- `qdrant.collection`：单个可信 collection 的状态；
- `qdrant.point_count`：单个可信 collection 的点数；
- `qdrant.query_smoke`：使用部署时配置的固定测试向量/样本；
- `rag.business_health`：固定健康问题和预期响应约束。

Connector 禁止任意 SQL、任意 HTTP URL、任意 collection、任意文件路径和 Shell。目标值只能来自 Resource 可信配置。

## 场景清单契约

每个场景使用版本化清单，至少包含：

```yaml
id: qdrant_down
version: 1
background: Qdrant 不可用导致检索失败
resources: []
inject: []
expectedAlerts: []
expectedInvestigation: []
requiredEvidence: []
allowedActions: []
forbiddenActions: []
recoveryCriteria: []
cleanup: []
assertions: []
```

首批纵向案例为 `qdrant_down` 和 `sqlite_locked`，随后补齐 `embedding_timeout`、`backend_500`、`collection_count_mismatch`。`disk_full_simulation`、`runner_disconnect` 和 `prometheus_unavailable` 作为第二组可靠性案例。

## 验收标准

- Lab 服务一键启动，故障注入和清理可重复执行；
- 至少五个场景通过自动化端到端测试；
- Agent 能区分进程存活、依赖可用和 RAG 业务可用；
- 每个结论引用 Evidence，失败观察同样可追踪；
- 同一 Agent 节点恢复不会创建第二个 RunnerTask；
- 控制面重启后等待关系不丢失；
- 所有变更动作仍经过 Policy、Approval、Resource Lock、Verification 和审计；
- 实验数据、测试向量和凭据均为本地非生产数据。

## 前端边界

5.4 已提供 Admin 控制面契约，浏览器只调用后端，不直接访问 Lab Controller，也不会接收 Lab Token：

- `GET /api/v1/lab/scenarios`：列出场景及其 `ready/active/unavailable` 状态；
- `POST /api/v1/lab/scenarios/{scenarioId}/inject`：幂等注入故障；
- `POST /api/v1/lab/scenarios/{scenarioId}/cleanup`：幂等清理故障。

两个写接口的请求体均为 `{ "idempotencyKey": "..." }`。同一个 key 重放同一操作会返回 `replayed=true`，绑定不同场景或操作则返回冲突。接口仅允许 Admin；生产环境禁止启用 Fault Lab。

前端已生成 OpenAPI 类型并提供 `labApi`，后续场景工作台可直接对接。Observation 等待态继续复用现有 RunnerTask、Checkpoint 和 Incident SSE。浏览器不得直连 `18010` 控制器端口，也不得保存 `OPSPILOT_LAB_TOKEN`。

## 本地启动

复制 `.env.compose.example` 为 `.env` 并填写所有 secret 及 `OPSPILOT_RUNNER_ENVIRONMENT_ID`，然后执行：

```bash
docker compose -f docker-compose.yml -f docker-compose.lab.yml --profile runner --profile lab up --build
```

RAG API 默认只绑定 `127.0.0.1:18000`；Lab Controller 不发布宿主机端口，只允许控制面通过 Compose 私网访问。五个已注册场景为 `qdrant_down`、`sqlite_locked`、`embedding_timeout`、`backend_500` 和 `collection_count_mismatch`。

## 场景自动化验证

五个场景的版本化清单位于 `lab/opspilot_lab/scenarios.py`，该清单是控制器注册场景和 E2E 验证的唯一数据源。每份清单均包含背景、预期告警、预期调查 Operation、必需 Evidence、允许及禁止动作、恢复标准和自动断言，不包含地址、凭据或 Connector 参数。

先创建一个仅用于本地 Lab 的 unrestricted Admin principal，并把其 access token 写入 `.env` 的 `OPSPILOT_LAB_E2E_ACCESS_TOKEN`。Compose Stack 健康后执行：

```bash
docker compose -f docker-compose.yml -f docker-compose.lab.yml \
  --profile runner --profile lab --profile lab-e2e run --rm lab-e2e
```

验证器对每个案例执行以下固定流程：

1. 通过后端 Admin API 清理残留故障；
2. 断言 RAG 基线恢复且能检索一个确定性测试点；
3. 通过后端 Admin API 注入故障；
4. 断言对应的 HTTP 降级状态或检索点数异常；
5. 投递场景清单声明的 Alertmanager 告警，断言告警匹配 Lab Resource 并关联 Incident；
6. 将 Incident 推进到 `INVESTIGATING` 并创建 `graph-v1` InvestigationRun；
7. 等待确定性 Lab Agent 从清单允许范围内选择只读 Operation，再由真实 Runner 生成 Evidence；
8. 断言 Investigation 完成、RunnerTask 终态、Evidence 与 Incident 关联，以及注入操作审计；
9. 在 `finally` 中清理故障，轮询断言业务恢复，并验证清理审计记录。

验证器会幂等创建 `fault-lab` Environment 和带可信只读 Operation 配置的 `rag-lab` Resource；不持有内部 Lab Token、不访问 Lab Controller 私有端口，每次 mutation 使用独立幂等键。即使降级、告警、调查、Evidence 或审计断言失败，也会先执行清理再退出。

`.github/workflows/lab.yml` 将以上验证纳入独立 CI：先执行 Lab Pytest、Ruff 和严格 MyPy，再校验
基础 Compose 与 Lab Overlay 的合并配置并构建 Lab 镜像，最后在 Linux Runner 上动态初始化一次性
Admin，使用真实 Backend、Runner 和 Lab 容器执行全部场景。E2E Job 上限为 25 分钟，场景命令上限为
12 分钟；失败时采集日志，并在 `always()` 清理容器和临时卷。

Compose Lab 后端启用 `lab_deterministic` Agent Provider。该 Provider 只在 `lab_enabled=true` 时允许启动，生产环境仍由配置校验禁止启用 Fault Lab。它不调用外部模型，不生成 URL、路径或参数，只根据 Lab Incident 标题选择一个预定义只读 Operation；实际 Connector 参数仍由 Resource 的可信配置编译和校验。正常部署继续使用默认 `openai` Provider。
