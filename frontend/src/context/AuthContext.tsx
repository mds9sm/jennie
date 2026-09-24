import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react'
import { fetchJSON } from '../api/client'

interface AuthState {
  np: { authenticated: boolean; role_name?: string; expires_in_minutes?: number }
  prd: { authenticated: boolean; role_name?: string; expires_in_minutes?: number }
}

interface AuthContextType {
  sessionId: string
  authState: AuthState
  refreshStatus: () => Promise<void>
  startSSO: (environment: string) => Promise<SSOStartResult>
  pollSSO: (deviceCode: string) => Promise<SSOPollResult>
}

interface SSOStartResult {
  device_code: string
  verification_uri_complete: string
  user_code: string
  expires_in: number
  interval: number
}

interface SSOPollResult {
  status: 'pending' | 'authenticated' | 'expired' | 'slow_down'
  message?: string
  environment?: string
  role_name?: string
  expires_in_minutes?: number
}

const AuthContext = createContext<AuthContextType | null>(null)

function getOrCreateSessionId(): string {
  let sid = localStorage.getItem('genie_session_id')
  if (!sid) {
    sid = crypto.randomUUID()
    localStorage.setItem('genie_session_id', sid)
  }
  return sid
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [sessionId] = useState(getOrCreateSessionId)
  const [authState, setAuthState] = useState<AuthState>({
    np: { authenticated: false },
    prd: { authenticated: false },
  })

  const refreshStatus = useCallback(async () => {
    try {
      const res = await fetchJSON<{ environments: AuthState }>(`/auth/sso/status?session_id=${sessionId}`)
      setAuthState(res.environments)
    } catch {
      // ignore — may not be in real mode
    }
  }, [sessionId])

  useEffect(() => {
    refreshStatus()
    const interval = setInterval(refreshStatus, 60000) // refresh every minute
    return () => clearInterval(interval)
  }, [refreshStatus])

  const startSSO = async (environment: string): Promise<SSOStartResult> => {
    return fetchJSON<SSOStartResult>('/auth/sso/start', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, environment }),
    })
  }

  const pollSSO = async (deviceCode: string): Promise<SSOPollResult> => {
    const result = await fetchJSON<SSOPollResult>('/auth/sso/poll', {
      method: 'POST',
      body: JSON.stringify({ device_code: deviceCode }),
    })
    if (result.status === 'authenticated') {
      await refreshStatus()
    }
    return result
  }

  return (
    <AuthContext.Provider value={{ sessionId, authState, refreshStatus, startSSO, pollSSO }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
