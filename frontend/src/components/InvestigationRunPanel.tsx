import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { keepPreviousData } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { dataApi } from '../api/dataApi'
import { investigationCheckpointsQuery, investigationHitlWaitsQuery, investigationRunsQuery } from '../api/queries'
import type { InvestigationRunStatus } from '../domain/types'
import { ErrorPanel, LoadingPanel } from './LoadingPanel'
import { PaginationControls } from './PaginationControls'

const RUN_PAGE_SIZE = 1
const HITL_WAIT_PAGE_SIZE = 10

const statusLabels: Record<InvestigationRunStatus, string> = {
  queued: '等待运行', running: '运行中', paused: '已暂停', completed: '已完成', failed: '运行失败', cancelled: '已取消',
}

export function investigationRunStatusLabel(status: InvestigationRunStatus) {
  return statusLabels[status]
}

export function investigationPauseReason(nextAction: string | null | undefined) {
  if (nextAction === 'no_progress') return '连续无进展'
  if (nextAction === 'max_iterations') return '达到最大迭代次数'
  return undefined
}

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
}

export function InvestigationRunPanel({ incidentId }: { incidentId: string }) {
  const httpEnabled = dataApi.mode === 'http'
  const [runOffset, setRunOffset] = useState(0)
  const [waitOffset, setWaitOffset] = useState(0)
  useEffect(() => setRunOffset(0), [incidentId])
  const runs = useQuery({ ...investigationRunsQuery(incidentId, { limit: RUN_PAGE_SIZE, offset: runOffset }), enabled: httpEnabled, placeholderData: keepPreviousData })
  const run = runs.data?.items[0]
  useEffect(() => setWaitOffset(0), [run?.id])
  const hitlWaits = useQuery({ ...investigationHitlWaitsQuery(run?.id ?? '', { limit: HITL_WAIT_PAGE_SIZE, offset: waitOffset }), enabled: httpEnabled && Boolean(run), placeholderData: keepPreviousData })
  const checkpoints = useQuery({ ...investigationCheckpointsQuery(run?.id ?? '', { limit: 200 }), enabled: httpEnabled && Boolean(run) })
  const latestCheckpoint = checkpoints.data?.length ? checkpoints.data[checkpoints.data.length - 1] : undefined
  const pauseReason = run?.status === 'paused' ? investigationPauseReason(latestCheckpoint?.nextAction) : undefined

  return <section className="panel investigation-panel">
    <div className="panel-heading"><div><h2>Agent 调查运行</h2><p>只读展示运行事实与恢复 Checkpoint；执行引擎接入前不提供启动或写入操作</p></div><span className="panel-note">READ ONLY</span></div>
    {!httpEnabled ? <p className="inline-empty">Mock 模式不模拟 InvestigationRun</p> : runs.isPending ? <LoadingPanel label="加载 Agent 调查运行" /> : runs.error ? <ErrorPanel error={runs.error} /> : !run ? <p className="inline-empty">当前 Incident 尚无 Agent 调查运行</p> : <>
      <div className="investigation-run-summary">
        <div><span>运行状态</span><strong className={`investigation-status investigation-${run.status}`}>{investigationRunStatusLabel(run.status)}</strong><small>{run.lastErrorCode ? `错误：${run.lastErrorCode}` : `record v${run.version}`}</small></div>
        <div><span>当前节点</span><strong>{run.currentNode ?? '尚未进入节点'}</strong><small>Graph {run.graphVersion}</small></div>
        <div><span>迭代进度</span><strong>{run.iterationCount} / {run.maxIterations}</strong><small>Checkpoint #{run.lastCheckpointSequence}</small></div>
        <div><span>模型请求预算</span><strong>{run.modelRequestsUsed} / {run.modelRequestLimit}</strong><small>剩余 {Math.max(0, run.modelRequestLimit - run.modelRequestsUsed)} 次</small></div>
        <div><span>模型 Token</span><strong>{run.modelInputTokensUsed.toLocaleString('zh-CN')} / {run.modelOutputTokensUsed.toLocaleString('zh-CN')}</strong><small>输入 / 输出</small></div>
        <div><span>运行时间</span><strong>{formatDate(run.startedAt)}</strong><small>{run.completedAt ? `结束 ${formatDate(run.completedAt)}` : `创建 ${formatDate(run.createdAt)}`}</small></div>
        <div><span>Thread ID</span><strong className="mono-cell">{run.threadId}</strong><small>Runtime 尝试 {run.runtimeAttempt} · Run {run.id}</small></div>
      </div>
      {runs.data && <PaginationControls page={runs.data} disabled={runs.isFetching} onOffsetChange={setRunOffset} />}
      {pauseReason && <div className="investigation-pause-reason" role="status"><strong>Agent 运行已自动暂停</strong><span>{pauseReason}</span><small>来源：最新 Checkpoint · {latestCheckpoint?.nextAction}</small></div>}
      <div className="checkpoint-heading"><strong>人工决议等待</strong><span>{hitlWaits.data?.totalCount ?? 0} 条记录</span></div>
      {hitlWaits.isPending ? <LoadingPanel label="加载 HITL Wait" /> : hitlWaits.error ? <ErrorPanel error={hitlWaits.error} /> : <><div className="checkpoint-timeline">{hitlWaits.data.items.length ? hitlWaits.data.items.map((wait) => <article key={wait.id} className="checkpoint-item"><div className="checkpoint-sequence">HITL</div><div className="checkpoint-content"><div><strong>{wait.subjectType} · {wait.status}</strong><span>{wait.subjectId}</span><time>{formatDate(wait.createdAt)}</time></div><p>{wait.outcome ?? '等待人工决议'}</p></div></article>) : <p className="inline-empty">本次运行没有 HITL Wait</p>}</div><PaginationControls page={hitlWaits.data} disabled={hitlWaits.isFetching} onOffsetChange={setWaitOffset} /></>}
      <div className="checkpoint-heading"><strong>Checkpoint 时间线</strong><span>{checkpoints.data?.length ?? run.lastCheckpointSequence} 条记录</span></div>
      {checkpoints.isPending ? <LoadingPanel label="加载 Checkpoint" /> : checkpoints.error ? <ErrorPanel error={checkpoints.error} /> : <div className="checkpoint-timeline">{checkpoints.data?.length ? checkpoints.data.map((checkpoint) => <article key={checkpoint.id} className="checkpoint-item"><div className="checkpoint-sequence">#{checkpoint.sequence}</div><div className="checkpoint-content"><div><strong>{checkpoint.node}</strong><span>迭代 {checkpoint.iteration} · {checkpoint.graphVersion}</span><time>{formatDate(checkpoint.createdAt)}</time></div><p>{checkpoint.outputSummary ?? '该 Checkpoint 未提供摘要'}</p><div className="checkpoint-refs"><span className={checkpoint.progressed ? 'checkpoint-progressed' : 'checkpoint-stalled'}>{checkpoint.progressed ? '有进展' : '无进展'}</span>{checkpoint.nextAction && <span>下一动作 {checkpoint.nextAction}</span>}<span>模型 {checkpoint.modelRequests} 次 · 输入 {checkpoint.modelInputTokens.toLocaleString('zh-CN')} · 输出 {checkpoint.modelOutputTokens.toLocaleString('zh-CN')}</span>{checkpoint.planStepId && <span>PlanStep {checkpoint.planStepId.slice(0, 8)}…</span>}<span>无进展计数 {checkpoint.noProgressCount}</span>{checkpoint.evidenceIds.length ? checkpoint.evidenceIds.map((evidenceId) => <Link key={evidenceId} to="/incidents/$incidentId/evidence/$evidenceId" params={{ incidentId, evidenceId }}>Evidence {evidenceId.slice(0, 8)}…</Link>) : <span>无关联 Evidence</span>}</div></div></article>) : <p className="inline-empty">本次运行尚无 Checkpoint</p>}</div>}
    </>}
  </section>
}
