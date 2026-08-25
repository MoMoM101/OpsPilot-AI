import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, useSyncExternalStore } from 'react'
import { apiConfig } from './config'
import { createEventIdDeduplicator, evidenceIdForAgentEvent, queryKeysForAgentEvent, saveLastEventId } from './incidentStream'
import { evidenceDetailQuery, incidentQuery, incidentTimelinePageQuery, INCIDENT_TIMELINE_PAGE_SIZE } from './queries'
import { SseConnectionError, streamIncidentEvents } from './sseClient'
import { authEpochSnapshot, subscribeAuthEpoch } from '../auth/authSession'

export type StreamState = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'error' | 'authentication_required' | 'forbidden'

export function useIncidentEventStream(incidentId?: string) {
  const queryClient = useQueryClient()
  const [state, setState] = useState<StreamState>('idle')
  const [lastEventAt, setLastEventAt] = useState<Date | null>(null)
  const authEpoch = useSyncExternalStore(subscribeAuthEpoch, authEpochSnapshot, authEpochSnapshot)

  useEffect(() => {
    if (!incidentId || apiConfig.mocksEnabled) {
      setState('idle')
      return
    }

    const controller = new AbortController()
    let retryAttempt = 0
    let retryTimer: number | undefined
    const eventIds = createEventIdDeduplicator()

    const connect = async () => {
      setState(retryAttempt ? 'reconnecting' : 'connecting')
      try {
        const snapshot = await queryClient.fetchQuery({
          ...incidentQuery(incidentId),
          staleTime: 0,
        })
        if (controller.signal.aborted) return
        const snapshotCursor = String(snapshot.eventCursor)
        saveLastEventId(incidentId, snapshotCursor)
        await streamIncidentEvents({
          incidentId,
          lastEventId: snapshotCursor,
          signal: controller.signal,
          onOpen: () => {
            retryAttempt = 0
            setState('connected')
          },
          onEvent: (frame, event) => {
            if (event.incidentId !== incidentId) return
            const eventId = frame.id || String(event.sequence)
            if (!eventIds.accept(eventId)) return
            saveLastEventId(incidentId, eventId)
            setLastEventAt(new Date(event.occurredAt))
            void queryClient.invalidateQueries({
              queryKey: incidentTimelinePageQuery(incidentId, { limit: INCIDENT_TIMELINE_PAGE_SIZE, offset: 0 }).queryKey,
              exact: true,
              refetchType: 'all',
            })
            for (const queryKey of queryKeysForAgentEvent(event)) {
              void queryClient.invalidateQueries({
                queryKey,
                exact: queryKey[0] !== 'plans' && queryKey[0] !== 'alerts' && queryKey[0] !== 'approvals' && queryKey[0] !== 'actions' && queryKey[0] !== 'compensations' && queryKey[0] !== 'resource-locks' && queryKey[0] !== 'hypotheses' && queryKey[0] !== 'investigation-runs' && queryKey[0] !== 'investigation-checkpoints' && queryKey[0] !== 'runners' && queryKey[0] !== 'runner-tasks' && queryKey[0] !== 'incident-evidence',
                refetchType: 'all',
              })
            }
            const evidenceId = evidenceIdForAgentEvent(event)
            if (evidenceId) void queryClient.fetchQuery(evidenceDetailQuery(evidenceId)).catch(() => undefined)
          },
        })
        if (controller.signal.aborted) return
        setState('reconnecting')
      } catch (error) {
        if (controller.signal.aborted) return
        if (error instanceof SseConnectionError && error.kind === 'authentication') {
          setState('authentication_required')
          return
        }
        if (error instanceof SseConnectionError && error.kind === 'permission') {
          setState('forbidden')
          return
        }
        setState('error')
      }

      retryAttempt += 1
      const delay = Math.min(1_000 * 2 ** (retryAttempt - 1), 30_000)
      retryTimer = window.setTimeout(() => void connect(), delay)
    }

    void connect()
    return () => {
      controller.abort()
      if (retryTimer !== undefined) window.clearTimeout(retryTimer)
    }
  }, [authEpoch, incidentId, queryClient])

  return { state, connected: state === 'connected', lastEventAt }
}
