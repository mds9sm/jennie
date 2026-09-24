import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Cloud, LogOut, GitBranch, Database } from 'lucide-react'
import SSOConnectModal from '../common/SSOConnectModal'
import NotificationBell from './NotificationBell'
import { useUser } from '../../context/UserContext'
import { usePillar } from '../../context/PillarContext'
import { useEnvironment } from '../../context/EnvironmentContext'
import { useAuth } from '../../context/AuthContext'
import { fetchJSON } from '../../api/client'

const PILLARS = [
  { id: '', name: 'All Pillars' },
  { id: 'onboard', name: 'Pillar 1: Onboard' },
  { id: 'trigger', name: 'Pillar 2: Trigger Return' },
  { id: 'content', name: 'Pillar 3: Makeable Content' },
  { id: 'matching', name: 'Pillar 4: Content Matching' },
  { id: 'design_make', name: 'Pillar 5: Design & Make' },
  { id: 'guided', name: 'Pillar 5A: Guided Flows' },
  { id: 'blank_canvas', name: 'Pillar 5B: Blank Canvas' },
  { id: 'platform', name: 'Data Platform' },
]

interface ConnectivityStatus {
  sso: Record<string, { connected: boolean; minutes_remaining?: number }>
  redshift: Record<string, { connected: boolean; method?: string | null }>
  git: { cloned: boolean; branch: string }
}

export default function Header() {
  const { pillar, setPillar } = usePillar()
  const { environment, setEnvironment } = useEnvironment()
  const { sessionId } = useAuth()
  const { user, logout, isAuthenticated } = useUser()
  const navigate = useNavigate()

  const [status, setStatus] = useState<ConnectivityStatus | null>(null)
  const [showSSOModal, setShowSSOModal] = useState<string | null>(null)
  const [ssoPromptShown, setSsoPromptShown] = useState(false)

  const poll = useCallback(() => {
    if (!sessionId) return
    fetchJSON<ConnectivityStatus>(`/connectivity?session_id=${sessionId}`)
      .then(setStatus)
      .catch(() => {})
  }, [sessionId])

  useEffect(() => {
    poll()
    const id = setInterval(poll, 30_000) // refresh every 30s
    return () => clearInterval(id)
  }, [poll])

  // Auto-prompt SSO if expired (once per session)
  useEffect(() => {
    if (!status || ssoPromptShown) return
    const npConnected = status?.sso?.np?.connected ?? false
    const prdConnected = status?.sso?.prd?.connected ?? false
    if (!npConnected && !prdConnected) {
      // Give the app a moment to load before prompting
      const timer = setTimeout(() => {
        setShowSSOModal('np')
        setSsoPromptShown(true)
      }, 2000)
      return () => clearTimeout(timer)
    }
  }, [status, ssoPromptShown])

  // Derived status
  const ssoNp = status?.sso?.np?.connected ?? false
  const ssoPrd = status?.sso?.prd?.connected ?? false
  const ssoAny = ssoNp || ssoPrd

  const rsNp = status?.redshift?.np?.connected ?? false
  const rsPrd = status?.redshift?.prd?.connected ?? false
  const rsAny = rsNp || rsPrd

  const gitCloned = status?.git?.cloned ?? false
  const gitBranch = status?.git?.branch ?? ''

  // Tooltip builders
  const ssoTitle = ssoAny
    ? `AWS SSO: ${ssoNp ? `NP ✓ (${status!.sso.np.minutes_remaining}m)` : 'NP ✗'} · ${ssoPrd ? `PRD ✓ (${status!.sso.prd.minutes_remaining}m)` : 'PRD ✗'}`
    : 'AWS SSO — not connected'

  const rsTitle = rsAny
    ? `Redshift: ${rsNp ? `NP ✓ (${status!.redshift.np.method})` : 'NP ✗'} · ${rsPrd ? `PRD ✓ (${status!.redshift.prd.method})` : 'PRD ✗'}`
    : 'Redshift — not connected'

  const gitTitle = gitCloned
    ? `Git: ${gitBranch}`
    : 'Git repo — not cloned'

  return (
    <header className="h-12 bg-white border-b border-gray-200 flex items-center justify-between px-4">
      {/* Left: logo + pillar */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 cursor-pointer" onClick={() => navigate('/')}>
          <img src="/logo.png" alt="Genie" className="h-7 w-7 rounded" />
          <h1 className="text-base font-bold text-gray-900 hidden sm:block">
            <span className="text-genie-600">the organization</span>.Data.<span className="text-genie-600">Genie</span>
          </h1>
        </div>

        <select
          value={pillar || ''}
          onChange={(e) => setPillar(e.target.value || null)}
          className="text-xs border border-gray-300 rounded px-2 py-1 bg-white focus:ring-genie-500"
        >
          {PILLARS.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>

      {/* Right: status icons + env + user */}
      <div className="flex items-center gap-2">
        {/* Connectivity icons */}
        <div className="flex items-center gap-1 mr-1">
          {/* AWS SSO — click opens connect modal if disconnected, Settings if connected */}
          <button
            onClick={() => ssoAny ? navigate('/settings?tab=connection') : setShowSSOModal('np')}
            className="relative p-1 rounded hover:bg-gray-100"
            title={ssoTitle}
          >
            <Cloud size={16} className={ssoAny ? 'text-green-500' : 'text-gray-300'} />
            {ssoAny && (
              <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-green-400 rounded-full border border-white" />
            )}
          </button>

          {/* Redshift */}
          <button
            onClick={() => navigate('/settings?tab=connection')}
            className="relative p-1 rounded hover:bg-gray-100"
            title={rsTitle}
          >
            <Database size={16} className={rsAny ? 'text-green-500' : 'text-gray-300'} />
            {rsAny && (
              <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-green-400 rounded-full border border-white" />
            )}
          </button>

          {/* Git */}
          <button
            onClick={() => navigate('/settings?tab=git')}
            className="relative p-1 rounded hover:bg-gray-100"
            title={gitTitle}
          >
            <GitBranch size={16} className={gitCloned ? 'text-green-500' : 'text-gray-300'} />
            {gitCloned && (
              <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-green-400 rounded-full border border-white" />
            )}
          </button>
        </div>

        {/* Notification bell */}
        <NotificationBell />

        {/* Environment toggle */}
        <button
          onClick={() => {
            if (environment === 'np') {
              if (window.confirm('Switch to PROD?')) setEnvironment('prd')
            } else {
              setEnvironment('np')
            }
          }}
          className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${
            environment === 'np' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
          }`}
        >
          {environment === 'np' ? 'NP' : 'PRD'}
        </button>

        {/* User */}
        {isAuthenticated ? (
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-gray-600 hidden md:inline">{user?.name}</span>
            <button onClick={logout} className="text-gray-400 hover:text-gray-600" title="Sign out">
              <LogOut size={14} />
            </button>
          </div>
        ) : (
          <button onClick={() => navigate('/login')}
            className="text-xs text-gray-500 hover:text-gray-700 px-2 py-1 rounded border border-gray-300">
            Sign In
          </button>
        )}
      </div>
      {/* SSO Connect Modal — auto-shown when expired, or on cloud icon click */}
      {showSSOModal && (
        <SSOConnectModal
          environment={showSSOModal}
          onClose={() => {
            setShowSSOModal(null)
            poll() // refresh status after modal closes
          }}
        />
      )}
    </header>
  )
}
