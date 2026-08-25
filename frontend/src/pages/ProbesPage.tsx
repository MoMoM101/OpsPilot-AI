import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { availableProbeOperations, type ProbeOperation } from '../api/runnerCapabilities'
import { incidentsQuery, runnersQuery, runnerTasksQuery } from '../api/queries'
import { runnerTaskApi, type RunnerTaskCreate } from '../api/runnerTaskApi'
import { useIncidentStreamTarget } from '../components/IncidentStreamContext'
import { ErrorPanel, LoadingPanel } from '../components/LoadingPanel'
import { RunnerTaskStatusBadge } from '../components/RunnerTaskStatusBadge'
import { RunnerTaskPlanStepField, useRunnerTaskPlanStep } from '../components/RunnerTaskPlanStepField'
import { PaginationControls } from '../components/PaginationControls'

function probeKey(operation: ProbeOperation) {
  return `${operation.replace('.', '-')}-${Date.now()}-${crypto.randomUUID()}`
}

function parseExpectedStatuses(value: string): number[] | undefined {
  const parts = value.split(',').map((item) => item.trim()).filter(Boolean)
  if (!parts.length || parts.length > 20) return undefined
  const statuses = parts.map(Number)
  if (statuses.some((status) => !Number.isInteger(status) || status < 100 || status > 599)) return undefined
  return [...new Set(statuses)]
}

function validateProbeUrl(value: string): string | undefined {
  try {
    const url = new URL(value)
    if (!['http:', 'https:'].includes(url.protocol)) return '只允许 HTTP 或 HTTPS 地址'
    if (url.username || url.password || url.search || url.hash) return 'URL 不能包含凭据、查询参数或 fragment'
    return undefined
  } catch {
    return '请输入有效的 HTTP/HTTPS URL'
  }
}

export function ProbesPage() {
  const queryClient = useQueryClient()
  const { setRequestedIncidentId } = useIncidentStreamTarget()
  const incidents = useQuery(incidentsQuery)
  const runners = useQuery({ ...runnersQuery({ status: 'online', limit: 100, offset: 0 }), placeholderData: keepPreviousData })
  const operations = useMemo(() => availableProbeOperations(runners.data?.items ?? []), [runners.data])
  const [incidentId, setIncidentId] = useState('')
  const [taskOffset, setTaskOffset] = useState(0)
  const planBinding = useRunnerTaskPlanStep(incidentId)
  const [operation, setOperation] = useState<ProbeOperation>('http.probe')
  const [url, setUrl] = useState('http://api.internal.example:8000/health')
  const [method, setMethod] = useState<'GET' | 'HEAD'>('GET')
  const [expectedStatuses, setExpectedStatuses] = useState('200, 204')
  const [captureBody, setCaptureBody] = useState(false)
  const [host, setHost] = useState('database.internal.example')
  const [port, setPort] = useState(5432)
  const [validationError, setValidationError] = useState<string>()
  const incident = incidents.data?.find((item) => item.id === incidentId)
  const tasks = useQuery({
    ...runnerTasksQuery(incidentId ? { incidentId, limit: 50, offset: taskOffset } : { limit: 50, offset: 0 }),
    enabled: Boolean(incidentId),
    placeholderData: keepPreviousData,
  })
  const probeTasks = (tasks.data?.items ?? []).filter((task) => task.operation === 'http.probe' || task.operation === 'tcp.probe')
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
  if (incidents.isPending || runners.isPending) return <LoadingPanel label="加载 Runner 探测能力" />

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setValidationError(undefined)
    if (!incident || !operations.includes(operation) || !planBinding.canCreate) return
    const common = { incidentId: incident.id, planStepId: planBinding.planStepId || undefined, resourceId: incident.resourceId, idempotencyKey: probeKey(operation) }
    let body: RunnerTaskCreate
    if (operation === 'http.probe') {
      const urlError = validateProbeUrl(url.trim())
      const statuses = parseExpectedStatuses(expectedStatuses)
      if (urlError) return setValidationError(urlError)
      if (!statuses) return setValidationError('期望状态码必须是 1–20 个 100–599 的整数')
      body = { ...common, connector: 'http', operation, parameters: { url: url.trim(), method, expectedStatuses: statuses, captureBody } }
    } else {
      if (!host.trim()) return setValidationError('TCP Host 不能为空')
      body = { ...common, connector: 'tcp', operation, parameters: { host: host.trim(), port } }
    }
    createTask.mutate(body)
  }

  return <>
    <section className="page-heading"><div><span className="eyebrow">ALLOWLISTED PROBES</span><h1>目标健康探测</h1><p>通过具备声明式能力的在线 Runner 执行 HTTP/TCP 探测，并将结果固化为 Evidence。</p></div></section>
    <section className="probe-semantics"><strong>状态语义</strong><p><code>succeeded</code> 仅表示 Runner 成功执行了探测，不代表目标健康。健康结论必须结合 resultSummary、期望条件和 Evidence 判断。</p></section>
    <section className="log-query-layout">
      <form className="panel log-query-form" onSubmit={submit}>
        <div className="panel-heading"><div><h2>创建探测</h2><p>由控制面按环境和 capability 自动调度 Runner</p></div><span className="panel-note">READ ONLY</span></div>
        <div className="log-form-body">
          <label>关联 Incident<select required value={incidentId} onChange={(event) => setIncidentId(event.target.value)}><option value="">请选择 Incident</option>{incidents.data?.map((item) => <option value={item.id} key={item.id}>{item.title} · {item.resource}</option>)}</select></label>
          {incident && <div className="selected-resource"><span>目标资源</span><strong>{incident.resource}</strong><small>{incident.resourceId}</small></div>}
          {incident && <RunnerTaskPlanStepField binding={planBinding} />}
          <div className="operation-tabs" role="tablist" aria-label="探测类型">
            {operations.includes('http.probe') && <button type="button" role="tab" aria-selected={operation === 'http.probe'} className={operation === 'http.probe' ? 'operation-active' : ''} onClick={() => setOperation('http.probe')}>HTTP Probe</button>}
            {operations.includes('tcp.probe') && <button type="button" role="tab" aria-selected={operation === 'tcp.probe'} className={operation === 'tcp.probe' ? 'operation-active' : ''} onClick={() => setOperation('tcp.probe')}>TCP Probe</button>}
          </div>
          {!operations.length && <div className="capability-empty"><strong>没有可用探测能力</strong><p>在线 Runner 尚未声明 `http.probe` 或 `tcp.probe`。</p></div>}
          {operations.length > 0 && operation === 'http.probe' && <div className="log-parameter-grid probe-grid"><label className="wide-field">目标 URL<input required type="url" value={url} onChange={(event) => setUrl(event.target.value)} /></label><label>方法<select value={method} onChange={(event) => setMethod(event.target.value as 'GET' | 'HEAD')}><option>GET</option><option>HEAD</option></select></label><label>期望状态码<input required value={expectedStatuses} onChange={(event) => setExpectedStatuses(event.target.value)} placeholder="200, 204" /></label><label className="checkbox-field"><input type="checkbox" checked={captureBody} onChange={(event) => setCaptureBody(event.target.checked)} /><span>捕获响应体</span></label></div>}
          {operations.length > 0 && operation === 'tcp.probe' && <div className="log-parameter-grid"><label className="wide-field">目标 Host<input required value={host} onChange={(event) => setHost(event.target.value)} /></label><label>端口<input required type="number" min={1} max={65535} value={port} onChange={(event) => setPort(event.target.valueAsNumber)} /></label></div>}
        </div>
        <div className="panel-actions"><button className="primary-button" type="submit" disabled={!incident || !operations.includes(operation) || !planBinding.canCreate || createTask.isPending}>{createTask.isPending ? '正在创建…' : '创建探测任务'}</button></div>
        {(validationError || createTask.error) && <p className="form-error" role="alert">{validationError ?? createTask.error?.message}</p>}
      </form>
      <aside className="panel capability-panel"><div className="panel-heading"><h2>在线能力</h2><span className="panel-note">{runners.data?.totalCount ?? 0} RUNNERS</span></div><div className="capability-summary"><div className={operations.includes('http.probe') ? 'capability-ready' : 'capability-missing'}><strong>http.probe</strong><span>{operations.includes('http.probe') ? '可调度' : '不可用'}</span></div><div className={operations.includes('tcp.probe') ? 'capability-ready' : 'capability-missing'}><strong>tcp.probe</strong><span>{operations.includes('tcp.probe') ? '可调度' : '不可用'}</span></div></div><p className="capability-help">只显示在线 Runner 在 `capabilities.observe` 中明确声明的探测操作。</p></aside>
    </section>
    <section className="panel task-results"><div className="panel-heading"><div><h2>探测任务</h2><p>{incident ? `Incident ${incident.id}` : '选择 Incident 后查看任务快照'}</p></div>{incidentId && <button onClick={() => void tasks.refetch()} disabled={tasks.isFetching}>{tasks.isFetching ? '刷新中…' : '刷新快照'}</button>}</div>
      {tasks.error ? <ErrorPanel error={tasks.error} /> : <div className="table-wrap"><table><thead><tr><th>任务</th><th>探测</th><th>执行状态</th><th>健康判断依据</th><th>Evidence</th><th>更新时间</th></tr></thead><tbody>{incidentId && probeTasks.length ? probeTasks.map((task) => <tr key={task.id}><td><span className="mono-link">{task.id}</span><span className="table-subline">{task.runnerId ? `Runner ${task.runnerId}` : '等待调度'}</span></td><td className="mono-cell">{task.operation}</td><td><RunnerTaskStatusBadge status={task.status} attempt={task.attempt} />{task.status === 'succeeded' && <span className="execution-only">≠ 健康</span>}</td><td><span>{task.resultSummary ?? (task.errorCode ? `执行错误：${task.errorCode}` : '等待 Evidence')}</span></td><td>{task.evidenceId ? <Link to="/incidents/$incidentId/evidence/$evidenceId" params={{ incidentId: task.incidentId, evidenceId: task.evidenceId }} className="mono-link">{task.evidenceId}</Link> : <span className="mono-cell">—</span>}</td><td className="mono-cell">{new Date(task.updatedAt).toLocaleString('zh-CN', { hour12: false })}</td></tr>) : <tr><td colSpan={6} className="empty-table">{incidentId ? '当前 Incident 还没有探测任务' : '请先选择 Incident'}</td></tr>}</tbody></table></div>}
    </section>
    {incidentId && tasks.data && <PaginationControls page={tasks.data} disabled={tasks.isFetching} onOffsetChange={setTaskOffset} />}
    <p className="log-boundary-note">收到 `runner_task.succeeded` SSE 后会刷新对应 RunnerTask 快照。健康判断保留在 Evidence 与调查流程中。 <Link to="/runners">查看 Runner 能力 →</Link></p>
  </>
}
