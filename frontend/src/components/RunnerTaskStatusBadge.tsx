import type { RunnerTaskStatus } from '../domain/types'

const labels: Record<RunnerTaskStatus, string> = {
  queued: '排队中',
  leased: '执行中',
  succeeded: '执行成功',
  failed: '执行失败',
  cancelled: '已取消',
}

export function runnerTaskStatusLabel(status: RunnerTaskStatus, attempt: number) {
  return status === 'queued' && attempt > 0 ? '已重新排队' : labels[status]
}

export function RunnerTaskStatusBadge({ status, attempt }: { status: RunnerTaskStatus; attempt: number }) {
  const requeued = status === 'queued' && attempt > 0
  return <span className={`badge task-${status}${requeued ? ' task-requeued' : ''}`}>{runnerTaskStatusLabel(status, attempt)}</span>
}
