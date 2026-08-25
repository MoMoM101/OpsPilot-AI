import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { router } from './app/router'
import './styles/global.css'
import './styles/safety.css'
import './styles/fault-lab.css'
import './styles/system.css'
import { AuthProvider } from './auth/AuthContext'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
})

const root = document.getElementById('root')
if (!root) throw new Error('Root element is missing')

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}><AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider></QueryClientProvider>
  </StrictMode>,
)
