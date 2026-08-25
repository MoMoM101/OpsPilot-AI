import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { IncidentStatusBadge, ObservabilityBadge } from './StatusBadge'

describe('IncidentStatusBadge', () => {
  it('renders the localized incident status', () => {
    render(<IncidentStatusBadge status="WAITING_APPROVAL" />)
    expect(screen.getByText('待审批')).toBeInTheDocument()
  })

  it('renders backend terminal and degraded states', () => {
    const { rerender } = render(<IncidentStatusBadge status="OBSERVABILITY_LOST" />)
    expect(screen.getByText('观测能力丢失')).toBeInTheDocument()
    rerender(<IncidentStatusBadge status="MITIGATED_NOT_RESOLVED" />)
    expect(screen.getByText('已缓解')).toBeInTheDocument()
  })
})

describe('ObservabilityBadge', () => {
  it('uses observation-loss wording without inferring a service outage', () => {
    render(<ObservabilityBadge status="lost" />)
    expect(screen.getByText('观测能力丢失')).toBeInTheDocument()
    expect(screen.queryByText('目标服务宕机')).not.toBeInTheDocument()
  })
})
