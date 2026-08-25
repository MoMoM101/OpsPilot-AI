import { useState, type FormEvent } from 'react'
import { setupApi } from '../api/setupApi'
import { useAuth } from '../auth/AuthContext'

export function SetupPage() {
  const { loginWithSession, setupStatus } = useAuth()
  const [name, setName] = useState('admin')
  const [bootstrapToken, setBootstrapToken] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string>()

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const adminName = name.trim()
    const token = bootstrapToken.trim()
    if (!adminName || token.length < 20) return
    setSubmitting(true)
    setError(undefined)
    try {
      const admin = await setupApi.createInitialAdmin(adminName, token)
      setBootstrapToken('')
      await loginWithSession(admin.accessToken)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '初始化失败，请检查 Bootstrap Token 和服务状态。')
    } finally {
      setSubmitting(false)
    }
  }

  return <main className="login-page setup-page">
    <section className="login-card setup-card">
      <div className="login-brand"><div className="brand-mark">✦</div><div><strong>OpsPilot</strong><span>FIRST-RUN INITIALIZATION</span></div></div>
      <span className="eyebrow">INITIAL ADMIN REQUIRED</span><h1>初始化控制面</h1><p>创建首个拥有全部 Environment 权限的用户 Admin。该流程只能成功执行一次。</p>
      {!setupStatus?.bootstrapAvailable ? <div className="setup-blocked" role="alert"><strong>Bootstrap 不可用</strong><span>服务端未配置 Bootstrap Token，无法从浏览器完成首次初始化。请由部署管理员检查服务配置。</span></div> : <form onSubmit={submit}>
        <label className="token-field">Admin 名称<input value={name} onChange={(event) => setName(event.target.value)} maxLength={100} required autoFocus placeholder="例如 ops-admin" /></label>
        <label className="token-field">Control Plane Bootstrap Token<input type="password" autoComplete="new-password" value={bootstrapToken} onChange={(event) => setBootstrapToken(event.target.value)} minLength={20} required placeholder="仅用于本次初始化请求" /></label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="primary-button" type="submit" disabled={submitting || !name.trim() || bootstrapToken.trim().length < 20}>{submitting ? '正在创建并建立 Session…' : '创建首个 Admin'}</button>
      </form>}
      <aside><strong>密钥处理</strong><span>Bootstrap Token 只放入创建请求的 Authorization Header，不写入浏览器存储。创建成功后，前端立即用新 Admin Token 交换 HttpOnly Cookie Session，不展示或保存该 Token。</span></aside>
    </section>
  </main>
}
