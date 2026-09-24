import { useState, useEffect, useRef } from 'react'
import { Cloud, CloudOff, RefreshCw, Loader2, Database, CheckCircle, BarChart3, GitBranch } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { fetchJSON } from '../../api/client'
import SSOConnectModal from '../common/SSOConnectModal'
import type { UserSettings } from './SettingsPage'

interface Props {
  settings?: UserSettings
  onUpdate?: (partial: Partial<UserSettings>) => void
}

export default function ConnectionTab({ settings, onUpdate }: Props) {
  const { sessionId, authState } = useAuth()
  const [showSSOModal, setShowSSOModal] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<Record<string, { status: string; user?: string; error?: string }>>({})
  const [testing, setTesting] = useState<string | null>(null)

  async function testConnection(env: string) {
    setTesting(env)
    try {
      const res = await fetchJSON<{ status: string; user?: string; database?: string; error?: string }>(
        `/redshift/test/${env}?session_id=${sessionId}`
      )
      setTestResult((prev) => ({ ...prev, [env]: res }))
    } catch (err) {
      setTestResult((prev) => ({
        ...prev,
        [env]: { status: 'error', error: err instanceof Error ? err.message : 'Failed' },
      }))
    } finally {
      setTesting(null)
    }
  }

  const envs = [
    { id: 'np', label: 'Nonprod', account: '111111111111', role: 'DataNonProdReadRole', cluster: 'nonprod-redshift-cluster' },
    { id: 'prd', label: 'Prod', account: '222222222222', role: 'DataProdReadOnlyRole', cluster: 'prod-redshift-cluster' },
  ]

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h3 className="text-base font-medium text-gray-900 mb-1">AWS & Redshift Connections</h3>
        <p className="text-sm text-gray-500 mb-4">
          Authenticate via AWS SSO to query Redshift. Each user connects independently with their own IAM role.
        </p>
      </div>

      {/* Environment Cards */}
      {envs.map((env) => {
        const auth = env.id === 'prd' ? authState.prd : authState.np
        const test = testResult[env.id]

        return (
          <div key={env.id} className="border border-gray-200 rounded-lg p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                {auth?.authenticated ? (
                  <Cloud size={18} className="text-green-500" />
                ) : (
                  <CloudOff size={18} className="text-gray-400" />
                )}
                <h4 className="font-medium text-gray-900">{env.label}</h4>
                {auth?.authenticated && (
                  <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">
                    Connected ({auth.expires_in_minutes}m)
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => testConnection(env.id)}
                  disabled={testing === env.id}
                  className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1"
                >
                  {testing === env.id ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                  Test
                </button>
                <button
                  onClick={() => setShowSSOModal(env.id)}
                  className={`text-sm px-3 py-1.5 rounded-lg font-medium ${
                    auth?.authenticated
                      ? 'border border-gray-300 text-gray-600 hover:bg-gray-50'
                      : 'bg-genie-600 text-white hover:bg-genie-700'
                  }`}
                >
                  {auth?.authenticated ? 'Reconnect' : 'Connect SSO'}
                </button>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3 text-xs text-gray-500">
              <div>
                <span className="block text-gray-400">Account</span>
                <span className="font-mono">{env.account}</span>
              </div>
              <div>
                <span className="block text-gray-400">IAM Role</span>
                <span className="font-mono">{env.role}</span>
              </div>
              <div>
                <span className="block text-gray-400">Cluster</span>
                <span className="font-mono">{env.cluster}</span>
              </div>
            </div>

            {/* Test Result */}
            {test && (
              <div className={`mt-3 text-xs rounded-md p-2 ${
                test.status === 'connected' ? 'bg-green-50 text-green-700'
                  : test.status === 'mock' ? 'bg-yellow-50 text-yellow-700'
                  : 'bg-red-50 text-red-700'
              }`}>
                {test.status === 'connected' && `Connected as ${test.user}`}
                {test.status === 'mock' && 'Running in mock mode — set REDSHIFT_MODE=real to connect'}
                {test.status === 'error' && `Error: ${test.error}`}
              </div>
            )}
          </div>
        )
      })}

      {/* Redshift from Airflow — removed: direct credentials form now handles host/port/db */}

      {/* DOMO Connection */}
      {/* GitHub Token */}
      <GitHubConnection />

      <DomoConnection />

      {/* Statsig Connection */}
      <StatsigConnection />

      {/* AI Provider removed — using SSO + Bedrock only */}

      {/* Redshift Credentials */}
      <div className="border border-gray-200 rounded-lg p-4">
        <div className="flex items-center gap-2 mb-2">
          <Database size={18} className="text-gray-400" />
          <h4 className="font-medium text-gray-900">Redshift Credentials</h4>
        </div>

        {/* Tabs: Direct / Okta SAML */}
        <RedshiftAuthTabs />
      </div>

      {/* Default Environment & Auto Route — only in Settings context */}
      {settings && onUpdate && (
        <>
          <div>
            <h4 className="text-sm font-medium text-gray-700 mb-2">Default Query Environment</h4>
            <div className="flex gap-3">
              {['np', 'prd'].map((env) => (
                <label key={env} className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="default_env"
                    checked={settings.redshift_config?.default_environment === env}
                    onChange={() =>
                      onUpdate({
                        redshift_config: { ...settings.redshift_config, default_environment: env },
                      })
                    }
                    className="text-genie-600 focus:ring-genie-500"
                  />
                  <span className="text-sm text-gray-700">{env === 'np' ? 'Nonprod (recommended)' : 'Prod'}</span>
                </label>
              ))}
            </div>
          </div>

          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={settings.redshift_config?.auto_route_prod}
              onChange={(e) =>
                onUpdate({
                  redshift_config: { ...settings.redshift_config, auto_route_prod: e.target.checked },
                })
              }
              className="mt-0.5 text-genie-600 focus:ring-genie-500 rounded"
            />
            <div>
              <span className="text-sm font-medium text-gray-700">Auto-route to prod when needed</span>
              <p className="text-xs text-gray-500 mt-0.5">
                Automatically use prod for MWAA logs, EXPLAIN plans, data profiling, and S3 reads.
              </p>
            </div>
          </label>
        </>
      )}

      {/* SSO Modal */}
      {showSSOModal && (
        <SSOConnectModal environment={showSSOModal} onClose={() => setShowSSOModal(null)} />
      )}
    </div>
  )
}

function RedshiftAuthTabs() {
  const [mode, setMode] = useState<'direct' | 'okta'>('direct')

  return (
    <div>
      <div className="flex gap-1 mb-3">
        {[
          { id: 'direct' as const, label: 'Direct Credentials' },
          { id: 'okta' as const, label: 'Okta SAML' },
        ].map(t => (
          <button key={t.id} onClick={() => setMode(t.id)}
            className={`px-3 py-1 text-xs rounded ${mode === t.id ? 'bg-genie-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {mode === 'direct' && (
        <div>
          <p className="text-xs text-gray-500 mb-3">
            Direct username/password. Stored encrypted in postgres — never sent to Claude or logged.
          </p>
          <RedshiftCredsForm env="np" label="Nonprod" />
          <RedshiftCredsForm env="prd" label="Prod" />
        </div>
      )}

      {mode === 'okta' && (
        <div>
          <p className="text-xs text-gray-500 mb-3">
            Okta SAML — same credentials as DataGrip. Uses Okta login to get Redshift access via IAM.
          </p>
          <OktaConnectForm />
        </div>
      )}
    </div>
  )
}

function RedshiftCredsForm({ env, label }: { env: string; label: string }) {
  const { sessionId } = useAuth()
  const [host, setHost] = useState('')
  const [port, setPort] = useState(5439)
  const [database, setDatabase] = useState('dev')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState<{ status: string; user?: string; error?: string } | null>(null)
  const [hasStored, setHasStored] = useState(false)

  useEffect(() => {
    fetchJSON<{ stored: boolean; user?: string; host?: string; port?: number; database?: string }>(
      `/auth/redshift/status?session_id=${sessionId}&environment=${env}`
    ).then(r => {
      setHasStored(r.stored)
      if (r.user) setUsername(r.user)
      if (r.host) setHost(r.host)
      if (r.port) setPort(r.port)
      if (r.database) setDatabase(r.database)
    }).catch(() => {})
  }, [sessionId, env])

  async function handleSave() {
    setSaving(true)
    setResult(null)
    try {
      const res = await fetchJSON<{ status: string; user?: string; error?: string }>('/auth/redshift/credentials', {
        method: 'POST',
        body: JSON.stringify({ session_id: sessionId, environment: env, host, port, database, username, password }),
      })
      setResult(res)
      if (res.status === 'connected') { setPassword(''); setHasStored(true) }
    } catch (err) {
      setResult({ status: 'error', error: err instanceof Error ? err.message : 'Failed' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mb-4">
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-xs font-medium text-gray-700 w-16">{label}</span>
        {hasStored && !result && (
          <span className="text-[10px] bg-green-100 text-green-700 px-1.5 py-0.5 rounded-full flex items-center gap-0.5">
            <CheckCircle size={8} /> stored
          </span>
        )}
      </div>
      <div className="space-y-1.5">
        <div className="flex gap-2">
          <input type="text" value={host} onChange={e => setHost(e.target.value)}
            placeholder="Host (e.g., cluster.xxx.us-west-2.redshift.amazonaws.com)" autoComplete="off"
            className="flex-[3] text-sm border border-gray-300 rounded-lg px-3 py-1.5 font-mono" />
          <input type="number" value={port} onChange={e => setPort(Number(e.target.value))}
            placeholder="Port"
            className="w-20 text-sm border border-gray-300 rounded-lg px-3 py-1.5 font-mono" />
          <input type="text" value={database} onChange={e => setDatabase(e.target.value)}
            placeholder="Database"
            className="w-24 text-sm border border-gray-300 rounded-lg px-3 py-1.5 font-mono" />
        </div>
        <div className="flex gap-2">
          <input type="text" value={username} onChange={e => setUsername(e.target.value)}
            placeholder="Username" autoComplete="off"
            className="flex-1 text-sm border border-gray-300 rounded-lg px-3 py-1.5" />
          <input type="password" value={password} onChange={e => setPassword(e.target.value)}
            placeholder={hasStored ? '••••••• (stored)' : 'Password'} autoComplete="new-password"
            className="flex-1 text-sm border border-gray-300 rounded-lg px-3 py-1.5" />
          <button onClick={handleSave} disabled={saving || !username || !password || !host}
            className="px-3 py-1.5 text-sm rounded-lg bg-genie-600 text-white hover:bg-genie-700 disabled:opacity-50 flex items-center gap-1 whitespace-nowrap">
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Database size={14} />}
            Save & Test
          </button>
        </div>
      </div>
      {result && (
        <div className={`text-xs rounded-md p-1.5 mt-1 ${
          result.status === 'connected' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
        }`}>
          {result.status === 'connected' ? `Connected as ${result.user}` : `${result.error}`}
        </div>
      )}
    </div>
  )
}

function AIProviderToggle() {
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [switching, setSwitching] = useState(false)

  useEffect(() => {
    fetchJSON<{ provider: string; model: string }>('/auth/ai/provider')
      .then(r => { setProvider(r.provider); setModel(r.model) })
      .catch(() => {})
  }, [])

  async function switchProvider(p: string) {
    setSwitching(true)
    try {
      const res = await fetchJSON<{ provider: string; model: string }>('/auth/ai/provider', {
        method: 'POST',
        body: JSON.stringify({ provider: p }),
      })
      setProvider(res.provider)
      setModel(res.model)
    } catch (err) {
      alert('Failed: ' + (err instanceof Error ? err.message : 'Unknown'))
    } finally {
      setSwitching(false)
    }
  }

  return (
    <div className="border border-gray-200 rounded-lg p-4">
      <h4 className="font-medium text-gray-900 mb-2">AI Provider</h4>
      <div className="flex gap-2">
        {[
          { id: 'anthropic', label: 'Anthropic API', desc: 'Direct API key' },
          { id: 'bedrock', label: 'AWS Bedrock', desc: 'Uses SSO credentials' },
        ].map(p => (
          <button
            key={p.id}
            onClick={() => switchProvider(p.id)}
            disabled={switching}
            className={`flex-1 px-3 py-2 rounded-lg text-sm border transition-colors ${
              provider === p.id
                ? 'border-genie-500 bg-genie-50 text-genie-700 font-medium'
                : 'border-gray-200 text-gray-600 hover:bg-gray-50'
            }`}
          >
            <div className="font-medium">{p.label}</div>
            <div className="text-[10px] text-gray-400 mt-0.5">{p.desc}</div>
          </button>
        ))}
      </div>
      {model && (
        <div className="text-[10px] text-gray-400 mt-2">
          Model: <span className="font-mono">{model}</span>
        </div>
      )}
    </div>
  )
}

function AirflowRedshiftConnect() {
  const { sessionId, authState } = useAuth()
  const [loading, setLoading] = useState<string | null>(null)
  const [results, setResults] = useState<Record<string, { status: string; user?: string; host?: string; error?: string }>>({})

  async function fetchCreds(env: string) {
    setLoading(env)
    try {
      const res = await fetchJSON<{ status: string; user?: string; host?: string; database?: string; error?: string; test_error?: string }>(
        '/auth/redshift/from-airflow',
        { method: 'POST', body: JSON.stringify({ session_id: sessionId, environment: env }) }
      )
      setResults(prev => ({ ...prev, [env]: res }))
    } catch (err) {
      setResults(prev => ({ ...prev, [env]: { status: 'error', error: err instanceof Error ? err.message : 'Failed' } }))
    } finally {
      setLoading(null)
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        {[
          { env: 'np', label: 'Nonprod', authed: authState.np?.authenticated },
          { env: 'prd', label: 'Prod', authed: authState.prd?.authenticated },
        ].map(({ env, label, authed }) => (
          <button
            key={env}
            onClick={() => fetchCreds(env)}
            disabled={!authed || loading === env}
            className="flex items-center gap-1.5 px-3 py-2 text-sm rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            {loading === env ? <Loader2 size={14} className="animate-spin" /> : <Database size={14} />}
            Fetch {label} from Airflow
            {!authed && <span className="text-[10px] text-amber-500">(SSO required)</span>}
          </button>
        ))}
      </div>
      {Object.entries(results).map(([env, r]) => (
        <div key={env} className={`text-xs rounded-md p-2 ${
          r.status === 'connected' ? 'bg-green-50 text-green-700' :
          r.status === 'credentials_stored' ? 'bg-yellow-50 text-yellow-700' :
          'bg-red-50 text-red-700'
        }`}>
          {r.status === 'connected' && (
            <span><CheckCircle size={12} className="inline mr-1" />
              {env}: Connected as <span className="font-mono">{r.user}</span> to {r.host}
            </span>
          )}
          {r.status === 'credentials_stored' && `${env}: Credentials stored (test pending)`}
          {r.status === 'error' && `${env}: ${r.error}`}
        </div>
      ))}
    </div>
  )
}

function StatsigConnection() {
  const [apiKey, setApiKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState<{ configured: boolean } | null>(null)
  const [result, setResult] = useState<{ status: string; error?: string } | null>(null)

  useEffect(() => {
    fetchJSON<{ configured: boolean }>('/auth/statsig/status')
      .then(setStatus).catch(() => {})
  }, [])

  async function handleSave() {
    setSaving(true)
    setResult(null)
    try {
      const res = await fetchJSON<{ status: string; error?: string }>('/auth/statsig/credentials', {
        method: 'POST',
        body: JSON.stringify({ api_key: apiKey }),
      })
      setResult(res)
      if (res.status === 'connected') { setApiKey(''); setStatus({ configured: true }) }
    } catch (err) {
      setResult({ status: 'error', error: err instanceof Error ? err.message : 'Failed' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="border border-gray-200 rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <BarChart3 size={18} className={status?.configured ? 'text-green-500' : 'text-gray-400'} />
          <h4 className="font-medium text-gray-900">Statsig</h4>
          {status?.configured && (
            <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full flex items-center gap-0.5">
              <CheckCircle size={8} /> Connected
            </span>
          )}
        </div>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        Console API key for experiment metadata, feature gates, and metrics. Read-only.
        <a href="https://docs.statsig.com/console-api/introduction" target="_blank" rel="noopener"
          className="text-genie-600 ml-1 hover:underline">Docs</a>
      </p>
      <div className="flex gap-2">
        <input
          type="password"
          value={apiKey}
          onChange={e => setApiKey(e.target.value)}
          placeholder={status?.configured ? '••••••• (stored)' : 'Console API Key'}
          autoComplete="new-password"
          className="flex-1 text-sm border border-gray-300 rounded-lg px-3 py-1.5"
        />
        <button
          onClick={handleSave}
          disabled={saving || !apiKey}
          className="px-3 py-1.5 text-sm rounded-lg bg-green-600 text-white hover:bg-green-700 disabled:opacity-50 flex items-center gap-1"
        >
          {saving ? <Loader2 size={14} className="animate-spin" /> : <BarChart3 size={14} />}
          Save & Test
        </button>
      </div>
      {result && (
        <div className={`text-xs rounded-md p-1.5 mt-1 ${
          result.status === 'connected' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
        }`}>
          {result.status === 'connected' ? 'Connected to Statsig' : result.error}
        </div>
      )}
    </div>
  )
}


function GitHubConnection() {
  const [token, setToken] = useState('')
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState<{ configured: boolean } | null>(null)
  const [result, setResult] = useState<{ status: string; error?: string } | null>(null)

  useEffect(() => {
    fetchJSON<{ configured: boolean }>('/auth/github/status')
      .then(setStatus).catch(() => {})
  }, [])

  async function handleSave() {
    setSaving(true)
    setResult(null)
    try {
      const res = await fetchJSON<{ status: string; error?: string }>('/auth/github/token', {
        method: 'POST',
        body: JSON.stringify({ token }),
      })
      setResult(res)
      if (res.status === 'connected') { setToken(''); setStatus({ configured: true }) }
    } catch (err) {
      setResult({ status: 'error', error: err instanceof Error ? err.message : 'Failed' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="border border-gray-200 rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <GitBranch size={18} className={status?.configured ? 'text-green-500' : 'text-gray-400'} />
          <h4 className="font-medium text-gray-900">GitHub</h4>
          {status?.configured && (
            <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full flex items-center gap-0.5">
              <CheckCircle size={8} /> Connected
            </span>
          )}
        </div>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        Personal access token with repo scope. Used for KB repo cloning and GitHub code search (MCP).
        Authorize for your GitHub org via SAML SSO.
      </p>
      <div className="flex gap-2">
        <input
          type="password"
          value={token}
          onChange={e => setToken(e.target.value)}
          placeholder={status?.configured ? '••••••• (stored)' : 'ghp_...'}
          autoComplete="new-password"
          className="flex-1 text-sm border border-gray-300 rounded-lg px-3 py-1.5 font-mono"
        />
        <button
          onClick={handleSave}
          disabled={saving || !token}
          className="px-3 py-1.5 text-sm rounded-lg bg-gray-800 text-white hover:bg-gray-900 disabled:opacity-50 flex items-center gap-1"
        >
          {saving ? <Loader2 size={14} className="animate-spin" /> : <GitBranch size={14} />}
          Save
        </button>
      </div>
      {result && (
        <div className={`text-xs rounded-md p-1.5 mt-1 ${
          result.status === 'connected' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
        }`}>
          {result.status === 'connected' ? 'GitHub token saved' : result.error}
        </div>
      )}
    </div>
  )
}


function DomoConnection() {
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState<{ configured: boolean } | null>(null)
  const [result, setResult] = useState<{ status: string; error?: string } | null>(null)

  useEffect(() => {
    fetchJSON<{ configured: boolean }>('/auth/domo/status')
      .then(setStatus).catch(() => {})
  }, [])

  async function handleSave() {
    setSaving(true)
    setResult(null)
    try {
      const res = await fetchJSON<{ status: string; error?: string }>('/auth/domo/credentials', {
        method: 'POST',
        body: JSON.stringify({ client_id: clientId, client_secret: clientSecret }),
      })
      setResult(res)
      if (res.status === 'connected') {
        setClientSecret('')
        setStatus({ configured: true })
      }
    } catch (err) {
      setResult({ status: 'error', error: err instanceof Error ? err.message : 'Failed' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="border border-gray-200 rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <BarChart3 size={18} className={status?.configured ? 'text-purple-500' : 'text-gray-400'} />
          <h4 className="font-medium text-gray-900">DOMO</h4>
          {status?.configured && (
            <span className="text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded-full flex items-center gap-0.5">
              <CheckCircle size={8} /> Connected
            </span>
          )}
        </div>
      </div>
      <p className="text-xs text-gray-500 mb-3">
        OAuth client credentials — same as Airflow DOMO Refresh DAGs. Read-only access to dataset metadata, schemas, and SQL queries. Credentials stored encrypted, never logged.
      </p>

      <div className="space-y-2">
        <div className="flex gap-2">
          <input
            type="text"
            value={clientId}
            onChange={e => setClientId(e.target.value)}
            placeholder="Client ID"
            autoComplete="off"
            className="flex-1 text-sm border border-gray-300 rounded-lg px-3 py-1.5"
          />
          <input
            type="password"
            value={clientSecret}
            onChange={e => setClientSecret(e.target.value)}
            placeholder={status?.configured ? '••••••• (stored)' : 'Client Secret'}
            autoComplete="new-password"
            className="flex-1 text-sm border border-gray-300 rounded-lg px-3 py-1.5"
          />
          <button
            onClick={handleSave}
            disabled={saving || !clientId || !clientSecret}
            className="px-3 py-1.5 text-sm rounded-lg bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-50 flex items-center gap-1"
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <BarChart3 size={14} />}
            Save & Test
          </button>
        </div>

        {result && (
          <div className={`text-xs rounded-md p-1.5 ${
            result.status === 'connected' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
          }`}>
            {result.status === 'connected' ? 'Connected to DOMO' : result.error}
          </div>
        )}
      </div>
    </div>
  )
}


function OktaStatus() {
  const { sessionId } = useAuth()
  const [status, setStatus] = useState<{ connected: boolean; username?: string }>({ connected: false })

  useEffect(() => {
    fetchJSON<{ connected: boolean; username?: string }>(`/auth/okta/status?session_id=${sessionId}`)
      .then(setStatus).catch(() => {})
  }, [sessionId])

  if (!status.connected) return null
  return (
    <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full flex items-center gap-1">
      <CheckCircle size={10} /> {status.username}
    </span>
  )
}

function OktaConnectForm() {
  const { sessionId } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [phase, setPhase] = useState<'idle' | 'connecting' | 'mfa_waiting' | 'done' | 'error'>('idle')
  const [message, setMessage] = useState('')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  async function handleConnect() {
    setPhase('connecting')
    setMessage('')
    try {
      // Try JDBC-style connection first (same as DataGrip)
      const res = await fetchJSON<{ status: string; user?: string; message?: string; error?: string }>('/auth/okta/test-jdbc', {
        method: 'POST',
        body: JSON.stringify({ session_id: sessionId, username, password, environment: 'np' }),
      })

      if (res.status === 'connected') {
        setPhase('done')
        setMessage(`Connected as ${res.user || 'IAM user'} via Okta SAML`)
        setPassword('')
        return
      }

      if (res.status === 'mfa_push_sent') {
        setPhase('mfa_waiting')
        setMessage(res.message || 'Approve push notification...')
        // Start polling
        pollRef.current = setInterval(async () => {
          try {
            const poll = await fetchJSON<{ status: string; message?: string; error?: string }>('/auth/okta/poll', {
              method: 'POST',
              body: JSON.stringify({ session_id: sessionId }),
            })
            if (poll.status === 'authenticated') {
              if (pollRef.current) clearInterval(pollRef.current)
              setPhase('done')
              setMessage('Connected to Redshift via Okta')
              setPassword('')
            } else if (poll.status === 'error') {
              if (pollRef.current) clearInterval(pollRef.current)
              setPhase('error')
              setMessage(poll.error || 'MFA failed')
            }
            // 'waiting' — keep polling
          } catch {
            // network error — keep trying
          }
        }, 3000)
        return
      }

      setPhase('error')
      setMessage(res.error || 'Authentication failed')
    } catch (err) {
      setPhase('error')
      setMessage(err instanceof Error ? err.message : 'Failed')
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <input
          type="text"
          value={username}
          onChange={e => setUsername(e.target.value)}
          placeholder="Okta username (e.g., admin@example.com)"
          disabled={phase === 'mfa_waiting'}
          className="flex-1 text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-genie-500 focus:border-genie-500 disabled:opacity-50"
        />
        <input
          type="password"
          value={password}
          onChange={e => setPassword(e.target.value)}
          placeholder="Okta password"
          disabled={phase === 'mfa_waiting'}
          className="flex-1 text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-genie-500 focus:border-genie-500 disabled:opacity-50"
        />
        <button
          onClick={handleConnect}
          disabled={phase === 'connecting' || phase === 'mfa_waiting' || !username || !password}
          className="px-4 py-2 text-sm rounded-lg bg-genie-600 text-white hover:bg-genie-700 disabled:opacity-50 flex items-center gap-1 whitespace-nowrap"
        >
          {(phase === 'connecting' || phase === 'mfa_waiting') ? <Loader2 size={14} className="animate-spin" /> : <Database size={14} />}
          Connect
        </button>
      </div>

      {phase === 'mfa_waiting' && (
        <div className="bg-blue-50 text-blue-700 text-xs rounded-md p-2 flex items-center gap-2">
          <Loader2 size={12} className="animate-spin" />
          {message}
        </div>
      )}
      {phase === 'done' && (
        <div className="bg-green-50 text-green-700 text-xs rounded-md p-2 flex items-center gap-1">
          <CheckCircle size={12} /> {message}
        </div>
      )}
      {phase === 'error' && (
        <div className="bg-red-50 text-red-700 text-xs rounded-md p-2">
          {message}
          <button onClick={() => setPhase('idle')} className="ml-2 underline">Try again</button>
        </div>
      )}

      <p className="text-[10px] text-gray-400">
        Credentials stored in-memory for this session. Supports Okta Verify Push MFA. Same auth as DataGrip.
      </p>
    </div>
  )
}
