import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { evidenceCropFlags } from '../api/evidenceAssessment'
import { formatBytes, formatDuration, parseHostSnapshot } from '../api/hostSnapshot'
import { hostSnapshotAvailable } from '../api/runnerCapabilities'
import { evidenceDetailQuery, incidentsQuery, runnersQuery, runnerTasksQuery } from '../api/queries'
import { runnerTaskApi, type RunnerTaskCreate } from '../api/runnerTaskApi'
import { useIncidentStreamTarget } from '../components/IncidentStreamContext'
import { ErrorPanel, LoadingPanel } from '../components/LoadingPanel'
import { RunnerTaskStatusBadge } from '../components/RunnerTaskStatusBadge'
import { RunnerTaskPlanStepField, useRunnerTaskPlanStep } from '../components/RunnerTaskPlanStepField'
import { PaginationControls } from '../components/PaginationControls'

function HostEvidence({ incidentId, evidenceId }: { incidentId: string; evidenceId: string }) {
  const detail = useQuery(evidenceDetailQuery(evidenceId))
  if (detail.isPending) return <LoadingPanel label="加载 Host Evidence" />
  if (detail.error) return <ErrorPanel error={detail.error} />
  const evidence = detail.data
  const snapshot = parseHostSnapshot(evidence)
  const crop = evidenceCropFlags(evidence)
  if (!snapshot) return <div className="host-snapshot-empty">Evidence 未包含可解析的 Host Snapshot。 <Link to="/incidents/$incidentId/evidence/$evidenceId" params={{ incidentId, evidenceId }}>查看原始 Evidence</Link></div>
  const network = Array.isArray(snapshot.network) ? snapshot.network : undefined
  return <div className="host-snapshot-card">
    <div className="host-snapshot-heading"><div><strong>{snapshot.platform?.hostname ?? '未提供主机名'}</strong><span>{snapshot.platform?.system ?? '未知平台'} {snapshot.platform?.release ?? ''} · {snapshot.platform?.machine ?? '未知架构'}</span></div><Link to="/incidents/$incidentId/evidence/$evidenceId" params={{ incidentId, evidenceId }} className="mono-link">Evidence →</Link></div>
    <div className="host-stat-grid"><div><span>CPU 逻辑核心</span><strong>{snapshot.cpu?.logicalCount ?? '未提供'}</strong><small>{snapshot.cpu?.loadAverage?.length ? `Load ${snapshot.cpu.loadAverage.join(' / ')}` : 'Load 未提供'}</small></div><div><span>内存</span><strong>{snapshot.memory?.usedPercent !== undefined ? `${snapshot.memory.usedPercent}%` : '未提供'}</strong><small>{snapshot.memory ? `${formatBytes(snapshot.memory.usedBytes)} / ${formatBytes(snapshot.memory.totalBytes)}` : '当前平台未提供'}</small></div><div><span>根磁盘</span><strong>{snapshot.disk?.usedPercent !== undefined ? `${snapshot.disk.usedPercent}%` : '未提供'}</strong><small>{snapshot.disk ? `${formatBytes(snapshot.disk.usedBytes)} / ${formatBytes(snapshot.disk.totalBytes)}` : '当前平台未提供'}</small></div><div><span>运行时长</span><strong>{formatDuration(snapshot.uptimeSeconds)}</strong><small>uptimeSeconds 可选</small></div><div><span>进程数量</span><strong>{snapshot.processCount ?? '未提供'}</strong><small>processCount 可选</small></div></div>
    <div className="host-network"><div className="host-section-title"><strong>网络计数器</strong><span>{network ? `${network.length} 个接口` : '当前平台未提供'}</span></div>{network?.length ? <div className="table-wrap"><table><thead><tr><th>接口</th><th>接收</th><th>接收包</th><th>发送</th><th>发送包</th></tr></thead><tbody>{network.map((item, index) => <tr key={`${item.interface ?? 'interface'}-${index}`}><td className="mono-cell">{item.interface ?? '未命名'}</td><td>{formatBytes(item.receiveBytes)}</td><td>{item.receivePackets ?? '未提供'}</td><td>{formatBytes(item.transmitBytes)}</td><td>{item.transmitPackets ?? '未提供'}</td></tr>)}</tbody></table></div> : <p>network 字段未提供，这在非 Linux 平台是正常情况。</p>}</div>
    <div className="evidence-notices">{crop.outputTruncated && <strong className="notice-truncated">内容已截断</strong>}{evidence.redacted && <strong className="notice-redacted">敏感信息已脱敏</strong>}</div>
  </div>
}

export function HostSnapshotsPage() {
  const queryClient = useQueryClient()
  const { setRequestedIncidentId } = useIncidentStreamTarget()
  const incidents = useQuery(incidentsQuery)
  const runners = useQuery({ ...runnersQuery({ status: 'online', limit: 100, offset: 0 }), placeholderData: keepPreviousData })
  const available = useMemo(() => hostSnapshotAvailable(runners.data?.items ?? []), [runners.data])
  const [incidentId, setIncidentId] = useState('')
  const [taskOffset, setTaskOffset] = useState(0)
  const planBinding = useRunnerTaskPlanStep(incidentId)
  const incident = incidents.data?.find((item) => item.id === incidentId)
  const tasks = useQuery({ ...runnerTasksQuery(incidentId ? { incidentId, limit: 50, offset: taskOffset } : { limit: 50, offset: 0 }), enabled: Boolean(incidentId), placeholderData: keepPreviousData })
  const hostTasks = (tasks.data?.items ?? []).filter((task) => task.operation === 'host.snapshot')
  const createTask = useMutation({
    mutationFn: (body: RunnerTaskCreate) => runnerTaskApi.create(body),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['runner-tasks'], exact: false, refetchType: 'all' }),
  })

  useEffect(() => {
    setRequestedIncidentId(incidentId || undefined)
    return () => setRequestedIncidentId(undefined)
  }, [incidentId, setRequestedIncidentId])
  useEffect(() => setTaskOffset(0), [incidentId])

  if (incidents.error) return <ErrorPanel error={incidents.error} />
  if (runners.error) return <ErrorPanel error={runners.error} />
  if (incidents.isPending || runners.isPending) return <LoadingPanel label="加载 Host Runner 能力" />

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!incident || !available || !planBinding.canCreate) return
    createTask.mutate({ incidentId: incident.id, planStepId: planBinding.planStepId || undefined, resourceId: incident.resourceId, connector: 'host', operation: 'host.snapshot', parameters: {}, idempotencyKey: `host-snapshot-${Date.now()}-${crypto.randomUUID()}` })
  }

  return <>
    <section className="page-heading"><div><span className="eyebrow">HOST OBSERVATION</span><h1>主机快照</h1><p>采集跨平台、无 Shell、无命令行和环境变量的有界主机汇总信息。</p></div></section>
    <section className="runner-safety-note"><span>跨平台字段</span><p>memory、network、uptimeSeconds 和 processCount 均为可选字段；未提供表示当前平台或权限不可用，不代表任务失败。</p></section>
    <section className="host-create-layout"><form className="panel log-query-form" onSubmit={submit}><div className="panel-heading"><div><h2>创建 Host Snapshot</h2><p>该操作不接受任何 parameters</p></div><span className={available ? 'success-text' : 'warn-text'}>{available ? 'CAPABILITY READY' : 'NO CAPABILITY'}</span></div><div className="log-form-body"><label>关联 Incident<select required value={incidentId} onChange={(event) => setIncidentId(event.target.value)}><option value="">请选择 Incident</option>{incidents.data?.map((item) => <option value={item.id} key={item.id}>{item.title} · {item.resource}</option>)}</select></label>{incident && <div className="selected-resource"><span>目标资源</span><strong>{incident.resource}</strong><small>{incident.resourceId}</small></div>}{incident && <RunnerTaskPlanStepField binding={planBinding} />}{!available && <div className="capability-empty"><strong>没有可用 Host Snapshot 能力</strong><p>在线 Runner 尚未声明 `host.snapshot`。</p></div>}</div><div className="panel-actions"><button className="primary-button" type="submit" disabled={!incident || !available || !planBinding.canCreate || createTask.isPending}>{createTask.isPending ? '正在创建…' : '采集主机快照'}</button></div>{createTask.error && <p className="form-error" role="alert">{createTask.error.message}</p>}</form></section>
    <section className="panel task-results"><div className="panel-heading"><div><h2>快照任务</h2><p>{incident ? `Incident ${incident.id}` : '选择 Incident 后查看快照'}</p></div>{incidentId && <button onClick={() => void tasks.refetch()} disabled={tasks.isFetching}>{tasks.isFetching ? '刷新中…' : '刷新快照'}</button>}</div><div className="host-task-list">{incidentId && hostTasks.length ? hostTasks.map((task) => <article className="host-task" key={task.id}><div className="host-task-meta"><RunnerTaskStatusBadge status={task.status} attempt={task.attempt} /><strong>{task.id}</strong><time>{new Date(task.updatedAt).toLocaleString('zh-CN', { hour12: false })}</time></div>{task.evidenceId ? <HostEvidence incidentId={task.incidentId} evidenceId={task.evidenceId} /> : <p className="inline-empty">{task.errorCode ? `采集失败：${task.errorCode}` : '等待 Runner 返回 Evidence'}</p>}</article>) : <p className="inline-empty">{incidentId ? '当前 Incident 还没有 Host Snapshot' : '请先选择 Incident'}</p>}</div></section>
    {incidentId && tasks.data && <PaginationControls page={tasks.data} disabled={tasks.isFetching} onOffsetChange={setTaskOffset} />}
  </>
}
