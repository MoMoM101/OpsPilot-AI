import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SetupPage } from './SetupPage'

const mocks = vi.hoisted(() => ({
  createInitialAdmin: vi.fn(),
  loginWithSession: vi.fn(),
  bootstrapAvailable: true,
}))

vi.mock('../api/setupApi', () => ({ setupApi: { createInitialAdmin: mocks.createInitialAdmin } }))
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({
    loginWithSession: mocks.loginWithSession,
    setupStatus: { status: 'initialization_required', bootstrapAvailable: mocks.bootstrapAvailable },
  }),
}))

beforeEach(() => {
  mocks.bootstrapAvailable = true
  mocks.createInitialAdmin.mockReset().mockResolvedValue({ accessToken: 'generated-admin-access-token-1234567890' })
  mocks.loginWithSession.mockReset().mockResolvedValue(undefined)
})
afterEach(() => cleanup())

describe('first Admin setup page', () => {
  it('creates the Admin and immediately exchanges its one-time token for a Session', async () => {
    render(<SetupPage />)
    fireEvent.change(screen.getByLabelText('Admin 名称'), { target: { value: 'platform-admin' } })
    fireEvent.change(screen.getByLabelText('Control Plane Bootstrap Token'), { target: { value: 'bootstrap-secret-token-1234567890' } })
    fireEvent.click(screen.getByRole('button', { name: '创建首个 Admin' }))

    await waitFor(() => expect(mocks.createInitialAdmin).toHaveBeenCalledWith('platform-admin', 'bootstrap-secret-token-1234567890'))
    await waitFor(() => expect(mocks.loginWithSession).toHaveBeenCalledWith('generated-admin-access-token-1234567890'))
    expect(mocks.createInitialAdmin.mock.invocationCallOrder[0]).toBeLessThan(mocks.loginWithSession.mock.invocationCallOrder[0])
    expect(screen.getByLabelText('Control Plane Bootstrap Token')).toHaveValue('')
  })

  it('does not render the secret form when bootstrap is unavailable', () => {
    mocks.bootstrapAvailable = false
    render(<SetupPage />)

    expect(screen.getByRole('alert')).toHaveTextContent('Bootstrap 不可用')
    expect(screen.queryByLabelText('Control Plane Bootstrap Token')).not.toBeInTheDocument()
  })
})
