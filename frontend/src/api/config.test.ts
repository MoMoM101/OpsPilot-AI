import { describe, expect, it } from 'vitest'
import { apiConfig } from './config'

describe('development API defaults', () => {
  it('uses the same-origin API path so Vite and Nginx can proxy cookies reliably', () => {
    expect(apiConfig.baseUrl).toBe('/api/v1')
    expect(apiConfig.baseUrl).not.toMatch(/^https?:\/\//)
  })
})
