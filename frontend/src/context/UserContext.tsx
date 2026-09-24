import React, { createContext, useContext, useState, useEffect } from 'react'
import { fetchJSON } from '../api/client'

interface User {
  id: number
  email: string
  name: string
  role: string
  pillar?: string
  team?: string
}

interface Permissions {
  [key: string]: boolean
}

interface UserContextType {
  user: User | null
  permissions: Permissions
  token: string
  isAuthenticated: boolean
  loading: boolean
  login: (email: string, password: string) => Promise<boolean>
  logout: () => void
  hasPermission: (perm: string) => boolean
}

const UserContext = createContext<UserContextType>({
  user: null,
  permissions: {},
  token: '',
  isAuthenticated: false,
  loading: true,
  login: async () => false,
  logout: () => {},
  hasPermission: () => true,
})

export function UserProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [permissions, setPermissions] = useState<Permissions>({})
  const [token, setToken] = useState(() => localStorage.getItem('genie_auth_token') || '')
  const [loading, setLoading] = useState(() => !!localStorage.getItem('genie_auth_token'))

  useEffect(() => {
    if (token) {
      setLoading(true)
      // Validate token on mount
      fetchJSON<{ authenticated: boolean; user?: User; permissions?: Permissions }>('/users/me', {
        headers: { 'X-Auth-Token': token },
      })
        .then(res => {
          if (res.authenticated && res.user) {
            setUser(res.user)
            setPermissions(res.permissions || {})
          } else {
            // Invalid token
            setToken('')
            localStorage.removeItem('genie_auth_token')
          }
        })
        .catch(() => {
          // API error — keep token, might be temporary
        })
        .finally(() => setLoading(false))
    }
  }, [token])

  async function login(email: string, password: string): Promise<boolean> {
    try {
      const res = await fetchJSON<{ token: string; user: { id: number; email: string; name: string; role: string; permissions: Permissions } }>('/users/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      })
      setToken(res.token)
      setUser(res.user)
      setPermissions(res.user.permissions || {})
      localStorage.setItem('genie_auth_token', res.token)
      return true
    } catch {
      return false
    }
  }

  function logout() {
    if (token) {
      fetchJSON('/users/logout', { method: 'POST', headers: { 'X-Auth-Token': token } }).catch(() => {})
    }
    setToken('')
    setUser(null)
    setPermissions({})
    localStorage.removeItem('genie_auth_token')
  }

  function hasPermission(perm: string): boolean {
    if (!user) return true  // unauthenticated = full access (backwards compatible until enforced)
    return permissions[perm] === true
  }

  return (
    <UserContext.Provider value={{ user, permissions, token, isAuthenticated: !!user, loading, login, logout, hasPermission }}>
      {children}
    </UserContext.Provider>
  )
}

export function useUser() {
  return useContext(UserContext)
}
