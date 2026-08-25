# 后台 Worker 健康检查

> 状态：已实现  
> 更新时间：2026-08-11

## 覆盖范围

控制面当前跟踪两个进程内 Worker：

- `observability_monitor`：检查 Runner Lease，并处理失联后的任务与 Incident 状态；
- `agent_runtime`：领取和执行 InvestigationRun，仅在显式启用 Agent Runtime 时参与检查。
- `outbox_publisher`：发布持久事件并清理超过保留期的已发布事件。

每个 Worker 都记录：启动时间、最后心跳、最近成功时间、最近错误时间、连续错误数、累计错误数、
最后错误类型以及后台 Task 是否仍在运行。慢数据库请求和模型调用执行期间也会定期刷新心跳。

## Readiness 行为

`GET /api/v1/ready` 保留原有响应格式，并为每个已启用 Worker 增加布尔检查：

```json
{
  "status": "ready",
  "checks": {
    "database": true,
    "worker:observability_monitor": true,
    "worker:agent_runtime": true
  }
}
```

出现以下任一情况时，对应检查为 `false`，整体返回 HTTP 503：

- 连续错误达到配置阈值；
- 心跳超过允许时间未更新；
- Worker 后台 Task 未启动或已经意外退出。

禁用的可选 Worker 不影响 readiness。一次后续成功迭代会清零连续错误并恢复 Ready。

## 详细状态

经过认证的 Admin、Operator 或 Viewer 可以请求：

```text
GET /api/v1/worker-health
```

该运维接口返回每个 Worker 的详细时间和错误计数。它不属于前端用户契约，故意不进入用户
OpenAPI；`/health` 和 `/ready` 仍是公开的容器探针接口，而详细状态需要 Bearer Token。

## 配置

```text
OPSPILOT_WORKER_HEALTH_STALE_MULTIPLIER=3
OPSPILOT_WORKER_HEALTH_ERROR_THRESHOLD=3
```

心跳超时时间取 `max(5 秒, Worker 间隔 × STALE_MULTIPLIER)`。生产部署如果将 Agent Runtime
拆分成独立进程，应把同样的状态写入共享指标存储，并让 API readiness 检查独立 Worker 实例，
不能继续依赖单进程内存状态。
