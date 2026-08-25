import type { Runner } from '../domain/types'

export type LogOperation = 'file.tail' | 'journal.query'
export type ProbeOperation = 'http.probe' | 'tcp.probe'
export type PrometheusOperation = 'prometheus.query' | 'prometheus.query_range'

function declaredOperations(runners: Runner[]) {
  const operations = new Set<string>()
  for (const runner of runners) {
    if (runner.status !== 'online') continue
    for (const capability of runner.capabilities) {
      if (!Array.isArray(capability.observe)) continue
      for (const operation of capability.observe) operations.add(operation)
    }
  }
  return operations
}

export function availableLogOperations(runners: Runner[]): LogOperation[] {
  const operations = declaredOperations(runners)
  return (['file.tail', 'journal.query'] as const).filter((operation) => operations.has(operation))
}

export function availableProbeOperations(runners: Runner[]): ProbeOperation[] {
  const operations = declaredOperations(runners)
  return (['http.probe', 'tcp.probe'] as const).filter((operation) => operations.has(operation))
}

export function availablePrometheusOperations(runners: Runner[]): PrometheusOperation[] {
  const operations = declaredOperations(runners)
  return (['prometheus.query', 'prometheus.query_range'] as const).filter((operation) => operations.has(operation))
}

export function hostSnapshotAvailable(runners: Runner[]) {
  return declaredOperations(runners).has('host.snapshot')
}
