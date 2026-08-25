import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { currentPlanQuery } from '../api/queries'
import { dataApi } from '../api/dataApi'

const observationalKinds = new Set(['observe', 'analyze', 'experiment', 'verify'])

export function useRunnerTaskPlanStep(incidentId: string) {
  const [planStepId, setPlanStepId] = useState('')
  const query = useQuery({ ...currentPlanQuery(incidentId), enabled: Boolean(incidentId) && dataApi.mode === 'http' })
  const activePlan = query.data?.status === 'active' ? query.data : null
  const eligibleSteps = useMemo(() => activePlan?.steps.filter((step) => step.status === 'running' && observationalKinds.has(step.kind)) ?? [], [activePlan])

  useEffect(() => {
    setPlanStepId((current) => eligibleSteps.some((step) => step.id === current) ? current : eligibleSteps.length === 1 ? eligibleSteps[0].id : '')
  }, [incidentId, eligibleSteps])

  return {
    planStepId,
    setPlanStepId,
    activePlan,
    eligibleSteps,
    isLoading: Boolean(incidentId) && dataApi.mode === 'http' && query.isPending,
    error: query.error,
    canCreate: (dataApi.mode === 'mock' || !query.isPending) && !query.error && (!activePlan || Boolean(planStepId)),
  }
}

export function RunnerTaskPlanStepField({ binding }: { binding: ReturnType<typeof useRunnerTaskPlanStep> }) {
  if (binding.isLoading) return <div className="plan-step-binding"><span>正在确认当前 Plan…</span></div>
  if (binding.error) return <div className="plan-step-binding binding-error"><strong>无法读取当前 Plan</strong><span>{binding.error.message}</span></div>
  if (!binding.activePlan) return <div className="plan-step-binding"><strong>独立观测任务</strong><span>当前没有活动 Plan，无需绑定 PlanStep。</span></div>
  return <div className="plan-step-binding"><label>关联活动 PlanStep<select required value={binding.planStepId} onChange={(event) => binding.setPlanStepId(event.target.value)}><option value="">请选择正在运行的观测步骤</option>{binding.eligibleSteps.map((step) => <option key={step.id} value={step.id}>Step {step.ordinal} · {step.title}</option>)}</select></label>{!binding.eligibleSteps.length && <p>活动 Plan 当前没有可执行只读观测的 running 步骤，请先启动对应 PlanStep。</p>}<small>Plan v{binding.activePlan.version} · 任务 Evidence 将自动关联到该步骤</small></div>
}
