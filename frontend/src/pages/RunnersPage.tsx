import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { connectorCatalogQuery, environmentsQuery, runnersQuery } from '../api/queries'
import { ErrorPanel, LoadingPanel } from '../components/LoadingPanel'
import { PaginationControls } from '../components/PaginationControls'
import type { RunnerCapability, RunnerStatus } from '../domain/types'
import type { ConnectorAvailabilityStatus, ConnectorCatalogItem } from '../api/connectorApi'

const statusLabels: Record<RunnerStatus, string> = {
  online: '在线',
  offline: '离线',
  draining: '排空中',
  disabled: '已禁用',
}

const connectorStatusMeta: Record<ConnectorAvailabilityStatus, { label: string; description: string }> = {
  ready: { label: '已就绪', description: '在线且兼容的 Runner 已覆盖全部声明能力。' },
  partial: { label: '部分就绪', description: '兼容 Runner 当前在线，但只覆盖部分能力。' },
  offline: { label: '离线', description: '已配置兼容 Runner，但当前没有有效在线 Lease。' },
  not_configured: { label: '未配置', description: '当前范围内没有 Runner 声明该 Connector。' },
  incompatible: { label: '版本不兼容', description: 'Runner 已声明该 Connector，但 Contract 主版本不兼容。' },
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function capabilityName(capability: RunnerCapability, index: number) {
  return typeof capability.connector === 'string' ? capability.connector : `能力 ${index + 1}`
}

function CapabilityList({ capabilities }: { capabilities: RunnerCapability[] }) {
  if (!capabilities.length) return <span className="mono-cell">未声明</span>
  return <div className="capability-list">{capabilities.map((capability, index) => {
    const observeCount = Array.isArray(capability.observe) ? capability.observe.length : 0
    const actionCount = Array.isArray(capability.actions) ? capability.actions.length : 0
    return <span className="capability-chip" key={`${capabilityName(capability, index)}-${index}`} title={`只读能力 ${observeCount} · 动作能力 ${actionCount}`}><strong>{capabilityName(capability, index)}</strong>{capability.contractVersion && <small>v{capability.contractVersion}</small>}<em>{observeCount}R / {actionCount}A</em></span>
  })}</div>
}

function OperationList({ title, operations }: { title: string; operations: string[] }) {
  return <div className="connector-operations"><strong>{title}</strong>{operations.length
    ? <div>{operations.map((operation) => <code key={operation}>{operation}</code>)}</div>
    : <span>当前无在线能力</span>}</div>
}

function ConnectorCard({ item }: { item: ConnectorCatalogItem }) {
  const availability = item.availability
  const meta = connectorStatusMeta[availability.status]
  return <article className={`connector-card connector-${availability.status}`}>
    <header><div><strong>{item.connector}</strong><span>Contract v{item.contractVersion}</span></div><span className="badge">{meta.label}</span></header>
    <p>{meta.description}</p>
    <div className="connector-counts"><span>在线 {availability.onlineRunnerCount}</span><span>兼容 {availability.compatibleRunnerCount}</span><span>不兼容 {availability.incompatibleRunnerCount}</span></div>
    <OperationList title="当前在线观测能力" operations={availability.readyObserveOperations} />
    <OperationList title="当前在线动作能力" operations={availability.readyActionOperations} />
    <div className="connector-deployment"><strong>Runner 部署配置</strong>{item.runnerSettingKeys.length
      ? <div>{item.runnerSettingKeys.map((key) => <code key={key}>{key}</code>)}</div>
      : <span>无需额外 Runner 配置键</span>}<small>只在 Runner 部署环境中配置。配置完成后重启 Runner，再刷新目录状态。</small></div>
  </article>
}

function ConnectorCatalogPanel() {
  const [environmentId, setEnvironmentId] = useState('')
  const environments = useQuery(environmentsQuery({ limit: 100, offset: 0 }))
  const catalog = useQuery(connectorCatalogQuery(environmentId || undefined))

  return <section className="panel connector-catalog-panel">
    <div className="panel-heading"><div><h2>Connector 配置向导</h2><p>按 Environment 检查 Runner 当前在线能力；配置动作只在 Runner 部署侧完成。</p></div><div className="connector-toolbar"><label htmlFor="connector-environment">Environment</label><select id="connector-environment" value={environmentId} onChange={(event) => setEnvironmentId(event.target.value)} disabled={environments.isPending || environments.isError}><option value="">当前授权范围（聚合）</option>{environments.data?.items.map((environment) => <option key={environment.id} value={environment.id}>{environment.name} · {environment.slug}</option>)}</select><button type="button" onClick={() => void catalog.refetch()} disabled={catalog.isFetching}>{catalog.isFetching ? '正在刷新…' : '刷新目录'}</button></div></div>
    {environments.error && <div className="connector-inline-error" role="alert">Environment 列表加载失败：{environments.error.message}</div>}
    {catalog.isPending ? <LoadingPanel label="加载 Connector 目录" /> : catalog.error ? <ErrorPanel error={catalog.error} /> : <>
      <div className="connector-scope-note"><strong>{environmentId ? '指定 Environment' : '当前授权范围聚合'}</strong><span>{catalog.data.environmentId ?? '未限定 Environment'}</span></div>
      <div className="connector-grid">{catalog.data.connectors.map((item) => <ConnectorCard key={item.connector} item={item} />)}</div>
    </>}
  </section>
}

export function RunnersPage() {
  const [status, setStatus] = useState<'' | RunnerStatus>('')
  const [offset, setOffset] = useState(0)
  const query = useQuery({ ...runnersQuery({ status: status || undefined, limit: 50, offset }), placeholderData: keepPreviousData })
  if (query.error) return <ErrorPanel error={query.error} />

  const runners = query.data?.items ?? []
  const online = runners.filter((runner) => runner.status === 'online').length
  const leaseAtRisk = runners.filter((runner) => runner.status === 'online' && new Date(runner.leaseExpiresAt).getTime() - Date.now() < 30_000).length

  return <>
    <section className="page-heading"><div><span className="eyebrow">RUNNERS</span><h1>Runner / Connector</h1><p>只读查看 Runner 在线状态、版本、连接器能力与 Lease 健康度。</p></div><button onClick={() => void query.refetch()} disabled={query.isFetching}>{query.isFetching ? '正在刷新…' : '立即刷新'}</button></section>
    <section className="runner-safety-note"><span>只读管理边界</span><p>注册和心跳由 Runner 程序调用。浏览器不接收、不保存 Runner Token，也不模拟 Runner 身份。Runner 离线只表示“观测能力丢失”，不代表目标服务宕机。</p></section>
    <ConnectorCatalogPanel />
    <section className="runner-summary"><article><span>筛选总数</span><strong>{query.data?.totalCount ?? 0}</strong></article><article><span>本页在线</span><strong className="success-text">{online}</strong></article><article><span>本页租约即将到期</span><strong className={leaseAtRisk ? 'warn-text' : undefined}>{leaseAtRisk}</strong></article><label>状态筛选<select value={status} onChange={(event) => { setStatus(event.target.value as '' | RunnerStatus); setOffset(0) }}><option value="">全部状态</option><option value="online">在线</option><option value="offline">离线</option><option value="draining">排空中</option><option value="disabled">已禁用</option></select></label></section>
    <section className="panel"><div className="table-wrap"><table><thead><tr><th>Runner</th><th>状态</th><th>软件版本</th><th>能力</th><th>最后在线</th><th>Lease 到期</th><th>环境</th></tr></thead><tbody>{runners.length ? runners.map((runner) => <tr key={runner.id}><td><strong>{runner.name}</strong><span className="table-subline">{runner.id} · record v{runner.version}</span></td><td><span className={`badge runner-${runner.status}`}>{statusLabels[runner.status]}</span></td><td className="mono-cell">{runner.softwareVersion}</td><td><CapabilityList capabilities={runner.capabilities} /></td><td className="mono-cell">{formatDateTime(runner.lastSeenAt)}</td><td className={`mono-cell ${new Date(runner.leaseExpiresAt).getTime() <= Date.now() ? 'danger-text' : ''}`}>{formatDateTime(runner.leaseExpiresAt)}</td><td className="mono-cell">{runner.environmentId ?? '全局'}</td></tr>) : <tr><td colSpan={7} className="empty-table">没有符合当前状态的 Runner</td></tr>}</tbody></table></div>{query.data && <PaginationControls page={query.data} disabled={query.isFetching} onOffsetChange={setOffset} />}</section>
  </>
}
