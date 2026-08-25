import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { RunnerTaskStatusBadge, runnerTaskStatusLabel } from './RunnerTaskStatusBadge'

describe('RunnerTaskStatusBadge', () => {
  it('distinguishes an initial queue from a lease-expiry requeue', () => {
    expect(runnerTaskStatusLabel('queued', 0)).toBe('排队中')
    render(<RunnerTaskStatusBadge status="queued" attempt={1} />)
    expect(screen.getByText('已重新排队')).toBeInTheDocument()
  })

  it('renders cancelled as a terminal task state', () => {
    render(<RunnerTaskStatusBadge status="cancelled" attempt={1} />)
    expect(screen.getByText('已取消')).toHaveClass('task-cancelled')
  })
})
