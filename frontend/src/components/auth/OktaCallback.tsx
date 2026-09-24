import { useState, useEffect, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { fetchJSON } from '../../api/client'
import { useUser } from '../../context/UserContext'
import { Loader2, Sparkles, ChevronDown } from 'lucide-react'
import RoleCapabilities from './RoleCapabilities'

const TEAMS = [
  'Data Engineering',
  'Data Analytics',
  'ML Engineering',
  'Marketing',
  'Product',
  'Other',
]

const PERSONAS = [
  { value: 'engineer', label: 'Data Engineer', desc: 'Build pipelines, manage transforms, optimize queries' },
  { value: 'analyst', label: 'Analyst', desc: 'Query data, build dashboards, define metrics' },
  { value: 'ml_engineer', label: 'ML Engineer', desc: 'Feature engineering, model pipelines, experiment tracking' },
  { value: 'executive', label: 'Executive', desc: 'High-level metrics, business impact, strategic questions' },
  { value: 'new_member', label: 'New Team Member', desc: 'Learning the platform, exploring data, onboarding' },
]

const PILLARS = [
  'Onboard',
  'Trigger Return',
  'Makeable Content',
  'Content Matching',
  'Design & Make',
  'Guided Flows',
  'Blank Canvas',
  'Marketing',
  'Platform',
]

interface CallbackResponse {
  token: string
  needs_onboarding: boolean
  user: {
    id: number
    email: string
    name: string
    role: string
    team?: string
    pillar?: string
    permissions: Record<string, boolean>
  }
}

export default function OktaCallback() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { login } = useUser()
  const exchanged = useRef(false)

  // Auth state
  const [status, setStatus] = useState<'exchanging' | 'onboarding' | 'done' | 'error'>('exchanging')
  const [error, setError] = useState('')
  const [authData, setAuthData] = useState<CallbackResponse | null>(null)

  // Onboarding form state
  const [name, setName] = useState('')
  const [team, setTeam] = useState('')
  const [persona, setPersona] = useState('engineer')
  const [pillar, setPillar] = useState('')
  const [showRoles, setShowRoles] = useState(false)
  const [onboardLoading, setOnboardLoading] = useState(false)

  useEffect(() => {
    if (exchanged.current) return
    exchanged.current = true

    const code = searchParams.get('code')
    const state = searchParams.get('state')

    if (!code || !state) {
      setError('Missing authorization code or state parameter')
      setStatus('error')
      return
    }

    exchangeCode(code, state)
  }, [searchParams])

  async function exchangeCode(code: string, state: string) {
    try {
      const res = await fetchJSON<CallbackResponse>('/okta/callback', {
        method: 'POST',
        body: JSON.stringify({ code, state }),
      })

      setAuthData(res)

      // Store token immediately
      localStorage.setItem('genie_auth_token', res.token)

      if (res.needs_onboarding) {
        setName(res.user.name || '')
        setStatus('onboarding')
      } else {
        // Fully logged in — reload to pick up user context
        setStatus('done')
        window.location.href = '/'
      }
    } catch (err: any) {
      setError(err?.message || 'Authentication failed')
      setStatus('error')
    }
  }

  async function handleOnboard(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim() || !team) return

    setOnboardLoading(true)
    try {
      await fetchJSON('/okta/onboard', {
        method: 'POST',
        body: JSON.stringify({
          name: name.trim(),
          team,
          persona,
          pillar,
        }),
      })
      // Done — redirect to app
      window.location.href = '/'
    } catch (err: any) {
      setError(err?.message || 'Onboarding failed')
    } finally {
      setOnboardLoading(false)
    }
  }

  // Exchanging code
  if (status === 'exchanging') {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <Loader2 size={32} className="animate-spin text-genie-600 mx-auto mb-4" />
          <p className="text-sm text-gray-600">Signing you in with Okta...</p>
        </div>
      </div>
    )
  }

  // Error
  if (status === 'error') {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8 max-w-sm w-full text-center">
          <div className="text-red-500 text-4xl mb-3">!</div>
          <h2 className="text-lg font-semibold text-gray-900 mb-2">Authentication Failed</h2>
          <p className="text-sm text-gray-600 mb-4">{error}</p>
          <button onClick={() => navigate('/login')}
            className="bg-genie-600 text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-genie-700">
            Back to Login
          </button>
        </div>
      </div>
    )
  }

  // Onboarding
  if (status === 'onboarding' && authData) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-genie-50 via-white to-blue-50 flex items-center justify-center p-4">
        <div className="w-full max-w-lg">
          {/* Welcome header */}
          <div className="text-center mb-6">
            <div className="inline-flex items-center gap-2 bg-genie-100 text-genie-700 rounded-full px-4 py-1.5 text-sm font-medium mb-4">
              <Sparkles size={16} />
              Welcome to Genie
            </div>
            <h1 className="text-2xl font-bold text-gray-900">
              Tell us about yourself
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              Help us personalize your experience. You can change these later in Settings.
            </p>
          </div>

          <form onSubmit={handleOnboard} className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 space-y-5">
            {/* Name */}
            <div>
              <label className="text-sm font-medium text-gray-700 block mb-1">
                Your name
              </label>
              <input type="text" value={name} onChange={e => setName(e.target.value)}
                placeholder="Full name" required autoFocus
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-genie-500 focus:border-genie-500" />
              <p className="text-[10px] text-gray-400 mt-0.5">
                Signed in as {authData.user.email}
              </p>
            </div>

            {/* Team */}
            <div>
              <label className="text-sm font-medium text-gray-700 block mb-1">
                Team <span className="text-red-400">*</span>
              </label>
              <select value={team} onChange={e => setTeam(e.target.value)} required
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-genie-500 focus:border-genie-500">
                <option value="">Select your team</option>
                {TEAMS.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>

            {/* Persona */}
            <div>
              <label className="text-sm font-medium text-gray-700 block mb-2">
                What describes your role best?
              </label>
              <div className="space-y-2">
                {PERSONAS.map(p => (
                  <label key={p.value}
                    className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                      persona === p.value
                        ? 'border-genie-400 bg-genie-50'
                        : 'border-gray-200 hover:border-gray-300'
                    }`}>
                    <input type="radio" name="persona" value={p.value}
                      checked={persona === p.value}
                      onChange={e => setPersona(e.target.value)}
                      className="mt-0.5 text-genie-600 focus:ring-genie-500" />
                    <div>
                      <span className="text-sm font-medium text-gray-800">{p.label}</span>
                      <p className="text-xs text-gray-500">{p.desc}</p>
                    </div>
                  </label>
                ))}
              </div>
            </div>

            {/* Pillar (optional) */}
            <div>
              <label className="text-sm font-medium text-gray-700 block mb-1">
                Pillar <span className="text-gray-400 font-normal">(optional)</span>
              </label>
              <select value={pillar} onChange={e => setPillar(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-genie-500 focus:border-genie-500">
                <option value="">None / All pillars</option>
                {PILLARS.map(p => <option key={p} value={p}>{p}</option>)}
              </select>
              <p className="text-[10px] text-gray-400 mt-0.5">
                Filter AI responses to your pillar's tables and metrics
              </p>
            </div>

            {/* Role capabilities (collapsible) */}
            <div className="border-t border-gray-100 pt-4">
              <button type="button" onClick={() => setShowRoles(!showRoles)}
                className="flex items-center gap-2 text-xs text-gray-500 hover:text-gray-700 font-medium w-full">
                <ChevronDown size={14} className={`transition-transform ${showRoles ? 'rotate-180' : ''}`} />
                See what each role can do
              </button>
              {showRoles && (
                <div className="mt-3">
                  <RoleCapabilities currentRole={authData.user.role} compact />
                  <p className="text-[10px] text-gray-400 mt-2">
                    You start as a <span className="font-medium">{authData.user.role}</span>.
                    You can request a role upgrade after onboarding.
                  </p>
                </div>
              )}
            </div>

            {error && (
              <div className="text-sm text-red-600 bg-red-50 rounded-lg p-2">{error}</div>
            )}

            <button type="submit" disabled={onboardLoading || !name.trim() || !team}
              className="w-full bg-genie-600 text-white rounded-lg py-2.5 text-sm font-medium hover:bg-genie-700 disabled:opacity-50 flex items-center justify-center gap-2">
              {onboardLoading ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
              Get Started
            </button>
          </form>
        </div>
      </div>
    )
  }

  // Done (should redirect, but just in case)
  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="text-center">
        <Loader2 size={32} className="animate-spin text-genie-600 mx-auto mb-4" />
        <p className="text-sm text-gray-600">Redirecting...</p>
      </div>
    </div>
  )
}
