import React, { useState, useEffect, useRef } from 'react'
import {
  Database, RefreshCw, Loader2, Play, Square, Trash2,
  CheckCircle, XCircle, Clock, Search, Zap, Calendar, Eye,
  ChevronRight, ChevronDown, Key, Hash, Type, Tag, ArrowUpDown
} from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { fetchJSON } from '../../api/client'

interface TableRow {
  id: number
  schema_name: string
  table_name: string
  database: string
  table_type: string | null
  table_type_auto: string | null
  table_type_manual: string | null
  row_count: number | null
  size_mb: number | null
  last_analyzed_at: string | null
  last_profiled_at: string | null
  analyze_enabled: boolean
  profile_enabled: boolean
  profile_data: Record<string, unknown> | null
  metadata: Record<string, unknown>
  updated_at: string
}

interface Job {
  id: number
  operation: string
  schema_name: string
  table_name: string
  environment: string
  status: string
  duration_seconds: number | null
  error: string | null
  created_at: string
  completed_at: string | null
}

interface RunnerStatus {
  running: boolean
  current_job: { id: number; operation: string; table: string; environment: string } | null
  queue_depth: number
  recent_jobs: Job[]
}

interface Schedule {
  id: number
  operation: string
  schema_name: string | null
  table_name: string | null
  cron_expression: string
  timeout_seconds: number
  enabled: boolean
}

interface DiscoverProgress {
  status: string
  phase: string
  found?: number
  total_in_registry?: number
  error?: string
  running: boolean
}

export default function TableOpsTab() {
  const { sessionId } = useAuth()
  const [tables, setTables] = useState<TableRow[]>([])
  const [runnerStatus, setRunnerStatus] = useState<RunnerStatus | null>(null)
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [loading, setLoading] = useState(true)
  const [timeout, setTimeout_] = useState(120)
  const [filter, setFilter] = useState('')
  const [dbFilter, setDbFilter] = useState('')
  const [schemaFilter, setSchemaFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [sortCol, setSortCol] = useState<string>('table_name')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [discoverProgress, setDiscoverProgress] = useState<DiscoverProgress | null>(null)
  const [activeSection, setActiveSection] = useState<'tables' | 'schedules'>('tables')
  const [capabilities, setCapabilities] = useState<{
    can_profile: boolean; can_analyze: boolean; can_discover_np: boolean; can_discover_prd: boolean
  }>({ can_profile: false, can_analyze: false, can_discover_np: false, can_discover_prd: false })

  // Discovery form
  const [discEnv, setDiscEnv] = useState('np')
  const [discDatabases, setDiscDatabases] = useState('')
  const [discSchemas, setDiscSchemas] = useState('')
  const [discTypes, setDiscTypes] = useState<string[]>(['TABLE', 'VIEW'])

  // Schedule form
  const [newSchedOp, setNewSchedOp] = useState('profile')
  const [newSchedCron, setNewSchedCron] = useState('0 2 * * 0')
  const [newSchedDb, setNewSchedDb] = useState('')
  const [newSchedSchema, setNewSchedSchema] = useState('')
  const [newSchedTables, setNewSchedTables] = useState<Set<string>>(new Set())

  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const discoverPollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    loadAll()
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
      if (discoverPollRef.current) clearInterval(discoverPollRef.current)
    }
  }, [])

  async function loadAll() {
    setLoading(true)
    try {
      const [t, s, sc, cap] = await Promise.all([
        fetchJSON<TableRow[]>('/table-ops/tables'),
        fetchJSON<RunnerStatus>('/table-ops/jobs/status'),
        fetchJSON<Schedule[]>('/table-ops/schedules'),
        fetchJSON<typeof capabilities>('/table-ops/capabilities'),
      ])
      setTables(t)
      setRunnerStatus(s)
      setSchedules(sc)
      setCapabilities(cap)
      if (s.running) startJobPolling()
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  function startJobPolling() {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const s = await fetchJSON<RunnerStatus>('/table-ops/jobs/status')
        setRunnerStatus(s)
        if (!s.running) {
          if (pollRef.current) clearInterval(pollRef.current)
          pollRef.current = null
          const t = await fetchJSON<TableRow[]>('/table-ops/tables')
          setTables(t)
        }
      } catch { /* ignore */ }
    }, 3000)
  }

  async function handleDiscover() {
    const body: Record<string, unknown> = {
      session_id: sessionId,
      environment: discEnv,
      object_types: discTypes,
      include_lineage_score: true,
    }
    if (discDatabases.trim()) body.databases = discDatabases.split(',').map(s => s.trim())
    if (discSchemas.trim()) body.schemas = discSchemas.split(',').map(s => s.trim())

    await fetchJSON('/table-ops/tables/discover', {
      method: 'POST',
      body: JSON.stringify(body),
    })

    // Poll discover status
    if (discoverPollRef.current) clearInterval(discoverPollRef.current)
    discoverPollRef.current = setInterval(async () => {
      const dp = await fetchJSON<DiscoverProgress>('/table-ops/tables/discover/status')
      setDiscoverProgress(dp)
      if (!dp.running) {
        if (discoverPollRef.current) clearInterval(discoverPollRef.current)
        discoverPollRef.current = null
        await loadAll()
      }
    }, 2000)
  }

  async function handleDiscoverLocal() {
    await fetchJSON('/table-ops/tables/discover/local', { method: 'POST' })
    await loadAll()
  }

  async function queueOperation(op: 'analyze' | 'profile') {
    const ids = Array.from(selected)
    if (!ids.length) return
    await fetchJSON('/table-ops/jobs/queue', {
      method: 'POST',
      body: JSON.stringify({ operation: op, table_ids: ids, timeout_seconds: timeout }),
    })
    await fetchJSON('/table-ops/jobs/start', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId }),
    })
    setSelected(new Set())
    startJobPolling()
    const s = await fetchJSON<RunnerStatus>('/table-ops/jobs/status')
    setRunnerStatus(s)
  }

  async function handleKill() {
    await fetchJSON('/table-ops/jobs/kill', { method: 'POST' })
    const s = await fetchJSON<RunnerStatus>('/table-ops/jobs/status')
    setRunnerStatus(s)
  }

  async function handleClearQueue() {
    await fetchJSON('/table-ops/jobs/clear', { method: 'DELETE' })
    const s = await fetchJSON<RunnerStatus>('/table-ops/jobs/status')
    setRunnerStatus(s)
  }

  async function setManualType(id: number, type: string) {
    await fetchJSON(`/table-ops/tables/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ table_type_manual: type }),
    })
    setTables(prev => prev.map(t => t.id === id ? { ...t, table_type_manual: type || null, table_type: type || t.table_type_auto } : t))
  }

  async function addSchedule() {
    const selectedTables = [...newSchedTables]
    if (selectedTables.length === 0) {
      // Schedule for all tables in schema
      await fetchJSON('/table-ops/schedules', {
        method: 'POST',
        body: JSON.stringify({
          operation: newSchedOp,
          cron_expression: newSchedCron,
          schema_name: newSchedSchema || null,
          table_name: null,
          timeout_seconds: timeout,
        }),
      })
    } else {
      // Create one schedule per selected table
      for (const tbl of selectedTables) {
        await fetchJSON('/table-ops/schedules', {
          method: 'POST',
          body: JSON.stringify({
            operation: newSchedOp,
            cron_expression: newSchedCron,
            schema_name: newSchedSchema || null,
            table_name: tbl,
            timeout_seconds: timeout,
          }),
        })
      }
    }
    const sc = await fetchJSON<Schedule[]>('/table-ops/schedules')
    setSchedules(sc)
    setNewSchedDb('')
    setNewSchedSchema('')
    setNewSchedTables(new Set())
  }

  async function deleteSchedule(id: number) {
    await fetchJSON(`/table-ops/schedules/${id}`, { method: 'DELETE' })
    setSchedules(prev => prev.filter(s => s.id !== id))
  }

  async function toggleSchedule(id: number) {
    await fetchJSON(`/table-ops/schedules/${id}/toggle`, { method: 'PUT' })
    setSchedules(prev => prev.map(s => s.id === id ? { ...s, enabled: !s.enabled } : s))
  }

  function toggleSelect(id: number) {
    setSelected(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  }

  const databases = [...new Set(tables.map(t => t.database))].sort()
  const schemasForDb = [...new Set(tables.filter(t => !dbFilter || t.database === dbFilter).map(t => t.schema_name))].sort()
  const objectTypes = [...new Set(tables.map(t => (t.metadata as any)?.object_type || '').filter(Boolean))].sort()

  function toggleSort(col: string) {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(col); setSortDir('asc') }
  }

  const filteredTables = tables.filter(t => {
    if (dbFilter && t.database !== dbFilter) return false
    if (schemaFilter && t.schema_name !== schemaFilter) return false
    if (typeFilter && (t.metadata as any)?.object_type !== typeFilter) return false
    if (filter && !`${t.schema_name}.${t.table_name}`.toLowerCase().includes(filter.toLowerCase())) return false
    return true
  }).sort((a, b) => {
    const dir = sortDir === 'asc' ? 1 : -1
    const getValue = (t: TableRow): any => {
      switch (sortCol) {
        case 'database': return t.database || ''
        case 'table_name': return `${t.schema_name}.${t.table_name}`
        case 'object_type': return (t.metadata as any)?.object_type || ''
        case 'references': return (t.metadata as any)?.lineage_score || 0
        case 'row_count': return t.row_count || 0
        case 'last_analyzed_at': return t.last_analyzed_at || ''
        case 'last_profiled_at': return t.last_profiled_at || ''
        case 'auto_type': return t.table_type_auto || ''
        default: return ''
      }
    }
    const va = getValue(a)
    const vb = getValue(b)
    if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir
    return String(va).localeCompare(String(vb)) * dir
  })

  const isRunning = runnerStatus?.running

  if (loading) {
    return <div className="flex items-center justify-center py-12"><Loader2 className="animate-spin text-gray-400" /></div>
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div>
        <h3 className="text-base font-medium text-gray-900">Table Operations</h3>
        <p className="text-xs text-gray-500">Discover from prod Redshift, ANALYZE on prod (stats), PROFILE on nonprod via datashare</p>
      </div>

      {/* Section Toggle */}
      <div className="flex gap-1 border-b border-gray-200">
        {(['tables', 'schedules'] as const).map(s => (
          <button key={s} onClick={() => setActiveSection(s)}
            className={`px-4 py-2 text-sm rounded-t-lg ${activeSection === s
              ? 'bg-white text-gray-900 font-medium border border-gray-200 border-b-white -mb-px'
              : 'text-gray-500 hover:text-gray-700'}`}>
            {s === 'tables' ? `Tables (${tables.length})` : `Schedules (${schedules.length})`}
          </button>
        ))}
      </div>

      {activeSection === 'tables' && (
        <>
          {/* Discovery Controls */}
          <div className="border border-gray-200 rounded-lg p-4">
            <h4 className="text-sm font-medium text-gray-700 mb-3 flex items-center gap-2">
              <Eye size={14} /> Discover from Prod Redshift
            </h4>
            <div className="flex items-end gap-3 flex-wrap">
              <div>
                <label className="text-[10px] text-gray-500 block mb-1">Environment</label>
                <select value={discEnv} onChange={e => setDiscEnv(e.target.value)}
                  className="text-xs border border-gray-300 rounded px-2 py-1.5">
                  <option value="np">Nonprod</option>
                  <option value="prd">Prod</option>
                </select>
              </div>
              <div>
                <label className="text-[10px] text-gray-500 block mb-1">Databases (comma-sep, empty=all)</label>
                <input value={discDatabases} onChange={e => setDiscDatabases(e.target.value)}
                  placeholder="prd_dw, prd_data_lake"
                  className="text-xs border border-gray-300 rounded px-2 py-1.5 w-48" />
              </div>
              <div>
                <label className="text-[10px] text-gray-500 block mb-1">Schemas (empty=all)</label>
                <input value={discSchemas} onChange={e => setDiscSchemas(e.target.value)}
                  placeholder="analytics, dim, fact"
                  className="text-xs border border-gray-300 rounded px-2 py-1.5 w-48" />
              </div>
              <div>
                <label className="text-[10px] text-gray-500 block mb-1">Object Types</label>
                <div className="flex gap-2">
                  {['TABLE', 'VIEW'].map(t => (
                    <label key={t} className="flex items-center gap-1 text-xs">
                      <input type="checkbox" checked={discTypes.includes(t)}
                        onChange={() => setDiscTypes(prev => prev.includes(t) ? prev.filter(x => x !== t) : [...prev, t])}
                        className="rounded text-genie-600" />
                      {t}
                    </label>
                  ))}
                </div>
              </div>
              <button onClick={handleDiscover}
                disabled={discoverProgress?.running}
                className="text-sm px-3 py-1.5 rounded-lg bg-genie-600 text-white hover:bg-genie-700 disabled:opacity-50 flex items-center gap-1">
                {discoverProgress?.running ? <Loader2 size={14} className="animate-spin" /> : <Database size={14} />}
                Discover from Redshift
              </button>
              <button onClick={handleDiscoverLocal}
                className="text-xs text-gray-500 hover:text-gray-700 underline">
                or from knowledge base
              </button>
            </div>
            {discoverProgress && discoverProgress.status !== 'success' && discoverProgress.running && (
              <div className="mt-2 text-xs text-blue-600 flex items-center gap-1">
                <Loader2 size={12} className="animate-spin" />
                {discoverProgress.phase} {discoverProgress.found ? `(${discoverProgress.found} found)` : ''}
              </div>
            )}
            {discoverProgress?.status === 'success' && (
              <div className="mt-2 text-xs text-green-600">
                Discovered {discoverProgress.found} objects. {discoverProgress.total_in_registry} total in registry.
              </div>
            )}
            {discoverProgress?.status === 'error' && (
              <div className="mt-2 text-xs text-red-600">Error: {discoverProgress.error}</div>
            )}
          </div>

          {/* Runner Status */}
          {isRunning && runnerStatus?.current_job && (
            <div className="bg-blue-50 rounded-lg p-3 flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm text-blue-700">
                <Loader2 size={14} className="animate-spin" />
                <span className="font-medium">
                  {runnerStatus.current_job.operation.toUpperCase()} {runnerStatus.current_job.table}
                </span>
                <span className="text-blue-500">({runnerStatus.current_job.environment})</span>
                {runnerStatus.queue_depth > 0 && (
                  <span className="text-xs bg-blue-100 px-2 py-0.5 rounded-full">+{runnerStatus.queue_depth} queued</span>
                )}
              </div>
              <div className="flex gap-2">
                <button onClick={handleKill} className="text-xs text-red-600 hover:text-red-800 flex items-center gap-1">
                  <Square size={12} /> Kill
                </button>
                <button onClick={handleClearQueue} className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1">
                  <Trash2 size={12} /> Clear Queue
                </button>
              </div>
            </div>
          )}

          {/* Filters + Actions */}
          <div className="flex items-center gap-2 flex-wrap">
            <select value={dbFilter} onChange={e => { setDbFilter(e.target.value); setSchemaFilter('') }}
              className="text-xs border border-gray-300 rounded px-2 py-1.5 bg-white">
              <option value="">All DB</option>
              {databases.map(db => <option key={db} value={db}>{db}</option>)}
            </select>
            <select value={schemaFilter} onChange={e => setSchemaFilter(e.target.value)}
              className="text-xs border border-gray-300 rounded px-2 py-1.5 bg-white">
              <option value="">All schemas</option>
              {schemasForDb.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)}
              className="text-xs border border-gray-300 rounded px-2 py-1.5 bg-white">
              <option value="">All types</option>
              {objectTypes.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
            <div className="relative flex-1 max-w-[200px]">
              <Search size={12} className="absolute left-2 top-2 text-gray-400" />
              <input value={filter} onChange={e => setFilter(e.target.value)}
                placeholder="Search..."
                className="w-full pl-7 pr-2 py-1.5 text-xs border border-gray-300 rounded focus:ring-genie-500" />
            </div>
            <span className="text-[10px] text-gray-400">
              {filteredTables.length} tables{selected.size > 0 && <span className="text-genie-600 font-semibold"> &middot; {selected.size} selected</span>}
            </span>
            <div className="border-l border-gray-300 h-4" />
            <label className="text-[10px] text-gray-500 flex items-center gap-1">
              Timeout: <input type="number" value={timeout} onChange={e => setTimeout_(+e.target.value)}
                className="w-14 px-1 py-0.5 text-[10px] border border-gray-300 rounded" />s
            </label>
            <button onClick={() => queueOperation('analyze')}
              disabled={!selected.size || !!isRunning || !capabilities.can_analyze}
              title={!capabilities.can_analyze ? 'Requires prod Redshift credentials' : ''}
              className="text-xs px-2.5 py-1.5 rounded bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-50 flex items-center gap-1">
              <Play size={12} /> ANALYZE ({selected.size})
              {!capabilities.can_analyze && <span className="text-[9px] opacity-75">(no prod creds)</span>}
            </button>
            <button onClick={() => queueOperation('profile')}
              disabled={!selected.size || !!isRunning || !capabilities.can_profile}
              title={!capabilities.can_profile ? 'Requires nonprod Redshift credentials' : ''}
              className="text-xs px-2.5 py-1.5 rounded bg-genie-600 text-white hover:bg-genie-700 disabled:opacity-50 flex items-center gap-1">
              <Play size={12} /> PROFILE ({selected.size})
              {!capabilities.can_profile && <span className="text-[9px] opacity-75">(no np creds)</span>}
            </button>
          </div>

          {/* Table List */}
          <div className="border border-gray-200 rounded-lg overflow-auto max-h-[500px]">
            <table className="w-full text-[11px]">
              <thead className="bg-gray-50 text-gray-500 uppercase sticky top-0">
                <tr>
                  <th className="w-7 px-1 py-2">
                    <input type="checkbox"
                      checked={filteredTables.length > 0 && filteredTables.every(t => selected.has(t.id))}
                      onChange={e => {
                        if (e.target.checked) setSelected(new Set(filteredTables.map(t => t.id)))
                        else setSelected(new Set())
                      }}
                      className="rounded text-genie-600 focus:ring-genie-500" />
                  </th>
                  {[
                    { key: 'database', label: 'DB', align: 'left' },
                    { key: 'table_name', label: 'Table', align: 'left' },
                    { key: 'object_type', label: 'Table/View', align: 'center' },
                    { key: 'references', label: 'References', align: 'center', title: 'Lineage: # upstream + downstream DAG dependencies' },
                    { key: 'row_count', label: 'Rows', align: 'right' },
                    { key: 'last_analyzed_at', label: 'Last Analyzed', align: 'center' },
                    { key: 'last_profiled_at', label: 'Last Profiled', align: 'center' },
                    { key: 'auto_type', label: 'Auto Type', align: 'center' },
                  ].map(col => (
                    <th key={col.key}
                      className={`px-2 py-2 text-${col.align} cursor-pointer hover:bg-gray-100 select-none`}
                      title={col.title}
                      onClick={() => toggleSort(col.key)}>
                      <span className="inline-flex items-center gap-0.5">
                        {col.label}
                        {sortCol === col.key && (
                          <span className="text-genie-600">{sortDir === 'asc' ? '\u2191' : '\u2193'}</span>
                        )}
                      </span>
                    </th>
                  ))}
                  <th className="px-2 py-2 text-center">Manual Type</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filteredTables.map(t => {
                  const lineageScore = (t.metadata as any)?.lineage_score || 0
                  const objType = (t.metadata as any)?.object_type || ''
                  const isExpanded = expanded.has(t.id)
                  const profileData = t.profile_data as any
                  const hasProfile = profileData && profileData.columns && Object.keys(profileData.columns).length > 0
                  return (
                    <React.Fragment key={t.id}>
                    <tr className={`hover:bg-gray-50 ${selected.has(t.id) ? 'bg-genie-50' : ''} ${isExpanded ? 'bg-gray-50' : ''}`}>
                      <td className="px-1 py-1.5 text-center">
                        <input type="checkbox" checked={selected.has(t.id)} onChange={() => toggleSelect(t.id)}
                          className="rounded text-genie-600 focus:ring-genie-500" />
                      </td>
                      <td className="px-2 py-1.5 text-gray-400 font-mono text-[10px]">{t.database}</td>
                      <td className="px-2 py-1.5 font-mono text-gray-900">
                        <button
                          onClick={() => setExpanded(prev => {
                            const next = new Set(prev)
                            next.has(t.id) ? next.delete(t.id) : next.add(t.id)
                            return next
                          })}
                          className="flex items-center gap-1 hover:text-genie-600"
                          disabled={!hasProfile}
                        >
                          {hasProfile ? (isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />) : <span className="w-3" />}
                          <span className="text-gray-500">{t.schema_name}.</span><span className="font-semibold">{t.table_name}</span>
                        </button>
                      </td>
                      <td className="px-2 py-1.5 text-center">
                        {objType && (
                          <span className={`text-[9px] px-1 py-0.5 rounded ${
                            objType === 'TABLE' ? 'bg-blue-50 text-blue-600' : 'bg-orange-50 text-orange-600'
                          }`}>{objType}</span>
                        )}
                      </td>
                      <td className="px-2 py-1.5 text-center">
                        {lineageScore > 0 && (
                          <span className={`inline-flex items-center gap-0.5 text-[10px] font-medium ${
                            lineageScore >= 10 ? 'text-red-600' : lineageScore >= 5 ? 'text-amber-600' : 'text-gray-500'
                          }`}>
                            <Zap size={10} /> {lineageScore}
                          </span>
                        )}
                      </td>
                      <td className="px-2 py-1.5 text-right text-gray-600 font-mono">
                        {t.row_count != null ? t.row_count.toLocaleString() : ''}
                      </td>
                      <td className="px-2 py-1.5 text-center">
                        {t.last_analyzed_at ? (
                          <span className="text-[9px] text-green-700 bg-green-50 px-1 py-0.5 rounded whitespace-nowrap">
                            {new Date(t.last_analyzed_at).toLocaleDateString()} {new Date(t.last_analyzed_at).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}
                          </span>
                        ) : <span className="text-gray-200">-</span>}
                      </td>
                      <td className="px-2 py-1.5 text-center">
                        {t.last_profiled_at ? (
                          <span className="text-[9px] text-green-700 bg-green-50 px-1 py-0.5 rounded whitespace-nowrap">
                            {new Date(t.last_profiled_at).toLocaleDateString()} {new Date(t.last_profiled_at).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}
                          </span>
                        ) : <span className="text-gray-200">-</span>}
                      </td>
                      <td className="px-2 py-1.5 text-center">
                        {(t.table_type_auto) && (
                          <span className={`text-[9px] px-1 py-0.5 rounded ${
                            t.table_type_auto === 'fact' ? 'bg-purple-50 text-purple-600' :
                            t.table_type_auto === 'dimension' ? 'bg-cyan-50 text-cyan-600' : 'bg-gray-50 text-gray-500'
                          }`}>{t.table_type_auto}</span>
                        )}
                      </td>
                      <td className="px-2 py-1.5 text-center">
                        <select value={t.table_type_manual || ''} onChange={e => setManualType(t.id, e.target.value)}
                          className="text-[10px] border border-gray-200 rounded px-1 py-0.5 bg-white w-16">
                          <option value="">auto</option>
                          <option value="fact">fact</option>
                          <option value="dimension">dim</option>
                          <option value="staging">stage</option>
                          <option value="view">view</option>
                        </select>
                      </td>
                    </tr>
                    {isExpanded && hasProfile && (
                      <tr>
                        <td colSpan={10} className="p-0">
                          <ColumnProfilePanel profileData={profileData} />
                        </td>
                      </tr>
                    )}
                    </React.Fragment>
                  )
                })}
              </tbody>
            </table>
            {filteredTables.length === 0 && (
              <div className="text-center py-8 text-xs text-gray-400">
                {tables.length === 0 ? 'No tables. Click "Discover from Redshift" to populate.' : 'No tables match filters.'}
              </div>
            )}
          </div>

          {/* Recent Jobs */}
          {runnerStatus?.recent_jobs && runnerStatus.recent_jobs.length > 0 && (
            <RecentJobs jobs={runnerStatus.recent_jobs} />
          )}
        </>
      )}

      {activeSection === 'schedules' && (
        <div className="space-y-4">
          {/* Schedule Runner Toggle */}
          <ScheduleRunnerToggle />

          {/* Add Schedule */}
          <div className="border border-gray-200 rounded-lg p-4">
            <h4 className="text-sm font-medium text-gray-700 mb-3 flex items-center gap-2">
              <Calendar size={14} /> Add Schedule
            </h4>
            <div className="flex items-end gap-3 flex-wrap">
              <div>
                <label className="text-[10px] text-gray-500 block mb-1">Operation</label>
                <select value={newSchedOp} onChange={e => setNewSchedOp(e.target.value)}
                  className="text-xs border border-gray-300 rounded px-2 py-1.5">
                  <option value="profile">PROFILE</option>
                  <option value="analyze">ANALYZE</option>
                </select>
              </div>
              <div>
                <label className="text-[10px] text-gray-500 block mb-1">Cron Expression</label>
                <input value={newSchedCron} onChange={e => setNewSchedCron(e.target.value)}
                  placeholder="0 2 * * 0"
                  className="text-xs border border-gray-300 rounded px-2 py-1.5 w-32 font-mono" />
              </div>
              <div>
                <label className="text-[10px] text-gray-500 block mb-1">Database</label>
                <select value={newSchedDb} onChange={e => { setNewSchedDb(e.target.value); setNewSchedSchema(''); setNewSchedTables(new Set()) }}
                  className="text-xs border border-gray-300 rounded px-2 py-1.5">
                  <option value="">All</option>
                  {databases.map(d => <option key={d} value={d}>{d}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[10px] text-gray-500 block mb-1">Schema</label>
                <select value={newSchedSchema} onChange={e => { setNewSchedSchema(e.target.value); setNewSchedTables(new Set()) }}
                  className="text-xs border border-gray-300 rounded px-2 py-1.5">
                  <option value="">All in {newSchedDb || 'database'}</option>
                  {[...new Set(tables.filter(t => !newSchedDb || t.database === newSchedDb).map(t => t.schema_name))].sort()
                    .map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <button onClick={addSchedule}
                className="text-xs px-3 py-1.5 rounded bg-genie-600 text-white hover:bg-genie-700 flex items-center gap-1">
                <Calendar size={12} /> Add {newSchedTables.size > 0 ? `(${newSchedTables.size} tables)` : ''}
              </button>
            </div>

            {/* Table checklist — shown when db+schema selected */}
            {newSchedSchema && (() => {
              const filteredTables = tables
                .filter(t => (!newSchedDb || t.database === newSchedDb) && t.schema_name === newSchedSchema)
                .sort((a, b) => a.table_name.localeCompare(b.table_name))
              return filteredTables.length > 0 ? (
                <div className="mt-2 border border-gray-200 rounded-lg overflow-y-auto" style={{ maxHeight: '200px' }}>
                  <div className="px-2 py-1.5 bg-gray-50 border-b border-gray-200 flex items-center justify-between sticky top-0">
                    <span className="text-[10px] text-gray-500">
                      {newSchedTables.size === 0 ? 'All tables (or select specific)' : `${newSchedTables.size} of ${filteredTables.length} selected`}
                    </span>
                    <div className="flex gap-2">
                      <button onClick={() => setNewSchedTables(new Set(filteredTables.map(t => t.table_name)))}
                        className="text-[10px] text-genie-600 hover:underline">Select all</button>
                      <button onClick={() => setNewSchedTables(new Set())}
                        className="text-[10px] text-gray-400 hover:underline">Clear</button>
                    </div>
                  </div>
                  {filteredTables.map(t => (
                    <label key={t.id} className="flex items-center gap-2 px-2 py-1 hover:bg-gray-50 cursor-pointer text-[11px]">
                      <input type="checkbox"
                        checked={newSchedTables.has(t.table_name)}
                        onChange={e => {
                          const next = new Set(newSchedTables)
                          if (e.target.checked) next.add(t.table_name)
                          else next.delete(t.table_name)
                          setNewSchedTables(next)
                        }}
                        className="rounded text-genie-600 focus:ring-genie-500" />
                      <span className="font-mono text-gray-700">{t.table_name}</span>
                      <span className="text-[9px] text-gray-400 ml-auto">{t.row_count?.toLocaleString() || ''} rows</span>
                    </label>
                  ))}
                </div>
              ) : null
            })()}

            <p className="text-[10px] text-gray-400 mt-2">
              Cron format: minute hour day-of-month month day-of-week. Example: "0 2 * * 0" = every Sunday at 2am.
              {newSchedTables.size === 0 && newSchedSchema ? ' No tables selected = schedules all tables in schema.' : ''}
            </p>
          </div>

          {/* Schedule List */}
          {schedules.length > 0 ? (
            <div className="border border-gray-200 rounded-lg overflow-hidden">
              <table className="w-full text-xs">
                <thead className="bg-gray-50 text-gray-500 uppercase">
                  <tr>
                    <th className="px-3 py-2 text-left">Operation</th>
                    <th className="px-3 py-2 text-left">Scope</th>
                    <th className="px-3 py-2 text-left font-mono">Cron</th>
                    <th className="px-3 py-2 text-center">Timeout</th>
                    <th className="px-3 py-2 text-center">Enabled</th>
                    <th className="px-3 py-2 text-center">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {schedules.map(s => (
                    <tr key={s.id} className="hover:bg-gray-50">
                      <td className="px-3 py-2 font-medium">{s.operation.toUpperCase()}</td>
                      <td className="px-3 py-2 font-mono text-gray-600">
                        {s.schema_name ? `${s.schema_name}${s.table_name ? '.' + s.table_name : '.*'}` : 'all enabled'}
                      </td>
                      <td className="px-3 py-2 font-mono">{s.cron_expression}</td>
                      <td className="px-3 py-2 text-center">{s.timeout_seconds}s</td>
                      <td className="px-3 py-2 text-center">
                        <button onClick={() => toggleSchedule(s.id)}
                          className={`text-xs px-2 py-0.5 rounded ${s.enabled ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                          {s.enabled ? 'ON' : 'OFF'}
                        </button>
                      </td>
                      <td className="px-3 py-2 text-center">
                        <button onClick={() => deleteSchedule(s.id)} className="text-red-500 hover:text-red-700">
                          <Trash2 size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-8 text-sm text-gray-400">
              No schedules configured. Add one above.
            </div>
          )}
        </div>
      )}
    </div>
  )
}


const CATEGORY_STYLES: Record<string, { bg: string; text: string; icon: any }> = {
  primary_key: { bg: 'bg-amber-50', text: 'text-amber-700', icon: Key },
  foreign_key: { bg: 'bg-orange-50', text: 'text-orange-600', icon: Key },
  metric: { bg: 'bg-purple-50', text: 'text-purple-700', icon: Hash },
  dimension: { bg: 'bg-cyan-50', text: 'text-cyan-700', icon: Tag },
  date: { bg: 'bg-blue-50', text: 'text-blue-700', icon: Clock },
  flag: { bg: 'bg-green-50', text: 'text-green-700', icon: CheckCircle },
  unknown: { bg: 'bg-gray-50', text: 'text-gray-500', icon: Type },
}

function ColumnProfilePanel({ profileData }: { profileData: any }) {
  const columns = profileData?.columns || {}
  const classifications = profileData?.column_classifications || {}
  const tableClass = profileData?.table_classification

  const colEntries = Object.entries(columns) as [string, any][]

  return (
    <div className="bg-gray-50 border-t border-gray-200">
      {/* Table classification summary */}
      {tableClass && (
        <div className="px-4 py-2 border-b border-gray-200 flex items-center gap-3 text-[10px]">
          <span className="text-gray-500">Classification:</span>
          <span className={`font-semibold px-1.5 py-0.5 rounded ${
            tableClass.classification === 'fact' ? 'bg-purple-100 text-purple-700' :
            tableClass.classification === 'dimension' ? 'bg-cyan-100 text-cyan-700' :
            'bg-gray-100 text-gray-600'
          }`}>{tableClass.classification}</span>
          <span className="text-gray-400">
            fact={tableClass.fact_score} dim={tableClass.dim_score} conf={tableClass.confidence}
          </span>
          <span className="text-gray-400 truncate flex-1" title={tableClass.signals?.join(', ')}>
            {tableClass.signals?.join(' | ')}
          </span>
        </div>
      )}

      {/* Column table */}
      <div className="overflow-auto max-h-[300px]">
        <table className="w-full text-[10px]">
          <thead className="bg-gray-100 text-gray-500 uppercase sticky top-0">
            <tr>
              <th className="px-3 py-1.5 text-left">Column</th>
              <th className="px-3 py-1.5 text-left">Type</th>
              <th className="px-3 py-1.5 text-center">Category</th>
              <th className="px-3 py-1.5 text-right">Distinct</th>
              <th className="px-3 py-1.5 text-right">Cardinality</th>
              <th className="px-3 py-1.5 text-right">Nulls</th>
              <th className="px-3 py-1.5 text-right">Null %</th>
              <th className="px-3 py-1.5 text-right">Min</th>
              <th className="px-3 py-1.5 text-right">Max</th>
              <th className="px-3 py-1.5 text-left">Signals</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {colEntries.map(([colName, info]) => {
              const cls = classifications[colName] || { category: 'unknown', confidence: 0, signals: [] }
              const style = CATEGORY_STYLES[cls.category] || CATEGORY_STYLES.unknown
              const Icon = style.icon
              return (
                <tr key={colName} className="hover:bg-white">
                  <td className="px-3 py-1 font-mono font-medium text-gray-900">{colName}</td>
                  <td className="px-3 py-1 font-mono text-gray-500">{info.type}</td>
                  <td className="px-3 py-1 text-center">
                    <span className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-medium ${style.bg} ${style.text}`}>
                      <Icon size={9} />
                      {cls.category}
                    </span>
                  </td>
                  <td className="px-3 py-1 text-right font-mono">{info.distinct_count?.toLocaleString() ?? ''}</td>
                  <td className="px-3 py-1 text-right font-mono">
                    {info.cardinality_ratio != null && (
                      <span className={info.cardinality_ratio > 0.9 ? 'text-green-600' : info.cardinality_ratio < 0.1 ? 'text-amber-600' : ''}>
                        {(info.cardinality_ratio * 100).toFixed(1)}%
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-1 text-right font-mono">{info.null_count?.toLocaleString() ?? ''}</td>
                  <td className="px-3 py-1 text-right font-mono">
                    {info.null_rate != null && (
                      <span className={info.null_rate > 0.1 ? 'text-red-600' : info.null_rate > 0 ? 'text-amber-600' : 'text-green-600'}>
                        {(info.null_rate * 100).toFixed(1)}%
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-1 text-right font-mono text-gray-500 truncate max-w-[80px]" title={info.min ?? ''}>
                    {info.min ?? ''}
                  </td>
                  <td className="px-3 py-1 text-right font-mono text-gray-500 truncate max-w-[80px]" title={info.max ?? ''}>
                    {info.max ?? ''}
                  </td>
                  <td className="px-3 py-1 text-gray-400 truncate max-w-[150px]" title={cls.signals?.join(', ')}>
                    {cls.signals?.join(', ')}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {profileData?.row_count != null && (
        <div className="px-4 py-1.5 border-t border-gray-200 text-[10px] text-gray-400">
          {profileData.row_count.toLocaleString()} rows, {colEntries.length} columns
          {profileData.sampled && ` (sampled ${profileData.sample_rows?.toLocaleString()} rows)`}
        </div>
      )}
    </div>
  )
}

function RecentJobs({ jobs }: { jobs: Job[] }) {
  const [statusFilter, setStatusFilter] = useState('')
  const [jobSearch, setJobSearch] = useState('')

  const statuses = [...new Set(jobs.map(j => j.status))].sort()
  const counts = {
    completed: jobs.filter(j => j.status === 'completed').length,
    running: jobs.filter(j => j.status === 'running').length,
    queued: jobs.filter(j => j.status === 'queued').length,
    failed: jobs.filter(j => ['failed', 'killed', 'timeout'].includes(j.status)).length,
  }

  const filtered = jobs.filter(j => {
    if (statusFilter && j.status !== statusFilter) return false
    if (jobSearch && !`${j.schema_name}.${j.table_name}`.toLowerCase().includes(jobSearch.toLowerCase())) return false
    return true
  })

  return (
    <div>
      <div className="flex items-center gap-2 mb-1.5 flex-wrap">
        <h4 className="text-xs font-medium text-gray-700">Recent Jobs</h4>
        <span className="text-[10px] text-gray-400">
          {counts.completed} completed, {counts.running} running, {counts.queued} queued
          {counts.failed > 0 && `, ${counts.failed} failed`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
            className="text-[10px] border border-gray-300 rounded px-1.5 py-0.5 bg-white">
            <option value="">All status</option>
            {statuses.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <div className="relative">
            <Search size={10} className="absolute left-1.5 top-1 text-gray-400" />
            <input value={jobSearch} onChange={e => setJobSearch(e.target.value)}
              placeholder="Filter table..."
              className="pl-5 pr-2 py-0.5 text-[10px] border border-gray-300 rounded w-28" />
          </div>
        </div>
      </div>
      <div className="border border-gray-200 rounded-lg overflow-y-auto" style={{ maxHeight: '350px' }}>
        <table className="w-full text-[10px]">
          <thead className="bg-gray-50 text-gray-500 uppercase sticky top-0 z-10">
            <tr>
              <th className="px-2 py-1.5 text-left">Op</th>
              <th className="px-2 py-1.5 text-left">Database</th>
              <th className="px-2 py-1.5 text-left">Table</th>
              <th className="px-2 py-1.5 text-left">Env</th>
              <th className="px-2 py-1.5 text-left">Status</th>
              <th className="px-2 py-1.5 text-left">Ran At</th>
              <th className="px-2 py-1.5 text-right">Duration</th>
              <th className="px-2 py-1.5 text-left">Error</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {filtered.map(j => (
              <tr key={j.id} className="hover:bg-gray-50">
                <td className="px-2 py-1 font-mono">{j.operation}</td>
                <td className="px-2 py-1 font-mono text-gray-400">{(j as any).database || ''}</td>
                <td className="px-2 py-1 font-mono">{j.schema_name}.{j.table_name}</td>
                <td className="px-2 py-1">{j.environment}</td>
                <td className="px-2 py-1">
                  <span className={`inline-flex items-center gap-0.5 ${
                    j.status === 'completed' ? 'text-green-600' :
                    j.status === 'running' ? 'text-blue-600' :
                    j.status === 'queued' ? 'text-gray-500' : 'text-red-600'
                  }`}>
                    {j.status === 'completed' && <CheckCircle size={10} />}
                    {j.status === 'running' && <Loader2 size={10} className="animate-spin" />}
                    {j.status === 'queued' && <Clock size={10} />}
                    {['failed', 'killed', 'timeout'].includes(j.status) && <XCircle size={10} />}
                    {j.status}
                  </span>
                </td>
                <td className="px-2 py-1 text-gray-400">{j.created_at ? new Date(j.created_at).toLocaleString() : ''}</td>
                <td className="px-2 py-1 text-right font-mono">{j.duration_seconds != null ? `${j.duration_seconds}s` : ''}</td>
                <td className="px-2 py-1 text-red-500 truncate max-w-[150px]" title={j.error || ''}>{j.error || ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <div className="text-center py-4 text-[10px] text-gray-400">No jobs match filter.</div>
        )}
      </div>
    </div>
  )
}

function ScheduleRunnerToggle() {
  const [active, setActive] = useState(false)
  const [toggling, setToggling] = useState(false)

  useEffect(() => {
    fetchJSON<{ active: boolean }>('/table-ops/schedule-runner/status')
      .then(r => setActive(r.active))
      .catch(() => {})
  }, [])

  async function toggle() {
    setToggling(true)
    try {
      const res = await fetchJSON<{ active: boolean }>('/table-ops/schedule-runner/toggle', { method: 'POST' })
      setActive(res.active)
    } catch { /* ignore */ }
    finally { setToggling(false) }
  }

  return (
    <div className="border border-gray-200 rounded-lg p-4 flex items-center justify-between">
      <div>
        <h4 className="text-sm font-medium text-gray-700">Schedule Runner</h4>
        <p className="text-xs text-gray-500 mt-0.5">
          Checks every 60 seconds for due schedules. Executes jobs sequentially.
        </p>
      </div>
      <button onClick={toggle} disabled={toggling}
        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
          active ? 'bg-green-500' : 'bg-gray-300'
        }`}>
        <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
          active ? 'translate-x-6' : 'translate-x-1'
        }`} />
      </button>
    </div>
  )
}
