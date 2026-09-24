import { useState, useEffect } from 'react'
import { Loader2, ArrowLeft, Shield } from 'lucide-react'
import { useUser } from '../../context/UserContext'
import { fetchJSON } from '../../api/client'

interface OktaConfig {
  enabled: boolean
  issuer?: string
  client_id?: string
  redirect_uri?: string
}

export default function LoginPage() {
  const { login } = useUser()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [showRegister, setShowRegister] = useState(false)
  const [showForgot, setShowForgot] = useState(false)
  const [showPasswordLogin, setShowPasswordLogin] = useState(false)

  // Forgot-password form state
  const [forgotEmail, setForgotEmail] = useState('')
  const [forgotError, setForgotError] = useState('')
  const [forgotSuccess, setForgotSuccess] = useState('')
  const [forgotLoading, setForgotLoading] = useState(false)

  // Okta state
  const [oktaConfig, setOktaConfig] = useState<OktaConfig | null>(null)
  const [oktaLoading, setOktaLoading] = useState(true)
  const [oktaRedirecting, setOktaRedirecting] = useState(false)

  // Registration form state
  const [regEmail, setRegEmail] = useState('')
  const [regName, setRegName] = useState('')
  const [regTeam, setRegTeam] = useState('')
  const [regReason, setRegReason] = useState('')
  const [regError, setRegError] = useState('')
  const [regSuccess, setRegSuccess] = useState('')
  const [regLoading, setRegLoading] = useState(false)

  useEffect(() => {
    fetchJSON<OktaConfig>('/okta/config')
      .then(setOktaConfig)
      .catch(() => setOktaConfig({ enabled: false }))
      .finally(() => setOktaLoading(false))
  }, [])

  async function handleOktaLogin() {
    setOktaRedirecting(true)
    setError('')
    try {
      const res = await fetchJSON<{ authorize_url: string; state: string }>('/okta/authorize')
      // Store state for verification on return
      sessionStorage.setItem('okta_state', res.state)
      // Redirect to Okta
      window.location.href = res.authorize_url
    } catch (err: any) {
      setError(err?.message || 'Failed to start Okta login')
      setOktaRedirecting(false)
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError('')
    const ok = await login(email, password)
    if (!ok) setError('Invalid email or password')
    setLoading(false)
  }

  async function handleForgotPassword(e: React.FormEvent) {
    e.preventDefault()
    setForgotError('')
    setForgotSuccess('')

    const trimmedEmail = forgotEmail.trim().toLowerCase()
    if (!trimmedEmail || !trimmedEmail.includes('@')) {
      setForgotError('Enter a valid email address')
      return
    }

    setForgotLoading(true)
    try {
      const res = await fetchJSON<{ message: string }>('/users/forgot-password', {
        method: 'POST',
        body: JSON.stringify({ email: trimmedEmail }),
      })
      setForgotSuccess(
        res.message ||
        'If that email is registered, an admin will reset the password and share the new one with you.'
      )
    } catch (err: any) {
      const msg = err?.message || err?.detail || 'Could not submit request'
      setForgotError(typeof msg === 'string' ? msg : JSON.stringify(msg))
    } finally {
      setForgotLoading(false)
    }
  }

  function resetForgotForm() {
    setShowForgot(false)
    setForgotEmail('')
    setForgotError('')
    setForgotSuccess('')
  }

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault()
    setRegError('')
    setRegSuccess('')

    const trimmedEmail = regEmail.trim().toLowerCase()
    if (!trimmedEmail.endsWith('@example.com')) {
      setRegError('Email must be a @example.com address')
      return
    }
    if (!regName.trim()) {
      setRegError('Name is required')
      return
    }

    setRegLoading(true)
    try {
      const res = await fetchJSON<{ message: string }>('/users/register', {
        method: 'POST',
        body: JSON.stringify({
          email: trimmedEmail,
          name: regName.trim(),
          team: regTeam.trim() || null,
          reason: regReason.trim() || null,
        }),
      })
      setRegSuccess(res.message || 'Registration request submitted. An admin will review your request.')
      setRegEmail('')
      setRegName('')
      setRegTeam('')
      setRegReason('')
    } catch (err: any) {
      const msg = err?.message || err?.detail || 'Registration failed'
      setRegError(typeof msg === 'string' ? msg : JSON.stringify(msg))
    } finally {
      setRegLoading(false)
    }
  }

  const oktaEnabled = oktaConfig?.enabled === true

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <img src="/logo.png" alt="Genie" className="h-16 w-16 mx-auto mb-3 rounded-lg" />
          <h1 className="text-2xl font-bold text-gray-900">
            <span className="text-genie-600">the organization</span>.Data.<span className="text-genie-600">Genie</span>
          </h1>
          <p className="text-sm text-gray-500 mt-1">AI-powered data engineering platform</p>
        </div>

        {showForgot ? (
          <>
            <form onSubmit={handleForgotPassword} className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 space-y-4">
              <div className="flex items-center gap-2 mb-1">
                <button type="button" onClick={resetForgotForm}
                  className="text-gray-400 hover:text-gray-600">
                  <ArrowLeft size={16} />
                </button>
                <h2 className="text-sm font-semibold text-gray-900">Reset password</h2>
              </div>

              <p className="text-xs text-gray-500">
                Enter your account email. An admin will reset the password and share the
                new one with you over Slack or team chat — there's no email server.
              </p>

              <div>
                <label className="text-sm font-medium text-gray-700 block mb-1">
                  Email <span className="text-red-400">*</span>
                </label>
                <input type="email" value={forgotEmail} onChange={e => setForgotEmail(e.target.value)}
                  placeholder="you@example.com" autoFocus required
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-genie-500 focus:border-genie-500" />
              </div>

              {forgotError && <div className="text-sm text-red-600 bg-red-50 rounded-lg p-2">{forgotError}</div>}
              {forgotSuccess && <div className="text-sm text-green-700 bg-green-50 rounded-lg p-2">{forgotSuccess}</div>}

              {!forgotSuccess && (
                <button type="submit" disabled={forgotLoading || !forgotEmail}
                  className="w-full bg-genie-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-genie-700 disabled:opacity-50 flex items-center justify-center gap-2">
                  {forgotLoading ? <Loader2 size={16} className="animate-spin" /> : null}
                  Submit Request
                </button>
              )}
            </form>

            <p className="text-center text-xs text-gray-400 mt-4">
              <button onClick={resetForgotForm}
                className="text-genie-600 hover:text-genie-700 font-medium">
                Back to sign in
              </button>
            </p>
          </>
        ) : !showRegister ? (
          <>
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 space-y-4">
              {/* Okta SSO button (primary when configured) */}
              {oktaLoading ? (
                <div className="flex items-center justify-center py-3">
                  <Loader2 size={16} className="animate-spin text-gray-400" />
                </div>
              ) : oktaEnabled ? (
                <>
                  <button onClick={handleOktaLogin}
                    disabled={oktaRedirecting}
                    className="w-full bg-genie-600 text-white rounded-lg py-2.5 text-sm font-medium hover:bg-genie-700 disabled:opacity-50 flex items-center justify-center gap-2">
                    {oktaRedirecting ? (
                      <Loader2 size={16} className="animate-spin" />
                    ) : (
                      <Shield size={16} />
                    )}
                    Sign in with Okta
                  </button>

                  {!showPasswordLogin && (
                    <div className="text-center">
                      <button onClick={() => setShowPasswordLogin(true)}
                        className="text-xs text-gray-400 hover:text-gray-600">
                        Use password instead
                      </button>
                    </div>
                  )}

                  {showPasswordLogin && (
                    <>
                      <div className="relative">
                        <div className="absolute inset-0 flex items-center">
                          <div className="w-full border-t border-gray-200" />
                        </div>
                        <div className="relative flex justify-center text-xs">
                          <span className="bg-white px-2 text-gray-400">or</span>
                        </div>
                      </div>
                    </>
                  )}
                </>
              ) : null}

              {/* Password login form — shown if Okta not configured, or user chose password */}
              {(!oktaEnabled || showPasswordLogin) && !oktaLoading && (
                <form onSubmit={handleSubmit} className="space-y-4">
                  <div>
                    <label className="text-sm font-medium text-gray-700 block mb-1">Email</label>
                    <input type="email" value={email} onChange={e => setEmail(e.target.value)}
                      placeholder="you@example.com" autoFocus={!oktaEnabled} required
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-genie-500 focus:border-genie-500" />
                  </div>
                  <div>
                    <div className="flex items-baseline justify-between mb-1">
                      <label className="text-sm font-medium text-gray-700">Password</label>
                      <button type="button" onClick={() => { setShowForgot(true); setError('') }}
                        className="text-xs text-genie-600 hover:text-genie-700">
                        Forgot password?
                      </button>
                    </div>
                    <input type="password" value={password} onChange={e => setPassword(e.target.value)}
                      placeholder="Password" required
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-genie-500 focus:border-genie-500" />
                  </div>

                  {error && <div className="text-sm text-red-600 bg-red-50 rounded-lg p-2">{error}</div>}

                  <button type="submit" disabled={loading || !email || !password}
                    className="w-full bg-genie-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-genie-700 disabled:opacity-50 flex items-center justify-center gap-2">
                    {loading ? <Loader2 size={16} className="animate-spin" /> : null}
                    Sign In
                  </button>
                </form>
              )}

              {/* Show Okta error outside form */}
              {oktaEnabled && !showPasswordLogin && error && (
                <div className="text-sm text-red-600 bg-red-50 rounded-lg p-2">{error}</div>
              )}
            </div>

            <p className="text-center text-xs text-gray-400 mt-4">
              Don't have an account?{' '}
              <button onClick={() => { setShowRegister(true); setError('') }}
                className="text-genie-600 hover:text-genie-700 font-medium">
                Request Access
              </button>
            </p>
          </>
        ) : (
          <>
            <form onSubmit={handleRegister} className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 space-y-4">
              <div className="flex items-center gap-2 mb-1">
                <button type="button" onClick={() => { setShowRegister(false); setRegError(''); setRegSuccess('') }}
                  className="text-gray-400 hover:text-gray-600">
                  <ArrowLeft size={16} />
                </button>
                <h2 className="text-sm font-semibold text-gray-900">Request Access</h2>
              </div>

              <div>
                <label className="text-sm font-medium text-gray-700 block mb-1">Email <span className="text-red-400">*</span></label>
                <input type="email" value={regEmail} onChange={e => setRegEmail(e.target.value)}
                  placeholder="you@example.com" autoFocus required
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-genie-500 focus:border-genie-500" />
                <p className="text-[10px] text-gray-400 mt-0.5">Must be a @example.com email</p>
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700 block mb-1">Name <span className="text-red-400">*</span></label>
                <input type="text" value={regName} onChange={e => setRegName(e.target.value)}
                  placeholder="Full name" required
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-genie-500 focus:border-genie-500" />
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700 block mb-1">Team</label>
                <input type="text" value={regTeam} onChange={e => setRegTeam(e.target.value)}
                  placeholder="e.g., Data Engineering, Analytics"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-genie-500 focus:border-genie-500" />
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700 block mb-1">Why do you need access?</label>
                <textarea value={regReason} onChange={e => setRegReason(e.target.value)}
                  placeholder="Brief description of your use case"
                  rows={2}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-genie-500 focus:border-genie-500 resize-none" />
              </div>

              {regError && <div className="text-sm text-red-600 bg-red-50 rounded-lg p-2">{regError}</div>}
              {regSuccess && <div className="text-sm text-green-700 bg-green-50 rounded-lg p-2">{regSuccess}</div>}

              {!regSuccess && (
                <button type="submit" disabled={regLoading || !regEmail || !regName}
                  className="w-full bg-genie-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-genie-700 disabled:opacity-50 flex items-center justify-center gap-2">
                  {regLoading ? <Loader2 size={16} className="animate-spin" /> : null}
                  Submit Request
                </button>
              )}
            </form>

            <p className="text-center text-xs text-gray-400 mt-4">
              Already have an account?{' '}
              <button onClick={() => { setShowRegister(false); setRegError(''); setRegSuccess('') }}
                className="text-genie-600 hover:text-genie-700 font-medium">
                Sign In
              </button>
            </p>
          </>
        )}
      </div>
    </div>
  )
}
