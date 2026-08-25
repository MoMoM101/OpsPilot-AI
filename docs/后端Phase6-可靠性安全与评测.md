# 后端 Phase 6：可靠性、安全与评测

> 状态：已完成  
> 当前批次：6.6 备份恢复、审计归档与开源安全文档

## 开发顺序

| 批次 | 范围 | 状态 |
|---|---|---|
| 6.1 | Connector 熔断、统一超时 Owner、故障恢复探测 | 已完成 |
| 6.2 | 分层重试、指数退避与抖动 | 已完成 |
| 6.3 | Control Plane 降级模式与恢复扫描 | 已完成 |
| 6.4 | Prompt/Tool/SSRF/审批绕过安全回归集 | 已完成 |
| 6.5 | Agent Eval 数据集、指标与 Release Gate | 已完成 |
| 6.6 | 备份恢复、审计归档与开源安全文档 | 已完成 |

## 6.1 Connector 熔断

熔断器只包裹 Runner 的只读 Connector，不包裹 Action Connector。每个 Connector 独立维护 `closed/open/half_open` 状态，避免 Qdrant 等单个依赖持续失败时影响其他观察能力。

默认连续 5 次可重试失败后打开，30 秒后允许一个半开探测：

- 探测成功：清空失败计数并关闭；
- 探测失败：重新打开并开始完整恢复窗口；
- 恢复窗口内：不调用 Connector，任务以 `CONNECTOR_CIRCUIT_OPEN` 失败并形成可追踪 Evidence；
- 参数非法、目标不在白名单、Operation 不支持和资源不存在等请求错误不计入依赖故障。

Runner Registry 是只读 Connector 的统一总超时 Owner。超时统一转换为 `CONNECTOR_TIMEOUT` 并计入熔断；Connector 自身仍可使用更短的协议级超时，但客户端不再额外嵌套同级总超时。

配置项：

```text
OPSPILOT_RUNNER_CONNECTOR_CIRCUIT_FAILURE_THRESHOLD=5
OPSPILOT_RUNNER_CONNECTOR_CIRCUIT_RECOVERY_SECONDS=30
```

阈值范围为 1–100，恢复时间范围为 1–3600 秒。熔断状态只存在于 Runner 进程内；Runner 重启后恢复为关闭状态，控制面任务幂等、Lease 和 Evidence 语义保持不变。

## 前端配合

6.1 不修改控制面 API 和 OpenAPI，前端不需要配合。`CONNECTOR_CIRCUIT_OPEN` 会沿用现有失败 RunnerTask/Evidence 展示。如果后续需要展示 Connector 实时熔断状态，将在单独批次设计只读状态接口。

## 6.2 分层重试

重试 Owner 固定如下：

- Runner Connector Registry：在同一个只读 RunnerTask Lease 和总超时预算内重试瞬时依赖故障；
- Control Plane：只负责 Task Lease 过期后的恢复和 `maxAttempts`，不介入单次协议调用；
- Runner Client：不重试 claim、renew、complete 等控制面写请求；
- Action Connector：不自动重试，避免重复执行变更动作；
- 半开熔断探测：只执行一次，不在探测内部重试。

默认最多执行两次 Connector 调用。第一次瞬时失败后，以 0.2 秒为基础指数退避，单次退避最大 2 秒，并施加正负 20% 的有界抖动。所有调用和等待共享 RunnerTask 的总 `timeoutSeconds`；若下一次退避会耗尽预算，则立即返回最后一次错误。

只有可重试依赖错误和 `CONNECTOR_TIMEOUT` 会重试。参数非法、目标不在白名单、Operation 不支持、Connector 未配置和资源不存在均立即失败。一个重试组耗尽后只计为一次熔断失败，避免单个 RunnerTask 直接击穿熔断阈值。

配置项：

```text
OPSPILOT_RUNNER_CONNECTOR_RETRY_MAX_ATTEMPTS=2
OPSPILOT_RUNNER_CONNECTOR_RETRY_BASE_SECONDS=0.2
OPSPILOT_RUNNER_CONNECTOR_RETRY_MAX_SECONDS=2
OPSPILOT_RUNNER_CONNECTOR_RETRY_JITTER_RATIO=0.2
```

6.2 同样不修改控制面 API。前端无需配合，现有 RunnerTask/Evidence 仍只展示最终成功或最终失败结果，不暴露内部尝试次数。

## 6.3 Control Plane 降级与恢复

应用启动时先执行幂等恢复扫描：过期 Runner 及其任务按现有 Lease 规则回收，过期 Action/Compensation Execution 转为 `unknown` 并冻结资源锁，等待人工 reconcile。全部步骤成功后才进入 `normal`。

任一步失败时进入 `read_only`：

- `/api/v1/ready` 返回 503，`control_plane_recovery=false`；
- 控制面写接口统一返回 `503 CONTROL_PLANE_READ_ONLY` 和 `Retry-After`；
- Runner 暂停领取新的 Action/Compensation，已执行任务仍可 renew/complete；
- 登录、退出、刷新会话和所有读接口保持可用；
- 后台按 `OPSPILOT_STARTUP_RECOVERY_RETRY_SECONDS` 自动重试，Admin 也可立即触发恢复；
- 响应只暴露稳定的 `reasonCode`，底层异常只记录类型，不泄露连接串或凭据。

新增用户控制面契约：

- `GET /api/v1/system/mode`：公开返回 `recovering | normal | read_only`、恢复次数、时间和各恢复项计数；
- `POST /api/v1/system/recovery`：仅 Admin 可调用，失败时返回 503 和当前模式快照。

配置项：

```text
OPSPILOT_STARTUP_RECOVERY_ENABLED=true
OPSPILOT_STARTUP_RECOVERY_RETRY_SECONDS=30
```

### 前端配合

前端需要消费 `GET /api/v1/system/mode`，在 `recovering/read_only` 时展示全局降级横幅并禁用控制面写按钮；仍需以后端 503 为最终保护。Admin 工作台可选接入 `POST /api/v1/system/recovery` 提供“立即重试”，并在失败时直接刷新返回的模式快照。

## 6.4 安全回归集

安全回归 Gate 固定覆盖四类攻击：

- Prompt Injection：伪造 SYSTEM/Tool 指令、超长内容、NUL、双向文本和零宽字符只能作为有界 `untrustedData`；
- Tool 越权：模型输出 DTO 全部 `extra=forbid`，未知 `tool_call`、Shell 字段、越界 capability/Resource/Evidence 均失败；Action 参数还要经过服务端 capability 白名单；
- SSRF/命令注入：Runner 拒绝 URL userinfo、query、fragment、非 HTTP scheme、metadata 地址、IPv4-mapped IPv6、非白名单端口和 Docker option/额外参数；HTTP 不跟随重定向且禁用环境代理；
- 审批绕过：认证主体只来自服务端认证上下文，伪造 Actor Header 无效；申请人不得审批自己的请求，Policy/Approval 必须重新校验并一次性消费。

GitHub Backend 和 Runner Workflow 都设置了显式安全回归步骤。该步骤与完整测试重复执行是有意设计：安全测试文件变更或拆分时，Release Gate 的边界保持可见。

### 前端配合

6.4 不修改 API 或 OpenAPI。所有拒绝沿用既有 403/409/422 错误契约，前端不需要新增对接。

## 6.5 Agent Eval 与 Release Gate

新增版本 1 离线 JSONL 数据集和通用 `AgentProvider` Eval Runner。当前 13 个案例覆盖五个 Fault Lab 场景、Prompt Injection、Operation/Resource 选择、Evidence Grounding、replan 决策和只读场景 Action 禁止。

指标及默认 Gate：Case Pass Rate ≥ 0.95；Schema Validity、Operation Accuracy、Resource Scope Accuracy、Evidence Grounding、Decision Accuracy 均为 1.0；Unsafe Action Rate 必须为 0。Runner 输出机器可读 JSON，失败时返回非零退出码，GitHub Backend Workflow 会显式执行 `python -m app.evaluation`。

详细的数据集演进和执行规则见 `docs/Agent-Eval与Release-Gate.md`。

### 前端配合

6.5 是离线后端 Release Gate，不增加控制面接口或 OpenAPI。前端无需配合。

## 6.6 备份恢复、审计归档与开源安全

- PostgreSQL 备份工具使用 custom format，拒绝覆盖，生成独立 SHA-256 manifest；密码只进入子进程环境，不进入命令参数；
- 恢复前验证文件大小、哈希和 `pg_restore --list`，目标数据库必须为空、名称必须与源库不同，并要求操作者二次确认目标名称；
- GitHub Backend CI 使用 PostgreSQL 17 客户端执行真实备份/新库恢复，并比较源库与恢复库 Alembic Head；
- 审计默认在线保留 365 天，旧记录按批导出为 gzip JSONL；文件和 manifest 持久化后，数据库事务才登记不可变批次并删除源行；
- 新增根目录 `SECURITY.md` 和完整备份、恢复、归档 Runbook，明确私密报告渠道、响应目标、Secret 边界和演练要求。

新增迁移 `20260820_0034` 创建 `audit_archive_batches`。Phase 6 至此完成。

### 前端配合

6.6 仅增加运维 CLI、数据库归档清单和仓库安全文档，不修改用户 API 或 OpenAPI。前端无需配合。
