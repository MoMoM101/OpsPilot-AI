# Runner 部署与安全配置

> 状态：当前实现说明  
> 更新时间：2026-08-13  
> 适用范围：OpsPilot Control Plane、Runner、只读 Connector 与受控 Docker Action Connector

## 1. Runner 是什么

Runner 是 OpsPilot 的独立执行面，部署在能够访问目标资源的机器或网络中。它负责：

- 向控制面注册并发送心跳；
- 声明本机实际可用的 Connector 能力；
- 领取带 Lease 和 Fencing Token 的只读任务与已授权 Action；
- 在本机执行受限观测操作；
- 本地脱敏、限制输出后回传结果；
- 不负责决定调查方向，也不调用大模型。

Runner 不是前端的一部分。浏览器不得保存 Runner Access Token，也不得直接调用 Runner
注册、心跳、领取、续租或结果回传接口。

## 2. 为什么需要部署配置

Runner 能够接触 Docker Engine、日志文件和内部网络，因此必须拥有独立于 Agent 和前端的
安全边界。控制面下发任务不等于 Runner 必须执行；Runner 会再次检查本地白名单。

白名单回答三个问题：

1. 哪些目录允许读取；
2. 哪些 systemd Unit 允许查询；
3. 哪些主机和端口允许探测。

这些配置由部署 Runner 的管理员设置一次，不是每次查询都配置。未配置某项白名单时，
Runner 不会向控制面声明对应能力，也不会领取这类任务，这属于 Fail Closed 行为。

## 3. 组件职责

| 组件 | 负责 | 不负责 |
|---|---|---|
| 前端 | 创建调查/只读任务、展示状态和 Evidence | 配置白名单、保存 Runner Token、执行系统命令 |
| 控制面 | 任务校验、排队、Lease、Fencing、Evidence、SSE | 直接访问 Docker、日志文件或目标端口 |
| Runner | 本地能力发现、白名单校验、只读执行、受控 Action、脱敏和截断 | 决策、授权扩张、任意 Shell、未声明写操作 |
| 部署管理员 | 首次配置 Runner 的资源范围和凭据 | 为每条前端查询手工配置参数 |

## 4. 当前支持的只读能力

| Connector | Operation | 默认状态 | 本地限制 |
|---|---|---|---|
| Docker | `docker.list_containers` | 启用 | 固定 Docker CLI 参数 |
| Docker | `docker.inspect_container` | 启用 | 输出字段白名单，移除 Env/Labels/宿主机源路径 |
| Docker | `docker.container_health` | 启用 | 只返回状态和健康摘要 |
| Docker | `docker.container_logs` | 启用 | 容器 ID、行数、时间范围受限 |
| File | `file.tail` | 默认关闭 | 必须配置允许目录，最多 2000 行 |
| Journal | `journal.query` | 默认关闭 | 必须配置允许 Unit，限制时间和优先级 |
| HTTP | `http.probe` | 默认关闭 | 主机/端口白名单，不跟随重定向，不使用系统代理 |
| TCP | `tcp.probe` | 默认关闭 | 主机/端口白名单，只连接后关闭，不发送数据 |
| Prometheus | `prometheus.query` | 默认关闭 | 复用主机/端口白名单，限制 PromQL 和响应大小 |
| Prometheus | `prometheus.query_range` | 默认关闭 | 最长 6 小时，限制步长、序列和样本数量 |
| Host | `host.snapshot` | 启用 | 无参数、无 Shell，不读取命令行、环境变量、IP 或 MAC |
| SQLite | `sqlite.health/lock_status/integrity_check` | 默认关闭 | 数据库路径根目录白名单、只读 URI、固定查询 |
| Qdrant | `qdrant.health/collection/point_count/query_smoke` | 默认关闭 | 主机/端口白名单、固定 collection 与有限向量 |
| RAG | `rag.business_health` | 默认关闭 | 固定 POST 契约、目标白名单、答案脱敏与限长 |

Runner 额外提供 `container.restart` 与 `health.check` 两个受控 Action。前者只接受
`containerId`，后者只接受表示 Docker 容器 ID 或名称的 `target`；两者都使用固定 Docker CLI
参数数组且不经过 Shell。Runner 不提供 `stop`、`remove`、`exec` 或任意 Shell 能力。

`host.snapshot` 在 Linux 上读取受限的 `/proc` 汇总字段；Windows 等平台会自动省略不可用的
Linux 字段。该能力不需要额外环境变量。

## 5. 启动顺序

### 5.1 启动 PostgreSQL

在仓库根目录执行：

```powershell
docker compose up -d postgres
```

### 5.2 执行数据库迁移并启动控制面

```powershell
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

### 5.3 配置并启动 Runner

在 `runner/` 目录创建 `.env`。首次本地联调示例：

```env
OPSPILOT_RUNNER_CONTROL_PLANE_URL=http://localhost:8000/runner/v1
OPSPILOT_RUNNER_ENVIRONMENT=development
OPSPILOT_RUNNER_ALLOW_INSECURE_HTTP=false
OPSPILOT_RUNNER_NAME=windows-docker-runner
OPSPILOT_RUNNER_ENVIRONMENT_ID=替换为环境UUID
OPSPILOT_RUNNER_BOOTSTRAP_TOKEN=替换为与后端相同的注册Token
OPSPILOT_RUNNER_CREDENTIAL_FILE=.opspilot-runner-credentials.json
OPSPILOT_RUNNER_HEARTBEAT_SECONDS=20
OPSPILOT_RUNNER_TASK_RENEW_SECONDS=30
OPSPILOT_RUNNER_ACTION_RENEW_SECONDS=30
OPSPILOT_RUNNER_ACTION_TIMEOUT_SECONDS=120
OPSPILOT_RUNNER_POLL_SECONDS=2
OPSPILOT_RUNNER_DOCKER_TIMEOUT_SECONDS=30
OPSPILOT_RUNNER_MAX_OUTPUT_BYTES=65536
OPSPILOT_RUNNER_SQLITE_ALLOWED_ROOTS=["D:/apps/rag/data"]
OPSPILOT_RUNNER_PROBE_ALLOWED_HOSTS=["qdrant","rag-api"]
OPSPILOT_RUNNER_PROBE_ALLOWED_PORTS=[6333,8000]
```

启动：

```powershell
cd runner
..\.venv\Scripts\python.exe -m opspilot_runner serve
```

环境 UUID 可以通过 `GET /api/v1/environments` 获取。生产环境下，后端和 Runner 必须配置
相同的 `OPSPILOT_RUNNER_BOOTSTRAP_TOKEN`。

Runner 只连接独立的 `/runner/v1` 服务面。注册、心跳、领取、续租和完成接口不再暴露在
`/api/v1` 用户面，也不会进入控制台使用的 OpenAPI。`GET /api/v1/runners` 与
`GET /api/v1/runner-tasks` 仍属于用户只读接口。

### 5.4 使用统一 Compose 启动 Runner

根目录 Compose 已包含 Runner 的可选 `runner` Profile，并通过 Compose Secret 文件注入注册
Token。先创建 Environment，将 UUID 写入根目录 `.env` 的
`OPSPILOT_RUNNER_ENVIRONMENT_ID`，再执行：

```powershell
docker compose --profile runner build runner
docker compose --profile runner up -d runner
```

Runner 镜像以 UID/GID `10001` 运行，凭据持久化到 `opspilot-runner-data` 命名卷。镜像只包含
Docker CLI，不运行 Docker Daemon；Docker Connector 通过只读执行逻辑访问宿主机转发的
`/var/run/docker.sock`。Linux 需要把 Socket 的组 ID 配置到 `OPSPILOT_DOCKER_GID`。完整服务
依赖、Secret 和升级步骤见 [容器化部署](容器化部署.md)。

## 6. Connector 白名单

### 6.1 Windows 文件日志

```env
OPSPILOT_RUNNER_LOG_ALLOWED_ROOTS=["D:/logs","D:/apps/opspilot/logs"]
```

注意：

- 使用 JSON 数组格式；
- 目标文件解析后的真实路径必须位于允许目录内；
- 目录、越界路径、失效文件和二进制内容会被拒绝；
- 不要把磁盘根目录或用户主目录整体加入白名单。

### 6.2 Linux 文件日志和 Journal

```env
OPSPILOT_RUNNER_LOG_ALLOWED_ROOTS=["/var/log/opspilot","/srv/app/logs"]
OPSPILOT_RUNNER_JOURNAL_ALLOWED_UNITS=["docker.service","opspilot.service"]
```

Journal Connector 依赖 Linux 的 `journalctl`。Windows Runner 不配置
`OPSPILOT_RUNNER_JOURNAL_ALLOWED_UNITS`。

### 6.3 HTTP/TCP Probe

```env
OPSPILOT_RUNNER_PROBE_ALLOWED_HOSTS=["localhost","127.0.0.1","*.internal.example"]
OPSPILOT_RUNNER_PROBE_ALLOWED_PORTS=[80,443,5432,6333,8000]
```

规则：

- 主机和端口必须同时命中白名单；
- `*.internal.example` 不包含根域名 `internal.example`；
- HTTP 只支持 `GET` 和 `HEAD`；
- URL 不允许用户名、密码、查询字符串或 Fragment；
- HTTP 不跟随重定向，响应正文默认不采集；
- TCP 只测试连接性，不发送业务协议数据；
- Prometheus 复用相同白名单，不需要新增环境变量；
- Prometheus URL 不允许凭据、查询字符串或 Fragment；
- PromQL 最长 2000 字符，范围查询最长 6 小时、每序列最多 11000 个请求点；
- 不建议配置任意主机或全端口范围。

### 6.4 SQLite、Qdrant 与 RAG Lab

```env
OPSPILOT_RUNNER_SQLITE_ALLOWED_ROOTS=["/lab/data"]
OPSPILOT_RUNNER_PROBE_ALLOWED_HOSTS=["qdrant","rag-api"]
OPSPILOT_RUNNER_PROBE_ALLOWED_PORTS=[6333,8000]
```

- SQLite 文件解析后的真实路径必须位于允许根目录，Connector 使用只读 URI 和固定诊断语句；
- 任务不能提交 SQL、PRAGMA 名称或数据库写参数；
- Qdrant collection 只能使用部署时写入 Resource 的固定名称；
- Qdrant smoke vector 最多 4096 个有限数值，不回传 point payload 或 vector；
- RAG 只向固定 URL 发送 `{"question": "..."}`，只读取 `answer` 字段；
- Qdrant/RAG 响应读取上限为 1 MiB，不跟随重定向、不使用系统代理；
- 生产环境不得把任意数据库目录、任意主机或全端口加入白名单。

## 7. 凭据生命周期

首次注册成功后，Runner 会收到一次性 Access Token，并保存到：

```text
runner/.opspilot-runner-credentials.json
```

该文件已加入 `.gitignore`。注意：

- 不得提交到 Git；
- 不得复制到前端或浏览器；
- 应随 Runner 数据持久化；
- 删除本地文件不会撤销服务端 Runner 身份；
- 如果文件丢失，需要由管理员轮换或重建 Runner 身份，不能直接使用同名 Runner 重注册。

控制面数据库只保存 Access Token 的 SHA-256 摘要，不保存明文。

## 8. 配置变更如何生效

修改 Runner `.env` 后需要重启 Runner。重启后的下一次心跳会重新上报能力：

- 新增白名单：对应 Connector 出现在 `GET /api/v1/runners` 的 `capabilities` 中；
- 删除白名单：对应 Connector 不再声明，也不会领取新任务；
- 已经租出的任务仍受 Task Lease、Runner Token 和 Fencing Token 约束。

前端应根据 Runner 实际上报的 `capabilities` 展示可用查询，而不是假设所有 Runner 都支持
全部 Connector。

### 8.1 Runner 失联与自动恢复

控制面默认每 15 秒扫描一次 Runner Lease。扫描间隔由控制面环境变量配置，不需要在
Runner 或前端重复配置：

```env
OPSPILOT_OBSERVABILITY_MONITOR_INTERVAL_SECONDS=15
```

当在线 Runner 的 Lease 过期时，控制面会在同一事务内：

- 将 Runner 标记为 `offline`；
- 将该 Runner 已租用且仍可重试的任务重新置为 `queued`，清除 Runner、Task Lease 和
  Task Fencing Token，使其他兼容 Runner 可以领取；
- 将已达到最大尝试次数的任务标记为 `failed`，错误码为
  `RUNNER_LEASE_EXPIRED`；
- 仅把确实存在上述租用任务、且处于 `INVESTIGATING` 的 Incident 转为
  `OBSERVABILITY_LOST`，记录失联 Runner 和时间；
- 发送 `incident.observability_lost` SSE 事件。

Runner 恢复心跳后，只有由该 Runner 造成失联的 Incident 会自动回到
`INVESTIGATING`，并发送 `incident.observability_restored` SSE 事件。同环境但没有关联
租用任务的 Incident 不受影响。

`offline` 只表示观测执行面失联，不表示业务目标宕机。前端和告警规则不得把 Runner
离线直接解释为目标资源故障。

Runner 在 Connector 执行期间不会停止维护控制面租约：它会继续按
`OPSPILOT_RUNNER_HEARTBEAT_SECONDS` 发送 Runner 心跳，并按
`OPSPILOT_RUNNER_TASK_RENEW_SECONDS` 指定的最大间隔续租任务。实际续租间隔还会根据 Claim
返回的 `leaseExpiresAt` 自动缩短到剩余租期的约三分之一，因此该配置不能强制 Runner
晚于安全续租点续租。任务本地执行时间仍受控制面 `timeoutSeconds` 与 Runner 本地超时上限
共同约束。

如果续租返回 `RUNNER_TASK_NOT_LEASED`、`STALE_TASK_FENCING_TOKEN` 或
`TASK_LEASE_EXPIRED`，Runner 会取消仍在进行的本地只读执行，不再上传该租约产生的结果。
Docker 和 Journal 子进程也会随取消被终止。网络故障等无法确认租约归属的错误会终止当前
执行流程，由进程监督器按部署策略重启 Runner；控制面在 Lease 到期后负责安全重排任务。

Action 执行期间使用 `OPSPILOT_RUNNER_ACTION_RENEW_SECONDS` 同时续租 Action Execution 和
Resource Lock，本地最长执行时间由 `OPSPILOT_RUNNER_ACTION_TIMEOUT_SECONDS` 限制。续租返回过期
或 Fencing 冲突时，Runner 会终止本地子进程且不发送完成结果；控制面随后将其置为 `unknown`，
必须对账后才能释放资源锁。完成请求只对网络错误和 5xx 做有限重试，所有重试复用同一个
`completionId`，不会在不确定结果下重新执行写动作。

批准后的 Compensation 复用相同 Runner Action Worker。Claim 中的 `executionKind` 会标记为
`compensation`，并附带 `compensationId`；Runner 不自行决定是否补偿，也不扩大 Capability 或
参数。补偿仍受相同的 Action 白名单、Execution/Resource 双 Fencing Token、续租和完成幂等约束。

### 8.2 Runner Token 自动轮换

Runner Access Token 不再永久有效。控制面默认配置：

```env
OPSPILOT_RUNNER_TOKEN_ROTATION_SECONDS=86400
OPSPILOT_RUNNER_TOKEN_TTL_SECONDS=604800
OPSPILOT_RUNNER_TOKEN_GRACE_SECONDS=600
```

- 注册响应包含 `tokenExpiresAt`；
- 达到轮换周期后，心跳响应通过一次性 `accessToken` 换发新 Token；
- Runner 先原子写入凭据文件，再切换内存凭据；
- 旧 Token 仅在宽限期内可用；如果轮换响应丢失，使用旧 Token 再次心跳会重新换发；
- 超过硬过期时间返回 `RUNNER_TOKEN_EXPIRED`，需要管理员重建 Runner 身份；
- 服务端始终只保存当前与宽限 Token 的 SHA-256 摘要，不保存明文。

`rotation < ttl` 且 `grace < ttl` 由配置校验强制保证。生产 Runner 的控制面地址必须使用
HTTPS；只有单机私有 Compose 网络才显式设置
`OPSPILOT_RUNNER_ALLOW_INSECURE_HTTP=true`。该例外不得复制到跨主机部署。

### 8.3 调查步骤与工具预算

当 Incident 存在活动 Plan 时，控制面创建 RunnerTask 必须携带 `planStepId`。控制面会在
任务进入队列前检查：

- PlanStep 属于该 Incident 的活动 Plan；
- PlanStep 当前为 `running`；
- Step 类型允许只读观测；
- Operation 存在于 Step 的 `allowedCapabilities`；
- 配置了 `resourceScope` 时，目标 Resource 必须在范围内；
- Incident 的 `maxToolCalls` 预算仍有剩余。

每个新的幂等任务消耗一个工具预算单位；使用同一个 Idempotency Key 重放不会重复扣减。
成功采集的 Evidence 会自动关联回原 PlanStep。Runner 只按收到的任务执行，不负责计算或
修改预算，也不能绕过控制面的 Step 范围。

发生 Replan 时，旧 Plan 中仍为 `queued` 或 `leased` 的任务会被控制面标记为
`cancelled`，清除 Task Lease 和 Fencing Token，并发送 `runner_task.cancelled`。步骤进入
`completed`、`failed`、`blocked` 或 `skipped` 时，其残留活动任务也采用相同行为。已经
消耗的工具预算不会返还，因为任务可能已经产生外部读取成本。

Runner 可能在本地执行期间遇到控制面取消。此时结果回传会收到任务不再处于 `leased` 的
冲突响应；Runner 应停止重试该次完成请求并继续领取新任务。由于当前仅允许有界只读任务，
取消不会引入写操作的半完成状态。

## 9. 常见问题

### Runner 注册提示名称冲突

检查 `.opspilot-runner-credentials.json` 是否被误删。如果凭据确实丢失，需要重建或轮换
服务端 Runner 身份，不要反复更换名称绕过。

### Runner 在线但领取不到任务

依次检查：

1. Runner 的 `environmentId` 是否与 Resource 环境一致；
2. `GET /api/v1/runners` 是否包含任务所需 Connector 和 Operation；
3. 白名单是否已配置并重启 Runner；
4. Runner 心跳 Lease 是否过期；
5. 任务是否已被其他 Runner 租用。

### Docker Connector 报权限错误

确认 Docker Desktop/Engine 已启动，并确保启动 Runner 的操作系统用户能够执行：

```powershell
docker version
docker container ls --all
```

不要为解决权限问题把 Runner 改成不必要的高权限账户。

### HTTP/TCP 目标被拒绝

检查目标主机和端口是否同时存在于白名单。白名单是 Runner 本地安全边界，前端参数不能
临时扩大它。

## 10. 当前限制与后续计划

当前版本已经实现严格白名单模式。以下内容尚未实现，不应按已具备能力使用：

- `local-dev` 一键宽松配置 Profile；
- Runner Token 在线轮换和吊销 API；
- Runner mTLS；
- 由控制面签名下发、Runner 验签的动态资源范围；
- 多套部署配置模板和安装服务脚本。

计划中的 `local-dev` Profile 只用于本地开发，正式环境仍必须使用显式白名单和默认拒绝。

## 11. 文档维护规则

本文件是 Runner 的持续维护文档。出现以下变更时，必须在同一个开发任务内同步更新：

- 新增、删除或重命名 Connector/Operation；
- 新增、删除或修改 Runner 环境变量；
- 注册、心跳、任务 Lease、Fencing 或凭据生命周期发生变化；
- 白名单、脱敏、输出限制、网络访问或权限边界发生变化；
- Windows、Linux、Docker 或服务化启动方式发生变化；
- 发现新的常见部署错误或排查步骤；
- `local-dev`、mTLS、Token 轮换等后续计划正式落地。

完成相关代码前应检查本文件，交付时应确认示例与 `.env.example`、OpenAPI 和实际行为一致。
