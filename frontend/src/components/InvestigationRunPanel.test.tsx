import { describe, expect, it } from 'vitest'
import { investigationPauseReason, investigationRunStatusLabel } from './InvestigationRunPanel'

describe('InvestigationRun status labels', () => {
  it.each([
    ['queued', '等待运行'], ['running', '运行中'], ['paused', '已暂停'], ['completed', '已完成'], ['failed', '运行失败'], ['cancelled', '已取消'],
  ] as const)('maps %s to %s', (status, label) => {
    expect(investigationRunStatusLabel(status)).toBe(label)
  })
})

describe('Investigation pause reason', () => {
  it('maps runtime stop actions from the latest Checkpoint', () => {
    expect(investigationPauseReason('no_progress')).toBe('连续无进展')
    expect(investigationPauseReason('max_iterations')).toBe('达到最大迭代次数')
    expect(investigationPauseReason('pause')).toBeUndefined()
  })
})
