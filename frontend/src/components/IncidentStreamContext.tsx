import { createContext, useContext } from 'react'

interface IncidentStreamTarget {
  setRequestedIncidentId: (incidentId?: string) => void
}

export const IncidentStreamContext = createContext<IncidentStreamTarget | null>(null)

export function useIncidentStreamTarget() {
  const context = useContext(IncidentStreamContext)
  if (!context) throw new Error('IncidentStreamContext is missing')
  return context
}
