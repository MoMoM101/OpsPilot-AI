import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import { Suspense } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IncidentsPage } from './IncidentsPage'

const router = vi.hoisted(() => ({
  navigate: vi.fn(),
  search: {} as { status?: string; environment?: string; q?: string },
}))

vi.mock('@tanstack/react-router', () => ({
  Link: ({ children }: { children: React.ReactNode }) => <a href="#">{children}</a>,
  useNavigate: () => router.navigate,
  useSearch: () => router.search,
}))

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
  router.search = {}
})

function environment(index: number) {
  return {
    id: `env-${index}`,
    name: `环境 ${index}`,
    slug: `environment-${index}`,
    description: null,
    createdAt: '2026-08-25T00:00:00Z',
    updatedAt: '2026-08-25T00:00:00Z',
  }
}

describe('IncidentsPage Environment pagination', () => {
  it('keeps requests within the backend limit and loads Environment records after the first 100', async () => {
    const environmentRequests: URL[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname.endsWith('/environments')) {
        environmentRequests.push(url)
        const offset = Number(url.searchParams.get('offset'))
        const items = offset === 0
          ? Array.from({ length: 100 }, (_, index) => environment(index + 1))
          : [environment(101)]
        return new Response(JSON.stringify(items), {
          headers: {
            'Content-Type': 'application/json',
            'X-Total-Count': '101',
            'X-Limit': '100',
            'X-Offset': String(offset),
          },
        })
      }
      if (url.pathname.endsWith('/incidents')) {
        return new Response('[]', {
          headers: {
            'Content-Type': 'application/json',
            'X-Total-Count': '0',
            'X-Limit': '25',
            'X-Offset': '0',
          },
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    }))

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <Suspense fallback={<div>加载中</div>}><IncidentsPage /></Suspense>
      </QueryClientProvider>,
    )

    const environmentSelect = await screen.findByLabelText('环境')
    expect(within(environmentSelect).getByRole('option', { name: '环境 101 · environment-101' })).toBeInTheDocument()
    await waitFor(() => expect(environmentRequests).toHaveLength(2))
    expect(environmentRequests.map((url) => ({
      limit: url.searchParams.get('limit'),
      offset: url.searchParams.get('offset'),
    }))).toEqual([
      { limit: '100', offset: '0' },
      { limit: '100', offset: '100' },
    ])
    expect(environmentRequests.every((url) => Number(url.searchParams.get('limit')) <= 100)).toBe(true)
  })
})
