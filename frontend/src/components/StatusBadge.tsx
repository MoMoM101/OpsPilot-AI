import type { ActionStatus, IncidentStatus, Severity } from '../domain/types'

const incidentLabels: Record<IncidentStatus, string> = {
  DETECTED: '已检测', CORRELATING: '关联中', INVESTIGATING: '调查中', DIAGNOSED: '已诊断', PLANNING: '规划中', WAITING_APPROVAL: '待审批', REMEDIATING: '修复中', VERIFYING: '验证中', RESOLVED: '已恢复', CLOSED: '已关闭', OBSERVABILITY_LOST: '观测能力丢失', NEEDS_HUMAN: '需人工', MITIGATED_NOT_RESOLVED: '已缓解', FAILED: '失败', CANCELLED: '已取消',
}

export function IncidentStatusBadge({ status }: { status: IncidentStatus }) {
  return <span className={`badge status status-${status.toLowerCase()}`}>{incidentLabels[status]}</span>
}

export function ObservabilityBadge({ status }: { status: 'observable' | 'lost' }) {
  return <span className={`badge observability-${status}`}>{status === 'lost' ? '观测能力丢失' : '观测正常'}</span>
}

export function ActionStatusBadge({ status }: { status: ActionStatus }) {
  return <span className={`badge action-status action-${status.toLowerCase()}`}>{status}</span>
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  const labels: Record<Severity, string> = { critical: '严重', high: '高', medium: '中', low: '低' }
  return <span className={`badge severity severity-${severity}`}>{labels[severity]}</span>
}
