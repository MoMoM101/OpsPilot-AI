import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { adminApi, type PrincipalCreate, type PrincipalCreateResponse, type PrincipalTokenRotation } from '../api/adminApi'
import { principalsQuery } from '../api/queries'
import { ErrorPanel, LoadingPanel } from '../components/LoadingPanel'
import { PaginationControls } from '../components/PaginationControls'
import { useAuth } from '../auth/AuthContext'
import { holdAutomaticSessionRefresh } from '../auth/authSession'

export function IdentityAdminPage() {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const [offset, setOffset] = useState(0)
  const [rotation, setRotation] = useState<PrincipalTokenRotation | PrincipalCreateResponse | null>(null)
  const principals = useQuery({ ...principalsQuery({ limit: 100, offset }), placeholderData: keepPreviousData, enabled: rotation === null })
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['principals'] })
  useEffect(() => rotation ? holdAutomaticSessionRefresh() : undefined, [rotation])
  const rotate = useMutation({
    mutationFn: (id: string) => adminApi.rotatePrincipalToken(id),
    onSuccess: (result) => {
      setRotation(result)
    },
  })
  const create = useMutation({ mutationFn: (body: PrincipalCreate) => adminApi.createPrincipal(body), onSuccess: (result) => { setRotation(result); setOffset(0) } })
  const deactivate = useMutation({ mutationFn: (id: string) => adminApi.deactivatePrincipal(id), onSuccess: refresh, onError: refresh })

  if (principals.isPending) return <LoadingPanel label="加载 Principal" />
  if (principals.error) return <ErrorPanel error={principals.error} />
  const confirmRotation = (id: string, name: string) => {
    if (window.confirm(`轮换 ${name} 的 Token？旧 Token 和该用户全部浏览器 Session 会立即失效。`)) rotate.mutate(id)
  }
  const submitCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const unrestrictedEnvironments = form.get('unrestrictedEnvironments') === 'on'
    create.mutate({ name: String(form.get('name')).trim(), kind: form.get('kind') as PrincipalCreate['kind'], role: form.get('role') as PrincipalCreate['role'], unrestrictedEnvironments, environmentIds: unrestrictedEnvironments ? [] : String(form.get('environmentIds')).split(',').map((item) => item.trim()).filter(Boolean) })
  }

  return <>
    <section className="page-heading"><div><span className="eyebrow">IDENTITY ADMINISTRATION</span><h1>Principal 与 Token</h1><p>查看控制面身份、角色、Environment 范围和 Token 生命周期。Token 轮换后只展示一次。</p></div><button onClick={() => void principals.refetch()} disabled={principals.isFetching || Boolean(rotation)}>{rotation ? '请先保存 Token' : principals.isFetching ? '刷新中…' : '刷新身份'}</button></section>
    {rotation && <section className="token-reveal" role="alert"><div><span className="unavailable-label">ONE-TIME SECRET</span><h2>新 Token 仅显示一次</h2><p>请立即通过安全的线下渠道交付。确认保存前暂停自动会话刷新和身份列表请求。</p></div><code>{rotation.accessToken}</code><div className="button-row"><button onClick={() => void navigator.clipboard.writeText(rotation.accessToken)}>复制 Token</button><button onClick={() => { setRotation(null); void refresh() }}>我已安全保存并关闭</button></div></section>}
    <form className="panel filter-bar" onSubmit={submitCreate}><label>名称<input name="name" required maxLength={150} /></label><label>类型<select name="kind" defaultValue="user"><option value="user">user</option><option value="service">service</option></select></label><label>角色<select name="role" defaultValue="viewer"><option value="viewer">viewer</option><option value="operator">operator</option><option value="admin">admin</option><option value="runtime">runtime</option></select></label><label className="search-field">Environment UUID（逗号分隔）<input name="environmentIds" /></label><label><input name="unrestrictedEnvironments" type="checkbox" /> 全部 Environment</label><button className="primary-button" type="submit" disabled={create.isPending}>{create.isPending ? '创建中…' : '创建 Principal'}</button></form>
    <section className="panel"><div className="panel-heading"><h2>Principal</h2><span className="panel-note">共 {principals.data.totalCount} 条</span></div><div className="table-wrap"><table><thead><tr><th>Principal</th><th>类型 / 角色</th><th>Environment 范围</th><th>状态</th><th>Token 到期</th><th>操作</th></tr></thead><tbody>{principals.data.items.map((principal) => { const isCurrent = principal.id === user?.id; return <tr key={principal.id}><td><strong>{principal.name}</strong><span className="table-subline">{principal.id}{isCurrent ? ' · 当前登录用户' : ''}</span></td><td>{principal.kind} / {principal.role}</td><td>{principal.unrestrictedEnvironments ? '全部 Environment' : principal.environmentIds.length ? principal.environmentIds.join(', ') : '无授权 Environment'}</td><td>{principal.active ? <span className="success-text">ACTIVE</span> : <span className="warn-text">INACTIVE</span>}</td><td className="mono-cell">{new Date(principal.tokenExpiresAt).toLocaleString('zh-CN', { hour12: false })}</td><td><div className="button-row"><button disabled={isCurrent || !principal.active || rotate.isPending || Boolean(rotation)} title={isCurrent ? '当前登录用户不能在此轮换 Token，请使用安全自轮换流程。' : undefined} onClick={() => confirmRotation(principal.id, principal.name)}>{rotate.isPending ? '轮换中…' : '轮换 Token'}</button><button className="danger-button" disabled={isCurrent || !principal.active || deactivate.isPending || Boolean(rotation)} title={isCurrent ? '当前登录用户不能停用自己。' : '最终安全限制以后端校验为准。'} onClick={() => { if (window.confirm(`停用 ${principal.name}？`)) deactivate.mutate(principal.id) }}>停用</button></div>{isCurrent && <span className="table-subline">当前用户不可自轮换或自停用</span>}</td></tr> })}</tbody></table></div><PaginationControls page={principals.data} disabled={principals.isFetching || Boolean(rotation)} onOffsetChange={setOffset} />{(rotate.error || create.error || deactivate.error) && <p className="form-error" role="alert">{(rotate.error ?? create.error ?? deactivate.error)?.message}</p>}</section>
  </>
}
