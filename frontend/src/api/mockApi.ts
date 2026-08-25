import type { ActionExecution, DashboardSummary, Incident, IncidentDetail } from '../domain/types'

const incidents: Incident[] = [
  { id: 'INC-0042', title: 'Qdrant 服务停止导致 RAG 检索失败', status: 'INVESTIGATING', severity: 'critical', resource: 'qdrant-prod-01', resourceId: 'res-qdrant-prod-01', environment: '生产', owner: '张运维', observabilityStatus: 'observable', observabilityRunnerId: null, observabilityLostAt: null, version: 4, createdAt: '2026-08-07T14:32:08+08:00', updatedAt: '2026-08-07T14:48:22+08:00', hypothesis: { id: 'H1', ordinal: 1, summary: 'segments 加载超时', confidence: 85, status: 'supported' } },
  { id: 'INC-0041', title: 'Embedding 服务超时导致文档入库失败', status: 'OBSERVABILITY_LOST', severity: 'high', resource: 'embedding-svc-01', resourceId: 'res-embedding-svc-01', environment: '生产', owner: '王SRE', observabilityStatus: 'lost', observabilityRunnerId: 'runner-prod-02', observabilityLostAt: '2026-08-07T15:16:20+08:00', version: 3, createdAt: '2026-08-07T15:08:00+08:00', updatedAt: '2026-08-07T15:16:20+08:00', hypothesis: { id: 'H1', ordinal: 1, summary: '连接池耗尽', confidence: 71, status: 'proposed' } },
  { id: 'INC-0040', title: 'SQLite WAL 文件持续增长影响写入', status: 'WAITING_APPROVAL', severity: 'medium', resource: 'rag-db-01', resourceId: 'res-rag-db-01', environment: '测试', owner: '李后端', observabilityStatus: 'observable', observabilityRunnerId: null, observabilityLostAt: null, version: 5, createdAt: '2026-08-07T13:15:00+08:00', updatedAt: '2026-08-07T14:02:10+08:00' },
  { id: 'INC-0038', title: 'FastAPI 问答接口持续返回 500', status: 'RESOLVED', severity: 'critical', resource: 'rag-api-01', resourceId: 'res-rag-api-01', environment: '生产', owner: '张运维', observabilityStatus: 'observable', observabilityRunnerId: null, observabilityLostAt: null, version: 8, createdAt: '2026-08-07T08:22:00+08:00', updatedAt: '2026-08-07T09:04:52+08:00' },
]

const incidentDetail: IncidentDetail = {
  ...incidents[0],
  traceId: '4f2a8c1e-6fd9-4f9b-982b-b1438e8bb207',
  eventCursor: 0,
  timelineTotal: 5,
  timelineTruncated: false,
  autonomyLevel: 'L1',
  planVersion: 2,
  replanCount: 1,
  toolBudget: { used: 8, limit: 30 },
  steps: [
    { id: 'step-1', ordinal: 1, title: '检查 Qdrant 进程与容器健康状态', objective: '确认基础进程和容器状态', kind: 'observe', status: 'completed', risk: 'read_only', attempts: 1, evidenceIds: ['E1'], resultSummary: '进程在线', version: 2, createdAt: '2026-08-07T14:35:41+08:00', updatedAt: '2026-08-07T14:43:55+08:00' },
    { id: 'step-2', ordinal: 2, title: '分析 Qdrant 日志中的异常模式', objective: '识别查询超时相关错误', kind: 'analyze', status: 'completed', risk: 'read_only', attempts: 1, evidenceIds: ['E2'], resultSummary: '发现 segments loading timeout', version: 2, createdAt: '2026-08-07T14:35:41+08:00', updatedAt: '2026-08-07T14:45:10+08:00' },
    { id: 'step-3', ordinal: 3, title: '检查 Collection 状态与索引进度', objective: '确认索引停滞范围', kind: 'observe', status: 'running', risk: 'read_only', attempts: 1, evidenceIds: [], version: 2, createdAt: '2026-08-07T14:35:41+08:00', updatedAt: '2026-08-07T14:48:22+08:00' },
    { id: 'step-4', ordinal: 4, title: '验证 Embedding 服务依赖是否正常', objective: '排除上游依赖故障', kind: 'verify', status: 'pending', risk: 'read_only', attempts: 0, evidenceIds: [], version: 1, createdAt: '2026-08-07T14:35:41+08:00', updatedAt: '2026-08-07T14:35:41+08:00' },
  ],
  timeline: [
    { id: 'evt-1', type: 'decision', occurredAt: '14:48:22', title: 'Replan 触发 — 新证据与假设冲突', detail: 'E3 证明 Embedding 服务正常，H2 降至 30%，计划转向 Qdrant segments。' },
    { id: 'evt-2', type: 'tool', occurredAt: '14:45:10', title: 'qdrant.collection_status', detail: '3 collections active · query_latency_p95=8.2s · duration=1.8s' },
    { id: 'evt-3', type: 'tool', occurredAt: '14:40:12', title: 'docker.logs(qdrant)', detail: '发现 segments loading timeout，输出已脱敏并截断。' },
    { id: 'evt-4', type: 'plan', occurredAt: '14:35:41', title: '创建复杂调查计划', detail: '健康检查 → 日志分析 → 依赖检查 → 根因定位' },
    { id: 'evt-5', type: 'event', occurredAt: '14:32:08', title: 'Incident 创建', detail: '来自 Prometheus Alertmanager Webhook，已聚合 3 条相关告警。' },
  ],
}

const action: ActionExecution = {
  id: 'ACT-0087', incidentId: 'INC-0035', approvalId: 'APR-0035', title: '重启 Embedding 服务单一容器', resource: 'embedding-svc-02', status: 'VERIFYING', risk: 'high',
  stages: ['PROPOSED', 'AUTHORIZED', 'DISPATCHING', 'APPLIED', 'VERIFYING', 'SUCCEEDED'], fencingToken: 1842, resourceVersion: 37, leaseSeconds: 78,
  verification: { passed: 3, required: 5, criterion: 'P95 < 500ms 且 HTTP 200 连续 5 次' },
  conflicts: [
    { taskId: 'ACT-0087', action: '容器重启与恢复验证', accessMode: 'MUTATE', state: 'CURRENT', resource: 'embedding-svc-02', detail: '持有独占锁，验证完成前禁止其他写动作。' },
    { taskId: 'TASK-0112', action: '更新连接池配置', accessMode: 'MUTATE', state: 'WAITING_RESOURCE', resource: 'embedding-svc-02', detail: '审批暂不生效，资源版本变化后重新评估。' },
    { taskId: 'TASK-0110', action: '查询服务指标', accessMode: 'OBSERVE', state: 'SHARED', resource: 'embedding-svc-02', detail: '允许并发读取，结果标记变更进行中。' },
  ],
}

const wait = (milliseconds = 260) => new Promise((resolve) => window.setTimeout(resolve, milliseconds))

export const mockApi = {
  async dashboard(): Promise<DashboardSummary> { await wait(); return { activeTasks: 3, waitingHuman: 1, rootCauseRate: 84, meanInvestigationSeconds: 402, runnerOnline: 12, runnerTotal: 12, safety: { pendingApprovals: 1, activeResourceLocks: 2, unknownActions: 1, actionsRequiringAttention: 2, observabilityLostIncidents: 1 }, incidents: incidents.slice(0, 3) } },
  async incidents(): Promise<Incident[]> { await wait(); return incidents },
  async incident(id: string): Promise<IncidentDetail> { await wait(); if (id !== incidentDetail.id) throw new Error(`Incident ${id} 不存在`); return incidentDetail },
  async action(): Promise<ActionExecution> { await wait(); return action },
}
