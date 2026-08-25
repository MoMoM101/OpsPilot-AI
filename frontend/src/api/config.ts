const fallbackApiBaseUrl = '/api/v1'

export const apiConfig = {
  baseUrl: (import.meta.env.VITE_API_BASE_URL || fallbackApiBaseUrl).replace(/\/$/, ''),
  mocksEnabled: import.meta.env.VITE_ENABLE_MOCKS === 'true',
  csrfCookieName: import.meta.env.VITE_CSRF_COOKIE_NAME || 'opspilot_csrf',
}
