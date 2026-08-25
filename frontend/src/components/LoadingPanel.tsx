export function LoadingPanel({ label = '加载控制面数据' }: { label?: string }) {
  return <div className="loading-panel" role="status"><span className="spinner" />{label}…</div>
}

export function ErrorPanel({ error }: { error: Error }) {
  const forbidden = error instanceof ApiError && error.status === 403
  return <div className="error-panel" role="alert"><strong>{forbidden ? '权限不足' : '数据加载失败'}</strong><span>{forbidden ? `当前账号可能没有该 Environment 或功能的访问权限。${error.message}` : error.message}</span></div>
}
import { ApiError } from '../api/httpClient'
