import { beforeEach, describe, expect, it, vi } from 'vitest'
import { actionIdempotencyKey, replaceActionIdempotencyKey } from './actionIdempotency'

describe('Action idempotency key', () => {
  beforeEach(() => window.sessionStorage.clear())

  it('persists and reuses the same key for retries', () => {
    vi.spyOn(crypto, 'randomUUID').mockReturnValue('00000000-0000-4000-8000-000000000001')
    const first = actionIdempotencyKey()
    expect(actionIdempotencyKey()).toBe(first)
    expect(first).toContain('00000000-0000-4000-8000-000000000001')
  })

  it('only creates a different key for an explicit new logical request', () => {
    vi.spyOn(crypto, 'randomUUID')
      .mockReturnValueOnce('00000000-0000-4000-8000-000000000001')
      .mockReturnValueOnce('00000000-0000-4000-8000-000000000002')
    const original = actionIdempotencyKey()
    const replacement = replaceActionIdempotencyKey()
    expect(replacement).not.toBe(original)
    expect(actionIdempotencyKey()).toBe(replacement)
  })
})
