import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { dataApi } from '../api/dataApi'
import { actionProposalsQuery } from '../api/queries'
import type { ActionProposalStatus } from '../api/actionProposalApi'
import { ErrorPanel, LoadingPanel } from './LoadingPanel'
import { PaginationControls } from './PaginationControls'
import { useEffect } from 'react'

const statusLabels: Record<ActionProposalStatus, string> = {
  proposed: '待策略评估',
  denied: '策略拒绝',
  awaiting_approval: '等待审批',
  action_ready: 'Action 已生成',
  rejected: '审批拒绝',
  cancelled: '已取消',
}

const statusOptions: Array<{ value: '' | ActionProposalStatus; label: string }> = [
  { value: '', label: '全部状态' },
  ...Object.entries(statusLabels).map(([value, label]) => ({ value: value as ActionProposalStatus, label })),
]

function shortId(value: string) {
  return `${value.slice(0, 8)}…`
}

function formatDate(value: string) {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

export function ActionProposalPanel({ incidentId }: { incidentId: string }) {
  const [status, setStatus] = useState<'' | ActionProposalStatus>('')
  const [offset, setOffset] = useState(0)
  useEffect(() => setOffset(0), [incidentId])
  const httpEnabled = dataApi.mode === 'http'
  const proposals = useQuery({
    ...actionProposalsQuery({ incidentId, status: status || undefined, limit: 50, offset }),
    enabled: httpEnabled,
    placeholderData: keepPreviousData,
  })

  return <section className="panel action-proposal-panel">
    <div className="panel-heading">
      <div><h2>Action Proposal 授权链</h2><p>Agent 只能提出动作；Policy、Approval 与最终 Action 均以控制面结果为准</p></div>
      <label className="proposal-filter">状态
        <select value={status} onChange={(event) => { setStatus(event.target.value as '' | ActionProposalStatus); setOffset(0) }}>
          {statusOptions.map((option) => <option key={option.value || 'all'} value={option.value}>{option.label}</option>)}
        </select>
      </label>
    </div>
    {!httpEnabled ? <p className="inline-empty">Mock 模式不模拟 Action Proposal</p>
      : proposals.isPending ? <LoadingPanel label="加载 Action Proposal" />
      : proposals.error ? <ErrorPanel error={proposals.error} />
      : proposals.data.items.length === 0 ? <p className="inline-empty">当前 Incident 在此状态下没有 Action Proposal</p>
      : <div className="proposal-list">{proposals.data.items.map((proposal) => <article className="proposal-card" key={proposal.id}>
        <div className="proposal-card-head">
          <div><strong>{proposal.capability}</strong><span className="mono-cell">Proposal {shortId(proposal.id)} · v{proposal.version}</span></div>
          <span className={`proposal-status proposal-${proposal.status}`}>{statusLabels[proposal.status]}</span>
        </div>
        <dl className="proposal-chain">
          <div><dt>Run / 节点</dt><dd><span className="mono-cell">{shortId(proposal.runId)}</span><small>{proposal.nodeExecutionId}</small></dd></div>
          <div><dt>Policy 结论</dt><dd>{proposal.decisionReason ?? '尚无 Policy 原因'}<small>{proposal.policyDecisionId ? `Decision ${shortId(proposal.policyDecisionId)}` : '等待策略决策'}</small></dd></div>
          <div><dt>Approval ID</dt><dd className="mono-cell">{proposal.approvalId ? shortId(proposal.approvalId) : '—'}</dd></div>
          <div><dt>最终 Action ID</dt><dd>{proposal.actionRequestId ? <Link to="/actions">{shortId(proposal.actionRequestId)}</Link> : <span className="mono-cell">—</span>}</dd></div>
        </dl>
        <div className="proposal-meta"><span>风险 {proposal.risk}</span><span>资源 {shortId(proposal.resourceId)}</span><time>{formatDate(proposal.updatedAt)}</time></div>
      </article>)}</div>}
    {httpEnabled && proposals.data && <PaginationControls page={proposals.data} disabled={proposals.isFetching} onOffsetChange={setOffset} />}
  </section>
}
