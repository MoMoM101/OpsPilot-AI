import type { Evidence } from '../domain/types'

interface HostPlatform {
  system?: string
  release?: string
  machine?: string
  hostname?: string
  pythonVersion?: string
}

interface HostCpu {
  logicalCount?: number | null
  loadAverage?: number[]
}

interface HostMemory {
  totalBytes?: number
  availableBytes?: number
  usedBytes?: number
  usedPercent?: number
}

interface HostDisk {
  root?: string
  totalBytes?: number
  usedBytes?: number
  freeBytes?: number
  usedPercent?: number
}

export interface HostNetworkCounter {
  interface?: string
  receiveBytes?: number
  receivePackets?: number
  transmitBytes?: number
  transmitPackets?: number
}

export interface HostSnapshot {
  schemaVersion?: string
  collectedAtUnix?: number
  platform?: HostPlatform
  cpu?: HostCpu
  memory?: HostMemory
  disk?: HostDisk
  uptimeSeconds?: number
  network?: HostNetworkCounter[]
  processCount?: number
}

export function parseHostSnapshot(evidence: Evidence): HostSnapshot | undefined {
  if (evidence.data.operation !== 'host.snapshot' || typeof evidence.data.content !== 'string') return undefined
  try {
    const parsed = JSON.parse(evidence.data.content) as unknown
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as HostSnapshot : undefined
  } catch {
    return undefined
  }
}

export function formatBytes(value?: number) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '未提供'
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let amount = value
  let unit = 0
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024
    unit += 1
  }
  return `${amount.toFixed(unit ? 1 : 0)} ${units[unit]}`
}

export function formatDuration(value?: number) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '未提供'
  const days = Math.floor(value / 86_400)
  const hours = Math.floor(value % 86_400 / 3_600)
  const minutes = Math.floor(value % 3_600 / 60)
  return `${days ? `${days}天 ` : ''}${hours}小时 ${minutes}分钟`
}
