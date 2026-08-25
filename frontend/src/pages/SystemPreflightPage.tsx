import { useMutation, useQuery } from '@tanstack/react-query'
import { systemApi, type DeploymentPreflightCheck, type ModelConnectionCheck } from '../api/systemApi'
import { ErrorPanel, LoadingPanel } from '../components/LoadingPanel'

function CheckList({ title, checks, tone, empty }: { title: string; checks: DeploymentPreflightCheck[]; tone: string; empty: string }) {
  return <section className={`panel preflight-section preflight-${tone}`}><div className="panel-heading"><div><h2>{title}</h2><p>{checks.length ? `${checks.length} 项检查` : empty}</p></div><span className="panel-note">{tone.toUpperCase()}</span></div>{checks.length ? <div className="preflight-list">{checks.map((check) => <article key={check.key}><span className="preflight-icon">{tone === 'blocking' ? '!' : tone === 'warning' ? '△' : '✓'}</span><div><strong>{check.message}</strong><code>{check.key}</code></div></article>)}</div> : <p className="preflight-empty">{empty}</p>}</section>
}

const modelStatusMeta: Record<ModelConnectionCheck['status'], { label: string; guidance: string }> = {
  ok: { label: '连接正常', guidance: 'Provider 已完成服务端固定的最小结构化探测。' },
  failed: { label: '连接失败', guidance: '请根据固定错误码和服务端提示检查 Provider 服务端配置。' },
  disabled: { label: 'Runtime 未启用', guidance: 'Agent Runtime 当前未启用，本次检查没有访问外部 Provider。' },
  not_configured: { label: 'Provider 未配置', guidance: 'Agent Runtime 已启用，但服务端当前没有可用的模型 Provider 配置。' },
}

function ModelConnectionResult({ result }: { result: ModelConnectionCheck }) {
  const meta = modelStatusMeta[result.status]
  return <div className={`model-check-result model-check-${result.status}`} role="status">
    <div className="model-check-status"><span>{result.status.toUpperCase()}</span><strong>{meta.label}</strong>{result.cached && <em>近期缓存结果</em>}</div>
    <p>{meta.guidance}</p>
    <dl><div><dt>服务端消息</dt><dd>{result.message}</dd></div><div><dt>错误码</dt><dd>{result.errorCode ?? '—'}</dd></div><div><dt>连接探测</dt><dd>{result.connectivityChecked ? '已执行' : '未执行'}</dd></div><div><dt>耗时</dt><dd>{result.latencyMs === null ? '—' : `${result.latencyMs} ms`}</dd></div><div><dt>检查时间</dt><dd>{new Date(result.checkedAt).toLocaleString('zh-CN', { hour12: false })}</dd></div></dl>
    {result.cached && <small>该结果来自服务端近期缓存，本次没有重复发起 Provider 探测。页面不会自动循环重试。</small>}
  </div>
}

export function SystemPreflightPage() {
  const query = useQuery({ queryKey: ['system', 'preflight'], queryFn: ({ signal }) => systemApi.preflight(signal) })
  const modelCheck = useMutation({ mutationFn: () => systemApi.checkModelConnection(), retry: false })
  if (query.isPending) return <LoadingPanel label="执行系统 Preflight" />
  if (query.error) return <ErrorPanel error={query.error} />

  const actionRequired = query.data.checks.filter((check) => check.status === 'action_required')
  const warnings = query.data.checks.filter((check) => check.status === 'warning')
  const passed = query.data.checks.filter((check) => check.status === 'pass')

  return <>
    <section className="page-heading"><div><span className="eyebrow">ADMIN · SYSTEM PREFLIGHT</span><h1>系统部署状态</h1><p>部署前置检查将阻塞性整改项与非阻塞警告分开展示，避免忽略必须处理的问题。</p></div><button type="button" onClick={() => void query.refetch()} disabled={query.isFetching}>{query.isFetching ? '正在检查…' : '重新检查'}</button></section>
    <section className={`preflight-overview preflight-overview-${query.data.status}`}><div><span>总体状态</span><strong>{query.data.status === 'ready' ? 'READY' : 'ACTION REQUIRED'}</strong></div><div><span>阻塞项</span><strong>{actionRequired.length}</strong></div><div><span>警告</span><strong>{warnings.length}</strong></div><time>检查时间 {new Date(query.data.checkedAt).toLocaleString('zh-CN', { hour12: false })}</time></section>
    <section className="panel model-check-panel"><div className="panel-heading"><div><h2>模型连接诊断</h2><p>使用服务端已验证配置执行一次固定探测；浏览器不提交模型配置、凭据或 Prompt。</p></div><button type="button" onClick={() => modelCheck.mutate()} disabled={modelCheck.isPending}>{modelCheck.isPending ? '正在检查连接…' : '检查模型连接'}</button></div>{modelCheck.data ? <ModelConnectionResult result={modelCheck.data} /> : <p className="model-check-empty">尚未执行连接检查。该操作只在点击后执行一次，不会自动轮询。</p>}{modelCheck.error && <p className="form-error" role="alert">{modelCheck.error.message}</p>}</section>
    <div className="preflight-grid"><CheckList title="必须处理" checks={actionRequired} tone="blocking" empty="当前没有阻塞部署的整改项。" /><CheckList title="警告" checks={warnings} tone="warning" empty="当前没有非阻塞警告。" /></div>
    <CheckList title="已通过" checks={passed} tone="passed" empty="暂无通过项。" />
  </>
}
