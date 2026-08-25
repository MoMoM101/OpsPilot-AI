import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useState, type FormEvent } from 'react'
import { dataApi } from '../api/dataApi'
import { hypothesisApi, type HypothesisCreate, type HypothesisUpdate } from '../api/hypothesisApi'
import { hypothesesQuery } from '../api/queries'
import type { Hypothesis, HypothesisStatus, HypothesisSummary } from '../domain/types'
import { ErrorPanel, LoadingPanel } from './LoadingPanel'
import { useAuth } from '../auth/AuthContext'
import { PaginationControls } from './PaginationControls'

const HYPOTHESIS_PAGE_SIZE = 20

const statusLabels: Record<HypothesisStatus, string> = {
  proposed: '待验证', supported: '已支持', weakened: '已弱化', rejected: '已排除', confirmed: '已确认',
}

const transitions: Record<HypothesisStatus, HypothesisStatus[]> = {
  proposed: ['supported', 'weakened', 'confirmed', 'rejected'],
  supported: ['weakened', 'confirmed', 'rejected'],
  weakened: ['supported', 'rejected'],
  confirmed: ['weakened', 'rejected'],
  rejected: [],
}

function EvidenceLinks({ incidentId, ids, empty }: { incidentId: string; ids: string[]; empty: string }) {
  if (!ids.length) return <span>{empty}</span>
  return <>{ids.map((id) => <Link key={id} to="/incidents/$incidentId/evidence/$evidenceId" params={{ incidentId, evidenceId: id }}>{id.slice(0, 8)}…</Link>)}</>
}

function HypothesisCard({ incidentId, hypothesis, updating, onTransition, canWrite }: { incidentId: string; hypothesis: Hypothesis; updating: boolean; onTransition: (hypothesis: Hypothesis, status: HypothesisStatus) => void; canWrite: boolean }) {
  return <article className={`hypothesis-card hypothesis-${hypothesis.status}`}>
    <div className="hypothesis-head"><span>H{hypothesis.ordinal}</span><strong>{hypothesis.summary}</strong><em>{hypothesis.confidence}%</em><small>{statusLabels[hypothesis.status]} · v{hypothesis.version}</small></div>
    <div className="confidence-track"><span style={{ width: `${hypothesis.confidence}%` }} /></div>
    <div className="hypothesis-evidence"><div><strong>支持 Evidence</strong><EvidenceLinks incidentId={incidentId} ids={hypothesis.supportingEvidenceIds} empty="暂无" /></div><div><strong>反证 Evidence</strong><EvidenceLinks incidentId={incidentId} ids={hypothesis.contradictingEvidenceIds} empty="暂无" /></div></div>
    {canWrite && transitions[hypothesis.status].length > 0 && <div className="hypothesis-actions">{transitions[hypothesis.status].map((status) => <button key={status} type="button" disabled={updating} onClick={() => onTransition(hypothesis, status)}>{statusLabels[status]}</button>)}</div>}
  </article>
}

function PrimarySummary({ hypothesis }: { hypothesis?: HypothesisSummary }) {
  return hypothesis ? <article className="hypothesis-card"><div className="hypothesis-head"><span>H{hypothesis.ordinal}</span><strong>{hypothesis.summary}</strong><em>{hypothesis.confidence}%</em><small>{statusLabels[hypothesis.status]}</small></div></article> : <p className="inline-empty">尚未形成主要假设</p>
}

export function HypothesisPanel({ incidentId, primary }: { incidentId: string; primary?: HypothesisSummary }) {
  const { canWrite } = useAuth()
  const queryClient = useQueryClient()
  const httpEnabled = dataApi.mode === 'http'
  const [offset, setOffset] = useState(0)
  useEffect(() => setOffset(0), [incidentId])
  const query = useQuery({ ...hypothesesQuery(incidentId, { limit: HYPOTHESIS_PAGE_SIZE, offset }), enabled: httpEnabled, placeholderData: keepPreviousData })
  const [summary, setSummary] = useState('')
  const [confidence, setConfidence] = useState(50)

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['hypotheses', incidentId] }),
      queryClient.invalidateQueries({ queryKey: ['incidents', incidentId] }),
      queryClient.invalidateQueries({ queryKey: ['incidents'], exact: true }),
      queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
    ])
  }
  const create = useMutation({ mutationFn: (body: HypothesisCreate) => hypothesisApi.create(incidentId, body), onSuccess: async () => { setSummary(''); setConfidence(50); await refresh() } })
  const update = useMutation({ mutationFn: ({ id, body }: { id: string; body: HypothesisUpdate }) => hypothesisApi.update(incidentId, id, body), onSuccess: refresh })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const value = summary.trim()
    if (value) create.mutate({ summary: value, confidence })
  }

  return <section className="panel hypothesis-panel">
    <div className="panel-heading"><div><h2>结构化假设</h2><p>按置信度选择当前主要假设；Rejected 假设不会成为主假设</p></div><span className="panel-note">{httpEnabled ? 'LIVE API' : 'MOCK SUMMARY'}</span></div>
    {!httpEnabled ? <PrimarySummary hypothesis={primary} /> : <>
      {query.isPending ? <LoadingPanel label="加载 Hypothesis" /> : query.error ? <ErrorPanel error={query.error} /> : <><div className="hypothesis-list">{query.data.items.length ? query.data.items.map((hypothesis) => <HypothesisCard key={hypothesis.id} incidentId={incidentId} hypothesis={hypothesis} updating={update.isPending} canWrite={canWrite} onTransition={(item, status) => update.mutate({ id: item.id, body: { expectedVersion: item.version, status } })} />) : <p className="inline-empty">当前 Incident 尚无 Hypothesis</p>}</div><PaginationControls page={query.data} disabled={query.isFetching} onOffsetChange={setOffset} /></>}
      {canWrite && <form className="hypothesis-create" onSubmit={submit}><label>新假设<input required maxLength={500} value={summary} onChange={(event) => setSummary(event.target.value)} placeholder="描述一个可由 Evidence 验证的原因" /></label><label>初始置信度<input required type="number" min={0} max={100} value={confidence} onChange={(event) => setConfidence(event.target.valueAsNumber)} /></label><button className="primary-button" type="submit" disabled={create.isPending || !summary.trim()}>{create.isPending ? '正在创建…' : '创建 Hypothesis'}</button></form>}
      {(create.error || update.error) && <p className="form-error" role="alert">{(create.error ?? update.error)?.message}</p>}
    </>}
  </section>
}
