import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { evidenceCropFlags, evidenceResultIsCropped } from '../api/evidenceAssessment'
import { availablePrometheusOperations, type PrometheusOperation } from '../api/runnerCapabilities'
import { evidenceDetailQuery, incidentsQuery, runnersQuery, runnerTasksQuery } from '../api/queries'
import { runnerTaskApi, type RunnerTaskCreate } from '../api/runnerTaskApi'
import { useIncidentStreamTarget } from '../components/IncidentStreamContext'
import { ErrorPanel, LoadingPanel } from '../components/LoadingPanel'
import { RunnerTaskStatusBadge } from '../components/RunnerTaskStatusBadge'
import { RunnerTaskPlanStepField, useRunnerTaskPlanStep } from '../components/RunnerTaskPlanStepField'
import { PaginationControls } from '../components/PaginationControls'

function localDateTime(date: Date) {
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 19)
}

function validateBaseUrl(value: string): string | undefined {
  try {
    const url = new URL(value)
    if (!['http:', 'https:'].includes(url.protocol)) return '只允许 HTTP 或 HTTPS 地址'
    if (url.username || url.password || url.search || url.hash) return 'Prometheus 地址不能包含凭据、查询参数或 fragment'
    return undefined
  } catch {
    return '请输入有效的 Prometheus URL'
  }
}

function EvidenceResult({ incidentId, evidenceId, taskTruncated }: { incidentId: string; evidenceId: string; taskTruncated: boolean }) {
  const detail = useQuery(evidenceDetailQuery(evidenceId))
  const flags = detail.data ? evidenceCropFlags(detail.data) : undefined
  const cropped = taskTruncated || (detail.data ? evidenceResultIsCropped(detail.data) : false)
  return <div className="prom-evidence"><Link to="/incidents/$incidentId/evidence/$evidenceId" params={{ incidentId, evidenceId }} className="mono-link">查看 Evidence</Link>{cropped && <strong>结果已裁剪</strong>}{flags && cropped && <small>{[flags.outputTruncated && '输出', flags.seriesTruncated && '序列', flags.samplesTruncated && '样本'].filter(Boolean).join(' / ')}</small>}{detail.isFetching && <small>正在同步详情…</small>}</div>
}

export function PrometheusPage() {
  const queryClient = useQueryClient()
  const { setRequestedIncidentId } = useIncidentStreamTarget()
  const incidents = useQuery(incidentsQuery)
  const runners = useQuery({ ...runnersQuery({ status: 'online', limit: 100, offset: 0 }), placeholderData: keepPreviousData })
  const operations = useMemo(() => availablePrometheusOperations(runners.data?.items ?? []), [runners.data])
  const [incidentId, setIncidentId] = useState('')
  const [taskOffset, setTaskOffset] = useState(0)
  const planBinding = useRunnerTaskPlanStep(incidentId)
  const [operation, setOperation] = useState<PrometheusOperation>('prometheus.query')
  const [baseUrl, setBaseUrl] = useState('http://prometheus.internal.example:9090')
  const [query, setQuery] = useState('up')
  const [end, setEnd] = useState(() => localDateTime(new Date()))
  const [start, setStart] = useState(() => localDateTime(new Date(Date.now() - 60 * 60_000)))
  const [stepSeconds, setStepSeconds] = useState(60)
  const [validationError, setValidationError] = useState<string>()
  const incident = incidents.data?.find((item) => item.id === incidentId)
  const tasks = useQuery({ ...runnerTasksQuery(incidentId ? { incidentId, limit: 50, offset: taskOffset } : { limit: 50, offset: 0 }), enabled: Boolean(incidentId), placeholderData: keepPreviousData })
  const prometheusTasks = (tasks.data?.items ?? []).filter((task) => task.operation === 'prometheus.query' || task.operation === 'prometheus.query_range')
  const createTask = useMutation({
    mutationFn: (body: RunnerTaskCreate) => runnerTaskApi.create(body),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['runner-tasks'], exact: false, refetchType: 'all' }),
  })

  useEffect(() => {
    setRequestedIncidentId(incidentId || undefined)
    return () => setRequestedIncidentId(undefined)
  }, [incidentId, setRequestedIncidentId])
  useEffect(() => setTaskOffset(0), [incidentId])
  useEffect(() => {
    if (!operations.length || operations.includes(operation)) return
    setOperation(operations[0])
  }, [operation, operations])

  if (incidents.error) return <ErrorPanel error={incidents.error} />
  if (runners.error) return <ErrorPanel error={runners.error} />
  if (incidents.isPending || runners.isPending) return <LoadingPanel label="加载 Prometheus Runner 能力" />

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setValidationError(undefined)
    if (!incident || !operations.includes(operation) || !planBinding.canCreate) return
    const urlError = validateBaseUrl(baseUrl.trim())
    if (urlError) return setValidationError(urlError)
    if (!query.trim() || query.trim().length > 2000) return setValidationError('PromQL 长度必须为 1–2000 个字符')
    const common = { incidentId: incident.id, planStepId: planBinding.planStepId || undefined, resourceId: incident.resourceId, idempotencyKey: `${operation.replace('.', '-')}-${Date.now()}-${crypto.randomUUID()}` }
    let body: RunnerTaskCreate
    if (operation === 'prometheus.query') {
      body = { ...common, connector: 'prometheus', operation, parameters: { baseUrl: baseUrl.trim(), query: query.trim() } }
    } else {
      const startDate = new Date(start)
      const endDate = new Date(end)
      const durationSeconds = (endDate.getTime() - startDate.getTime()) / 1000
      if (!Number.isFinite(durationSeconds) || durationSeconds <= 0 || durationSeconds > 21_600) return setValidationError('范围必须大于 0 且不超过 6 小时')
      if (durationSeconds / stepSeconds > 11_000) return setValidationError('当前范围与步长超过每序列 11000 个请求点')
      body = { ...common, connector: 'prometheus', operation, parameters: { baseUrl: baseUrl.trim(), query: query.trim(), start: startDate.toISOString(), end: endDate.toISOString(), stepSeconds } }
    }
    createTask.mutate(body)
  }

  return <>
    <section className="page-heading"><div><span className="eyebrow">PROMETHEUS OBSERVATION</span><h1>Prometheus 查询</h1><p>通过受控 Runner 执行即时或范围 PromQL，并将标准化结果保存为 Evidence。</p></div></section>
    <section className="log-query-layout">
      <form className="panel log-query-form" onSubmit={submit}><div className="panel-heading"><div><h2>创建指标查询</h2><p>最长范围 6 小时，响应序列与样本受限</p></div><span className="panel-note">READ ONLY</span></div><div className="log-form-body">
        <label>关联 Incident<select required value={incidentId} onChange={(event) => setIncidentId(event.target.value)}><option value="">请选择 Incident</option>{incidents.data?.map((item) => <option value={item.id} key={item.id}>{item.title} · {item.resource}</option>)}</select></label>
        {incident && <div className="selected-resource"><span>目标资源</span><strong>{incident.resource}</strong><small>{incident.resourceId}</small></div>}
        {incident && <RunnerTaskPlanStepField binding={planBinding} />}
        <div className="operation-tabs" role="tablist" aria-label="Prometheus 查询类型">{operations.includes('prometheus.query') && <button type="button" role="tab" aria-selected={operation === 'prometheus.query'} className={operation === 'prometheus.query' ? 'operation-active' : ''} onClick={() => setOperation('prometheus.query')}>即时查询</button>}{operations.includes('prometheus.query_range') && <button type="button" role="tab" aria-selected={operation === 'prometheus.query_range'} className={operation === 'prometheus.query_range' ? 'operation-active' : ''} onClick={() => setOperation('prometheus.query_range')}>范围查询</button>}</div>
        {!operations.length && <div className="capability-empty"><strong>没有可用 Prometheus 能力</strong><p>在线 Runner 尚未声明 Prometheus 查询 capability。</p></div>}
        {operations.length > 0 && <div className="prom-form"><label>Prometheus Base URL<input required type="url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} /></label><label>PromQL<textarea required maxLength={2000} value={query} onChange={(event) => setQuery(event.target.value)} spellCheck={false} /></label>{operation === 'prometheus.query_range' && <div className="prom-range-grid"><label>开始时间<input required type="datetime-local" step={1} value={start} onChange={(event) => setStart(event.target.value)} /></label><label>结束时间<input required type="datetime-local" step={1} value={end} onChange={(event) => setEnd(event.target.value)} /></label><label>步长（秒）<input required type="number" min={1} max={3600} value={stepSeconds} onChange={(event) => setStepSeconds(event.target.valueAsNumber)} /></label></div>}</div>}
      </div><div className="panel-actions"><button className="primary-button" type="submit" disabled={!incident || !operations.includes(operation) || !planBinding.canCreate || createTask.isPending}>{createTask.isPending ? '正在创建…' : '创建 Prometheus Task'}</button></div>{(validationError || createTask.error) && <p className="form-error" role="alert">{validationError ?? createTask.error?.message}</p>}</form>
      <aside className="panel capability-panel"><div className="panel-heading"><h2>在线能力</h2><span className="panel-note">{runners.data?.totalCount ?? 0} RUNNERS</span></div><div className="capability-summary"><div className={operations.includes('prometheus.query') ? 'capability-ready' : 'capability-missing'}><strong>prometheus.query</strong><span>{operations.includes('prometheus.query') ? '可调度' : '不可用'}</span></div><div className={operations.includes('prometheus.query_range') ? 'capability-ready' : 'capability-missing'}><strong>query_range</strong><span>{operations.includes('prometheus.query_range') ? '可调度' : '不可用'}</span></div></div><p className="capability-help">查询选项来自在线 Runner 的 `capabilities.observe`，前端不直连 Prometheus。</p></aside>
    </section>
    <section className="panel task-results"><div className="panel-heading"><div><h2>指标查询任务</h2><p>{incident ? `Incident ${incident.id}` : '选择 Incident 后查看任务快照'}</p></div>{incidentId && <button onClick={() => void tasks.refetch()} disabled={tasks.isFetching}>{tasks.isFetching ? '刷新中…' : '刷新快照'}</button>}</div>{tasks.error ? <ErrorPanel error={tasks.error} /> : <div className="table-wrap"><table><thead><tr><th>任务</th><th>查询类型</th><th>状态</th><th>结果摘要</th><th>Evidence / 裁剪</th><th>更新时间</th></tr></thead><tbody>{incidentId && prometheusTasks.length ? prometheusTasks.map((task) => <tr key={task.id}><td><span className="mono-link">{task.id}</span><span className="table-subline">{task.runnerId ? `Runner ${task.runnerId}` : '等待调度'}</span></td><td className="mono-cell">{task.operation}</td><td><RunnerTaskStatusBadge status={task.status} attempt={task.attempt} /></td><td>{task.resultSummary ?? (task.errorCode ? `错误：${task.errorCode}` : '等待结果')}</td><td>{task.evidenceId ? <EvidenceResult incidentId={task.incidentId} evidenceId={task.evidenceId} taskTruncated={task.outputTruncated} /> : task.outputTruncated ? <strong className="crop-warning">结果已裁剪</strong> : <span className="mono-cell">—</span>}</td><td className="mono-cell">{new Date(task.updatedAt).toLocaleString('zh-CN', { hour12: false })}</td></tr>) : <tr><td colSpan={6} className="empty-table">{incidentId ? '当前 Incident 还没有 Prometheus 查询任务' : '请先选择 Incident'}</td></tr>}</tbody></table></div>}</section>
    {incidentId && tasks.data && <PaginationControls page={tasks.data} disabled={tasks.isFetching} onOffsetChange={setTaskOffset} />}
    <p className="log-boundary-note">任务成功后通过 SSE 中的 evidenceId 获取 Evidence。任一输出、序列或样本裁剪标记为 true 时，页面显示“结果已裁剪”。 <Link to="/runners">查看 Runner 能力 →</Link></p>
  </>
}
