const storageKey = 'opspilot:action-create:idempotency-key'

function storage() {
  try { return window.sessionStorage } catch { return undefined }
}

function generate(): string {
  return `action-${Date.now()}-${crypto.randomUUID()}`
}

export function actionIdempotencyKey(): string {
  const existing = storage()?.getItem(storageKey)
  if (existing) return existing
  const created = generate()
  storage()?.setItem(storageKey, created)
  return created
}

export function replaceActionIdempotencyKey(): string {
  const created = generate()
  storage()?.setItem(storageKey, created)
  return created
}
