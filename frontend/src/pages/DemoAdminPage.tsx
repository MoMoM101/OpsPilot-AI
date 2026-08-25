import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import { demoApi, type DemoStatus } from '../api/demoApi'
import { ApiError } from '../api/httpClient'
import { ErrorPanel, LoadingPanel } from '../components/LoadingPanel'

const demoStatusKey = ['demo', 'status'] as const

const statusMeta: Record<DemoStatus['status'], { label: string; description: string }> = {
  unavailable: { label: 'UNAVAILABLE', description: '当前部署不允许使用 Demo 数据。' },
  inactive: { label: 'INACTIVE', description: 'Demo 工作区可用，但当前没有活动故事数据。' },
  active: { label: 'ACTIVE', description: 'Demo 故事已初始化，可以从快捷入口开始体验。' },
  drifted: { label: 'DRIFTED', description: '服务端管理清单与实际数据不一致，需要人工检查。' },
}

const unavailableReason: Record<NonNullable<DemoStatus['reasonCode']>, string> = {
  DEMO_DISABLED: '服务端未启用 OPSPILOT_DEMO_DATA_ENABLED，请由部署管理员在隔离环境开启。',
  PRODUCTION_DISABLED: '生产环境强制禁用 Demo 数据，不能通过前端或配置开关绕过。',
}

async function invalidateDemoConsumers(queryClient: ReturnType<typeof useQueryClient>) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ['incidents'] }),
    queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
    queryClient.invalidateQueries({ queryKey: ['resources'] }),
  ])
}

export function DemoAdminPage() {
  const queryClient = useQueryClient()
  const [feedback, setFeedback] = useState<string>()
  const [preparingCleanup, setPreparingCleanup] = useState(false)
  const status = useQuery({ queryKey: demoStatusKey, queryFn: ({ signal }) => demoApi.status(signal), retry: false })
  const initialize = useMutation({
    mutationFn: () => demoApi.initialize(),
    retry: false,
    onSuccess: async (result) => {
      queryClient.setQueryData(demoStatusKey, result)
      setFeedback(result.replayed ? `Demo generation ${result.generation} 已存在，本次直接复用现有数据。` : `Demo generation ${result.generation} 初始化完成。`)
      await invalidateDemoConsumers(queryClient)
      await queryClient.invalidateQueries({ queryKey: demoStatusKey })
    },
  })
  const cleanup = useMutation({
    mutationFn: (generation: number) => demoApi.cleanup(generation),
    retry: false,
    onSuccess: async (result) => {
      queryClient.setQueryData(demoStatusKey, result)
      setFeedback(result.replayed ? 'Demo 已处于清理完成状态，本次未重复删除。' : `已清理 generation ${result.generation} 的 ${result.deletedIncidentCount} 个 Demo Incident；工作区骨架已保留。`)
      await invalidateDemoConsumers(queryClient)
      await queryClient.invalidateQueries({ queryKey: demoStatusKey })
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.status === 409) await queryClient.invalidateQueries({ queryKey: demoStatusKey })
    },
  })

  if (status.isPending) return <LoadingPanel label="加载 Demo 数据状态" />
  if (status.error) return <ErrorPanel error={status.error} />

  const current = status.data
  const busy = initialize.isPending || cleanup.isPending || preparingCleanup
  const initializeDemo = () => {
    if (!window.confirm(current.status === 'active' ? '确认重新请求初始化并复用当前 Demo 数据吗？' : '确认初始化 Guided Demo 数据吗？')) return
    setFeedback(undefined)
    initialize.mutate()
  }
  const cleanupLatestGeneration = async () => {
    setPreparingCleanup(true)
    setFeedback(undefined)
    try {
      const latest = await status.refetch()
      if (!latest.data || latest.data.status !== 'active') {
        setFeedback(latest.data?.status === 'drifted' ? 'Demo 数据已发生漂移，请人工检查，前端不会提供强制清理。' : 'Demo 状态已变化，本次未执行清理。')
        return
      }
      const generation = latest.data.generation
      if (!window.confirm(`确认清理 Demo generation ${generation} 的受管 Incident 吗？Environment 和 Resource 骨架会保留。`)) return
      try { await cleanup.mutateAsync(generation) } catch { /* mutation 状态负责展示错误；409 会刷新状态 */ }
    } finally {
      setPreparingCleanup(false)
    }
  }

  return <>
    <section className="page-heading"><div><span className="eyebrow">ADMIN · GUIDED DEMO</span><h1>Demo 数据引导</h1><p>初始化隔离的合成 Incident 故事，并按服务端所有权清单安全清理；不会按名称批量删除用户数据。</p></div><button type="button" disabled={busy || status.isFetching} onClick={() => void status.refetch()}>{status.isFetching ? '正在刷新…' : '刷新状态'}</button></section>
    <section className={`demo-overview demo-${current.status}`}><div><span>状态</span><strong>{statusMeta[current.status].label}</strong><p>{statusMeta[current.status].description}</p></div><dl><div><dt>Generation</dt><dd>{current.generation}</dd></div><div><dt>Manifest</dt><dd>v{current.manifestVersion}</dd></div><div><dt>Resources</dt><dd>{current.resourceIds.length}</dd></div><div><dt>Incidents</dt><dd>{current.incidentIds.length}</dd></div></dl></section>

    {current.status === 'unavailable' && <section className="demo-notice demo-unavailable" role="alert"><strong>Demo 不可用</strong><p>{current.reasonCode ? unavailableReason[current.reasonCode] : '当前部署未提供 Demo 数据能力。'}</p><code>{current.reasonCode ?? 'UNAVAILABLE'}</code></section>}
    {current.status === 'drifted' && <section className="demo-notice demo-drifted" role="alert"><strong>需要人工检查</strong><p>受管 Incident、Environment 或 Resource 与服务端清单不一致。为避免误删，页面不会提供清理、强制清理或重新初始化操作。</p><code>DEMO_DATA_DRIFT</code></section>}
    {feedback && <section className="demo-feedback" role="status">{feedback}</section>}
    {(initialize.error || cleanup.error) && <p className="form-error" role="alert">{(initialize.error ?? cleanup.error)?.message}</p>}

    {current.status !== 'unavailable' && current.status !== 'drifted' && <section className="panel demo-actions"><div className="panel-heading"><div><h2>生命周期操作</h2><p>清理前会重新读取最新 generation；版本冲突只刷新状态，不自动重试。</p></div><div className="button-row"><button type="button" disabled={busy} onClick={initializeDemo}>{initialize.isPending ? '正在初始化…' : current.status === 'active' ? '复用当前 Demo' : '初始化 Demo'}</button>{current.status === 'active' && <button type="button" className="danger-button" disabled={busy} onClick={() => void cleanupLatestGeneration()}>{preparingCleanup ? '正在读取最新状态…' : cleanup.isPending ? '正在清理…' : '清理 Demo'}</button>}</div></div></section>}

    {current.environmentId && <section className="panel demo-assets"><div className="panel-heading"><div><h2>Demo 快捷入口</h2><p>Environment、Resource 拓扑与本 generation 的 Incident</p></div><Link to="/resources">打开资源拓扑</Link></div><dl><div><dt>Environment</dt><dd>{current.environmentId}</dd></div><div><dt>Resources</dt><dd>{current.resourceIds.join(', ') || '—'}</dd></div></dl><div className="demo-incident-links">{current.incidentIds.map((incidentId, index) => <Link key={incidentId} to="/incidents/$incidentId" params={{ incidentId }}><strong>Demo Incident {index + 1}</strong><span>{incidentId}</span></Link>)}{!current.incidentIds.length && <p>当前 generation 没有活动 Demo Incident。</p>}</div></section>}
  </>
}
