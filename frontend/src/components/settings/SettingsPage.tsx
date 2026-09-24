import { useState, useEffect, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Save, Loader2 } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { useUser } from '../../context/UserContext'
import { fetchJSON } from '../../api/client'
import ClaudeIntegrationTab from './ClaudeIntegrationTab'
import PersonaTab from './PersonaTab'
import SystemPromptTab from './SystemPromptTab'
import UserContextTab from './UserContextTab'
import ConnectionTab from './ConnectionTab'
import KnowledgeBaseTab from './KnowledgeBaseTab'
import TableOpsTab from './TableOpsTab'
import AgentPrompts from '../admin/AgentPrompts'
import UserManagement from '../admin/UserManagement'
// FeedbackBoard moved to /tasks as TaskBoard
import ActivityPage from '../activity/ActivityPage'
import CostExplorer from './CostExplorer'


interface TabDef {
  id: string
  label: string
  permission?: string  // required permission, undefined = visible to all
}

export interface UserSettings {
  session_id: string
  persona: string
  system_prompt: string
  user_context: string
  user_context_optimized: string
  redshift_config: {
    default_environment: string
    auto_route_prod: boolean
  }
}

const DEFAULT_SYSTEM_PROMPT = `## Query Safety Rules
- NEVER generate DELETE, DROP, TRUNCATE, INSERT, UPDATE, or CREATE statements
- All generated SQL must be SELECT or EXPLAIN only
- Default to nonprod (np_) for all queries

## Environment Routing
- Use nonprod for: all analytics queries, schema browsing, SQL validation, business questions
- Use prod ONLY for: MWAA/Airflow logs (prod pipelines), Redshift EXPLAIN plans (prod stats),
  data profiling (row counts/distributions not available via datashare), S3 prod-only data
- When prod is required, explain WHY to the user before executing`

const ALL_TABS: TabDef[] = [
  // User tabs — visible to everyone
  { id: 'claude-integration', label: 'Claude Integration' },
  { id: 'persona', label: 'Persona' },
  { id: 'system-prompt', label: 'System Prompt' },
  { id: 'user-context', label: 'User Context' },
  { id: 'git', label: 'Git' },
  { id: 'activity', label: 'Activity' },
  // Admin / elevated tabs
  { id: 'connection', label: 'Connection', permission: 'admin_console' },
  { id: 'knowledge-base', label: 'Knowledge Base', permission: 'kb_build' },
  { id: 'table-ops', label: 'Table Ops', permission: 'table_ops_view' },
  { id: 'agents', label: 'Agent Prompts', permission: 'admin_console' },
  // Feedback board moved to sidebar /tasks route
  { id: 'users', label: 'Users', permission: 'user_management' },
  { id: 'cost-explorer', label: 'Cost Explorer', permission: 'admin_console' },
]

export default function SettingsPage() {
  const { sessionId } = useAuth()
  const { hasPermission } = useUser()
  const [searchParams, setSearchParams] = useSearchParams()

  const visibleTabs = useMemo(
    () => ALL_TABS.filter(t => !t.permission || hasPermission(t.permission)),
    [hasPermission],
  )

  const [activeTab, setActiveTab] = useState(() => {
    const param = searchParams.get('tab')
    if (param && visibleTabs.some(t => t.id === param)) return param
    return 'persona'
  })

  function changeTab(tab: string) {
    setActiveTab(tab)
    setSearchParams({ tab })
  }
  const [settings, setSettings] = useState<UserSettings>({
    session_id: sessionId,
    persona: 'engineer',
    system_prompt: DEFAULT_SYSTEM_PROMPT,
    user_context: '',
    user_context_optimized: '',
    redshift_config: { default_environment: 'np', auto_route_prod: true },
  })
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadSettings()
  }, [sessionId])

  async function loadSettings() {
    setLoading(true)
    try {
      const res = await fetchJSON<UserSettings>('/settings')
      setSettings({ ...res, session_id: sessionId })
    } catch {
      // Use defaults
    } finally {
      setLoading(false)
    }
  }

  async function handleSave() {
    setSaving(true)
    setSaved(false)
    try {
      await fetchJSON('/settings', {
        method: 'PUT',
        body: JSON.stringify({ ...settings, session_id: sessionId }),
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (err) {
      alert('Failed to save settings: ' + (err instanceof Error ? err.message : 'Unknown error'))
    } finally {
      setSaving(false)
    }
  }

  function updateSettings(partial: Partial<UserSettings>) {
    setSettings((prev) => ({ ...prev, ...partial }))
    setSaved(false)
  }

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 size={24} className="animate-spin text-gray-400" />
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="border-b border-gray-200 px-6 pt-5 pb-0">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900">Settings</h2>
          <button
            onClick={handleSave}
            disabled={saving}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              saved
                ? 'bg-green-100 text-green-700'
                : 'bg-genie-600 text-white hover:bg-genie-700'
            } disabled:opacity-50`}
          >
            {saving ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Save size={16} />
            )}
            {saved ? 'Saved!' : 'Save Settings'}
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 flex-wrap">
          {visibleTabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => changeTab(tab.id)}
              className={`px-4 py-2 text-sm rounded-t-lg transition-colors ${
                activeTab === tab.id
                  ? 'bg-white text-gray-900 font-medium border border-gray-200 border-b-white -mb-px'
                  : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-auto p-6">
        {activeTab === 'claude-integration' && <ClaudeIntegrationTab />}
        {activeTab === 'persona' && (
          <PersonaTab settings={settings} onUpdate={updateSettings} />
        )}
        {activeTab === 'system-prompt' && (
          <SystemPromptTab settings={settings} onUpdate={updateSettings} />
        )}
        {activeTab === 'user-context' && (
          <UserContextTab settings={settings} onUpdate={updateSettings} />
        )}
        {activeTab === 'git' && <GitSettingsTab />}
        {activeTab === 'activity' && <ActivityPage />}

        {activeTab === 'connection' && <ConnectionTab settings={settings} onUpdate={updateSettings} />}
        {activeTab === 'knowledge-base' && <KnowledgeBaseTab />}
        {activeTab === 'table-ops' && <TableOpsTab />}
        {activeTab === 'agents' && <AgentPrompts />}
        {/* Feedback board moved to /tasks */}
        {activeTab === 'users' && <UserManagement />}
        {activeTab === 'cost-explorer' && <CostExplorer />}
      </div>
    </div>
  )
}

function GitSettingsTab() {
  const [gitName, setGitName] = useState('')
  const [gitEmail, setGitEmail] = useState('')
  const [githubToken, setGithubToken] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [hasToken, setHasToken] = useState(false)

  useEffect(() => {
    fetchJSON<{ git_name: string; git_email: string; has_token: boolean }>('/users/me/git')
      .then(r => { setGitName(r.git_name || ''); setGitEmail(r.git_email || ''); setHasToken(r.has_token) })
      .catch(() => {})
  }, [])

  async function handleSave() {
    setSaving(true)
    try {
      await fetchJSON('/users/me/git', {
        method: 'PUT',
        body: JSON.stringify({
          git_name: gitName,
          git_email: gitEmail,
          github_token: githubToken || undefined,
        }),
      })
      setSaved(true)
      setGithubToken('')
      if (githubToken) setHasToken(true)
      setTimeout(() => setSaved(false), 3000)
    } catch { /* ignore */ }
    finally { setSaving(false) }
  }

  return (
    <div className="max-w-lg space-y-4">
      <div>
        <h3 className="text-base font-medium text-gray-900 mb-1">Git Configuration</h3>
        <p className="text-sm text-gray-500">Your git identity for commits and PRs. GitHub token for push access.</p>
      </div>

      <div>
        <label className="text-sm font-medium text-gray-700 block mb-1">Git Name</label>
        <input value={gitName} onChange={e => setGitName(e.target.value)}
          placeholder="Sri Maru"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
        <p className="text-xs text-gray-400 mt-0.5">Shows as commit author</p>
      </div>

      <div>
        <label className="text-sm font-medium text-gray-700 block mb-1">Git Email</label>
        <input value={gitEmail} onChange={e => setGitEmail(e.target.value)}
          placeholder="admin@example.com"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
        <p className="text-xs text-gray-400 mt-0.5">Shows as commit email</p>
      </div>

      <div>
        <label className="text-sm font-medium text-gray-700 block mb-1">GitHub Personal Access Token</label>
        <input type="password" value={githubToken} onChange={e => setGithubToken(e.target.value)}
          placeholder={hasToken ? '••••••• (stored)' : 'ghp_...'}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono" />
        <p className="text-xs text-gray-400 mt-0.5">
          Needs <code className="bg-gray-100 px-1 rounded">repo</code> scope + SAML SSO authorization for your-org org.
          Stored encrypted, never logged.
        </p>
      </div>

      <button onClick={handleSave} disabled={saving}
        className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium ${
          saved ? 'bg-green-100 text-green-700' : 'bg-genie-600 text-white hover:bg-genie-700'
        } disabled:opacity-50`}>
        {saving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
        {saved ? 'Saved!' : 'Save Git Config'}
      </button>
    </div>
  )
}
