import type { PaginatedResult } from '../api/httpClient'

export function PaginationControls<T>({ page, onOffsetChange, disabled = false }: { page: PaginatedResult<T>; onOffsetChange: (offset: number) => void; disabled?: boolean }) {
  const from = page.totalCount === 0 ? 0 : page.offset + 1
  const to = Math.min(page.offset + page.items.length, page.totalCount)
  const hasPrevious = page.offset > 0
  const hasNext = page.offset + page.limit < page.totalCount
  return <nav className="pagination-controls" aria-label="列表分页"><span>第 {from}–{to} 条，共 {page.totalCount} 条</span><div><button type="button" disabled={disabled || !hasPrevious} onClick={() => onOffsetChange(Math.max(0, page.offset - page.limit))}>上一页</button><button type="button" disabled={disabled || !hasNext} onClick={() => onOffsetChange(page.offset + page.limit)}>下一页</button></div></nav>
}
