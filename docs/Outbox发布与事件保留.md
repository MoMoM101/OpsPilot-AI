# Outbox 发布与事件保留

> 状态：发布、退避重试、Dead Letter、幂等和清理闭环已实现  
> 更新时间：2026-08-21

## 定位

`outbox_events` 同时承担两个明确职责：

1. 事务内事件 Outbox：业务状态和待发布事件在同一个数据库事务中提交；
2. 有界 SSE 重放存储：Incident SSE 按全局 `sequence` 和 `Last-Event-ID` 重放保留期内事件。

`incident_events` 仍是 Incident 时间线的长期业务记录。Outbox 不是无限期审计存储。

## 发布语义

后台 `outbox_publisher` 按 `sequence` 领取未发布事件。多实例 PostgreSQL 部署使用
`FOR UPDATE SKIP LOCKED` 避免两个 Publisher 同时处理同一批数据库记录。

- 每次尝试先增加 `publish_attempts`；
- Sink 成功后才写入 `published_at`；
- 单条失败不会阻塞同批其他事件；
- 临时失败按指数退避和随机抖动设置 `next_attempt_at`，到期后才会再次领取；
- HTTP 5xx、408、409、425、429、网络错误和超时作为临时失败；其他 HTTP 4xx 直接进入
  Dead Letter；
- 达到最大尝试次数的临时失败也进入 Dead Letter，不再自动重试；
- 发布语义是 at-least-once，`eventId` 在所有重试中保持不变；
- Webhook 请求使用 `Idempotency-Key: <eventId>`，接收方必须按该值去重。

进程可能在 Sink 已接收、数据库尚未写入 `published_at` 时退出，因此不能承诺 exactly-once。

## Sink 模式

```text
OPSPILOT_OUTBOX_PUBLISHER_MODE=log       # disabled | log | webhook
OPSPILOT_OUTBOX_PUBLISHER_INTERVAL_SECONDS=1
OPSPILOT_OUTBOX_PUBLISHER_BATCH_SIZE=100
OPSPILOT_OUTBOX_MAX_PUBLISH_ATTEMPTS=10
OPSPILOT_OUTBOX_RETRY_BASE_SECONDS=2
OPSPILOT_OUTBOX_RETRY_MAX_SECONDS=300
OPSPILOT_OUTBOX_RETENTION_DAYS=7
```

`log` 是默认模式，将完整结构化事件交给容器日志采集链路；`webhook` 将相同事件 JSON 发送至
配置地址：

```text
OPSPILOT_OUTBOX_WEBHOOK_URL=https://events.example.com/opspilot
OPSPILOT_OUTBOX_WEBHOOK_TOKEN_FILE=/run/secrets/outbox_webhook_token
OPSPILOT_OUTBOX_WEBHOOK_TIMEOUT_SECONDS=10
```

Webhook Token 通过文件 Secret 注入时优先于普通环境变量。若没有任何下游消费需求，可以显式
选择 `disabled`；此时事件仍可供 SSE 使用，但不会更新发布字段，也不会进行发布后清理。

## 保留与 SSE

Publisher 只删除 `published_at` 早于保留截止时间的事件，永远不清理尚未成功发布的事件。
默认保留 7 天。清理后，早于现存最小 sequence 的 SSE 游标无法完整重放历史，前端应重新读取
Incident 详情和时间线。`IncidentDetailResponse.eventCursor` 与该快照在同一事务事件链路内推进；
前端应用完整快照后，以该值作为 `Last-Event-ID` 建立新流，即可只接收快照之后的增量。历史数据库
由迁移 `20260821_0037` 按各 Incident 当前 Outbox 最大 sequence 回填游标。

Publisher 已纳入 `/api/v1/ready` 和认证的 `/api/v1/worker-health`。连续发布失败、后台 Task
退出或心跳过期会使服务进入 Not Ready，避免 API 看似正常而事件发布长期失效。

Admin 可通过以下接口查看积压、最老未发布事件年龄和 Dead Letter，并人工重放：

```text
GET  /api/v1/outbox/status
GET  /api/v1/outbox/dead-letters
POST /api/v1/outbox/dead-letters/{event_id}/replay
```

人工重放会清零尝试次数、错误和 Dead Letter 状态，并将 `next_attempt_at` 设置为当前时间；实际
发布仍由 Publisher 完成，保持相同 `eventId`。
