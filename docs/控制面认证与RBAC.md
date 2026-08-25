# 控制面认证与 RBAC

> 状态：已实现 Principal、浏览器 Session、RBAC 和原子写操作审计  
> 更新时间：2026-08-20

## 1. 安全默认

控制面认证默认开启。用户面、Runner 面和 Runtime 内部面采用不同路径与身份边界：

| API 面 | 前缀 | 身份 |
|---|---|---|
| 用户控制面 | `/api/v1` | Admin、Operator、Viewer |
| Runner 服务面 | `/runner/v1` | Runner Bootstrap Token 或 Runner Access Token |
| Runtime 内部面 | `/internal/v1` | `service/runtime` Principal |

除健康检查、Readiness、Alertmanager Webhook 和具备独立令牌校验的 Runner 服务接口外，请求必须携带：

```text
Authorization: Bearer <control-plane-token>
```

缺少或无效令牌分别返回 `AUTHENTICATION_REQUIRED` 和 `INVALID_ACCESS_TOKEN`。认证通过但权限不足
返回 `PERMISSION_DENIED`。生产环境开启认证时必须配置
`OPSPILOT_CONTROL_PLANE_BOOTSTRAP_TOKEN`，否则应用拒绝启动。

## 2. Principal 与角色

| 角色 | 能力 |
| --- | --- |
| `admin` | 管理 Principal、Environment，并执行普通控制面读写 |
| `operator` | 在授权 Environment 内读取和执行调查控制面写操作 |
| `viewer` | 在授权 Environment 内只读 |
| `runtime` | 仅供 Agent Runtime 服务写 Checkpoint 和推进 Run 状态 |

`runtime` 必须是 `service` 类型，不能读取普通控制台接口。普通用户角色和 Admin 都不能调用内部
Checkpoint/Runtime transition，避免伪造模型用量或 Agent 执行事实。

Runtime Principal 示例：

```json
{
  "name": "agent-runtime",
  "kind": "service",
  "role": "runtime",
  "environmentIds": ["环境UUID"],
  "unrestrictedEnvironments": false
}
```

其一次性 `accessToken` 只允许调用 `/internal/v1/investigation-runs/{run_id}/transitions` 和
`/internal/v1/investigation-runs/{run_id}/checkpoints`。旧的 `/api/v1` 内部 POST 路径已经移除，
不会保留兼容后门。内部路由和 Runner 服务路由不进入用户 OpenAPI。

控制台可通过 `GET /api/v1/auth/me` 读取当前身份、角色和 Environment 范围。Operator 需要终止
Agent Run 时使用单用途 `POST /api/v1/investigation-runs/{run_id}/cancel`；通用 transition API 不向
用户身份开放。

## 3. 初始配置

Bootstrap Token 只用于首次创建持久 Principal：

部署或前端初始化向导可以先调用公开的 `GET /api/v1/setup/status`。该接口不返回 Token、模型地址、
Principal 名称或 Environment 数据，只返回是否需要初始化、是否已创建首个 Admin，以及 Bootstrap
凭据是否已配置且仍可消费。

```http
POST /api/v1/principals
Authorization: Bearer <bootstrap-token>
Content-Type: application/json

{
  "name": "platform-admin",
  "kind": "user",
  "role": "admin",
  "unrestrictedEnvironments": true
}
```

响应中的 `accessToken` 只返回一次，数据库只保存 SHA-256 摘要。Bootstrap Token 只能创建首个
`user/admin` 且必须拥有全局 Environment 权限。后端使用 `control_plane_setup` 单例行和行锁在创建
事务内消费 Bootstrap 权限，防止并发请求创建多个首始 Admin；历史已有 Admin 的数据库在迁移时
自动标记为已消费。完成后即使首个 Admin 后续被停用，也不会重新开放 Bootstrap Token。
`DELETE /api/v1/principals/{id}` 会立即停用令牌并吊销该 Principal 的全部浏览器 Session。

Principal Token 默认有效 30 天，可通过 `OPSPILOT_PRINCIPAL_TOKEN_TTL_SECONDS` 调整。Admin 使用
`POST /api/v1/principals/{id}/rotate-token` 轮换 Token；轮换会使旧 Token 和现有浏览器 Session
立即失效。静态 Bearer Token 不应写入前端源码、LocalStorage、日志或 URL。

## 4. Alpha 浏览器 Session 协议

Alpha 阶段暂不强制部署外部 OIDC Provider。浏览器只在首次登录时把一次性获得的 Principal
Token 发送到 `POST /api/v1/auth/session`。后端随后设置：

- `opspilot_session`：HttpOnly、SameSite=Lax，生产环境强制 Secure；
- `opspilot_csrf`：SameSite=Lax、生产环境 Secure，供前端读取并复制到 `X-CSRF-Token`；
- 所有 Cookie 认证的 POST、PUT、PATCH、DELETE 都执行双提交 CSRF 校验。

Session 默认闲置有效期 8 小时、绝对有效期 7 天。`POST /api/v1/auth/session/refresh` 同时轮换
Session Token 和 CSRF Token；`DELETE /api/v1/auth/session` 服务端吊销 Session 并删除 Cookie。
Principal 被停用或 Token 被管理员轮换时，其全部 Session 立即失效。

Alpha Token 获取流程是：部署者使用 Bootstrap Token 创建首个 Admin；Admin 再为用户创建
Principal，并通过安全的线下 Secret 渠道交付一次性显示的 Token；用户浏览器用它换取 Session。
该流程不具备企业 SSO、MFA 和 IdP 生命周期联动能力，是明确的 Alpha 限制。正式多用户生产部署
应接入 OIDC Authorization Code + PKCE；当前 Session、CSRF 和 RBAC 层可以继续复用。

## 5. Environment 数据范围

受限 Principal 使用 `environmentIds` 声明范围。Environment、Resource、Incident、Plan、
Hypothesis、Evidence、Alert、Runner、RunnerTask、InvestigationRun 和 SSE 查询在 Repository 层
应用范围过滤。跨范围详情和写入按资源不存在处理，避免泄露对象是否存在。

Dashboard 的 Incident、Approval、Action、Resource Lock 和 Runner 聚合均在 Repository 层应用
Environment Scope。受限 Principal 可以读取自己的 Dashboard；未绑定 Environment 的全局 Runner
仅以聚合数量计入，不通过 Dashboard 暴露身份或配置。

## 6. Actor 审计

认证请求的 Actor 来自服务端认证上下文，不信任请求体中的 `actorId`：

- Incident 领域事件写入 `actorType` 和 `actorId`；
- 所有成功的控制面写请求写入 `control_plane_audit_log`；
- 审计记录包含角色、HTTP 方法、路径、状态码、Request ID、Trace ID 和时间；
- Admin 可通过 `GET /api/v1/audit-logs` 分页读取。

HTTP 请求内的业务 Service、领域事件、Outbox 和控制面审计共享同一个 AsyncSession 与数据库
事务。Service 在请求中只 flush；中间件在成功响应后先写审计，再统一 commit。业务或审计任一
写入失败都会整体 rollback，因此不会出现“业务已经成功但客户端因第二个审计事务失败收到 500”。
Actor 仍只来自服务端 Principal Context，不接受请求体伪造。

审计日志不保存请求体和令牌，避免把 Secret 或运维数据复制进审计表。

Session 认证使用专门的审计动作：`auth.session.create`、`auth.session.refresh` 和
`auth.session.logout`。登录成功记录服务端认证出的 Principal；登录失败记录 `anonymous`、错误码、
直接连接来源 IP 和 User-Agent 的 SHA-256，不记录 Bearer Token、Cookie、CSRF Token 或请求体。
每一次连续失败都会持久化，安全日志同时输出同一来源最近 15 分钟的失败次数，便于告警规则检测
暴力尝试。失败审计可以在 401 响应时单独提交，但不会提交任何业务变更。

## 7. 生产传输安全

`production` 环境采用以下不可忽略的代码默认值：

- API 文档、OpenAPI、Swagger 和 ReDoc 默认关闭；显式尝试开启会导致配置校验失败；
- 除 `/api/v1/health` 和 `/api/v1/ready` 外，HTTP 请求返回 `426 HTTPS_REQUIRED`；
- 只有明确配置 `OPSPILOT_TRUST_FORWARDED_PROTO=true` 时才信任反向代理的
  `X-Forwarded-Proto`，并且代理必须覆盖客户端传入的同名 Header；
- TLS 应由受信负载均衡器或入口代理终止，后端端口不得直接暴露到公网。

根目录 Compose 是本地单机模板，为允许 `http://localhost` 联调显式设置了
`OPSPILOT_REQUIRE_HTTPS=false`。该例外不是生产推荐值；部署到共享网络或公网时必须删除覆盖并
配置 HTTPS 入口。
