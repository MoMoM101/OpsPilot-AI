import { apiConfig } from './config'
import type { AgentEventDto } from './contracts'
import { invalidateSession, requestAuth } from '../auth/authSession'

export interface ServerSentEvent {
  id: string
  type: string
  data: string
}

interface StreamOptions {
  incidentId: string
  lastEventId?: string
  signal: AbortSignal
  onOpen: () => void
  onEvent: (event: ServerSentEvent, data: AgentEventDto) => void
}

export class SseConnectionError extends Error {
  constructor(readonly kind: 'authentication' | 'permission' | 'network' | 'response', message: string, readonly status?: number) {
    super(message)
    this.name = 'SseConnectionError'
  }
}

export function createSseParser(onEvent: (event: ServerSentEvent) => void) {
  let buffer = ''

  const dispatch = (block: string) => {
    let id = ''
    let type = 'message'
    const data: string[] = []
    for (const line of block.split('\n')) {
      if (!line || line.startsWith(':')) continue
      const colon = line.indexOf(':')
      const field = colon < 0 ? line : line.slice(0, colon)
      let value = colon < 0 ? '' : line.slice(colon + 1)
      if (value.startsWith(' ')) value = value.slice(1)
      if (field === 'id' && !value.includes('\0')) id = value
      if (field === 'event') type = value
      if (field === 'data') data.push(value)
    }
    if (data.length) onEvent({ id, type, data: data.join('\n') })
  }

  return {
    push(chunk: string) {
      buffer = (buffer + chunk).replace(/\r\n/g, '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        dispatch(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
        boundary = buffer.indexOf('\n\n')
      }
    },
    finish() {
      if (buffer.trim()) dispatch(buffer)
      buffer = ''
    },
  }
}

export async function streamIncidentEvents(options: StreamOptions): Promise<void> {
  const headers = new Headers({ Accept: 'text/event-stream' })
  const auth = requestAuth(`/incidents/${options.incidentId}/stream`, 'GET')
  auth.headers.forEach((value, key) => headers.set(key, value))
  if (options.lastEventId !== undefined) headers.set('Last-Event-ID', options.lastEventId)
  let response: Response
  try {
    response = await fetch(`${apiConfig.baseUrl}/incidents/${encodeURIComponent(options.incidentId)}/stream`, {
      headers,
      credentials: auth.credentials,
      cache: 'no-store',
      signal: options.signal,
    })
  } catch (error) {
    if (options.signal.aborted) throw error
    throw new SseConnectionError('network', 'SSE 网络连接中断')
  }
  if (response.status === 401) {
    invalidateSession()
    throw new SseConnectionError('authentication', 'SSE 身份已失效，请重新登录。', 401)
  }
  if (response.status === 403) throw new SseConnectionError('permission', '当前角色或 Environment 范围无权订阅此 Incident。', 403)
  if (!response.ok) throw new SseConnectionError('response', `SSE 连接失败（HTTP ${response.status}）`, response.status)
  if (!response.body) throw new SseConnectionError('response', '浏览器未提供 SSE 响应流')

  options.onOpen()
  const parser = createSseParser((event) => {
    let data: AgentEventDto
    try {
      data = JSON.parse(event.data) as AgentEventDto
    } catch {
      return
    }
    options.onEvent(event, data)
  })
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      parser.push(decoder.decode(value, { stream: true }))
    }
    parser.push(decoder.decode())
    parser.finish()
  } finally {
    reader.releaseLock()
  }
}
