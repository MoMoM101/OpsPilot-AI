# OpsPilot Console

OpsPilot 正式前端工程，使用 React、TypeScript、Vite、TanStack Router 和 TanStack Query。

## 当前数据接入

- Dashboard：`GET /api/v1/dashboard`
- Incident 列表：`GET /api/v1/incidents`；状态、Environment ID 与关键词均由服务端筛选，筛选条件写入 URL，分页总数读取 `X-Total-Count`
- Incident 详情：`GET /api/v1/incidents/{incidentId}`
- Incident 实时事件：`GET /api/v1/incidents/{incidentId}/stream`
- 告警列表：`GET /api/v1/alerts`，支持 `status`、`resource_id`、`incident_id` 过滤
- Runner 管理：只读调用 `GET /api/v1/runners`；注册、心跳和 Runner Token 不进入浏览器
- 日志查询：根据在线 Runner capabilities 显示 File/Journal 表单，通过 `POST /api/v1/runner-tasks` 创建只读任务，并由 Incident SSE 刷新任务快照
- 健康探测：根据在线 Runner capabilities 显示 HTTP/TCP 探测；`succeeded` 只代表执行完成，健康结论依据 resultSummary 与 Evidence
- Incident Evidence：使用 `GET /api/v1/incidents/{id}/evidence` 加载列表、`GET /api/v1/evidence/{evidenceId}` 加载详情；展示截断、脱敏和 Evidence 健康数据
- Prometheus 查询：支持即时/范围 RunnerTask；Evidence 中 `outputTruncated`、`seriesTruncated` 或 `samplesTruncated` 为 true 时提示结果已裁剪
- 主机快照：创建无参数 `host.snapshot` RunnerTask；跨平台可选字段缺失时显示“未提供”而非失败
- Action：接入能力目录、Policy/Approval 授权、创建、派发、Execution、Verification、Compensation、Reconcile 与活动资源锁只读状态；资源锁获取和 Fencing Token 仅由服务端管理

## 运行模式边界

- HTTP 模式是默认和生产模式。浏览器通过同源 `/api/v1` 使用真实控制面 API、Session/CSRF 与 Incident SSE；所有权限、状态机、分页总数和幂等结果以后端为准。
- Mock 模式仅在显式设置 `VITE_ENABLE_MOCKS=true` 时启用，只替换 `dataApi` 中的 Dashboard、Incident 和演示 Action 数据，用于无后端的静态界面开发。它不模拟完整认证、审批、Runner、Policy、Fault Lab 或执行安全语义，不得用于验收或生产。
- Demo 模式不是 Mock。它仍运行在 HTTP 模式并调用 Admin `/demo/status`、`/demo/initialize`、`/demo/cleanup`，创建后端登记的隔离合成数据；生产环境可由后端强制禁用，drifted 状态只允许人工检查。

## 用户认证

- 页面启动时调用 `GET /api/v1/auth/me` 初始化当前用户、角色与 Environment 范围。
- 默认登录方式调用 `POST /api/v1/auth/session`，把管理员分配的用户 Access Token 交换为 HttpOnly Session Cookie；交换完成后不保留原 Token。
- Alpha Bearer 兼容模式只写入当前标签页的 `sessionStorage`，不得输入 Control Plane Bootstrap Token 或 Runner Token。
- HTTP 与 Incident SSE 统一注入认证信息；Runner 服务端点和公开端点不会收到用户 Bearer。
- 401 会清理本地凭据并返回登录页；403 会展示角色或 Environment 权限不足提示。
- Cookie Session 支持 `POST /api/v1/auth/session/refresh` 主动及定时轮换，并通过 `DELETE /api/v1/auth/session` 服务端登出。
- CSRF Token 由认证模块集中持有，优先使用登录/刷新响应中的 `csrfToken`；页面重载后的 Cookie 恢复使用可配置的 `VITE_CSRF_COOKIE_NAME`，请求代码不再硬编码 Cookie 名。
- Viewer 不显示写操作；Operator 使用后端授权的 Environment 范围；Admin 可见身份管理和审计入口。所有权限仍以后端校验为准。
- Admin 身份管理页支持 Principal 创建、停用和 Token 轮换；当前登录 Principal 不允许在普通管理表格中自轮换或自停用。新 Token 只在响应后一次性展示，不写入 LocalStorage、SessionStorage 或日志，确认保存前暂停自动 Session 刷新。
- Admin Outbox 页面展示积压、最老待发布年龄和 Dead Letter，并通过重放接口将事件重新交给 Publisher。
- Admin Policy 页面支持按 Environment 加载、创建和带 `expectedVersion` 的规则修改，并配置维护星期、UTC 起止分钟与单 Incident 次数限制。Dry Run 展示 `allowed`、`approvalRequired`、匹配规则、规则版本、剩余次数与 `reason`；前端不自行判定，也不调用会生成快照并占用额度的正式 `evaluate`。
- Approval 页面支持按 Incident 和状态过滤，展示申请人、决议人、评论、过期时间和当前状态；审批决议携带 `expectedVersion`，且只允许编辑后端 `editableParameterKeys` 声明的参数。
- Action 页面接入真实列表与创建接口，绑定 Policy 决策、验证标准和可持久复用的幂等键；审批场景只提交审批完成后的最终参数，并展示 `replayed`、状态和取消原因。
- Action 页面只读展示活动资源锁状态和到期时间，不展示 Fencing Token，也不提供 acquire/renew/release 调试操作。
- Action 详情接入 Execution 快照，展示执行状态、租约、结果和错误；派发不接收客户端 Fencing Token，由服务端在同一事务中获取资源锁、选择 Runner、创建 Execution 并将 Action 转为 `dispatching`；`unknown` 会冻结常规操作且只能 reconcile 为 `succeeded` 或 `failed`。
- Action 状态包含 `applied`、`verifying`、`verification_failed`；详情接入 Verification 快照，展示验证状态、RunnerTask、Evidence、错误与 `compensationRequired`。
- Action 状态包含 `compensating`、`compensated`、`escalated`；详情支持 Compensation 请求、批准/拒绝、服务端冻结锁校验派发、Execution 状态和人工升级，客户端不读取或提交锁 Token。

生产部署推荐 OIDC + BFF/HttpOnly Session Cookie。任何 Token 都不得写入 `VITE_*` 环境变量、源码或 Docker 构建参数。

## 开发

```bash
npm install
copy .env.example .env
npm run dev
```

开发服务默认使用 `http://127.0.0.1:5173`。浏览器始终请求同源 `/api/v1`，Vite 将 `/api` 代理到 `VITE_DEV_API_TARGET`（默认 `http://127.0.0.1:8000`），因此 Session 与 CSRF Cookie 不跨站。生产 Nginx 使用相同的 `/api` 代理模型。

## 验证

```bash
npm run build
npm run test
npm run openapi:check
```

Vitest 覆盖页面、权限、分页头、SSE、401 跳转、一次性 Token 和幂等交互；`npm run build` 会先执行 TypeScript 类型检查，再生成按 Admin、Fault Lab、日志、监控和 Incident 详情拆分的生产 chunks。

后端 OpenAPI 快照位于 `openapi.json`，TypeScript 类型生成到 `src/api/generated/schema.d.ts`。Incident 与 Dashboard 的传输类型直接引用生成结果；后端 schema 变化后运行 `npm run openapi:generate` 并审查差异，CI 会通过 `openapi:check` 阻止未提交的契约漂移。

类型检查不再写入 `tsbuildinfo`，Vite/Vitest 使用 runner config loader，避免依赖 `node_modules/.vite-temp`。项目缓存统一写入 `.cache/vite`。

## 接入边界

页面统一通过 `src/api` 获取服务端数据，不直连 Runner、Lab Controller、Prometheus 或其他目标系统。Incident 详情页会先重取完整快照，再以 `eventCursor` 建立 SSE；事件按 SSE `id` 去重，并根据事件类型刷新 Incident、Timeline、Dashboard、Plan、Action、RunnerTask 或资源锁缓存。当前仍没有全局事件订阅，非 Incident 页面使用查询失效或定时刷新维持快照。

原始静态设计已由项目维护者另行保存；当前 `frontend` 目录是正式 TypeScript 前端工程。
