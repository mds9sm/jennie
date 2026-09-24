import { useState, useEffect, useRef } from 'react'
import { GitBranch, Cloud, RefreshCw, Loader2, CheckCircle, AlertCircle, Database, FileCode, Server, Plus, Trash2, X, BarChart3 } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { fetchJSON } from '../../api/client'

interface RepoStatus {
  exists: boolean
  path: string
  branch?: string
  commit?: string
  commit_date?: string
  yaml_files?: number
  sql_files?: number
}

interface KBRepo {
  id: number
  name: string
  url: string
  branch: string
  is_active: boolean
  parse_all: boolean
  clone_path: string | null
  created_at: string
}

interface BuildStatus {
  running: boolean
  status: string
  phase?: string
  mwaa_detail?: string
  last_refresh_time?: string | null
  table_count?: number
  transform_count?: number
  lineage_count?: number
  glossary_count?: number
  glossary_terms?: number
  duration_seconds?: number
  error?: string | null
  errors?: string[]
  repo_clone?: { status: string; commit?: string; branch?: string; error?: string | null }
  mwaa_transforms_found?: number
  mwaa_dag_runs?: number
  repo_transforms_found?: number
  logs?: string[]
}

export default function KnowledgeBaseTab() {
  const { sessionId, authState } = useAuth()
  const [repoStatus, setRepoStatus] = useState<RepoStatus | null>(null)
  const [buildStatus, setBuildStatus] = useState<BuildStatus | null>(null)
  const [cloning, setCloning] = useState(false)
  const [kbSchedule, setKbSchedule] = useState('')
  const [scheduleSaving, setScheduleSaving] = useState(false)
  // Persist KB build preferences in localStorage
  const loadPref = (key: string, fallback: string) => {
    try { return localStorage.getItem(`kb_${key}`) ?? fallback } catch { return fallback }
  }
  const savePref = (key: string, val: string) => {
    try { localStorage.setItem(`kb_${key}`, val) } catch { /* ignore */ }
  }

  const [repoUrl, setRepoUrl] = useState('')
  const [repoUrlSaving, setRepoUrlSaving] = useState(false)
  const [repoUrlStatus, setRepoUrlStatus] = useState<string | null>(null)

  const [includeRepo, _setIncludeRepo] = useState(() => loadPref('repo', 'true') === 'true')
  const [includeMwaa, _setIncludeMwaa] = useState(() => loadPref('mwaa', 'true') === 'true')
  const [includeRedshift, _setIncludeRedshift] = useState(() => loadPref('redshift', 'true') === 'true')
  const [includeDomoS3, _setIncludeDomoS3] = useState(() => loadPref('domo_s3', 'true') === 'true')
  const [redshiftEnv, setRedshiftEnv] = useState(() => loadPref('rs_env', 'prd'))
  const [mwaaEnvs, setMwaaEnvs] = useState<string[]>(() => {
    try { return JSON.parse(loadPref('mwaa_envs', '["np","prd"]')) } catch { return ['np', 'prd'] }
  })
  const [enrichmentModel, _setEnrichmentModel] = useState(() => loadPref('model', 'sonnet'))
  const [selectedPhases, setSelectedPhases] = useState<string[]>([])  // empty = all

  const setIncludeRepo = (v: boolean) => { _setIncludeRepo(v); savePref('repo', String(v)) }
  const setIncludeMwaa = (v: boolean) => { _setIncludeMwaa(v); savePref('mwaa', String(v)) }
  const setIncludeRedshift = (v: boolean) => { _setIncludeRedshift(v); savePref('redshift', String(v)) }
  const setIncludeDomoS3 = (v: boolean) => { _setIncludeDomoS3(v); savePref('domo_s3', String(v)) }
  const setEnrichmentModel = (v: string) => { _setEnrichmentModel(v); savePref('model', v) }
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    loadStatus()
    // Load KB schedule
    fetchJSON<{ cron: string }>('/catalog-engine/kb-schedule')
      .then(r => { if (r.cron) setKbSchedule(r.cron) })
      .catch(() => {})
    // Load repo URL
    fetchJSON<{ configured: boolean; url: string }>('/auth/repo-url/status')
      .then(r => { if (r.url) setRepoUrl(r.url) })
      .catch(() => {})
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  async function loadStatus() {
    try {
      const [repo, build] = await Promise.all([
        fetchJSON<RepoStatus>('/catalog-engine/repo/status'),
        fetchJSON<BuildStatus>('/catalog-engine/status'),
      ])
      setRepoStatus(repo)
      setBuildStatus(build)

      // If a build is already running, start polling
      if (build.running) startPolling()
    } catch {
      // ignore
    }
  }

  function startPolling() {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const status = await fetchJSON<BuildStatus>('/catalog-engine/status')
        setBuildStatus(status)
        if (!status.running) {
          if (pollRef.current) clearInterval(pollRef.current)
          pollRef.current = null
          // Refresh repo status too
          const repo = await fetchJSON<RepoStatus>('/catalog-engine/repo/status')
          setRepoStatus(repo)
        }
      } catch {
        // ignore
      }
    }, 2000)
  }

  async function handleCloneRepo() {
    setCloning(true)
    try {
      const result = await fetchJSON<RepoStatus & { status: string; error?: string }>('/catalog-engine/repo/clone', {
        method: 'POST',
      })
      if (result.status === 'error') {
        alert('Clone failed: ' + result.error)
      }
      await loadStatus()
    } catch (err) {
      alert('Clone failed: ' + (err instanceof Error ? err.message : 'Unknown error'))
    } finally {
      setCloning(false)
    }
  }

  async function handleBuild() {
    try {
      const result = await fetchJSON<{ status: string; message: string }>('/catalog-engine/refresh', {
        method: 'POST',
        body: JSON.stringify({
          session_id: sessionId,
          include_repo: includeRepo,
          include_mwaa: includeMwaa,
          include_redshift: includeRedshift,
          include_s3_metadata: includeDomoS3,
          mwaa_environments: mwaaEnvs,
          redshift_environment: redshiftEnv,
          enrichment_model: enrichmentModel,
          phases: selectedPhases,
        }),
      })

      if (result.status === 'already_running') {
        // Already running — just poll
      }

      setBuildStatus({ running: true, status: 'running', phase: 'starting' })
      startPolling()
    } catch (err) {
      alert('Build failed: ' + (err instanceof Error ? err.message : 'Unknown error'))
    }
  }

  function toggleMwaaEnv(env: string) {
    setMwaaEnvs((prev) => (prev.includes(env) ? prev.filter((e) => e !== env) : [...prev, env]))
  }

  const npAuth = authState.np?.authenticated
  const prdAuth = authState.prd?.authenticated
  const isRunning = buildStatus?.running

  return (
    <div className="max-w-2xl space-y-6">
      {/* Header */}
      <div>
        <h3 className="text-base font-medium text-gray-900 mb-1">Knowledge Base</h3>
        <p className="text-sm text-gray-500">
          Build Genie's knowledge from real sources: MWAA (primary — rendered SQL, run stats) and Git repo (secondary — who changed what, when).
        </p>
      </div>

      {/* Git Repo Card */}
      <div className="border border-gray-200 rounded-lg p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <GitBranch size={18} className={repoStatus?.exists ? 'text-green-500' : 'text-gray-400'} />
            <h4 className="font-medium text-gray-900">Data Platform Repo</h4>
            {repoStatus?.exists && (
              <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">
                {repoStatus.branch}@{repoStatus.commit}
              </span>
            )}
          </div>
          <button
            onClick={handleCloneRepo}
            disabled={cloning || !!isRunning}
            className="text-sm px-3 py-1.5 rounded-lg font-medium border border-gray-300 text-gray-600 hover:bg-gray-50 disabled:opacity-50 flex items-center gap-1"
          >
            {cloning ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            {repoStatus?.exists ? 'Pull Latest' : 'Clone Repo'}
          </button>
        </div>

        <div className="flex items-center gap-2 mb-2">
          <input
            type="text"
            value={repoUrl}
            onChange={e => { setRepoUrl(e.target.value); setRepoUrlStatus(null) }}
            placeholder="https://github.com/your-org/data-platform-dags"
            className="flex-1 text-xs font-mono bg-gray-50 border border-gray-200 rounded px-3 py-2 focus:outline-none focus:ring-1 focus:ring-green-500"
          />
          <button
            onClick={async () => {
              if (!repoUrl.trim()) return
              setRepoUrlSaving(true)
              setRepoUrlStatus(null)
              try {
                await fetchJSON('/auth/repo-url', { method: 'POST', body: JSON.stringify({ url: repoUrl.trim() }) })
                setRepoUrlStatus('saved')
              } catch {
                setRepoUrlStatus('error')
              }
              setRepoUrlSaving(false)
            }}
            disabled={repoUrlSaving || !repoUrl.trim()}
            className="text-xs px-3 py-2 rounded border border-gray-300 text-gray-600 hover:bg-gray-50 disabled:opacity-50"
          >
            {repoUrlSaving ? <Loader2 size={12} className="animate-spin" /> : 'Save'}
          </button>
        </div>
        {repoUrlStatus === 'saved' && <p className="text-xs text-green-600 mb-1">Repo URL saved</p>}
        {repoUrlStatus === 'error' && <p className="text-xs text-red-600 mb-1">Failed to save</p>}

        {repoStatus?.exists && (
          <div className="grid grid-cols-3 gap-3 text-xs text-gray-500">
            <div>
              <span className="block text-gray-400">Last Commit</span>
              {repoStatus.commit_date ? new Date(repoStatus.commit_date).toLocaleDateString() : '—'}
            </div>
            <div>
              <span className="block text-gray-400">YAML Files</span>
              {repoStatus.yaml_files ?? '—'}
            </div>
            <div>
              <span className="block text-gray-400">SQL Files</span>
              {repoStatus.sql_files ?? '—'}
            </div>
          </div>
        )}
      </div>

      {/* Additional KB Repos */}
      <AdditionalRepos />

      {/* MWAA Card */}
      <div className="border border-gray-200 rounded-lg p-4">
        <div className="flex items-center gap-2 mb-3">
          <Cloud size={18} className={npAuth || prdAuth ? 'text-green-500' : 'text-gray-400'} />
          <h4 className="font-medium text-gray-900">MWAA Environments</h4>
          <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">Primary Source</span>
        </div>

        <div className="space-y-2">
          {[
            { id: 'np', label: 'Nonprod', env: 'nonprod-airflow-mwaa', authed: npAuth },
            { id: 'prd', label: 'Prod', env: 'prod-airflow-mwaa', authed: prdAuth },
          ].map((mwaa) => (
            <label
              key={mwaa.id}
              className="flex items-center gap-3 p-2 rounded-lg hover:bg-gray-50 cursor-pointer"
            >
              <input
                type="checkbox"
                checked={mwaaEnvs.includes(mwaa.id)}
                onChange={() => toggleMwaaEnv(mwaa.id)}
                disabled={!!isRunning}
                className="rounded text-genie-600 focus:ring-genie-500"
              />
              <div className="flex-1">
                <span className="text-sm font-medium text-gray-700">{mwaa.label}</span>
                <span className="text-xs text-gray-400 ml-2 font-mono">{mwaa.env}</span>
              </div>
              {mwaa.authed ? (
                <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">SSO Connected</span>
              ) : (
                <span className="text-xs bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded-full">Not Connected</span>
              )}
            </label>
          ))}
        </div>

        {!npAuth && !prdAuth && (
          <p className="text-xs text-amber-600 mt-2">
            Connect via SSO in the Connection tab to fetch MWAA data.
          </p>
        )}
      </div>

      {/* Build Controls */}
      <div className="border border-gray-200 rounded-lg p-4">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h4 className="font-medium text-gray-900">Build Catalog</h4>
            <p className="text-xs text-gray-500 mt-0.5">
              Fetches MWAA rendered SQL + run stats, enriches with repo git metadata, and writes the knowledge base.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleBuild}
              disabled={!!isRunning}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-genie-600 text-white hover:bg-genie-700 disabled:opacity-50"
            >
              {isRunning ? <Loader2 size={16} className="animate-spin" /> : <Database size={16} />}
              {isRunning ? 'Building...' : 'Build Knowledge Base'}
            </button>
            {isRunning && (
              <button
                onClick={async () => {
                  try {
                    await fetchJSON('/catalog-engine/cancel', { method: 'POST' })
                    loadStatus()
                  } catch { /* ignore */ }
                }}
                className="flex items-center gap-1 px-3 py-2 rounded-lg text-sm font-medium border border-red-300 text-red-600 hover:bg-red-50"
              >
                <X size={14} />
                Cancel
              </button>
            )}
          </div>
        </div>

        {/* Source toggles */}
        <div className="flex flex-wrap gap-4 mb-4">
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={includeMwaa}
              onChange={(e) => setIncludeMwaa(e.target.checked)}
              disabled={!!isRunning}
              className="rounded text-genie-600 focus:ring-genie-500"
            />
            <Cloud size={14} className="text-gray-400" />
            MWAA (primary)
          </label>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={includeRedshift}
              onChange={(e) => setIncludeRedshift(e.target.checked)}
              disabled={!!isRunning}
              className="rounded text-genie-600 focus:ring-genie-500"
            />
            <Server size={14} className="text-gray-400" />
            Redshift (prod metadata + nonprod profiling)
          </label>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={includeRepo}
              onChange={(e) => setIncludeRepo(e.target.checked)}
              disabled={!!isRunning}
              className="rounded text-genie-600 focus:ring-genie-500"
            />
            <FileCode size={14} className="text-gray-400" />
            Git Repo
          </label>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={includeDomoS3}
              onChange={(e) => setIncludeDomoS3(e.target.checked)}
              disabled={!!isRunning}
              className="rounded text-genie-600 focus:ring-genie-500"
            />
            <BarChart3 size={14} className="text-purple-400" />
            DOMO / S3 Metadata
          </label>
        </div>
        {includeRedshift && (
          <p className="text-xs text-gray-500 mb-4 -mt-2">
            Fetches table/column metadata from prod Redshift, then profiles each table via nonprod datashare.
            Profiles include row counts, cardinality, null rates, min/max per column. Read-only.
          </p>
        )}

        {/* AI Enrichment Model */}
        <div className="flex items-center gap-3 mb-4">
          <span className="text-sm text-gray-600">AI Enrichment Model:</span>
          {(['opus', 'sonnet', 'haiku'] as const).map(m => (
            <label key={m} className="flex items-center gap-1.5 text-xs cursor-pointer">
              <input type="radio" name="enrichment_model" value={m}
                checked={enrichmentModel === m}
                onChange={() => setEnrichmentModel(m)}
                disabled={!!isRunning}
                className="text-genie-600 focus:ring-genie-500" />
              <span className={`font-medium ${m === 'opus' ? 'text-purple-600' : m === 'sonnet' ? 'text-blue-600' : 'text-green-600'}`}>
                {m.charAt(0).toUpperCase() + m.slice(1)}
              </span>
              <span className="text-gray-400">
                {m === 'opus' ? '(best quality)' : m === 'sonnet' ? '(balanced)' : '(cheapest)'}
              </span>
            </label>
          ))}
        </div>

        {/* Build Phases */}
        <div className="mb-4">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="text-sm text-gray-600">Phases:</span>
            <button onClick={() => setSelectedPhases([])}
              className={`text-[10px] px-2 py-0.5 rounded-full ${selectedPhases.length === 0 ? 'bg-genie-100 text-genie-700 font-medium' : 'text-gray-500 hover:bg-gray-100'}`}
              disabled={!!isRunning}>
              All
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {[
              { id: 'data_collection', label: 'Data Collection', desc: 'MWAA + Repo + Redshift' },
              { id: 'domo_views', label: 'DOMO Views', desc: 'Parse views + downstream DAGs' },
              { id: 's3_metadata', label: 'S3 Metadata', desc: 'DOMO S3 columns + freshness' },
              { id: 'glossary', label: 'Glossary', desc: 'Extract + rewrite definitions' },
              { id: 'enrichment', label: 'AI Enrichment', desc: 'Descriptions, summaries' },
            ].map(phase => (
              <label key={phase.id} className="flex items-center gap-1.5 text-xs cursor-pointer" title={phase.desc}>
                <input type="checkbox"
                  checked={selectedPhases.includes(phase.id)}
                  onChange={e => {
                    if (e.target.checked) setSelectedPhases(prev => [...prev, phase.id])
                    else setSelectedPhases(prev => prev.filter(p => p !== phase.id))
                  }}
                  disabled={!!isRunning}
                  className="rounded text-genie-600 focus:ring-genie-500" />
                <span className="text-gray-700">{phase.label}</span>
                <span className="text-[10px] text-gray-400">({phase.desc})</span>
              </label>
            ))}
          </div>
          {selectedPhases.length > 0 && (
            <p className="text-[10px] text-amber-600 mt-1">
              Partial build: only selected phases will run. Uses existing data from previous builds for skipped phases.
            </p>
          )}
        </div>

        {/* Schedule */}
        <div className="flex items-center gap-3 mb-4 pt-3 border-t border-gray-100">
          <span className="text-sm text-gray-600">Auto-build:</span>
          <select
            value={kbSchedule}
            onChange={async (e) => {
              const cron = e.target.value
              setKbSchedule(cron)
              setScheduleSaving(true)
              try {
                await fetchJSON('/catalog-engine/kb-schedule', {
                  method: 'POST',
                  body: JSON.stringify({ cron }),
                })
              } catch { /* ignore */ }
              finally { setScheduleSaving(false) }
            }}
            className="text-xs border border-gray-300 rounded px-2 py-1 bg-white"
          >
            <option value="">Disabled</option>
            <option value="0 6 * * *">Daily 6am UTC</option>
            <option value="0 6 * * 1">Weekly Monday 6am UTC</option>
            <option value="0 6 1 * *">Monthly 1st 6am UTC</option>
            <option value="0 */6 * * *">Every 6 hours</option>
          </select>
          {scheduleSaving && <Loader2 size={12} className="animate-spin text-gray-400" />}
          {kbSchedule && <span className="text-[10px] text-green-600">Active</span>}
        </div>

        {/* S3 Storage */}
        <KBStorageConfig />

        {/* Live Progress */}
        {isRunning && buildStatus && (
          <div className="bg-blue-50 rounded-lg p-3 text-sm">
            <div className="flex items-center gap-2 mb-2">
              <Loader2 size={14} className="animate-spin text-blue-600" />
              <span className="font-medium text-blue-700">
                Building knowledge base...
              </span>
            </div>
            <div className="text-xs text-blue-600 space-y-1">
              <div>Phase: <span className="font-mono">{buildStatus.phase}</span></div>
              {buildStatus.mwaa_detail && (
                <div className="font-mono truncate">{buildStatus.mwaa_detail}</div>
              )}
            </div>
            {/* Build Logs */}
            {buildStatus.logs && buildStatus.logs.length > 0 && (
              <div className="mt-2 bg-gray-900 rounded text-[11px] font-mono text-gray-300 p-2 max-h-48 overflow-auto">
                {buildStatus.logs.map((line, i) => (
                  <div key={i} className={
                    line.includes('failed') || line.includes('error') ? 'text-red-400' :
                    line.includes('complete') || line.includes('found') || line.includes('parsed') ? 'text-green-400' :
                    'text-gray-400'
                  }>{line}</div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Completed Build Result */}
        {!isRunning && buildStatus && buildStatus.status === 'success' && (
          <div className="bg-green-50 rounded-lg p-3 text-sm">
            <div className="flex items-center gap-2 mb-2">
              <CheckCircle size={14} className="text-green-600" />
              <span className="font-medium text-green-700">
                Build complete
                {buildStatus.duration_seconds ? ` in ${buildStatus.duration_seconds}s` : ''}
              </span>
              {(buildStatus.last_refresh_time) && (
                <span className="text-xs text-gray-500 ml-auto">
                  {new Date(buildStatus.last_refresh_time).toLocaleString()}
                </span>
              )}
            </div>
            <div className="grid grid-cols-4 gap-2 text-xs text-gray-600 mt-2">
              <div><span className="block text-gray-400">Tables</span>{buildStatus.table_count ?? 0}</div>
              <div><span className="block text-gray-400">Transforms</span>{buildStatus.transform_count ?? 0}</div>
              <div><span className="block text-gray-400">Lineage</span>{buildStatus.lineage_count ?? 0}</div>
              <div><span className="block text-gray-400">Glossary</span>{buildStatus.glossary_terms ?? buildStatus.glossary_count ?? 0}</div>
            </div>
            {buildStatus.repo_clone && (
              <div className="text-xs text-gray-500 mt-2">
                Repo: {buildStatus.repo_clone.status}
                {buildStatus.repo_clone.commit && ` (${buildStatus.repo_clone.branch}@${buildStatus.repo_clone.commit})`}
              </div>
            )}
            {buildStatus.mwaa_transforms_found != null && buildStatus.mwaa_transforms_found > 0 && (
              <div className="text-xs text-gray-500">
                MWAA: {buildStatus.mwaa_transforms_found} transforms, {buildStatus.mwaa_dag_runs ?? 0} DAG runs
              </div>
            )}
            {(buildStatus as any).redshift_tables_found > 0 && (
              <div className="text-xs text-gray-500">
                Redshift: {(buildStatus as any).redshift_tables_found} tables (columns, distkeys, row counts)
              </div>
            )}
            {buildStatus.repo_transforms_found != null && (
              <div className="text-xs text-gray-500">
                Repo: {buildStatus.repo_transforms_found} configs with git metadata
              </div>
            )}
            {buildStatus.errors && buildStatus.errors.length > 0 && (
              <div className="text-xs text-amber-600 mt-2">
                {buildStatus.errors.map((e, i) => (
                  <div key={i}>Warning: {e}</div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Error State */}
        {!isRunning && buildStatus && buildStatus.status === 'error' && (
          <div className="bg-red-50 rounded-lg p-3 text-sm">
            <div className="flex items-center gap-2">
              <AlertCircle size={14} className="text-red-600" />
              <span className="font-medium text-red-700">Build failed</span>
            </div>
            <div className="text-xs text-red-600 mt-1">
              {buildStatus.error}
            </div>
          </div>
        )}

        {/* Never Run */}
        {!isRunning && buildStatus && buildStatus.status === 'never_run' && (
          <div className="bg-gray-50 rounded-lg p-3 text-xs text-gray-500">
            No builds run yet. Click "Build Knowledge Base" to start.
          </div>
        )}
      </div>

      {/* KB Explorer */}
      <KBExplorer />

      {/* Build History */}
      <KBHistory />
    </div>
  )
}


function KBStorageConfig() {
  const [bucket, setBucket] = useState('')
  const [prefix, setPrefix] = useState('knowledge/')
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState<{ configured: boolean; bucket: string; prefix: string } | null>(null)

  useEffect(() => {
    fetchJSON<{ configured: boolean; bucket: string; prefix: string }>('/auth/kb-storage/status')
      .then(r => { setStatus(r); if (r.bucket) setBucket(r.bucket); if (r.prefix) setPrefix(r.prefix) })
      .catch(() => {})
  }, [])

  async function handleSave() {
    if (!bucket) return
    setSaving(true)
    try {
      await fetchJSON('/auth/kb-storage', {
        method: 'POST',
        body: JSON.stringify({ bucket, prefix }),
      })
      setStatus({ configured: true, bucket, prefix })
    } catch { /* ignore */ }
    finally { setSaving(false) }
  }

  return (
    <div className="flex items-center gap-3 mb-4 pt-3 border-t border-gray-100">
      <span className="text-sm text-gray-600">S3 Storage:</span>
      <input type="text" value={bucket} onChange={e => setBucket(e.target.value)}
        placeholder="Bucket name (e.g., genie-kb-bucket)"
        className="text-xs border border-gray-300 rounded px-2 py-1 flex-1 font-mono" />
      <input type="text" value={prefix} onChange={e => setPrefix(e.target.value)}
        placeholder="Prefix"
        className="text-xs border border-gray-300 rounded px-2 py-1 w-32 font-mono" />
      <button onClick={handleSave} disabled={saving || !bucket}
        className="text-xs px-3 py-1 rounded bg-gray-700 text-white hover:bg-gray-800 disabled:opacity-50">
        {saving ? <Loader2 size={10} className="animate-spin" /> : 'Save'}
      </button>
      {status?.configured && <span className="text-[10px] text-green-600">s3://{status.bucket}/{status.prefix}</span>}
    </div>
  )
}


function KBExplorer() {
  const [data, setData] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState<string>('summary')
  const [search, setSearch] = useState('')

  async function load() {
    setLoading(true)
    try {
      const res = await fetchJSON<Record<string, unknown>>('/catalog-engine/kb/explore')
      setData(res)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  if (loading) return (
    <div className="border border-gray-200 rounded-lg p-8 flex justify-center">
      <Loader2 size={20} className="animate-spin text-gray-400" />
    </div>
  )

  if (!data) return null

  const summary = data.summary as Record<string, number>
  const transforms = (data.transforms || []) as Array<Record<string, unknown>>
  const profiles = (data.profiles || []) as Array<Record<string, unknown>>
  const domoMetrics = (data.domo_metrics || []) as Array<Record<string, unknown>>
  const glossary = (data.glossary || []) as Array<Record<string, unknown>>

  const tabs = [
    { id: 'summary', label: 'Summary', count: null },
    { id: 'transforms', label: 'Transforms', count: summary.transform_count },
    { id: 'tables', label: 'Tables & Profiles', count: summary.profile_count || summary.table_count },
    { id: 'domo', label: 'DOMO Metrics', count: summary.domo_metric_count },
    { id: 'glossary', label: 'Glossary', count: summary.glossary_count },
  ]

  function filterList<T extends Record<string, unknown>>(list: T[]): T[] {
    if (!search.trim()) return list
    const q = search.toLowerCase()
    return list.filter(item =>
      Object.values(item).some(v => String(v).toLowerCase().includes(q))
    )
  }

  const pillarColors: Record<string, string> = {
    'Onboard': 'bg-blue-100 text-blue-700',
    'Trigger Return': 'bg-purple-100 text-purple-700',
    'Makeable Content': 'bg-green-100 text-green-700',
    'Content Matching': 'bg-yellow-100 text-yellow-700',
    'Design & Make': 'bg-orange-100 text-orange-700',
    'Guided Flows': 'bg-orange-50 text-orange-600',
    'Marketing': 'bg-pink-100 text-pink-700',
    'Platform': 'bg-gray-100 text-gray-700',
  }

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <div className="px-4 py-3 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
        <h4 className="font-medium text-gray-900 text-sm">KB Explorer — What Genie Knows</h4>
        <button onClick={load} className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1">
          <RefreshCw size={12} /> Refresh
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-gray-200 bg-white overflow-x-auto">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-xs font-medium whitespace-nowrap border-b-2 transition-colors ${
              activeTab === tab.id
                ? 'border-genie-600 text-genie-700'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {tab.label}
            {tab.count != null && (
              <span className="ml-1.5 text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded-full">{tab.count}</span>
            )}
          </button>
        ))}
      </div>

      {/* Search (for non-summary tabs) */}
      {activeTab !== 'summary' && (
        <div className="px-4 py-2 border-b border-gray-100">
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Filter..."
            className="w-full text-xs border border-gray-200 rounded px-2.5 py-1.5 focus:ring-genie-500 focus:border-genie-500"
          />
        </div>
      )}

      <div className="max-h-[500px] overflow-auto">
        {/* Summary Tab */}
        {activeTab === 'summary' && (
          <div className="p-4">
            {/* Last build info */}
            {(() => {
              const lb = (data as Record<string, unknown>).last_build as Record<string, unknown> | null
              if (!lb) return null
              const status = String(lb.status || '')
              const dur = lb.duration_seconds ? `${Number(lb.duration_seconds).toFixed(0)}s` : ''
              return (
                <div className={`flex items-center gap-3 mb-4 px-3 py-2 rounded-lg text-xs ${
                  status === 'success' ? 'bg-green-50 text-green-700' :
                  status === 'running' ? 'bg-blue-50 text-blue-700' :
                  'bg-red-50 text-red-700'
                }`}>
                  <span className={`w-2 h-2 rounded-full ${
                    status === 'success' ? 'bg-green-400' : status === 'running' ? 'bg-blue-400' : 'bg-red-400'
                  }`} />
                  <span className="font-medium">Build #{String(lb.id)}</span>
                  <span>{lb.created_at ? new Date(String(lb.created_at)).toLocaleString() : ''}</span>
                  {dur && <span>{dur}</span>}
                  <span className="font-medium">{status}</span>
                </div>
              )
            })()}

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                { label: 'Transforms', value: summary.transform_count, icon: '🔧' },
                { label: 'Table Profiles', value: summary.profile_count, icon: '📊' },
                { label: 'DOMO Metrics', value: summary.domo_metric_count, icon: '📐' },
                { label: 'Glossary Terms', value: summary.glossary_count, icon: '📖' },
                { label: 'Lineage Entries', value: summary.lineage_count, icon: '🔗' },
                { label: 'Tables in Catalog', value: summary.table_count, icon: '🗃️' },
                { label: 'Metadata DAGs', value: summary.metadata_dag_count, icon: '⚙️' },
                { label: 'With Downstream', value: summary.lineage_with_downstream, icon: '↓' },
              ].map(s => (
                <div key={s.label} className="bg-gray-50 rounded-lg p-3">
                  <div className="text-lg font-bold text-gray-900">{s.value ?? 0}</div>
                  <div className="text-[11px] text-gray-500">{s.icon} {s.label}</div>
                </div>
              ))}
            </div>
            {summary.table_count === 0 && summary.profile_count > 0 && (
              <p className="text-xs text-amber-600 mt-3 bg-amber-50 rounded-lg px-3 py-2">
                Table catalog is empty — enable Redshift source in the next KB build to populate it.
                Table Ops has {summary.profile_count} profiled tables that agents can use via profiles.
              </p>
            )}
          </div>
        )}

        {/* Transforms Tab */}
        {activeTab === 'transforms' && (
          <table className="w-full text-xs">
            <thead className="bg-gray-50 sticky top-0">
              <tr>
                <th className="text-left px-3 py-2 text-gray-500 font-medium">Name</th>
                <th className="text-left px-3 py-2 text-gray-500 font-medium">Target</th>
                <th className="text-left px-3 py-2 text-gray-500 font-medium">Type</th>
                <th className="text-left px-3 py-2 text-gray-500 font-medium">Schedule</th>
                <th className="text-left px-3 py-2 text-gray-500 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {filterList(transforms).slice(0, 100).map((t, i) => (
                <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
                  <td className="px-3 py-1.5 font-mono text-gray-800 truncate max-w-[200px]" title={String(t.name)}>{String(t.name)}</td>
                  <td className="px-3 py-1.5 text-gray-600 truncate max-w-[180px] font-mono" title={String(t.target_table || '')}>{String(t.target_table || '—')}</td>
                  <td className="px-3 py-1.5">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                      t.dag_type === 'transform' ? 'bg-blue-50 text-blue-600' :
                      t.dag_type === 'domo' ? 'bg-purple-50 text-purple-600' :
                      t.dag_type === 'dq_validation' ? 'bg-green-50 text-green-600' :
                      'bg-gray-100 text-gray-500'
                    }`}>{String(t.dag_type || '—')}</span>
                  </td>
                  <td className="px-3 py-1.5 text-gray-500 font-mono">{String(t.schedule || '—')}</td>
                  <td className="px-3 py-1.5">
                    {String(t.run_state || '') !== '' && (
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                        t.run_state === 'success' ? 'bg-green-100 text-green-700' :
                        t.run_state === 'failed' ? 'bg-red-100 text-red-700' :
                        'bg-gray-100 text-gray-500'
                      }`}>{String(t.run_state)}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {/* Tables & Profiles Tab */}
        {activeTab === 'tables' && (
          <table className="w-full text-xs">
            <thead className="bg-gray-50 sticky top-0">
              <tr>
                <th className="text-left px-3 py-2 text-gray-500 font-medium">Table</th>
                <th className="text-right px-3 py-2 text-gray-500 font-medium">Rows</th>
                <th className="text-left px-3 py-2 text-gray-500 font-medium">Type</th>
                <th className="text-left px-3 py-2 text-gray-500 font-medium">Last Profiled</th>
              </tr>
            </thead>
            <tbody>
              {filterList(profiles).slice(0, 100).map((p, i) => {
                const rc = p.row_count as number || 0
                const rcStr = rc > 1e9 ? `${(rc/1e9).toFixed(1)}B` : rc > 1e6 ? `${(rc/1e6).toFixed(0)}M` : rc > 1e3 ? `${(rc/1e3).toFixed(0)}K` : String(rc)
                return (
                  <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="px-3 py-1.5 font-mono text-gray-800">{String(p.name)}</td>
                    <td className="px-3 py-1.5 text-right text-gray-600 tabular-nums">{rcStr}</td>
                    <td className="px-3 py-1.5">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                        p.type === 'fact' ? 'bg-blue-50 text-blue-600' :
                        p.type === 'dimension' ? 'bg-green-50 text-green-600' :
                        'bg-gray-100 text-gray-500'
                      }`}>{String(p.type || '?')}</span>
                    </td>
                    <td className="px-3 py-1.5 text-[10px] text-gray-500">
                      {p.last_profiled ? new Date(String(p.last_profiled)).toLocaleDateString() : (
                        p.has_profile ? <CheckCircle size={12} className="text-green-500" /> : <span className="text-gray-300">—</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}

        {/* DOMO Metrics Tab */}
        {activeTab === 'domo' && (
          <table className="w-full text-xs">
            <thead className="bg-gray-50 sticky top-0">
              <tr>
                <th className="text-left px-3 py-2 text-gray-500 font-medium">Metric</th>
                <th className="text-left px-3 py-2 text-gray-500 font-medium">Pillar</th>
                <th className="text-left px-3 py-2 text-gray-500 font-medium">Type</th>
                <th className="text-left px-3 py-2 text-gray-500 font-medium">SQL</th>
                <th className="text-left px-3 py-2 text-gray-500 font-medium">S3 Data</th>
              </tr>
            </thead>
            <tbody>
              {filterList(domoMetrics).slice(0, 100).map((m, i) => (
                <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
                  <td className="px-3 py-1.5 font-mono text-gray-800 truncate max-w-[200px]" title={String(m.name)}>{String(m.name)}</td>
                  <td className="px-3 py-1.5">
                    {m.pillar ? (
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${pillarColors[String(m.pillar)] || 'bg-gray-100 text-gray-500'}`}>
                        {String(m.pillar)}
                      </span>
                    ) : <span className="text-gray-300">—</span>}
                  </td>
                  <td className="px-3 py-1.5 text-gray-500">{String(m.metric_type || '—')}</td>
                  <td className="px-3 py-1.5">
                    {m.has_view_sql ? <CheckCircle size={12} className="text-green-500" /> : <span className="text-gray-300">—</span>}
                  </td>
                  <td className="px-3 py-1.5">
                    {(m.s3_size_mb as number) > 0 ? (
                      <span className="text-[10px] text-gray-600">{String(m.s3_size_mb)}MB</span>
                    ) : <span className="text-gray-300">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {/* Glossary Tab */}
        {activeTab === 'glossary' && (
          <table className="w-full text-xs">
            <thead className="bg-gray-50 sticky top-0">
              <tr>
                <th className="text-left px-3 py-2 text-gray-500 font-medium">Term</th>
                <th className="text-left px-3 py-2 text-gray-500 font-medium">Definition</th>
                <th className="text-left px-3 py-2 text-gray-500 font-medium">Formula</th>
                <th className="text-right px-3 py-2 text-gray-500 font-medium">Sources</th>
              </tr>
            </thead>
            <tbody>
              {filterList(glossary).slice(0, 100).map((g, i) => (
                <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
                  <td className="px-3 py-1.5 font-medium text-gray-800">{String(g.term)}</td>
                  <td className="px-3 py-1.5 text-gray-600 truncate max-w-[300px]">{String(g.definition || '—')}</td>
                  <td className="px-3 py-1.5">
                    {g.has_formula ? <CheckCircle size={12} className="text-green-500" /> : <span className="text-gray-300">—</span>}
                  </td>
                  <td className="px-3 py-1.5 text-right text-gray-500 tabular-nums">{String(g.source_tables || 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}


function AdditionalRepos() {
  const [repos, setRepos] = useState<KBRepo[]>([])
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editToken, setEditToken] = useState('')
  const [form, setForm] = useState({ name: '', url: '', token: '', branch: 'main', parse_all: false })
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    loadRepos()
  }, [])

  async function loadRepos() {
    try {
      const data = await fetchJSON<KBRepo[]>('/kb-repos')
      setRepos(data)
    } catch {
      // ignore
    }
  }

  async function handleAdd() {
    if (!form.name || !form.url) return
    setSaving(true)
    try {
      await fetchJSON('/kb-repos', {
        method: 'POST',
        body: JSON.stringify({
          name: form.name,
          url: form.url,
          token: form.token || null,
          branch: form.branch,
          parse_all: form.parse_all,
        }),
      })
      setForm({ name: '', url: '', token: '', branch: 'main', parse_all: false })
      setShowForm(false)
      await loadRepos()
    } catch (err) {
      alert('Failed to add repo: ' + (err instanceof Error ? err.message : 'Unknown error'))
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(id: number) {
    try {
      await fetchJSON(`/kb-repos/${id}`, { method: 'DELETE' })
      await loadRepos()
    } catch {
      // ignore
    }
  }

  return (
    <div className="border border-gray-200 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <GitBranch size={18} className="text-gray-400" />
          <h4 className="font-medium text-gray-900">Additional Repos</h4>
          <span className="text-xs text-gray-400">({repos.filter(r => r.is_active).length} active)</span>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="text-sm px-3 py-1.5 rounded-lg font-medium border border-gray-300 text-gray-600 hover:bg-gray-50 flex items-center gap-1"
        >
          {showForm ? <X size={14} /> : <Plus size={14} />}
          {showForm ? 'Cancel' : 'Add Repo'}
        </button>
      </div>

      {showForm && (
        <div className="bg-gray-50 rounded-lg p-3 mb-3 space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <input
              type="text"
              placeholder="Repo name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:ring-genie-500 focus:border-genie-500"
            />
            <input
              type="text"
              placeholder="Branch (default: main)"
              value={form.branch}
              onChange={(e) => setForm({ ...form, branch: e.target.value })}
              className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:ring-genie-500 focus:border-genie-500"
            />
          </div>
          <input
            type="text"
            placeholder="https://github.com/org/repo"
            value={form.url}
            onChange={(e) => setForm({ ...form, url: e.target.value })}
            className="w-full text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:ring-genie-500 focus:border-genie-500"
          />
          <input
            type="password"
            placeholder="GitHub token (optional)"
            value={form.token}
            onChange={(e) => setForm({ ...form, token: e.target.value })}
            className="w-full text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:ring-genie-500 focus:border-genie-500"
          />
          <div className="flex items-center justify-between">
            <label className="flex items-center gap-2 text-xs cursor-pointer">
              <input
                type="checkbox"
                checked={form.parse_all}
                onChange={(e) => setForm({ ...form, parse_all: e.target.checked })}
                className="rounded text-genie-600 focus:ring-genie-500"
              />
              <span className="text-gray-600">Parse all files</span>
              <span className="text-gray-400">(not just YAML/SQL)</span>
            </label>
            <button
              onClick={handleAdd}
              disabled={saving || !form.name || !form.url}
              className="text-sm px-4 py-1.5 rounded-lg font-medium bg-genie-600 text-white hover:bg-genie-700 disabled:opacity-50 flex items-center gap-1"
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              Add
            </button>
          </div>
        </div>
      )}

      {repos.length === 0 && !showForm && (
        <p className="text-xs text-gray-400">No additional repos configured. Add repos to include more sources in the knowledge base.</p>
      )}

      {repos.length > 0 && (
        <div className="space-y-1">
          {repos.map((repo) => (
            <div key={repo.id} className={`rounded-lg text-sm ${repo.is_active ? 'bg-white' : 'bg-gray-50 opacity-60'}`}>
              <div className="flex items-center justify-between p-2">
                <div className="flex items-center gap-2 min-w-0 cursor-pointer"
                  onClick={() => setEditingId(editingId === repo.id ? null : repo.id)}>
                  <GitBranch size={14} className={repo.is_active ? 'text-green-500' : 'text-gray-300'} />
                  <span className="font-medium text-gray-700 truncate">{repo.name}</span>
                  <span className="text-xs text-gray-400 font-mono truncate hidden sm:inline">{repo.url}</span>
                  <span className="text-xs bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">{repo.branch}</span>
                  {repo.parse_all && (
                    <span className="text-[10px] bg-blue-100 text-blue-600 px-1.5 py-0.5 rounded-full">all files</span>
                  )}
                  {!repo.is_active && (
                    <span className="text-[10px] bg-red-100 text-red-500 px-1.5 py-0.5 rounded-full">inactive</span>
                  )}
                </div>
                <button
                  onClick={() => handleDelete(repo.id)}
                  className="text-gray-400 hover:text-red-500 p-1"
                  title="Deactivate repo"
                >
                  <Trash2 size={14} />
                </button>
              </div>
              {editingId === repo.id && (
                <div className="px-2 pb-2">
                  <div className="flex gap-2">
                    <input type="password" value={editToken} onChange={e => setEditToken(e.target.value)}
                      placeholder="Update GitHub token" autoComplete="new-password"
                      className="flex-1 text-xs border border-gray-300 rounded px-2 py-1" />
                    <button onClick={async () => {
                      if (!editToken) return
                      try {
                        await fetchJSON(`/kb-repos/${repo.id}`, {
                          method: 'PUT',
                          body: JSON.stringify({ name: repo.name, url: repo.url, branch: repo.branch, parse_all: repo.parse_all, token: editToken }),
                        })
                        setEditToken('')
                        setEditingId(null)
                        await loadRepos()
                      } catch { /* ignore */ }
                    }} disabled={!editToken}
                      className="text-xs px-3 py-1 rounded bg-genie-600 text-white hover:bg-genie-700 disabled:opacity-50">
                      Update Token
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}


interface BuildRecord {
  id: number
  status: string
  triggered_by: string
  duration_seconds: number | null
  sources: Record<string, boolean>
  stats: Record<string, unknown>
  diff: Record<string, { added_count?: number; removed_count?: number; unchanged_count?: number; added?: string[]; removed?: string[]; delta?: number }>
  error: string | null
  created_at: string
}

function KBHistory() {
  const [builds, setBuilds] = useState<BuildRecord[]>([])
  const [expanded, setExpanded] = useState<number | null>(null)

  useEffect(() => {
    fetchJSON<BuildRecord[]>('/catalog-engine/kb/history')
      .then(setBuilds).catch(() => {})
  }, [])

  if (builds.length === 0) return null

  return (
    <div className="mt-6">
      <h4 className="text-sm font-medium text-gray-700 mb-2">Build History</h4>
      <div className="border border-gray-200 rounded-lg overflow-hidden">
        {builds.map(b => (
          <div key={b.id} className="border-b border-gray-100 last:border-0">
            <div
              className="flex items-center gap-3 px-3 py-2 hover:bg-gray-50 cursor-pointer text-xs"
              onClick={() => setExpanded(expanded === b.id ? null : b.id)}
            >
              <span className={`w-2 h-2 rounded-full ${b.status === 'success' ? 'bg-green-400' : (b.status === 'error' || b.status === 'failed') ? 'bg-red-400' : 'bg-yellow-400'}`} />
              <span className="font-medium text-gray-700">Build #{b.id}</span>
              <span className="text-gray-400">{new Date(b.created_at).toLocaleString()}</span>
              {b.duration_seconds && <span className="text-gray-400">{Math.round(Number(b.duration_seconds) / 60)}m</span>}
              {/* Token cost */}
              {(() => {
                const enrichment = (b.stats?.enrichment || {}) as Record<string, number>
                const tokensUsed = enrichment.tokens_used || 0
                if (!tokensUsed) return null
                // Estimate cost — assume Opus pricing for now
                const inputCost = (enrichment.tokens_input || 0) / 1_000_000 * 15
                const outputCost = (enrichment.tokens_output || 0) / 1_000_000 * 75
                const cost = inputCost + outputCost
                return (
                  <span className="text-[10px] bg-purple-50 text-purple-600 px-1.5 py-0.5 rounded-full">
                    {(tokensUsed / 1000).toFixed(0)}K tok · ${cost.toFixed(2)}
                  </span>
                )
              })()}
              {/* Diff summary */}
              {b.diff && Object.entries(b.diff).map(([cat, d]) => {
                if (!d || typeof d !== 'object') return null
                const added = d.added_count || 0
                const removed = d.removed_count || 0
                const delta = d.delta
                if (!added && !removed && delta === undefined) return null
                return (
                  <span key={cat} className="text-[10px]">
                    <span className="text-gray-400">{cat}: </span>
                    {added > 0 && <span className="text-green-600">+{added}</span>}
                    {added > 0 && removed > 0 && <span className="text-gray-300"> / </span>}
                    {removed > 0 && <span className="text-red-500">-{removed}</span>}
                    {delta !== undefined && delta !== 0 && <span className={delta > 0 ? 'text-green-600' : 'text-red-500'}>{delta > 0 ? '+' : ''}{delta}</span>}
                  </span>
                )
              })}
              {(b.status === 'error' || b.status === 'failed') && b.error && <span className="text-red-500 truncate max-w-[300px]">{b.error}</span>}
            </div>
            {expanded === b.id && (
              <div className="px-3 pb-3 bg-gray-50 space-y-2">
                {(b.status === 'error' || b.status === 'failed') && b.error && (
                  <div className="text-[11px] text-red-600 bg-red-50 rounded px-2 py-1 font-mono break-all">{b.error}</div>
                )}
                <div className="flex flex-wrap gap-3 text-[10px] text-gray-500">
                  <span>Triggered by: {b.triggered_by}</span>
                  {b.sources && Object.entries(b.sources).map(([s, v]) => (
                    <span key={s} className={v ? 'text-green-600' : 'text-gray-400'}>{s}: {v ? 'yes' : 'no'}</span>
                  ))}
                </div>
                {/* Enrichment stats */}
                {(() => {
                  const statsObj = (b.stats || {}) as Record<string, unknown>
                  if (!statsObj.enrichment) return null
                  const e = (statsObj.enrichment || {}) as Record<string, number>
                  if (!e.tokens_used) return null
                  const inputCost = (e.tokens_input || 0) / 1_000_000 * 15
                  const outputCost = (e.tokens_output || 0) / 1_000_000 * 75
                  return (
                    <div className="flex flex-wrap gap-3 text-[10px] bg-purple-50 rounded px-2 py-1">
                      <span className="text-purple-700 font-medium">AI Enrichment</span>
                      <span>Input: {((e.tokens_input || 0) / 1000).toFixed(1)}K</span>
                      <span>Output: {((e.tokens_output || 0) / 1000).toFixed(1)}K</span>
                      <span>Total: {((e.tokens_used || 0) / 1000).toFixed(1)}K tokens</span>
                      <span className="font-medium">Cost: ${(inputCost + outputCost).toFixed(2)}</span>
                      {e.pipeline_summaries ? <span>{e.pipeline_summaries} DAG summaries</span> : null}
                      {e.table_descriptions ? <span>{e.table_descriptions} table descriptions</span> : null}
                      {e.column_descriptions ? <span>{e.column_descriptions} column descriptions</span> : null}
                    </div>
                  )
                })()}
                {b.stats && (
                  <div className="flex flex-wrap gap-3 text-[10px]">
                    {Object.entries(b.stats).filter(([k]) => !['errors', 'status'].includes(k)).map(([k, v]) => (
                      <span key={k} className="text-gray-600">{k}: <span className="font-medium">{String(v)}</span></span>
                    ))}
                  </div>
                )}
                {b.diff && Object.entries(b.diff).map(([cat, d]) => {
                  if (!d || typeof d !== 'object') return null
                  const added = (d as any).added as string[] | undefined
                  const removed = (d as any).removed as string[] | undefined
                  if ((!added || added.length === 0) && (!removed || removed.length === 0)) return null
                  return (
                    <div key={cat} className="text-[10px]">
                      <span className="font-medium text-gray-600">{cat}:</span>
                      {added && added.length > 0 && (
                        <div className="ml-2">
                          {added.slice(0, 10).map(a => <span key={a} className="inline-block mr-1 text-green-600 font-mono">+{a}</span>)}
                          {added.length > 10 && <span className="text-gray-400">...and {added.length - 10} more</span>}
                        </div>
                      )}
                      {removed && removed.length > 0 && (
                        <div className="ml-2">
                          {removed.slice(0, 10).map(r => <span key={r} className="inline-block mr-1 text-red-500 font-mono">-{r}</span>)}
                          {removed.length > 10 && <span className="text-gray-400">...and {removed.length - 10} more</span>}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
