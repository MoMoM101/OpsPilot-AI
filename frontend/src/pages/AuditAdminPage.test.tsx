import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuditAdminPage } from './AuditAdminPage'

const auditMocks = vi.hoisted(() => ({ list: vi.fn() }))
vi.mock('../api/auditApi', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api/auditApi')>()), auditApi: auditMocks }))

afterEach(() => { cleanup(); auditMocks.list.mockReset() })

describe('Audit Admin page', () => {
  it('paginates by header total and resets offset when filters are applied', async () => {
    auditMocks.list.mockImplementation(async (filters: { limit: number; offset: number }) => ({ items: [], totalCount: 120, limit: filters.limit, offset: filters.offset }))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><AuditAdminPage /></QueryClientProvider>)

    fireEvent.click(await screen.findByRole('button', { name: '下一页' }))
    await waitFor(() => expect(auditMocks.list).toHaveBeenCalledWith(expect.objectContaining({ offset: 50 }), expect.anything()))

    fireEvent.change(screen.getByLabelText('Actor ID'), { target: { value: 'admin-1' } })
    fireEvent.click(screen.getByRole('button', { name: '应用筛选' }))

    await waitFor(() => expect(auditMocks.list).toHaveBeenCalledWith(expect.objectContaining({ actorId: 'admin-1', offset: 0 }), expect.anything()))
  })
})
