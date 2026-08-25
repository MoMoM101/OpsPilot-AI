import { useState, type FormEvent } from 'react'
import { useAuth } from '../auth/AuthContext'

export function LoginPage() {
  const { loginWithBearer, loginWithSession } = useAuth()
  const [token, setToken] = useState('')
  const [mode, setMode] = useState<'session' | 'bearer'>('session')
  const [error, setError] = useState<string>()
  const [submitting, setSubmitting] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const value = token.trim()
    if (!value) return
    setSubmitting(true)
    setError(undefined)
    try {
      if (mode === 'session') await loginWithSession(value)
      else await loginWithBearer(value)
      setToken('')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '登录失败，请检查用户 Token。')
    } finally {
      setSubmitting(false)
    }
  }

  return <main className="login-page">
    <section className="login-card">
      <div className="login-brand"><div className="brand-mark">✦</div><div><strong>OpsPilot</strong><span>CONTROL PLANE ACCESS</span></div></div>
      <span className="eyebrow">IDENTITY REQUIRED</span><h1>登录运维控制台</h1><p>使用管理员分配的用户 Access Token 建立会话。不要输入 Control Plane Bootstrap Token 或 Runner Token。</p>
      <form onSubmit={submit}>
        <fieldset><legend>认证方式</legend><label><input type="radio" checked={mode === 'session'} onChange={() => setMode('session')} /> 安全会话（推荐）<small>Token 交换后由 HttpOnly Cookie 维持登录，前端不保留原 Token。</small></label><label><input type="radio" checked={mode === 'bearer'} onChange={() => setMode('bearer')} /> Alpha Bearer<small>仅保存在当前标签页的 sessionStorage，关闭标签页后失效。</small></label></fieldset>
        <label className="token-field">用户 Access Token<input type="password" autoComplete="off" value={token} onChange={(event) => setToken(event.target.value)} minLength={20} required placeholder="粘贴用户 Token" /></label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="primary-button" type="submit" disabled={submitting || token.trim().length < 20}>{submitting ? '正在验证身份…' : mode === 'session' ? '交换为安全会话' : '使用本标签页 Bearer'}</button>
      </form>
      <aside><strong>生产建议</strong><span>部署 OIDC + BFF，由服务端完成身份交换，并只向浏览器发放 HttpOnly Session Cookie。</span></aside>
    </section>
  </main>
}
