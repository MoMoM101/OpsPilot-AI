# 后端 Phase 7：前端与产品化支撑

> 状态：架构 Review 整改完成，待运行验收与复审  
> 当前批次：7.13 Admin 安全、Demo 漂移与列表契约整改

Phase 7 的页面和交互由前端负责；后端只建设产品化所需的安全契约、初始化流程和运行检查，不修改前端页面代码。

## 开发顺序

| 批次 | 后端范围 | 状态 |
|---|---|---|
| 7.1 | 首次启动状态、一次性 Admin 初始化、部署预检 | 已完成 |
| 7.2 | 模型连接检查与安全诊断 | 已完成 |
| 7.3 | Demo 数据初始化与可重复清理 | 已完成 |
| 7.4 | 控制台列表分页、筛选与错误文案契约收敛 | 已完成 |
| 7.5 | Connector 能力目录、环境就绪度与兼容性诊断 | 已完成 |
| 7.6 | Dashboard 真实 Runner、运行安全指标与聚合 Scope 收敛 | 已完成 |
| 7.7 | Action 参数、风险、验证与补偿能力只读元数据 | 已完成 |
| 7.8 | Incident 快照游标、SSE 确定性续流与历史回填 | 已完成 |
| 7.9 | Incident Timeline 最近窗口、有界分页与 Scope 收敛 | 已完成 |
| 7.10 | Investigation Run、Evidence、Hypothesis、HITL Wait 分页收敛 | 已完成 |
| 7.11 | Environment、Resource、Runner、RunnerTask、ResourceLock 分页收敛 | 已完成 |
| 7.12 | ActionProposal、Compensation、Dead Letter、Policy、Principal 分页收口 | 已完成 |
| 7.13 | Admin 防锁死、Demo Fail Closed、稳定分页与 Incident 完整筛选 | 已完成 |

## 7.1 首次启动与部署预检

新增公开接口：

```http
GET /api/v1/setup/status
```

返回服务版本、认证是否启用、首个 Admin 是否创建，以及 Bootstrap 凭据是否可用。该响应不包含
Bootstrap Token、Principal、Environment、模型配置或其他可枚举信息。部署向导无需先持有用户身份
即可判断进入初始化页还是登录页。

新增 Admin 专属接口：

```http
GET /api/v1/system/preflight
```

预检将结果分为：

- `action_required`：数据库、Control Plane 模式、首个 Admin、至少一个 Environment 等阻塞项；
- `warning`：在线 Runner、Agent Runtime、Alertmanager 鉴权等不阻塞控制台基础访问的推荐项；
- `pass`：检查通过。

响应仅包含固定检查键、状态和面向操作者的说明，不返回 Secret 值、模型 Base URL 或身份名称。

新增迁移 `20260820_0035` 创建 `control_plane_setup` 单例状态。升级历史数据库时，如果已存在有效
`user/admin`，迁移自动记录最早创建的 Admin 并将初始化标记为完成；全新数据库保持待初始化。
首次管理员创建事务会锁定该单例行并同时写入完成状态，避免 Bootstrap Token 被并发重复消费。

## 前端配合

本批次需要前端对接两个契约：

1. 未登录时调用 `GET /api/v1/setup/status`：`initialization_required` 进入首次 Admin 初始化引导，
   `ready` 进入普通登录页；不要缓存 `bootstrapAvailable`。
2. Admin 系统状态页调用 `GET /api/v1/system/preflight`：阻塞项和警告项分开展示，不应把 `warning`
   当作服务不可用。

创建首个 Admin 仍使用 `POST /api/v1/principals`，Bootstrap Token 放在 `Authorization: Bearer`，
不得写入 URL、日志、LocalStorage 或前端配置文件。成功响应中的 Admin `accessToken` 只显示一次，
随后应立即调用 `POST /api/v1/auth/session` 交换为浏览器 Session。

## 7.2 模型连接检查与安全诊断

新增 Admin 专属接口：

```http
POST /api/v1/system/model-connection-check
```

接口没有请求体，不接受浏览器提供的模型名、Base URL、API Key、Prompt 或超时参数。它只使用服务端
启动时已验证的 Agent Provider 配置，发出一次固定、结构化且无 Tool 的最小探测请求。独立总超时
默认 15 秒；同一进程中的并发请求串行合并，完成后默认 30 秒内复用结果，防止重复点击产生并发
费用或放大 Provider 故障。

状态语义：

| status | 含义 |
|---|---|
| `ok` | Provider 完成固定结构化响应 |
| `failed` | 已尝试连接但失败，结合固定 `errorCode` 展示 |
| `disabled` | Agent Runtime 未启用，未访问外部 Provider |
| `not_configured` | Runtime 已启用但当前进程没有可用 Provider |

固定错误码包括认证失败、限流、超时、上游不可用、Provider 拒绝和通用检查失败。后端不把 Provider
原始异常、响应 Body、凭据、模型名或 Base URL 返回浏览器。探测接口在 Control Plane 只读降级模式
下仍可调用，因为它不写业务数据库；调用本身继续受 Admin RBAC、浏览器 CSRF 和写请求审计保护。

配置项：

```text
OPSPILOT_AGENT_MODEL_CHECK_TIMEOUT_SECONDS=15
OPSPILOT_AGENT_MODEL_CHECK_COOLDOWN_SECONDS=30
```

### 前端配合

Admin 模型设置/系统诊断页增加“检查连接”操作，对接无请求体的
`POST /api/v1/system/model-connection-check`：

- `cached=true` 时可标记为近期结果，不要自动循环重试；
- `disabled` 和 `not_configured` 展示配置引导，不作为 HTTP 错误处理；
- `failed` 只根据 `errorCode` 和服务端 `message` 展示，不拼接本地保存的模型配置；
- 前端不得向该接口发送 API Key、模型名、Base URL 或自定义 Prompt。

本批次不修改其他业务 API，也不要求调整 Incident、Action、Runner 或 Fault Lab 页面。

## 7.3 Demo 数据初始化与可重复清理

Demo 数据默认关闭，且在 `production` 环境中即使错误配置开关也强制不可用：

```text
OPSPILOT_DEMO_DATA_ENABLED=true
```

仅应在 `development`、`test` 或隔离的 `staging` 部署启用。接口全部限制为 Admin：

```http
GET  /api/v1/demo/status
POST /api/v1/demo/initialize
POST /api/v1/demo/cleanup
```

初始化创建一个带服务端管理标记的 Guided Demo Environment、三个 Resource、依赖拓扑，以及两个
Incident 故事：一个停留在调查阶段，另一个展示从发现到关闭的完整合法状态路径。每个故事包含有界
合成 Evidence、Hypothesis 和 Timeline/Outbox 事件，不包含真实地址、凭据或 Connector 参数。

新增 `demo_installations` 所有权清单和迁移 `20260821_0036`。清单记录固定 manifest 版本、当前
generation，以及后端实际创建的 Environment、Resource 和 Incident ID。初始化采用单例行锁；当前
generation 已处于 active 时返回 `replayed=true`，不会生成重复数据。

清理请求必须携带当前 generation：

```json
{
  "expectedGeneration": 1
}
```

后端仅按清单中的 Incident UUID 删除，并依赖 Incident 外键级联清理对应 Evidence、Hypothesis、
Timeline、Plan、Action 和 Outbox 数据。它不会按名称、slug 或整个 Environment 批量删除，也不会
删除用户后来在 Demo Resource 上创建的 Incident。Environment、Resource 和拓扑骨架保留供下一轮
初始化复用；再次初始化递增 generation 并生成全新的 Incident ID。

如果清单中的 Incident 被外部方式删除，状态返回 `drifted`，初始化拒绝静默覆盖；如果 Environment
或 Resource 的服务端管理标记、版本或归属发生变化，同样返回 `DEMO_DATA_DRIFT`。旧页面使用过期
generation 清理时返回 `DEMO_GENERATION_CONFLICT`。

### 前端配合

Admin Demo 引导页需要对接：

- 页面加载调用 `GET /demo/status`；`unavailable` 根据 `reasonCode` 展示开关或环境说明；
- 点击初始化调用无请求体的 `POST /demo/initialize`；`replayed=true` 直接复用返回的 ID；
- 使用返回的 `environmentId`、`resourceIds`、`incidentIds` 提供拓扑和 Incident 快捷入口；
- 清理时必须发送页面刚读取到的 `expectedGeneration`，409 后重新获取状态，不自动重试；
- `drifted` 状态只提供人工检查提示，不提供“强制清理”按钮。

普通 Operator、Viewer 页面不需要新增 Demo 写操作。初始化或清理成功后，应使 Incident、Dashboard
和 Resource 查询缓存失效。

## 7.4 控制台列表分页、筛选与错误契约

以下高频列表继续返回原有 JSON 数组，避免破坏现有客户端；同时新增标准分页响应头：

```text
X-Total-Count: 当前筛选条件下的记录总数
X-Limit:        本次请求的 limit
X-Offset:       本次请求的 offset
```

覆盖接口：

- `GET /incidents`
- `GET /alerts`
- `GET /approvals`
- `GET /actions`
- `GET /audit-logs`

`X-Total-Count` 在数据库中应用与列表完全相同的 Environment Scope 和业务筛选后计算，不是当前页
长度。以上响应头已加入 CORS `Access-Control-Expose-Headers`，浏览器可以直接读取。OpenAPI 同步声明
三个响应头，生成的 TypeScript 契约将其表示为数字。

Admin 审计列表新增数据库筛选参数：

```http
GET /api/v1/audit-logs?actorId=...&action=...&outcome=...&from=...&to=...
```

`from` 和 `to` 是 ISO 8601 时间且包含边界；二者同时提供时 `from > to` 返回
`INVALID_TIME_RANGE`。筛选在 `limit/offset` 之前执行。

所有请求校验错误仍使用统一错误信封，但 `details` 只包含 `type`、`location` 和 `message`。后端不再
返回 Pydantic 的原始 `input`、`ctx` 或文档 URL，避免 Token、密码和 Webhook 内容因 422 响应进入
浏览器、日志或监控。OpenAPI 的全局 422 响应已更新为实际的 `ValidationErrorResponse`，不再声明
FastAPI 默认的 `HTTPValidationError`。

容器构建也调整了依赖层：Python 依赖只受 `pyproject.toml`、`README.md` 和包入口文件变化影响，
普通业务源代码变更不再使依赖安装层失效；BuildKit 同时复用 pip 缓存。

### 前端配合

本批次前端需要完成：

1. 上述五个列表的分页组件从响应头读取 `X-Total-Count`，不要再用 `items.length` 推断是否有下一页；
   请求和响应 Body 均保持不变。
2. Admin 审计页可对接 `actorId`、`action`、`outcome`、`from`、`to` 服务端筛选；修改筛选条件时将
   `offset` 重置为 0。
3. 统一 422 展示逻辑改读 `error.details[].location/message`。不得依赖已删除的 `input`、`ctx`、
   `loc` 或 Pydantic `url` 字段，也不要展示用户提交的 Secret。

Incident、Alert、Approval、Action 的现有筛选参数和数组数据结构没有变化；其他列表本批次无需改造。

## 7.5 Connector 配置向导只读支撑

新增所有已认证控制面角色可读取的接口：

```http
GET /api/v1/connectors?environmentId={environmentId}
```

接口返回当前版本支持的十类 Connector 固定目录：Docker、Host、File、Journal、HTTP、TCP、
Prometheus、SQLite、Qdrant 和 RAG。每项包含：

- Connector Contract 版本、只读 Observation 和受控 Action Operation；
- `built_in` 或 `allowlist` 配置方式；
- Runner 本地配置键名、平台要求和固定前置条件；
- 当前环境可用 Runner 的聚合就绪度。

就绪度状态：

| status | 含义 |
|---|---|
| `ready` | 至少一个在线、Contract 主版本兼容的 Runner 覆盖全部声明 Operation |
| `partial` | 存在兼容在线 Runner，但只覆盖部分 Operation |
| `offline` | 已配置兼容 Runner，但当前没有有效在线 Lease |
| `not_configured` | 当前 Scope 内没有 Runner 声明该 Connector |
| `incompatible` | Runner 已声明该 Connector，但 Contract 主版本不兼容 |

`environmentId` 不提供时，按当前 Principal 的 Environment Scope 聚合；提供时先通过受 Scope 约束的
Environment 查询验证，不能用其他环境 UUID 探测 Runner 能力。绑定特定环境的 Runner 只计入该环境；
未绑定环境的全局 Runner 按现有任务调度语义计入所有已授权环境。

响应只包含 Runner 数量和在线 Runner 可提供的 Operation 并集，不包含 Runner ID、名称、标签、
软件版本、目标地址、允许路径、查询语句、Token 或其他凭据。浏览器不能通过该接口写入 Runner 配置；
配置仍由部署者在 Runner 本地完成，Runner 重启或心跳后以既有 Capability 协议声明实际能力。

目录测试强制覆盖 `RunnerReadOperation` 的全部枚举值，新增 Operation 如果没有同步更新产品目录会使
测试失败，避免控制面、Runner 和前端向导静默漂移。本批次不新增数据库表或迁移。

### 前端配合

Connector 配置向导需要：

1. 页面进入或切换 Environment 时调用 `GET /connectors?environmentId=...`，按固定 `status` 展示
   已就绪、部分就绪、离线、未配置或版本不兼容。
2. 仅把 `runnerSettingKeys` 作为 Runner 部署说明展示；不要生成向控制面提交地址、路径、端口或
   Secret 的表单。配置完成后提示用户重启 Runner，再刷新目录状态。
3. `readyObserveOperations` 和 `readyActionOperations` 表示当前在线能力；目录中的
   `observeOperations/actionOperations` 表示产品支持上限，二者不能混用。
4. `ENVIRONMENT_NOT_FOUND` 同时表示环境不存在或当前用户无权访问，不应提示“该环境确实存在但无权”。

现有 Runner 列表和注册/心跳协议没有变化；本批次不要求修改 Runner Agent。

## 7.6 Dashboard 运行与安全聚合

`GET /api/v1/dashboard` 原有响应字段保持兼容，`runnerOnline` 和 `runnerTotal` 不再返回固定 0：

- `runnerOnline` 统计状态为 online 且 Lease 尚未过期的可见 Runner；
- `runnerTotal` 统计当前 Principal Scope 可使用的全部注册 Runner；
- 未绑定 Environment 的全局 Runner 只计数一次，并按调度语义对受限 Scope 可用；
- 响应仍不返回额外 Runner 身份或配置数据。

新增 `safety`：

```json
{
  "pendingApprovals": 0,
  "activeResourceLocks": 0,
  "unknownActions": 0,
  "actionsRequiringAttention": 0,
  "observabilityLostIncidents": 0
}
```

字段语义：

- `pendingApprovals`：尚未过期的 pending Approval；
- `activeResourceLocks`：尚未释放且 Lease 有效，或明确要求 reconcile 的锁；
- `unknownActions`：状态为 `unknown`、必须先对账的 Action；
- `actionsRequiringAttention`：`unknown/failed/verification_failed/escalated` Action 总数；
- `observabilityLostIncidents`：当前处于 `OBSERVABILITY_LOST` 的 Incident。

本批次同时修复 Dashboard 聚合侧信道：此前 Incident 状态计数、完成率和平均调查时长没有应用
Environment Scope，因此接口只能对拥有全局 Environment 权限的 Principal 开放。现在所有 Incident、
Approval、Action、Resource Lock 和 Runner 聚合都在 Repository 层应用 Scope，受限 Viewer/Operator
可以安全读取 Dashboard；隐藏环境既不影响数值，也不出现在最近 Incident 列表中。

本批次不新增数据库表或迁移。

### 前端配合

Dashboard 需要：

1. 移除 Runner 指标和运行安全区的“暂未接入”占位，直接使用 `runnerOnline/runnerTotal` 与
   `safety` 五项指标。
2. `actionsRequiringAttention` 是多个需人工关注状态的并集，不能与 `unknownActions` 相加；UNKNOWN
   已包含在前者中。
3. 受限 Viewer/Operator 现在可以访问 Dashboard；前端不应再因为用户不是全局 Principal 而隐藏
   Dashboard 导航。
4. 所有数字都是当前用户 Environment Scope 下的快照。切换身份或授权范围后应使 Dashboard 查询
   缓存失效。

## 7.7 Action Capability 只读元数据

新增所有已认证控制面角色可读取的固定契约：

```http
GET /api/v1/action-capabilities
```

目录包含服务端 Action Allowlist 的全部能力，并明确区分：

- `available`：内置 Runner 当前具备执行与可信验证映射；
- `reserved`：领域和 Policy 已保留名称，但当前版本没有内置执行/验证链路，不能作为可用操作展示。

每项返回唯一参数键、字符串长度约束、操作效果、建议风险、执行 Connector、审批模式、验证映射和
补偿语义。`approvalMode=policy` 表示是否审批仍由 Policy Decision 决定，前端不能根据风险自行跳过
审批。当前可用能力只有：

| capability | 参数 | effect | 建议风险 | 验证 | 补偿 |
|---|---|---|---|---|---|
| `container.restart` | `containerId` | mutation | medium | `docker.container_health` | manual_escalation |
| `health.check` | `target` | observation | read_only | `docker.container_health` | not_applicable |

`container.restart` 明确不支持自动补偿，目录不会把“再次 restart”描述为回滚。其余保留能力在内置
Runner 和独立验证模型完成前均为 `reserved/unavailable`。所有目录项的 `compensation.supported`
当前均为 `false`，因此控制面不应再让用户自由填写 `rollbackCapability`。

后端参数校验、Action 调度的 Runner 选择、Verification Task 参数映射和目录共用同一组定义；测试还
会校验 `available` 集合与 Docker Runner Contract 完全一致，防止新增能力时只修改其中一层。本批次
不新增数据库表或迁移。

### 前端配合

Action 创建/提议页面需要：

1. 读取 `GET /action-capabilities`，只允许选择 `availability=available` 的能力；`reserved` 可隐藏或
   只读展示为“尚未提供”，不能提交。
2. 根据 `parameter.key/minLength/maxLength` 生成唯一参数输入，不再维护 capability 到参数名的本地
   映射；`secret=false` 仍不代表可以把参数写入遥测日志。
3. `recommendedRisk` 仅用于默认提示，最终风险来自 Investigation Plan/Policy 流程，不能由前端据此
   推导是否需要审批；审批状态继续以 Policy Decision 和 Approval 接口为准。
4. 移除 `rollbackCapability` 自由输入。依据 `compensation.mode` 展示“人工升级”或“不适用”，仅当
   未来后端返回 `compensation.supported=true` 时才启用结构化补偿交互。
5. `verificationCriteriaRequired=true` 时仍需提交至少一条验证标准；目录中的 `verification` 仅用于
   解释后端实际验证方式，不是让浏览器直接调用 Runner。

## 7.8 Incident 快照与 SSE 恢复游标

`IncidentDetailResponse` 新增：

```json
{
  "eventCursor": 123
}
```

`eventCursor` 是该 Incident 快照已包含的最新 SSE/Outbox 全局序号。事件写入 Outbox 后，后端在同一
数据库事务中原子推进 Incident 游标；即使多个 Worker 并发产生事件，游标也只能增大，不能被较晚
提交的低序号覆盖。Incident 创建、状态流转和所有返回 Detail 的接口都会携带当前游标。

浏览器恢复连接时使用以下顺序：

1. 重新读取 `GET /api/v1/incidents/{incidentId}`，用响应完整替换本地 Incident、Plan、Step 和
   Timeline 快照；
2. 保存响应中的 `eventCursor`；
3. 请求 `GET /api/v1/incidents/{incidentId}/stream`，设置
   `Last-Event-ID: <eventCursor>`；
4. 仅把随后收到的事件作为增量应用，并持续保存每个 SSE `id`。

这样即使网络中断时间超过 Outbox 保留期，也不需要依赖已清理的历史事件恢复状态；快照提供当前
真相，游标保证快照之后提交的事件仍会重放。重复事件仍应按 SSE `id` 幂等处理。

新增迁移 `20260821_0037`。升级历史数据库时按每个 Incident 当前保留的最大 Outbox sequence 回填；
没有 Outbox 事件的记录回填为 0。迁移测试覆盖有历史事件、无事件和降级场景。本批次不改变 SSE
事件 Body 或事件类型。

### 前端配合

1. Incident 首次加载、页面重新可见、SSE 网络重连或身份刷新后，先重新获取 Incident Detail，再用
   `eventCursor` 作为 `Last-Event-ID` 建立流；不要只依赖内存中的旧 SSE ID。
2. Detail 快照必须先落地，再处理新流事件，避免旧快照覆盖已经收到的增量。
3. 继续按 SSE `id` 去重；`eventCursor=0` 是合法值，表示快照尚未对应任何可续流事件。
4. Incident 列表响应没有新增游标。只有进入具体 Incident 并取得 Detail 后才能建立该 Incident 的
   恢复流。

## 7.9 Incident Timeline 有界分页

此前 `IncidentDetailResponse.timeline` 会加载 Incident 的全部长期事件。长时间运行、包含大量
RunnerTask、Checkpoint、Action 和验证事件的 Incident 会导致数据库查询、API 响应和浏览器渲染
无界增长。

现在 Incident Detail 固定返回按 `occurredAt DESC, id DESC` 排序的最近 100 条事件，并新增：

```json
{
  "timelineTotal": 106,
  "timelineTruncated": true
}
```

- `timelineTotal` 是当前 Incident 的完整长期事件数量；
- `timelineTruncated=true` 表示 Detail 中只包含最近窗口；
- `timeline` 顺序保持最新事件在前，与原有页面展示顺序兼容；
- `eventCursor` 语义不变，它仍是 SSE/Outbox 游标，不是 Timeline 数组下标。

补齐架构约定的有界查询接口：

```http
GET /api/v1/incidents/{incidentId}/timeline?limit=100&offset=0
```

`limit` 范围为 1–200，默认 100；`offset` 从 0 开始。响应 Body 是
`IncidentEventResponse[]`，并返回 `X-Total-Count`、`X-Limit` 和 `X-Offset`。计数和分页都在数据库
完成，排序增加 UUID 次级键，避免同一时间戳事件跨页漂移。

接口先通过受 Environment Scope 约束的 Incident 查询验证访问权限。不存在和无权访问均返回
`INCIDENT_NOT_FOUND`，不能用 Timeline API 枚举隐藏环境。Timeline 是长期业务记录，与只有有限保留
期的 SSE Outbox 含义不同。本批次不新增数据库迁移。

### 前端配合

1. Incident Detail 适配必填 `timelineTotal` 和 `timelineTruncated`。未截断时可继续直接展示
   `timeline`。
2. `timelineTruncated=true` 时提供“加载更早事件”或分页入口，调用 `/timeline`；首次分页可以直接
   从 `offset=100` 获取 Detail 窗口之后的事件，或由页面统一改为从 `offset=0` 使用分页接口。
3. 分页总数读取 `X-Total-Count`，筛选/切换 Incident 时重置 offset；最大页大小不得超过 200。
4. SSE 新事件到达后应刷新 Detail 或 Timeline 第一页，并使 `timelineTotal` 缓存失效；不要简单把新
   事件永久追加到所有分页缓存。
5. `eventCursor` 仅用于 SSE `Last-Event-ID`，不得作为 Timeline 的 offset。

## 7.10 Investigation 派生数据分页收敛

以下四个已有查询统一支持数据库 `limit/offset` 分页并返回标准响应头：

```http
GET /api/v1/incidents/{incidentId}/investigation-runs?limit=50&offset=0
GET /api/v1/incidents/{incidentId}/evidence?limit=50&offset=0
GET /api/v1/incidents/{incidentId}/hypotheses?limit=50&offset=0
GET /api/v1/investigation-runs/{runId}/hitl-waits?limit=100&offset=0
```

每个响应均包含：

- `X-Total-Count`：应用当前 Incident、Environment Scope 和 Evidence 筛选后的完整总数；
- `X-Limit`：实际页大小；
- `X-Offset`：当前偏移。

Run、Evidence 原本已有请求分页参数，但没有返回总数；Hypothesis 和 HITL Wait 原本会返回全部记录，
现在分别限制最大页大小为 100 和 200。所有计数均在数据库完成，不使用“先取一页再内存过滤”的
方式。Evidence 的 `evidence_type/resource_id` 同时作用于列表和总数。

分页排序增加稳定次级键：Run、Evidence 使用时间倒序后按 ID；Hypothesis 使用置信度倒序和 Incident
内 ordinal；HITL Wait 使用创建时间和 ID 正序。受限 Principal 仍需先通过 Incident 或 Run 的
Environment Scope 验证，不存在和越权保持相同 404 语义。

`GET /investigation-runs/{runId}/checkpoints` 继续使用 `after_sequence + limit` 的有界 Keyset 查询，
不混入 offset 分页，也不返回 `X-Offset`。本批次不新增数据库迁移。

### 前端配合

1. Investigation Run、Evidence、Hypothesis 和 HITL Wait 列表统一从 `X-Total-Count` 获取总数，不用
   当前数组长度推断下一页。
2. Hypothesis 和 HITL Wait 请求新增 `limit/offset`；切换 Incident/Run 或 Evidence 筛选条件时将
   offset 重置为 0。
3. Evidence 总数已经包含 `evidence_type/resource_id` 条件；前端不能复用其他筛选组合的总数缓存。
4. Checkpoint 继续使用 `after_sequence`，不要改成 offset，也不要与本批次四个列表共用错误的分页
   状态模型。

## 7.11 资源与运行时列表分页收敛

以下五类已有列表统一补齐标准分页响应头：

```http
GET /api/v1/environments?limit=50&offset=0
GET /api/v1/resources?limit=50&offset=0
GET /api/v1/runners?limit=50&offset=0&status=online
GET /api/v1/runner-tasks?limit=50&offset=0&status=queued
GET /api/v1/resource-locks?limit=100&offset=0
```

响应继续使用原数组 Body，同时返回 `X-Total-Count`、`X-Limit` 和 `X-Offset`。其中：

- Environment、Resource 总数严格应用当前 Principal 的 Environment Scope；
- Runner 总数应用与 Runner 列表相同的 status 和 Scope 条件，不暴露隐藏环境 Runner 数量；
- RunnerTask 总数同时应用 status、incident_id、runner_id、plan_step_id 和 Resource Environment Scope；
- ResourceLock 只统计尚未释放且 Lease 有效，或明确要求 reconciliation 的活动锁；列表和计数使用
  同一个服务端时间快照，避免锁恰好到期时出现页长度与总数漂移。

列表排序增加稳定 ID 次级键：Environment、Resource、Runner 使用名称正序；RunnerTask 使用创建时间
倒序；ResourceLock 使用到期时间正序。计数全部在数据库完成。本批次不改变请求 Body、数组响应结构
或 Runner 协议，也不新增数据库迁移。

### 前端配合

1. Environment、Resource、Runner、RunnerTask、ResourceLock 分页组件统一读取 `X-Total-Count`，不要
   使用当前页数组长度推断下一页。
2. Runner status 和 RunnerTask 的四个筛选条件变化时重置 offset，并隔离不同筛选组合的总数缓存。
3. ResourceLock 的总数是当前时刻活动锁快照；前端定时刷新或收到锁 SSE 后应同时刷新列表和总数。
4. 受限用户看到的总数已经过 Scope 过滤，前端不得再与全局 Dashboard 数字拼接或推测隐藏资源。

## 7.12 控制面剩余列表分页收口

以下五类控制面列表完成统一分页契约：

```http
GET /api/v1/action-proposals?limit=50&offset=0
GET /api/v1/compensations?limit=100&offset=0
GET /api/v1/outbox/dead-letters?limit=100&offset=0
GET /api/v1/policies?environmentId={environmentId}&limit=100&offset=0
GET /api/v1/principals?limit=100&offset=0
```

响应 Body 继续使用原数组结构，并统一返回 `X-Total-Count`、`X-Limit` 和 `X-Offset`。Policy 和
Principal 新增 `limit/offset` 查询参数，最大页大小均为 200；其他三个接口保持原有查询参数和最大页
大小。ActionProposal 的 `incident_id/status`、Compensation 的 `incidentId` 会同时作用于列表和总数。

ActionProposal、Compensation 和 Policy 的总数严格应用当前 Principal 的 Environment Scope；无权访问
的环境不会通过总数泄露记录。Outbox Dead Letter 和 Principal 仍由现有 Admin 权限边界保护。所有计数
均在数据库完成，列表排序补充稳定唯一键，避免同一创建时间或名称的数据跨页漂移。本批次不修改数组
响应结构，不新增数据库迁移。

### 前端配合

1. 五类列表统一读取 `X-Total-Count`，不要使用当前页数组长度推断总数或下一页。
2. Policy 和 Principal 请求增加 `limit/offset`；Environment、Incident 或 status 筛选变化时重置
   offset。
3. 不同 Environment、Incident 和 status 组合的总数缓存必须隔离。
4. Dead Letter replay、Principal 创建/停用，以及 Policy 创建/更新后，应同时刷新当前页和总数。

## 7.13 架构 Review 整改

### Admin 防锁死

Principal 停用增加控制面单例 setup 行事务锁，串行化不同 Admin 的并发停用判定。禁止当前 Admin
停用自身；停用有效的全环境用户 Admin 前，必须确认还存在另一个 active、Token 未过期的全环境用户
Admin，否则返回 `LAST_UNRESTRICTED_ADMIN`。并发停用不同 Admin 时最多只有一个请求成功。

### Demo cleanup Fail Closed

Cleanup 获取 Demo installation 行锁后，数据库中实际存在的受管 Incident ID 集合必须与 Manifest 完全
一致，且 Manifest 不得包含重复 ID。任一 Incident 缺失或资源归属漂移时返回 `DEMO_DATA_DRIFT`，不删除
剩余数据，也不把 installation 标记为 inactive。

### Offset 分页稳定排序

Action Request、Action Proposal、Compensation、Incident、Alert、Approval 和 Audit Event 等 Offset
分页列表均以唯一 ID 作为最终排序键。相同时间戳的数据跨页查询不会因数据库未定义顺序而重复或遗漏。

### Incident 服务端筛选

```http
GET /api/v1/incidents?environmentId={environmentId}&q={keyword}&status={status}&severity={severity}
```

`q` 最大 200 字符，覆盖 Incident ID、标题、Resource ID、Resource 名称和负责人。列表和
`X-Total-Count` 共用同一个 Repository 筛选函数，同时应用 Environment Scope、`environmentId`、
`status`、`severity` 和 `q`，避免列表与总数条件漂移。

### 前端配合

1. Incident 列表的环境筛选传 `environmentId`，搜索框传 `q`，不再只对当前页做内存筛选。
2. Environment、status、severity 或 q 变化时重置 offset；总数继续读取 `X-Total-Count`。
3. 停用 Principal 收到 `PRINCIPAL_SELF_DEACTIVATION_FORBIDDEN` 或 `LAST_UNRESTRICTED_ADMIN` 时展示
   明确阻止原因并刷新 Principal 列表。
4. Demo cleanup 收到 `DEMO_DATA_DRIFT` 时进入人工检查流程，不自动重试初始化或清理。
