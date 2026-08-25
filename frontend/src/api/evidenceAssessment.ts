import type { Evidence } from '../domain/types'

export interface EvidenceAssessment {
  state: 'healthy' | 'unhealthy' | 'unknown' | 'not_probe'
  label: string
  detail?: string
}

function contentPayload(evidence: Evidence): Record<string, unknown> | undefined {
  const content = evidence.data.content
  if (typeof content !== 'string') return undefined
  try {
    const parsed = JSON.parse(content) as unknown
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as Record<string, unknown> : undefined
  } catch {
    return undefined
  }
}

export function assessEvidence(evidence: Evidence): EvidenceAssessment {
  const operation = evidence.data.operation
  if (operation !== 'http.probe' && operation !== 'tcp.probe') return { state: 'not_probe', label: '非探测证据' }
  const payload = contentPayload(evidence)
  if (!payload) return { state: 'unknown', label: '无法解析健康数据', detail: evidence.summary }
  if (operation === 'http.probe' && typeof payload.healthy === 'boolean') {
    return {
      state: payload.healthy ? 'healthy' : 'unhealthy',
      label: payload.healthy ? '目标健康' : '目标不健康',
      detail: `HTTP ${String(payload.statusCode ?? '不可达')} · ${String(payload.latencyMs ?? '—')} ms`,
    }
  }
  if (operation === 'tcp.probe' && typeof payload.reachable === 'boolean') {
    return {
      state: payload.reachable ? 'healthy' : 'unhealthy',
      label: payload.reachable ? '目标可达' : '目标不可达',
      detail: `${String(payload.latencyMs ?? '—')} ms`,
    }
  }
  return { state: 'unknown', label: '健康状态未知', detail: evidence.summary }
}

export function evidenceIsTruncated(evidence: Evidence) {
  return evidenceResultIsCropped(evidence)
}

export interface EvidenceCropFlags {
  outputTruncated: boolean
  seriesTruncated: boolean
  samplesTruncated: boolean
}

export function evidenceCropFlags(evidence: Evidence): EvidenceCropFlags {
  const payload = contentPayload(evidence)
  const result = payload?.data && typeof payload.data === 'object' && !Array.isArray(payload.data)
    ? (payload.data as Record<string, unknown>).result
    : undefined
  const series = Array.isArray(result) ? result : []
  return {
    outputTruncated: evidence.data.outputTruncated === true,
    seriesTruncated: evidence.data.seriesTruncated === true || payload?.seriesTruncated === true,
    samplesTruncated: evidence.data.samplesTruncated === true || series.some((item) => item && typeof item === 'object' && (item as Record<string, unknown>).samplesTruncated === true),
  }
}

export function evidenceResultIsCropped(evidence: Evidence) {
  return Object.values(evidenceCropFlags(evidence)).some(Boolean)
}
