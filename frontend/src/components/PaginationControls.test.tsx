import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PaginationControls } from './PaginationControls'

afterEach(cleanup)

describe('PaginationControls', () => {
  it('enables next page from X-Total-Count even when the current array is short', () => {
    const onOffsetChange = vi.fn()
    render(<PaginationControls page={{ items: ['only-item'], totalCount: 100, limit: 25, offset: 0 }} onOffsetChange={onOffsetChange} />)

    const next = screen.getByRole('button', { name: '下一页' })
    expect(next).toBeEnabled()
    fireEvent.click(next)
    expect(onOffsetChange).toHaveBeenCalledWith(25)
  })

  it('disables next page when the header total is exhausted', () => {
    render(<PaginationControls page={{ items: Array.from({ length: 25 }), totalCount: 25, limit: 25, offset: 0 }} onOffsetChange={vi.fn()} />)
    expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled()
  })
})
