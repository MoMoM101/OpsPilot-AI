import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { labApi, type LabScenario, type LabScenarioAction } from '../api/labApi'
import { ApiError } from '../api/httpClient'
import { ErrorPanel, LoadingPanel } from '../components/LoadingPanel'

const labScenariosQueryKey = ['lab', 'scenarios'] as const

const statusMeta: Record<LabScenario['status'], { label: string; description: string }> = {
  ready: { label: 'READY', description: '可以注入故障' },
  active: { label: 'ACTIVE', description: '故障已激活，可以执行清理' },
  unavailable: { label: 'UNAVAILABLE', description: '当前控制器不支持或无法执行此场景' },
}

const actionLabels: Record<LabScenarioAction, string> = {
  inject: '注入故障',
  cleanup: '清理故障',
}

interface LabOperation {
  scenarioId: string
  scenarioTitle: string
  action: LabScenarioAction
  idempotencyKey: string
}

interface Feedback {
  kind: 'success' | 'replayed' | 'conflict' | 'unavailable' | 'forbidden' | 'error'
  message: string
}

export function createLabIdempotencyKey(action: LabScenarioAction): string {
  return `fault-lab-${action}-${crypto.randomUUID()}`
}

function operationError(error: Error): { feedback: Feedback; retryable: boolean } {
  if (error instanceof ApiError) {
    if (error.status === 403) return { feedback: { kind: 'forbidden', message: `权限不足：只有 Admin 可以操作 Fault Lab。${error.message}` }, retryable: false }
    if (error.status === 409 || error.code === 'LAB_SCENARIO_CONFLICT') return { feedback: { kind: 'conflict', message: `操作冲突：${error.message} 请刷新状态后发起新操作。` }, retryable: false }
    if (error.status === 503 || error.code === 'LAB_CONTROLLER_UNAVAILABLE') return { feedback: { kind: 'unavailable', message: `控制器不可用：${error.message}` }, retryable: true }
  }
  return { feedback: { kind: 'error', message: `操作失败：${error.message}` }, retryable: !(error instanceof ApiError) }
}

export function FaultLabPage() {
  const queryClient = useQueryClient()
  const [feedback, setFeedback] = useState<Feedback>()
  const [retryOperation, setRetryOperation] = useState<LabOperation>()
  const scenarios = useQuery({
    queryKey: labScenariosQueryKey,
    queryFn: ({ signal }) => labApi.list(signal),
  })
  const mutation = useMutation({
    mutationFn: (operation: LabOperation) => labApi.mutate(operation.scenarioId, operation.action, { idempotencyKey: operation.idempotencyKey }),
    onSuccess: (result, operation) => {
      setRetryOperation(undefined)
      setFeedback(result.replayed
        ? { kind: 'replayed', message: `${operation.scenarioTitle} 的${actionLabels[operation.action]}请求已幂等重放，未重复执行。` }
        : { kind: 'success', message: `${operation.scenarioTitle}：${actionLabels[operation.action]}已完成。` })
      queryClient.setQueryData<LabScenario[]>(labScenariosQueryKey, (current) => current?.map((scenario) => scenario.id === result.scenario.id ? result.scenario : scenario))
    },
    onError: (error: Error, operation) => {
      const outcome = operationError(error)
      setFeedback(outcome.feedback)
      setRetryOperation(outcome.retryable ? operation : undefined)
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: labScenariosQueryKey })
    },
  })

  if (scenarios.isPending) return <LoadingPanel label="加载 Fault Lab 场景" />
  if (scenarios.error) return <ErrorPanel error={scenarios.error} />

  const startOperation = (scenario: LabScenario, action: LabScenarioAction) => {
    const confirmed = window.confirm(`确认要对“${scenario.title}”执行“${actionLabels[action]}”吗？此操作会影响本地实验环境。`)
    if (!confirmed) return
    setFeedback(undefined)
    setRetryOperation(undefined)
    mutation.mutate({
      scenarioId: scenario.id,
      scenarioTitle: scenario.title,
      action,
      idempotencyKey: createLabIdempotencyKey(action),
    })
  }

  const busy = mutation.isPending
  const activeOperation = mutation.variables

  return <>
    <section className="page-heading"><div><span className="eyebrow">ADMIN · FAULT LAB</span><h1>故障场景工作台</h1><p>仅用于受控实验环境。浏览器只调用 OpsPilot 后端，不连接 Lab Controller，也不接触 Controller Token。</p></div><button type="button" onClick={() => void scenarios.refetch()} disabled={scenarios.isFetching || busy}>{scenarios.isFetching ? '正在刷新…' : '刷新状态'}</button></section>

    <section className="lab-boundary-note"><strong>安全边界</strong><p>注入和清理均需要二次确认。每次新操作使用独立幂等键；对失败操作的网络重试会复用原 key，避免重复执行。</p></section>

    {feedback && <section className={`lab-feedback lab-feedback-${feedback.kind}`} role="alert"><div><strong>{feedback.kind === 'replayed' ? 'REPLAYED' : feedback.kind === 'conflict' ? 'CONFLICT' : feedback.kind === 'unavailable' ? 'CONTROLLER UNAVAILABLE' : feedback.kind === 'forbidden' ? 'FORBIDDEN' : feedback.kind === 'success' ? 'SUCCEEDED' : 'FAILED'}</strong><span>{feedback.message}</span></div>{retryOperation && <button type="button" disabled={busy} onClick={() => mutation.mutate(retryOperation)}>{busy ? '正在重试…' : '重试本次操作'}</button>}</section>}

    <section className="lab-summary" aria-label="Fault Lab 场景汇总"><article><span>场景总数</span><strong>{scenarios.data.length}</strong></article><article><span>可注入</span><strong>{scenarios.data.filter((scenario) => scenario.status === 'ready').length}</strong></article><article><span>已激活</span><strong className="danger-text">{scenarios.data.filter((scenario) => scenario.status === 'active').length}</strong></article><article><span>不可用</span><strong className="warn-text">{scenarios.data.filter((scenario) => scenario.status === 'unavailable').length}</strong></article></section>

    <section className="lab-scenario-grid" aria-label="Fault Lab 场景列表">
      {scenarios.data.map((scenario) => {
        const operationRunning = busy && activeOperation?.scenarioId === scenario.id
        return <article className={`lab-scenario-card lab-scenario-${scenario.status}`} key={scenario.id}>
          <header><div><span className={`lab-status lab-status-${scenario.status}`}>{statusMeta[scenario.status].label}</span><small>{statusMeta[scenario.status].description}</small></div><span className="mono-cell">v{scenario.version}</span></header>
          <div className="lab-scenario-body"><h2>{scenario.title}</h2><p>{scenario.description}</p><code>{scenario.id}</code></div>
          <footer><button type="button" className="danger-button" disabled={busy || scenario.status !== 'ready' || !scenario.supported} onClick={() => startOperation(scenario, 'inject')}>{operationRunning && activeOperation?.action === 'inject' ? '正在注入…' : '注入故障'}</button><button type="button" disabled={busy || scenario.status !== 'active' || !scenario.supported} onClick={() => startOperation(scenario, 'cleanup')}>{operationRunning && activeOperation?.action === 'cleanup' ? '正在清理…' : '清理故障'}</button></footer>
        </article>
      })}
      {scenarios.data.length === 0 && <div className="lab-empty"><strong>没有可用场景</strong><p>后端当前未返回 Fault Lab 场景，请检查 Lab 配置后刷新。</p></div>}
    </section>
  </>
}
