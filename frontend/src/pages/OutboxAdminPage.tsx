import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { adminApi } from '../api/adminApi'
import { outboxDeadLettersQuery, outboxStatusQuery } from '../api/queries'
import { ErrorPanel, LoadingPanel } from '../components/LoadingPanel'
import { PaginationControls } from '../components/PaginationControls'

export function OutboxAdminPage() {
  const queryClient = useQueryClient()
  const [offset, setOffset] = useState(0)
  const status = useQuery(outboxStatusQuery)
  const deadLetters = useQuery({ ...outboxDeadLettersQuery({ limit: 100, offset }), placeholderData: keepPreviousData })
  const replay = useMutation({
    mutationFn: (eventId: string) => adminApi.replayDeadLetter(eventId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['outbox', 'status'] }),
        queryClient.invalidateQueries({ queryKey: ['outbox', 'dead-letters'] }),
      ])
    },
  })
  if (status.isPending || deadLetters.isPending) return <LoadingPanel label="加载 Outbox 状态" />
  if (status.error) return <ErrorPanel error={status.error} />
  if (deadLetters.error) return <ErrorPanel error={deadLetters.error} />

  return <>
    <section className="page-heading"><div><span className="eyebrow">EVENT DELIVERY</span><h1>Outbox 发布管理</h1><p>查看事件积压、最老待发布年龄与 Dead Letter；重放保持原 eventId，由 Publisher 异步执行。</p></div><button onClick={() => void Promise.all([status.refetch(), deadLetters.refetch()])}>刷新状态</button></section>
    <section className="metric-grid outbox-metrics"><article className="metric-card"><span>待发布</span><strong>{status.data.pendingCount}</strong><small>pending events</small></article><article className="metric-card"><span>Dead Letter</span><strong className={status.data.deadLetterCount ? 'warn-text' : 'success-text'}>{status.data.deadLetterCount}</strong><small>manual attention</small></article><article className="metric-card"><span>最老积压年龄</span><strong>{status.data.oldestPendingAgeSeconds === null ? '—' : `${status.data.oldestPendingAgeSeconds}s`}</strong><small>{status.data.oldestPendingAt ? new Date(status.data.oldestPendingAt).toLocaleString('zh-CN', { hour12: false }) : '当前无积压'}</small></article></section>
    <section className="panel"><div className="panel-heading"><div><h2>Dead Letter</h2><p>HTTP 非重试错误或达到最大尝试次数的事件</p></div><span className="panel-note">{deadLetters.data.totalCount} EVENTS</span></div><div className="table-wrap"><table><thead><tr><th>Event</th><th>类型</th><th>Incident / Aggregate</th><th>尝试</th><th>最后错误</th><th>进入时间</th><th>操作</th></tr></thead><tbody>{deadLetters.data.items.map((event) => <tr key={event.eventId}><td><span className="mono-link">{event.eventId}</span><span className="table-subline">sequence {event.sequence}</span></td><td>{event.eventType}</td><td><span>{event.incidentId}</span><span className="table-subline">{event.aggregateType} · {event.aggregateId}</span></td><td>{event.publishAttempts}</td><td>{event.lastStatusCode ? `HTTP ${event.lastStatusCode} · ` : ''}{event.lastError ?? '未提供'}</td><td className="mono-cell">{new Date(event.deadLetteredAt).toLocaleString('zh-CN', { hour12: false })}</td><td><button disabled={replay.isPending} onClick={() => replay.mutate(event.eventId)}>重放</button></td></tr>)}{deadLetters.data.items.length === 0 && <tr><td colSpan={7} className="empty-table">当前没有 Dead Letter</td></tr>}</tbody></table></div><PaginationControls page={deadLetters.data} disabled={deadLetters.isFetching} onOffsetChange={setOffset} />{replay.error && <p className="form-error" role="alert">{replay.error.message}</p>}</section>
  </>
}
