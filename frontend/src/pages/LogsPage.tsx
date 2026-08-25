import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { availableLogOperations, type LogOperation } from '../api/runnerCapabilities'
import { incidentsQuery, runnersQuery, runnerTasksQuery } from '../api/queries'
import { runnerTaskApi, type RunnerTaskCreate } from '../api/runnerTaskApi'
import { ErrorPanel, LoadingPanel } from '../components/LoadingPanel'
import { useIncidentStreamTarget } from '../components/IncidentStreamContext'
import { RunnerTaskStatusBadge } from '../components/RunnerTaskStatusBadge'
import { RunnerTaskPlanStepField, useRunnerTaskPlanStep } from '../components/RunnerTaskPlanStepField'
import { PaginationControls } from '../components/PaginationControls'

function idempotencyKey(operation: LogOperation) {
  return `log-${operation}-${Date.now()}-${crypto.randomUUID()}`
}

export function LogsPage() {
  const queryClient = useQueryClient()
  const { setRequestedIncidentId } = useIncidentStreamTarget()
  const incidents = useQuery(incidentsQuery)
  const runners = useQuery({ ...runnersQuery({ status: 'online', limit: 100, offset: 0 }), placeholderData: keepPreviousData })
  const operations = useMemo(() => availableLogOperations(runners.data?.items ?? []), [runners.data])
  const [incidentId, setIncidentId] = useState('')
  const [taskOffset, setTaskOffset] = useState(0)
  const planBinding = useRunnerTaskPlanStep(incidentId)
  const [operation, setOperation] = useState<LogOperation>('file.tail')
  const [path, setPath] = useState('D:/logs/service.log')
  const [unit, setUnit] = useState('docker.service')
  const [lines, setLines] = useState(200)
  const [sinceMinutes, setSinceMinutes] = useState(30)
  const [priority, setPriority] = useState(4)
  const incident = incidents.data?.find((item) => item.id === incidentId)
  const tasks = useQuery({
    ...runnerTasksQuery(incidentId ? { incidentId, limit: 50, offset: taskOffset } : { limit: 50, offset: 0 }),
    enabled: Boolean(incidentId),
    placeholderData: keepPreviousData,
  })
  const createTask = useMutation({
    mutationFn: (body: RunnerTaskCreate) => runnerTaskApi.create(body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['runner-tasks'], exact: false, refetchType: 'all' })
    },
  })

  useEffect(() => {
    setRequestedIncidentId(incidentId || undefined)
    return () => setRequestedIncidentId(undefined)
  }, [incidentId, setRequestedIncidentId])

  useEffect(() => {
    if (!operations.length || operations.includes(operation)) return
    setOperation(operations[0])
  }, [operation, operations])

  if (incidents.error) return <ErrorPanel error={incidents.error} />
  if (runners.error) return <ErrorPanel error={runners.error} />
  if (incidents.isPending || runners.isPending) return <LoadingPanel label="加载 Runner 日志能力" />

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!incident || !operations.includes(operation) || !planBinding.canCreate) return
    const common = {
      incidentId: incident.id,
      planStepId: planBinding.planStepId || undefined,
      resourceId: incident.resourceId,
      idempotencyKey: idempotencyKey(operation),
    }
    const body: RunnerTaskCreate = operation === 'file.tail'
      ? { ...common, connector: 'file', operation, parameters: { path: path.trim(), lines } }
      : { ...common, connector: 'journal', operation, parameters: { unit: unit.trim(), lines, sinceMinutes, priority } }
    createTask.mutate(body)
  }

  return <>
    <section className="page-heading"><div><span className="eyebrow">BOUNDED LOG QUERY</span><h1>目标日志查询</h1><p>依据在线 Runner 声明的只读能力创建有界查询，结果由 Incident SSE 驱动刷新。</p></div></section>
    <section className="log-query-layout">
      <form className="panel log-query-form" onSubmit={submit}>
        <div className="panel-heading"><div><h2>创建查询</h2><p>任务由控制面调度，浏览器不持有 Runner 身份</p></div><span className="panel-note">READ ONLY</span></div>
        <div className="log-form-body">
          <label>关联 Incident<select required value={incidentId} onChange={(event) => { setIncidentId(event.target.value); setTaskOffset(0) }}><option value="">请选择 Incident</option>{incidents.data?.map((item) => <option value={item.id} key={item.id}>{item.title} · {item.resource}</option>)}</select></label>
          {incident && <div className="selected-resource"><span>目标资源</span><strong>{incident.resource}</strong><small>{incident.resourceId}</small></div>}
          {incident && <RunnerTaskPlanStepField binding={planBinding} />}
          <div className="operation-tabs" role="tablist" aria-label="日志查询类型">
            {operations.includes('file.tail') && <button type="button" role="tab" aria-selected={operation === 'file.tail'} className={operation === 'file.tail' ? 'operation-active' : ''} onClick={() => setOperation('file.tail')}>文件日志</button>}
            {operations.includes('journal.query') && <button type="button" role="tab" aria-selected={operation === 'journal.query'} className={operation === 'journal.query' ? 'operation-active' : ''} onClick={() => setOperation('journal.query')}>Journal</button>}
          </div>
          {!operations.length && <div className="capability-empty"><strong>没有可用日志能力</strong><p>在线 Runner 尚未声明 `file.tail` 或 `journal.query`。</p></div>}
          {operations.length > 0 && operation === 'file.tail' && <div className="log-parameter-grid"><label className="wide-field">日志路径<input required value={path} onChange={(event) => setPath(event.target.value)} placeholder="D:/logs/service.log" /></label><label>返回行数<input required type="number" min={1} max={2000} value={lines} onChange={(event) => setLines(event.target.valueAsNumber)} /></label></div>}
          {operations.length > 0 && operation === 'journal.query' && <div className="log-parameter-grid"><label className="wide-field">Systemd Unit<input required value={unit} onChange={(event) => setUnit(event.target.value)} placeholder="docker.service" /></label><label>返回行数<input required type="number" min={1} max={2000} value={lines} onChange={(event) => setLines(event.target.valueAsNumber)} /></label><label>时间范围（分钟）<input required type="number" min={1} max={1440} value={sinceMinutes} onChange={(event) => setSinceMinutes(event.target.valueAsNumber)} /></label><label>最高 Priority<input required type="number" min={0} max={7} value={priority} onChange={(event) => setPriority(event.target.valueAsNumber)} /></label></div>}
        </div>
        <div className="panel-actions"><button className="primary-button" type="submit" disabled={!incident || !operations.includes(operation) || !planBinding.canCreate || createTask.isPending}>{createTask.isPending ? '正在创建…' : '创建 Runner Task'}</button></div>
        {createTask.error && <p className="form-error" role="alert">{createTask.error.message}</p>}
      </form>
      <aside className="panel capability-panel"><div className="panel-heading"><h2>在线能力</h2><span className="panel-note">{runners.data?.totalCount ?? 0} RUNNERS</span></div><div className="capability-summary"><div className={operations.includes('file.tail') ? 'capability-ready' : 'capability-missing'}><strong>file.tail</strong><span>{operations.includes('file.tail') ? '可调度' : '不可用'}</span></div><div className={operations.includes('journal.query') ? 'capability-ready' : 'capability-missing'}><strong>journal.query</strong><span>{operations.includes('journal.query') ? '可调度' : '不可用'}</span></div></div><p className="capability-help">选项只根据状态为 online 的 Runner `capabilities.observe` 动态显示。</p></aside>
    </section>
    <section className="panel task-results"><div className="panel-heading"><div><h2>查询任务</h2><p>{incident ? `Incident ${incident.id}` : '选择 Incident 后查看任务快照'}</p></div>{incidentId && <button onClick={() => void tasks.refetch()} disabled={tasks.isFetching}>{tasks.isFetching ? '刷新中…' : '刷新快照'}</button>}</div>
      {tasks.error ? <ErrorPanel error={tasks.error} /> : <div className="table-wrap"><table><thead><tr><th>任务</th><th>查询类型</th><th>状态</th><th>尝试</th><th>结果摘要</th><th>Evidence</th><th>更新时间</th></tr></thead><tbody>{incidentId && tasks.data?.items.length ? tasks.data.items.map((task) => <tr key={task.id}><td><span className="mono-link">{task.id}</span><span className="table-subline">{task.runnerId ? `Runner ${task.runnerId}` : '等待调度'}</span></td><td className="mono-cell">{task.operation}</td><td><RunnerTaskStatusBadge status={task.status} attempt={task.attempt} /></td><td className="mono-cell">{task.attempt} / {task.maxAttempts}</td><td><span>{task.resultSummary ?? (task.errorCode ? `错误：${task.errorCode}` : '—')}</span>{task.outputTruncated && <span className="truncated-mark">内容已截断</span>}</td><td>{task.evidenceId ? <Link to="/incidents/$incidentId/evidence/$evidenceId" params={{ incidentId: task.incidentId, evidenceId: task.evidenceId }} className="mono-link">{task.evidenceId}</Link> : <span className="mono-cell">—</span>}</td><td className="mono-cell">{new Date(task.updatedAt).toLocaleString('zh-CN', { hour12: false })}</td></tr>) : <tr><td colSpan={7} className="empty-table">{incidentId ? '当前 Incident 还没有日志查询任务' : '请先选择 Incident'}</td></tr>}</tbody></table></div>}
    </section>
    {incidentId && tasks.data && <PaginationControls page={tasks.data} disabled={tasks.isFetching} onOffsetChange={setTaskOffset} />}
    <p className="log-boundary-note">日志输出由 Runner 提交至后端 Evidence，并执行服务端脱敏和大小限制。前端只展示任务摘要，不直接接收原始 Runner Token 或执行凭证。 <Link to="/runners">查看 Runner 能力 →</Link></p>
  </>
}
