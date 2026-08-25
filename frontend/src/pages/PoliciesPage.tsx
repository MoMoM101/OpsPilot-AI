import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { policyApi, type PolicyDecision, type PolicyDryRunRequest, type PolicyRule, type PolicyRuleCreate, type PolicyRuleUpdate } from '../api/policyApi'
import { policyRulesQuery } from '../api/queries'
import { ApiError } from '../api/httpClient'
import { ErrorPanel } from '../components/LoadingPanel'
import { useAuth } from '../auth/AuthContext'
import { PaginationControls } from '../components/PaginationControls'

const uuidPattern = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}'
const splitValues = (value: string) => value.split(',').map((item) => item.trim()).filter(Boolean)
const weekdayLabels = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const optionalNumber = (value: FormDataEntryValue | null) => value === null || String(value) === '' ? null : Number(value)

export function policyAccessForRole(role: 'viewer' | 'operator' | 'admin' | 'runtime') {
  return { canRead: true, canDryRun: role === 'operator' || role === 'admin', canManage: role === 'admin' }
}

function ruleBody(form: FormData): PolicyRuleCreate {
  return {
    environmentId: String(form.get('environmentId')),
    name: String(form.get('name')).trim(),
    description: String(form.get('description')).trim() || null,
    priority: Number(form.get('priority')),
    enabled: form.get('enabled') === 'on',
    effect: form.get('effect') as PolicyRuleCreate['effect'],
    approvalRequired: form.get('approvalRequired') === 'on',
    autonomyLevels: form.getAll('autonomyLevels') as PolicyRuleCreate['autonomyLevels'],
    riskLevels: form.getAll('riskLevels') as PolicyRuleCreate['riskLevels'],
    capabilities: splitValues(String(form.get('capabilities'))),
    resourceIds: splitValues(String(form.get('resourceIds'))),
    maintenanceDays: form.getAll('maintenanceDays').map(Number),
    maintenanceStartMinute: optionalNumber(form.get('maintenanceStartMinute')),
    maintenanceEndMinute: optionalNumber(form.get('maintenanceEndMinute')),
    maxExecutionsPerIncident: optionalNumber(form.get('maxExecutionsPerIncident')),
  }
}

function RuleFields({ rule }: { rule?: PolicyRule }) {
  return <div className="policy-form-body">
    <label>Environment UUID<input name="environmentId" required pattern={uuidPattern} defaultValue={rule?.environmentId} /></label><label>规则名称<input name="name" required maxLength={150} defaultValue={rule?.name} /></label>
    <label className="span-two">说明<textarea name="description" maxLength={2000} defaultValue={rule?.description ?? ''} /></label><label>优先级<input name="priority" type="number" min={-10000} max={10000} defaultValue={rule?.priority ?? 0} /></label><label>效果<select name="effect" defaultValue={rule?.effect ?? 'deny'}><option value="deny">deny</option><option value="allow">allow</option></select></label>
    <fieldset><legend>自主等级</legend>{['L0','L1','L2','L3','L4'].map((level) => <label key={level}><input type="checkbox" name="autonomyLevels" value={level} defaultChecked={rule?.autonomyLevels.includes(level as never)} />{level}</label>)}</fieldset><fieldset><legend>风险等级</legend>{['read_only','low','medium','high'].map((risk) => <label key={risk}><input type="checkbox" name="riskLevels" value={risk} defaultChecked={rule?.riskLevels.includes(risk as never)} />{risk}</label>)}</fieldset>
    <label className="span-two">Capabilities（逗号分隔）<input name="capabilities" defaultValue={rule?.capabilities.join(', ')} placeholder="runner.task.create, action.execute" /></label><label className="span-two">Resource UUID（逗号分隔）<input name="resourceIds" defaultValue={rule?.resourceIds.join(', ')} /></label>
    <fieldset className="span-two maintenance-days"><legend>维护星期（UTC）</legend>{weekdayLabels.map((label, day) => <label key={day}><input type="checkbox" name="maintenanceDays" value={day} defaultChecked={rule?.maintenanceDays.includes(day)} />{label}</label>)}</fieldset>
    <label>UTC 起始分钟<input name="maintenanceStartMinute" type="number" min={0} max={1439} defaultValue={rule?.maintenanceStartMinute ?? ''} placeholder="0–1439" /></label><label>UTC 结束分钟<input name="maintenanceEndMinute" type="number" min={1} max={1440} defaultValue={rule?.maintenanceEndMinute ?? ''} placeholder="1–1440" /></label>
    <label>单 Incident 次数限制<input name="maxExecutionsPerIncident" type="number" min={1} max={10000} defaultValue={rule?.maxExecutionsPerIncident ?? ''} placeholder="不填表示不限" /></label><label className="check-field"><input name="enabled" type="checkbox" defaultChecked={rule?.enabled ?? true} />启用</label><label className="check-field"><input name="approvalRequired" type="checkbox" defaultChecked={rule?.approvalRequired} />要求审批</label>
  </div>
}

export function PoliciesPage() {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const access = policyAccessForRole(user?.role ?? 'viewer')
  const [environmentId, setEnvironmentId] = useState('')
  const [offset, setOffset] = useState(0)
  const [editing, setEditing] = useState<PolicyRule | null>(null)
  const [decision, setDecision] = useState<PolicyDecision | null>(null)
  const rules = useQuery({ ...policyRulesQuery({ environmentId, limit: 100, offset }), enabled: Boolean(environmentId), placeholderData: keepPreviousData })
  const create = useMutation({ mutationFn: (body: PolicyRuleCreate) => policyApi.create(body), onSuccess: async (rule) => { setEnvironmentId(rule.environmentId); setOffset(0); await queryClient.invalidateQueries({ queryKey: ['policies'] }) } })
  const update = useMutation({ mutationFn: ({ id, body }: { id: string; body: PolicyRuleUpdate }) => policyApi.update(id, body), onSuccess: async () => { setEditing(null); await queryClient.invalidateQueries({ queryKey: ['policies'] }) }, onError: (error) => { if (error instanceof ApiError && error.code === 'POLICY_RULE_VERSION_CONFLICT') void rules.refetch() } })
  const dryRun = useMutation({ mutationFn: (body: PolicyDryRunRequest) => policyApi.dryRun(body), onSuccess: setDecision })
  const submitRule = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const body = ruleBody(new FormData(event.currentTarget)); if (editing) update.mutate({ id: editing.id, body: { ...body, expectedVersion: editing.version } }); else create.mutate(body) }
  const submitDryRun = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const form = new FormData(event.currentTarget); dryRun.mutate({ environmentId: String(form.get('environmentId')), resourceId: String(form.get('resourceId')), capability: String(form.get('capability')).trim(), autonomyLevel: form.get('autonomyLevel') as PolicyDryRunRequest['autonomyLevel'], risk: form.get('risk') as PolicyDryRunRequest['risk'] }) }
  const mutation = editing ? update : create

  return <>
    <section className="page-heading"><div><span className="eyebrow">SERVER-AUTHORITATIVE POLICY</span><h1>Policy 规则与 Dry Run</h1><p>所有角色可按 Environment 查看规则；Operator 可执行 Dry Run，只有 Admin 可以创建或修改规则。</p></div></section>
    <section className="policy-layout">
      {access.canManage && <form key={editing?.id ?? 'new'} className="panel policy-form" onSubmit={submitRule}><div className="panel-heading"><div><h2>{editing ? `修改规则 · v${editing.version}` : '创建规则'}</h2><p>{editing ? 'PUT 请求将携带 expectedVersion' : 'Admin 管理 Environment 级策略'}</p></div><span className="panel-note">ADMIN ONLY</span></div><RuleFields rule={editing ?? undefined} /><div className="panel-actions"><button className="primary-button" type="submit" disabled={mutation.isPending}>{mutation.isPending ? '保存中…' : editing ? '保存修改' : '创建 Policy Rule'}</button>{editing && <button type="button" onClick={() => setEditing(null)}>取消编辑</button>}</div>{mutation.error && <p className="form-error" role="alert">{mutation.error.message}</p>}</form>}
      {access.canDryRun ? <form className="panel policy-form" onSubmit={submitDryRun}><div className="panel-heading"><div><h2>Dry Run</h2><p>只评估，不生成快照、不占用额度</p></div></div><div className="policy-form-body"><label>Environment UUID<input name="environmentId" required pattern={uuidPattern} defaultValue={environmentId} /></label><label>Resource UUID<input name="resourceId" required pattern={uuidPattern} /></label><label className="span-two">Capability<input name="capability" required maxLength={150} placeholder="action.execute" /></label><label>自主等级<select name="autonomyLevel" defaultValue="L1">{['L0','L1','L2','L3','L4'].map((level) => <option key={level}>{level}</option>)}</select></label><label>风险<select name="risk" defaultValue="read_only">{['read_only','low','medium','high'].map((risk) => <option key={risk}>{risk}</option>)}</select></label></div><div className="panel-actions"><button className="primary-button" type="submit" disabled={dryRun.isPending}>{dryRun.isPending ? '评估中…' : '请求后端 Dry Run'}</button></div>{dryRun.error && <p className="form-error" role="alert">{dryRun.error.message}</p>}</form> : <section className="panel permission-panel"><span className="panel-note">READ ONLY</span><h2>当前为只读 Policy 视图</h2><p>Viewer 可以查询规则；Dry Run 需要 Operator 或 Admin 权限。</p></section>}
    </section>
    {decision && <section className={`policy-decision ${decision.allowed ? 'decision-allowed' : 'decision-denied'}`} role="status"><div><span>后端 Dry Run 决策</span><strong>{decision.allowed ? 'ALLOWED' : 'DENIED'}</strong></div><dl><div><dt>allowed</dt><dd>{String(decision.allowed)}</dd></div><div><dt>approvalRequired</dt><dd>{String(decision.approvalRequired)}</dd></div><div><dt>匹配规则</dt><dd>{decision.matchedRuleName ?? '无'}{decision.matchedRuleId ? ` · ${decision.matchedRuleId}` : ''}</dd></div><div><dt>规则版本</dt><dd>{decision.matchedRuleVersion === null ? '—' : `v${decision.matchedRuleVersion}`}</dd></div><div><dt>剩余可创建 Action 数</dt><dd>{decision.remainingExecutions === null ? '不限或不适用' : decision.remainingExecutions}</dd></div><div><dt>reason</dt><dd>{decision.reason}</dd></div></dl></section>}
    <section className="panel"><div className="panel-heading"><div><h2>Policy 规则列表</h2><p>输入 Environment UUID 后从后端加载</p></div><form className="inline-filter" onSubmit={(event) => { event.preventDefault(); setEnvironmentId(String(new FormData(event.currentTarget).get('environmentId'))); setOffset(0) }}><input name="environmentId" required pattern={uuidPattern} placeholder="Environment UUID" defaultValue={environmentId} /><button type="submit">加载规则</button></form></div>{rules.error ? <ErrorPanel error={rules.error} /> : <><div className="table-wrap"><table><thead><tr><th>优先级</th><th>规则</th><th>效果</th><th>约束</th><th>额度</th><th>状态</th>{access.canManage && <th>操作</th>}</tr></thead><tbody>{rules.data?.items.map((rule) => <tr key={rule.id}><td>{rule.priority}</td><td><strong>{rule.name}</strong><span className="table-subline">v{rule.version} · {rule.description ?? rule.id}</span></td><td className={rule.effect === 'allow' ? 'success-text' : 'warn-text'}>{rule.effect}</td><td><span>{rule.autonomyLevels.join(', ') || '全部自主等级'} · {rule.riskLevels.join(', ') || '全部风险'}</span><span className="table-subline">维护日 {rule.maintenanceDays.length ? rule.maintenanceDays.map((day) => weekdayLabels[day]).join(', ') : '不限'} · UTC {rule.maintenanceStartMinute ?? '—'}–{rule.maintenanceEndMinute ?? '—'}</span></td><td>{rule.maxExecutionsPerIncident === null ? '不限' : `${rule.maxExecutionsPerIncident} / Incident`}</td><td>{rule.enabled ? 'ENABLED' : 'DISABLED'}</td>{access.canManage && <td><button type="button" onClick={() => setEditing(rule)}>修改</button></td>}</tr>)}{environmentId && !rules.isPending && !rules.data?.items.length && <tr><td colSpan={access.canManage ? 7 : 6} className="empty-table">当前 Environment 尚无 Policy 规则</td></tr>}{!environmentId && <tr><td colSpan={access.canManage ? 7 : 6} className="empty-table">请输入 Environment UUID 加载规则</td></tr>}</tbody></table></div>{rules.data && <PaginationControls page={rules.data} disabled={rules.isFetching} onOffsetChange={setOffset} />}</>}</section>
  </>
}
