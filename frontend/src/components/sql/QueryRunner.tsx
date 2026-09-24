import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Play, Loader2, Sparkles, Plus, X, Database, Clock, Download, ChevronRight, ChevronDown, Table2, Columns3, RefreshCw, GitBranch, FileCode, Save, Zap, Bookmark, Search } from 'lucide-react'
import { RepoFileBrowser, GitControlPanel } from './GitPanel'
import { fetchJSON, generateSQL, executeSQL } from '../../api/client'
import { usePillar } from '../../context/PillarContext'
import { useEnvironment } from '../../context/EnvironmentContext'
import { useAuth } from '../../context/AuthContext'
import ResultsTable from '../common/ResultsTable'

interface Connection {
  id: number
  name: string
  host: string
  port: number
  database: string
  username: string
  environment: string
  is_default: boolean
}

interface QueryResult {
  sql: string
  columns: string[]
  rows: unknown[][]
  executionInfo: { time: number; env: string; rows: number; truncated?: boolean }
  error?: string
}

interface QueryTab {
  id: string
  title: string
  sql: string
  environment: string
  connectionId: number | null
  repoFilePath: string | null  // if opened from repo
  dirty: boolean               // unsaved changes to repo file
  results: { columns: string[]; rows: unknown[][] } | null
  executionInfo: { time: number; env: string; rows: number; truncated?: boolean } | null
  error: string
  executing: boolean
  multiResults: QueryResult[]  // multi-statement results
  activeResultIdx: number      // which result tab is active
}

let tabCounter = 1

function createTab(env: string, sql: string = '', connId: number | null = null, repoPath: string | null = null): QueryTab {
  return {
    id: `tab-${tabCounter++}`,
    title: repoPath ? repoPath.split('/').pop() || `Query ${tabCounter - 1}` : `Query ${tabCounter - 1}`,
    sql,
    environment: env,
    connectionId: connId,
    repoFilePath: repoPath,
    dirty: false,
    results: null,
    executionInfo: null,
    error: '',
    executing: false,
    multiResults: [],
    activeResultIdx: 0,
  }
}

export default function QueryRunner() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { pillar } = usePillar()
  const { environment } = useEnvironment()
  const { sessionId } = useAuth()

  const [connections, setConnections] = useState<Connection[]>([])
  const [tabs, setTabs] = useState<QueryTab[]>([createTab(environment)])
  const [activeTabId, setActiveTabId] = useState(tabs[0].id)
  const [question, setQuestion] = useState('')
  const [generating, setGenerating] = useState(false)
  const [optimizing, setOptimizing] = useState(false)
  const [optimization, setOptimization] = useState<string | null>(null)
  const [history, setHistory] = useState<{ sql: string; env: string; time: number; rows: number; ts: string }[]>([])
  const [showHistory, setShowHistory] = useState(false)
  const [showBrowser, setShowBrowser] = useState(true)
  const [showGit, setShowGit] = useState(false)
  const [gitRefreshKey, setGitRefreshKey] = useState(0)
  const [browserMode, setBrowserMode] = useState<'schema' | 'files'>('schema')
  const [showSaveDialog, setShowSaveDialog] = useState(false)
  const [saveName, setSaveName] = useState('')
  const [saveDesc, setSaveDesc] = useState('')
  const [saveTags, setSaveTags] = useState('')
  const [savedQueries, setSavedQueries] = useState<Array<Record<string, unknown>>>([])
  const [showSavedQueries, setShowSavedQueries] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Load connections
  useEffect(() => {
    fetchJSON<Connection[]>('/connections').then(setConnections).catch(() => {})
  }, [])

  const activeTab = tabs.find(t => t.id === activeTabId) || tabs[0]

  // Pre-fill from URL param
  useEffect(() => {
    const prefill = searchParams.get('sql')
    if (prefill) {
      updateTab(activeTabId, { sql: prefill })
      setSearchParams({}, { replace: true })
    }
  }, [searchParams])

  function updateTab(id: string, updates: Partial<QueryTab>) {
    setTabs(prev => prev.map(t => t.id === id ? { ...t, ...updates } : t))
  }

  function addTab() {
    const newTab = createTab(environment)
    setTabs(prev => [...prev, newTab])
    setActiveTabId(newTab.id)
  }

  function closeTab(id: string) {
    if (tabs.length <= 1) return
    const idx = tabs.findIndex(t => t.id === id)
    const newTabs = tabs.filter(t => t.id !== id)
    setTabs(newTabs)
    if (activeTabId === id) {
      setActiveTabId(newTabs[Math.min(idx, newTabs.length - 1)].id)
    }
  }

  async function handleGenerate() {
    if (!question.trim()) return
    setGenerating(true)
    try {
      const res = await generateSQL(question, pillar, activeTab.environment)
      const sqlMatch = res.sql.match(/```sql\n?([\s\S]*?)```/)
      const sql = sqlMatch ? sqlMatch[1].trim() : res.sql
      updateTab(activeTabId, { sql, title: question.slice(0, 30) || `Query ${tabCounter - 1}` })
    } catch (err) {
      updateTab(activeTabId, { error: err instanceof Error ? err.message : 'Generation failed' })
    } finally {
      setGenerating(false)
    }
  }

  function getSelectedSQL(): string | null {
    const ta = textareaRef.current
    if (!ta) return null
    const sel = ta.value.substring(ta.selectionStart, ta.selectionEnd).trim()
    return sel || null
  }

  function splitStatements(sql: string): string[] {
    return sql.split(';').map(s => s.trim()).filter(s => s.length > 0)
  }

  async function executeSingle(sql: string): Promise<QueryResult> {
    try {
      let res: any
      if (activeTab.connectionId) {
        res = await fetchJSON<any>('/connections/execute', {
          method: 'POST',
          body: JSON.stringify({ connection_id: activeTab.connectionId, sql }),
        })
      } else {
        res = await executeSQL(sql, activeTab.environment, sessionId)
      }
      if (res.error) {
        return { sql, columns: [], rows: [], executionInfo: { time: 0, env: activeTab.environment, rows: 0 }, error: res.error }
      }
      return {
        sql,
        columns: res.columns || [],
        rows: res.rows || [],
        executionInfo: { time: res.execution_time_ms, env: res.environment, rows: res.row_count, truncated: res.truncated },
      }
    } catch (err) {
      return { sql, columns: [], rows: [], executionInfo: { time: 0, env: activeTab.environment, rows: 0 }, error: err instanceof Error ? err.message : 'Query failed' }
    }
  }

  async function handleExecute() {
    const selected = getSelectedSQL()
    const fullSql = activeTab.sql.trim()
    if (!fullSql && !selected) return

    updateTab(activeTabId, { executing: true, error: '', results: null, executionInfo: null, multiResults: [], activeResultIdx: 0 })

    const statements = splitStatements(selected || fullSql)

    if (statements.length <= 1) {
      // Single query — use original simple path
      const result = await executeSingle(statements[0] || fullSql)
      if (result.error) {
        updateTab(activeTabId, { error: result.error, executing: false })
      } else if (result.rows.length === 0 && result.columns.length === 0) {
        updateTab(activeTabId, { error: 'No results returned', executing: false })
      } else {
        updateTab(activeTabId, {
          results: { columns: result.columns, rows: result.rows },
          executionInfo: result.executionInfo,
          executing: false,
          multiResults: [result],
          activeResultIdx: 0,
        })
      }
      setHistory(prev => [{
        sql: (selected || fullSql).slice(0, 200),
        env: activeTab.environment,
        time: result.executionInfo.time,
        rows: result.executionInfo.rows,
        ts: new Date().toLocaleTimeString(),
      }, ...prev].slice(0, 50))
    } else {
      // Multi-query — execute sequentially, show per-statement results
      const allResults: QueryResult[] = []
      for (const stmt of statements) {
        const result = await executeSingle(stmt)
        allResults.push(result)
        // Update live as each completes
        const lastGood = [...allResults].reverse().find(r => !r.error && r.columns.length > 0)
        updateTab(activeTabId, {
          multiResults: [...allResults],
          activeResultIdx: allResults.length - 1,
          results: lastGood ? { columns: lastGood.columns, rows: lastGood.rows } : null,
          executionInfo: lastGood?.executionInfo || null,
          executing: allResults.length < statements.length,
        })
        // Stop on error
        if (result.error) break
      }
      updateTab(activeTabId, { executing: false })
      // Add to history
      setHistory(prev => [{
        sql: statements.map(s => s.slice(0, 60)).join(' ; ').slice(0, 200),
        env: activeTab.environment,
        time: allResults.reduce((sum, r) => sum + r.executionInfo.time, 0),
        rows: allResults.reduce((sum, r) => sum + r.executionInfo.rows, 0),
        ts: new Date().toLocaleTimeString(),
      }, ...prev].slice(0, 50))
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault()
      handleExecute()
    }
    if ((e.metaKey || e.ctrlKey) && e.key === 's') {
      e.preventDefault()
      if (activeTab.repoFilePath && activeTab.dirty) handleSaveFile()
    }
  }

  function handleOptimize() {
    if (!activeTab.sql.trim()) return
    const sql = activeTab.sql.trim()
    const question = encodeURIComponent(`Optimize this Redshift SQL. Check actual table sizes, distkeys, and suggest improvements:\n\n\`\`\`sql\n${sql}\n\`\`\``)
    window.location.href = `/?q=${question}`
  }

  async function handleSaveFile() {
    if (!activeTab.repoFilePath) return
    try {
      await fetchJSON('/git/file', {
        method: 'PUT',
        body: JSON.stringify({ path: activeTab.repoFilePath, content: activeTab.sql }),
      })
      updateTab(activeTabId, { dirty: false })
      setGitRefreshKey(k => k + 1)  // trigger Git panel refresh
    } catch (err) {
      updateTab(activeTabId, { error: err instanceof Error ? err.message : 'Save failed' })
    }
  }

  async function handleSaveToLibrary() {
    if (!saveName.trim() || !activeTab.sql.trim()) return
    try {
      await fetchJSON('/saved-queries', {
        method: 'POST',
        body: JSON.stringify({
          name: saveName,
          sql: activeTab.sql,
          description: saveDesc,
          environment: activeTab.environment,
          tags: saveTags.split(',').map(t => t.trim()).filter(Boolean),
          pillar: null,
        }),
      })
      setShowSaveDialog(false)
      setSaveName('')
      setSaveDesc('')
      setSaveTags('')
      loadSavedQueries()
    } catch { /* ignore */ }
  }

  async function loadSavedQueries() {
    try {
      const data = await fetchJSON<Array<Record<string, unknown>>>('/saved-queries')
      setSavedQueries(data)
    } catch { /* ignore */ }
  }

  function loadSavedQuery(q: Record<string, unknown>) {
    const newTab: QueryTab = {
      id: crypto.randomUUID(),
      title: String(q.name || 'Saved Query'),
      sql: String(q.sql || ''),
      environment: String(q.environment || 'np'),
      connectionId: null,
      repoFilePath: null,
      dirty: false,
      results: null,
      executionInfo: null,
      executing: false,
      error: '',
      multiResults: [],
      activeResultIdx: 0,
    }
    setTabs(prev => [...prev, newTab])
    setActiveTabId(newTab.id)
    setShowSavedQueries(false)
    // Record usage
    if (q.id) fetchJSON(`/saved-queries/${q.id}/use`, { method: 'POST' }).catch(() => {})
  }

  function exportCSV() {
    // Export the active result (from multi-results or single result)
    let columns: string[] | undefined
    let rows: unknown[][] | undefined
    if (activeTab.multiResults.length > 0) {
      const active = activeTab.multiResults[activeTab.activeResultIdx]
      if (active && active.columns.length > 0) {
        columns = active.columns
        rows = active.rows
      }
    }
    if (!columns && activeTab.results) {
      columns = activeTab.results.columns
      rows = activeTab.results.rows
    }
    if (!columns || !rows) return
    const csv = [columns.join(','), ...rows.map(r => r.map(c => `"${String(c ?? '').replace(/"/g, '""')}"`).join(','))].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `query_results_${Date.now()}.csv`
    a.click()
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Tab bar */}
      <div className="flex items-center bg-gray-100 border-b border-gray-200 px-2 h-9 gap-0.5 overflow-x-auto">
        {tabs.map(tab => (
          <div key={tab.id}
            onClick={() => setActiveTabId(tab.id)}
            className={`flex items-center gap-1.5 px-3 py-1 text-xs rounded-t-md cursor-pointer min-w-0 max-w-[180px] group ${
              tab.id === activeTabId
                ? 'bg-white text-gray-800 border border-gray-200 border-b-white -mb-px font-medium'
                : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
            }`}>
            <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
              tab.executing ? 'bg-blue-400 animate-pulse' :
              tab.results ? 'bg-green-400' :
              tab.error ? 'bg-red-400' : 'bg-gray-300'
            }`} />
            <span className="truncate">{tab.title}{tab.dirty ? ' •' : ''}</span>
            <span className={`text-[9px] px-1 py-0 rounded ${
              tab.environment === 'np' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
            }`}>{tab.environment}</span>
            {tabs.length > 1 && (
              <button onClick={e => { e.stopPropagation(); closeTab(tab.id) }}
                className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-gray-600 -mr-1">
                <X size={10} />
              </button>
            )}
          </div>
        ))}
        <button onClick={addTab} className="p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-200 rounded ml-1" title="New tab">
          <Plus size={12} />
        </button>
        <div className="ml-auto flex items-center gap-1">
          <button onClick={() => { setShowBrowser(!showBrowser); if (!showBrowser) { setShowHistory(false); setShowGit(false) } }}
            className={`p-1 rounded text-xs flex items-center gap-1 ${showBrowser ? 'bg-genie-100 text-genie-700' : 'text-gray-400 hover:text-gray-600'}`}>
            <Database size={12} /> Browser
          </button>
          <button onClick={() => { setShowGit(!showGit); if (!showGit) { setShowHistory(false) } }}
            className={`p-1 rounded text-xs flex items-center gap-1 ${showGit ? 'bg-genie-100 text-genie-700' : 'text-gray-400 hover:text-gray-600'}`}>
            <GitBranch size={12} /> Git
          </button>
          <button onClick={() => { setShowHistory(!showHistory); if (!showHistory) { setShowBrowser(false); setShowGit(false) } }}
            className={`p-1 rounded text-xs flex items-center gap-1 ${showHistory ? 'bg-genie-100 text-genie-700' : 'text-gray-400 hover:text-gray-600'}`}>
            <Clock size={12} /> History
          </button>
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden min-h-0">
        {/* Schema browser */}
        {showBrowser && (
          <ResizablePanel minWidth={180} maxWidth={500} defaultWidth={240}>
            <div className="h-full flex flex-col">
              {/* Schema / Files toggle */}
              <div className="flex border-b border-gray-200 bg-gray-50">
                {(['schema', 'files'] as const).map(mode => (
                  <button key={mode} onClick={() => setBrowserMode(mode)}
                    className={`flex-1 px-2 py-1 text-[10px] flex items-center justify-center gap-1 ${
                      browserMode === mode ? 'bg-white text-gray-800 font-medium border-b-2 border-genie-500' : 'text-gray-500 hover:text-gray-700'
                    }`}>
                    {mode === 'schema' ? <><Database size={9} /> Schema</> : <><FileCode size={9} /> Repo Files</>}
                  </button>
                ))}
              </div>
              {browserMode === 'schema' ? (
                <SchemaBrowser
                  environment={activeTab.connectionId ? (connections.find(c => c.id === activeTab.connectionId)?.environment || activeTab.environment) : activeTab.environment}
                  connectionId={activeTab.connectionId}
                  sessionId={sessionId}
                  onInsertTable={(table) => {
                    const cur = activeTab.sql
                    const pos = textareaRef.current?.selectionStart || cur.length
                    const newSql = cur.slice(0, pos) + table + cur.slice(pos)
                    updateTab(activeTabId, { sql: newSql })
                    textareaRef.current?.focus()
                  }}
                />
              ) : (
                <RepoFileBrowser
                  onOpenFile={(path, content) => {
                    const newTab = createTab(activeTab.environment, content, null, path)
                    setTabs(prev => [...prev, newTab])
                    setActiveTabId(newTab.id)
                  }}
                  onCreateFile={(path, content) => {
                    const newTab = createTab(activeTab.environment, content, null, path)
                    newTab.dirty = true
                    setTabs(prev => [...prev, newTab])
                    setActiveTabId(newTab.id)
                  }}
                />
              )}
            </div>
          </ResizablePanel>
        )}

        {/* Main query area */}
        <div className="flex-1 flex flex-col min-h-0 min-w-0">
          {/* Toolbar */}
          <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-100 bg-white">
            {/* Connection picker */}
            {connections.length > 0 ? (
              <select value={activeTab.connectionId || ''}
                onChange={e => {
                  const connId = e.target.value ? parseInt(e.target.value) : null
                  const conn = connections.find(c => c.id === connId)
                  updateTab(activeTabId, {
                    connectionId: connId,
                    environment: conn?.environment || activeTab.environment,
                  })
                }}
                className="text-xs border border-gray-300 rounded px-2 py-1 bg-white max-w-[200px]">
                <option value="">Default ({activeTab.environment})</option>
                {connections.map(c => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.username}@{c.database})
                  </option>
                ))}
              </select>
            ) : (
              <select value={activeTab.environment}
                onChange={e => updateTab(activeTabId, { environment: e.target.value, connectionId: null })}
                className={`text-xs border rounded px-2 py-1 ${
                  activeTab.environment === 'np' ? 'border-green-300 text-green-700 bg-green-50' : 'border-red-300 text-red-700 bg-red-50'
                }`}>
                <option value="np">nonprod</option>
                <option value="prd">PROD</option>
              </select>
            )}

            <div className="border-l border-gray-200 h-4" />

            <div className="border-l border-gray-200 h-4" />

            <button onClick={handleExecute} disabled={!activeTab.sql.trim() || activeTab.executing}
              className="text-xs px-3 py-1 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1"
              title="Run query (⌘+Enter). Select text to run only that portion.">
              {activeTab.executing ? <Loader2 size={10} className="animate-spin" /> : <Play size={10} />}
              Run
            </button>
            <button onClick={handleOptimize} disabled={!activeTab.sql.trim() || optimizing}
              className="text-xs px-2 py-1 rounded border border-amber-300 text-amber-700 hover:bg-amber-50 disabled:opacity-50 flex items-center gap-1">
              {optimizing ? <Loader2 size={10} className="animate-spin" /> : <Zap size={10} />}
              Optimize
            </button>
            {activeTab.repoFilePath && (
              <button onClick={handleSaveFile} disabled={!activeTab.dirty}
                className="text-xs px-3 py-1 rounded bg-green-600 text-white hover:bg-green-700 disabled:opacity-50 flex items-center gap-1">
                <Save size={10} /> Save
              </button>
            )}
            <button onClick={() => { setShowSaveDialog(true); setSaveName(activeTab.title) }}
              disabled={!activeTab.sql.trim()}
              className="text-xs px-2 py-1 rounded border border-genie-300 text-genie-700 hover:bg-genie-50 disabled:opacity-50 flex items-center gap-1">
              <Bookmark size={10} /> Save to Library
            </button>
            <button onClick={() => { setShowSavedQueries(!showSavedQueries); if (!showSavedQueries) loadSavedQueries() }}
              className={`text-xs px-2 py-1 rounded border flex items-center gap-1 ${showSavedQueries ? 'border-genie-500 bg-genie-50 text-genie-700' : 'border-gray-300 text-gray-600 hover:bg-gray-50'}`}>
              <Search size={10} /> Shared
            </button>
            <span className="text-[9px] text-gray-400">⌘+Enter</span>

            {activeTab.repoFilePath && (
              <span className="text-[9px] text-gray-400 font-mono truncate ml-2" title={activeTab.repoFilePath}>
                {activeTab.repoFilePath}
              </span>
            )}
            {(activeTab.results || activeTab.multiResults.length > 0) && (
              <button onClick={exportCSV} className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-0.5 ml-auto"
                title="Download current result as CSV">
                <Download size={10} /> CSV
              </button>
            )}
          </div>

          {/* Optimization panel */}
          {optimization && (
            <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 max-h-48 overflow-auto">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium text-amber-700 flex items-center gap-1"><Zap size={10} /> Optimization Suggestions</span>
                <button onClick={() => setOptimization(null)} className="text-[10px] text-amber-600 hover:text-amber-800">dismiss</button>
              </div>
              <pre className="text-xs text-gray-700 whitespace-pre-wrap font-mono">{optimization}</pre>
            </div>
          )}

          {/* Save to Library dialog */}
          {showSaveDialog && (
            <div className="border-b border-genie-200 bg-genie-50 px-4 py-3">
              <div className="flex items-center gap-2 mb-2">
                <Bookmark size={12} className="text-genie-600" />
                <span className="text-xs font-medium text-genie-700">Save to Shared Library</span>
                <button onClick={() => setShowSaveDialog(false)} className="ml-auto text-gray-400 hover:text-gray-600"><X size={12} /></button>
              </div>
              <div className="flex gap-2 mb-2">
                <input type="text" value={saveName} onChange={e => setSaveName(e.target.value)}
                  placeholder="Query name" className="flex-1 text-xs border border-gray-300 rounded px-2 py-1" />
                <input type="text" value={saveTags} onChange={e => setSaveTags(e.target.value)}
                  placeholder="Tags (comma-separated)" className="flex-1 text-xs border border-gray-300 rounded px-2 py-1" />
              </div>
              <div className="flex gap-2">
                <input type="text" value={saveDesc} onChange={e => setSaveDesc(e.target.value)}
                  placeholder="Description (optional)" className="flex-1 text-xs border border-gray-300 rounded px-2 py-1" />
                <button onClick={handleSaveToLibrary} disabled={!saveName.trim()}
                  className="text-xs px-3 py-1 rounded bg-genie-600 text-white hover:bg-genie-700 disabled:opacity-50">
                  Save
                </button>
              </div>
            </div>
          )}

          {/* Shared Query Library */}
          {showSavedQueries && (
            <div className="border-b border-gray-200 bg-white px-4 py-2 max-h-48 overflow-auto">
              <div className="flex items-center gap-2 mb-2">
                <Search size={12} className="text-genie-600" />
                <span className="text-xs font-medium text-gray-700">Shared Query Library ({savedQueries.length})</span>
                <button onClick={() => setShowSavedQueries(false)} className="ml-auto text-gray-400 hover:text-gray-600"><X size={12} /></button>
              </div>
              {savedQueries.length === 0 ? (
                <p className="text-xs text-gray-400 py-2">No saved queries yet. Use "Save to Library" to add one.</p>
              ) : (
                <div className="space-y-1">
                  {savedQueries.map(q => (
                    <div key={String(q.id)} onClick={() => loadSavedQuery(q)}
                      className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-gray-50 cursor-pointer group">
                      <Bookmark size={10} className="text-genie-400 flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="text-xs font-medium text-gray-800 truncate">{String(q.name || '')}</div>
                        {String(q.description || '') !== '' && <div className="text-[10px] text-gray-400 truncate">{String(q.description)}</div>}
                      </div>
                      <div className="flex items-center gap-1.5 flex-shrink-0">
                        {(Array.isArray(q.tags) ? q.tags : []).slice(0, 2).map((tag) => (
                          <span key={String(tag)} className="text-[9px] bg-gray-100 text-gray-500 px-1 py-0.5 rounded">{String(tag)}</span>
                        ))}
                        <span className="text-[9px] text-gray-400">{String(q.use_count || 0)} uses</span>
                        <span className="text-[9px] text-gray-300">{String(q.created_by_name || '')}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* SQL editor + Results split */}
          <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
            {/* SQL textarea — fixed height */}
            <textarea
              ref={textareaRef}
              value={activeTab.sql}
              onChange={e => updateTab(activeTabId, { sql: e.target.value, dirty: !!activeTab.repoFilePath })}
              onKeyDown={handleKeyDown}
              className="h-[140px] shrink-0 border-b border-gray-200 px-4 py-3 text-sm font-mono bg-gray-50 resize-y focus:outline-none focus:bg-white"
              placeholder="SELECT * FROM prd_dw.dim.country LIMIT 10;"
              spellCheck={false}
            />

            {/* Error */}
            {activeTab.error && (
              <div className="bg-red-50 border-b border-red-200 text-red-700 text-xs px-4 py-2 shrink-0">
                {activeTab.error}
              </div>
            )}

            {/* Multi-result sub-tabs */}
            {activeTab.multiResults.length > 1 && (
              <div className="flex items-center gap-0.5 px-3 py-1 bg-gray-50 border-b border-gray-200 overflow-x-auto">
                {activeTab.multiResults.map((r, idx) => (
                  <button key={idx}
                    onClick={() => updateTab(activeTabId, {
                      activeResultIdx: idx,
                      results: r.columns.length > 0 ? { columns: r.columns, rows: r.rows } : null,
                      executionInfo: r.executionInfo,
                      error: r.error || '',
                    })}
                    className={`text-[10px] px-2 py-0.5 rounded flex items-center gap-1 ${
                      idx === activeTab.activeResultIdx
                        ? 'bg-white text-gray-800 shadow-sm border border-gray-200 font-medium'
                        : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
                    }`}
                    title={r.sql.slice(0, 100)}>
                    <span className={`w-1.5 h-1.5 rounded-full ${r.error ? 'bg-red-400' : r.columns.length > 0 ? 'bg-green-400' : 'bg-gray-300'}`} />
                    Result {idx + 1}
                    {r.executionInfo.rows > 0 && <span className="text-gray-400">({r.executionInfo.rows})</span>}
                  </button>
                ))}
                <span className="text-[9px] text-gray-400 ml-2">
                  {activeTab.multiResults.reduce((s, r) => s + r.executionInfo.time, 0)}ms total
                </span>
              </div>
            )}

            {/* Results — use calc for guaranteed height */}
            {activeTab.results ? (
              <div>
                {activeTab.executionInfo && (
                  <div className="flex items-center gap-3 px-4 py-1.5 text-[10px] text-gray-500 border-b border-gray-100 bg-white">
                    <span>{activeTab.executionInfo.rows.toLocaleString()} rows</span>
                    <span>{activeTab.executionInfo.time}ms</span>
                    <span className={activeTab.executionInfo.env === 'np' ? 'text-green-600' : 'text-red-600'}>
                      {activeTab.executionInfo.env === 'np' ? 'nonprod' : 'PROD'}
                    </span>
                    {activeTab.executionInfo.truncated && <span className="text-amber-600">truncated</span>}
                  </div>
                )}
                <div className="overflow-auto" style={{ maxHeight: 'calc(100vh - 340px)' }}>
                  <ResultsTable columns={activeTab.results.columns} rows={activeTab.results.rows} />
                </div>
              </div>
            ) : !activeTab.executing ? (
              <div className="flex items-center justify-center text-gray-300 text-sm" style={{ height: '200px' }}>
                Run a query to see results{activeTab.multiResults.length === 0 && ' — select text to run a portion'}
              </div>
            ) : (
              <div className="flex items-center justify-center" style={{ height: '200px' }}>
                <Loader2 size={20} className="animate-spin text-blue-400" />
              </div>
            )}
          </div>
        </div>

        {/* Git panel */}
        {showGit && (
          <div className="w-64 border-l border-gray-200 overflow-hidden bg-white">
            <GitControlPanel refreshKey={gitRefreshKey} />
          </div>
        )}

        {/* History sidebar */}
        {showHistory && (
          <div className="w-64 border-l border-gray-200 overflow-auto bg-white">
            <div className="px-3 py-2 border-b border-gray-100 text-xs font-medium text-gray-700">
              Query History ({history.length})
            </div>
            {history.map((h, i) => (
              <button key={i} onClick={() => updateTab(activeTabId, { sql: h.sql })}
                className="w-full text-left px-3 py-2 text-xs border-b border-gray-50 hover:bg-gray-50">
                <div className="font-mono text-gray-700 truncate">{h.sql}</div>
                <div className="flex gap-2 text-[10px] text-gray-400 mt-0.5">
                  <span>{h.rows} rows</span>
                  <span>{h.time}ms</span>
                  <span className={h.env === 'np' ? 'text-green-600' : 'text-red-600'}>{h.env}</span>
                  <span className="ml-auto">{h.ts}</span>
                </div>
              </button>
            ))}
            {history.length === 0 && (
              <div className="text-center py-8 text-[10px] text-gray-400">No queries run yet</div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Schema Browser — expandable tree: databases → schemas → tables → columns
// ---------------------------------------------------------------------------

interface BrowserNode {
  type: 'database' | 'schema' | 'table' | 'column'
  name: string
  children?: BrowserNode[]
  tableType?: string
  colType?: string
  nullable?: string
  tableCount?: number
  loaded?: boolean
  loading?: boolean
}

// ---------------------------------------------------------------------------
// Resizable Panel — drag the right edge to resize
// ---------------------------------------------------------------------------

function ResizablePanel({ children, minWidth = 180, maxWidth = 500, defaultWidth = 240 }: {
  children: React.ReactNode
  minWidth?: number
  maxWidth?: number
  defaultWidth?: number
}) {
  const [width, setWidth] = useState(() => {
    const saved = localStorage.getItem('schema_browser_width')
    return saved ? parseInt(saved) : defaultWidth
  })
  const [dragging, setDragging] = useState(false)
  const startX = useRef(0)
  const startW = useRef(0)

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setDragging(true)
    startX.current = e.clientX
    startW.current = width
  }, [width])

  useEffect(() => {
    if (!dragging) return
    const handleMove = (e: MouseEvent) => {
      const newW = Math.max(minWidth, Math.min(maxWidth, startW.current + e.clientX - startX.current))
      setWidth(newW)
    }
    const handleUp = () => {
      setDragging(false)
      localStorage.setItem('schema_browser_width', String(width))
    }
    document.addEventListener('mousemove', handleMove)
    document.addEventListener('mouseup', handleUp)
    return () => {
      document.removeEventListener('mousemove', handleMove)
      document.removeEventListener('mouseup', handleUp)
    }
  }, [dragging, minWidth, maxWidth, width])

  return (
    <div className="relative flex-shrink-0 h-full" style={{ width }}>
      {children}
      {/* Drag handle */}
      <div
        className={`absolute top-0 right-0 w-1 h-full cursor-col-resize hover:bg-genie-400 transition-colors ${dragging ? 'bg-genie-500' : 'bg-transparent'}`}
        onMouseDown={handleMouseDown}
      />
    </div>
  )
}


function SchemaBrowser({ environment, connectionId, sessionId, onInsertTable }: {
  environment: string
  connectionId: number | null
  sessionId: string
  onInsertTable: (fqTable: string) => void
}) {
  // Persist schema tree in localStorage
  const storageKey = `schema_browser_${environment}_${connectionId || 'default'}`
  const [databases, setDatabases] = useState<BrowserNode[]>(() => {
    try {
      const saved = localStorage.getItem(storageKey)
      return saved ? JSON.parse(saved) : []
    } catch { return [] }
  })
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    try {
      const saved = localStorage.getItem(`${storageKey}_expanded`)
      return saved ? new Set(JSON.parse(saved)) : new Set()
    } catch { return new Set() }
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const cacheRef = useRef<Record<string, any>>({})

  // Save to localStorage on change
  useEffect(() => {
    if (databases.length > 0) {
      localStorage.setItem(storageKey, JSON.stringify(databases))
    }
  }, [databases, storageKey])

  useEffect(() => {
    localStorage.setItem(`${storageKey}_expanded`, JSON.stringify([...expanded]))
  }, [expanded, storageKey])

  const params = `environment=${environment}&connection_id=${connectionId || 0}&session_id=${sessionId}`

  const loadDatabases = useCallback(async () => {
    setLoading(true)
    setError('')
    cacheRef.current = {}
    setExpanded(new Set())
    try {
      const p = `environment=${environment}&connection_id=${connectionId || 0}&session_id=${sessionId}`
      const res = await fetchJSON<{ databases: string[]; error?: string }>(`/connections/browse/databases?${p}`)
      if (res.error) { setError(res.error); setLoading(false); return }
      setDatabases(res.databases.map(d => ({ type: 'database' as const, name: d })))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed')
    } finally {
      setLoading(false)
    }
  }, [environment, connectionId, sessionId])

  // Only auto-load if no cached data
  useEffect(() => {
    if (databases.length === 0) loadDatabases()
  }, [loadDatabases])

  async function toggleNode(path: string, node: BrowserNode) {
    if (expanded.has(path)) {
      setExpanded(prev => { const n = new Set(prev); n.delete(path); return n })
      return
    }

    // Load children if not loaded
    if (!node.loaded && !node.loading) {
      node.loading = true
      setDatabases([...databases]) // trigger re-render

      const cached = cacheRef.current[path]
      if (cached) {
        node.children = cached
        node.loaded = true
        node.loading = false
      } else {
        try {
          const parts = path.split('/')
          if (node.type === 'database') {
            const res = await fetchJSON<{ schemas: { name: string; table_count: number }[] }>(
              `/connections/browse/schemas?database=${node.name}&environment=${environment}&connection_id=${connectionId || 0}&session_id=${sessionId}`)
            node.children = res.schemas.map(s => ({
              type: 'schema' as const, name: s.name, tableCount: s.table_count,
            }))
          } else if (node.type === 'schema') {
            const db = parts[0]
            const res = await fetchJSON<{ tables: { name: string; type: string }[] }>(
              `/connections/browse/tables?database=${db}&schema=${node.name}&environment=${environment}&connection_id=${connectionId || 0}&session_id=${sessionId}`)
            node.children = res.tables.map(t => ({
              type: 'table' as const, name: t.name, tableType: t.type,
            }))
          } else if (node.type === 'table') {
            const [db, schema] = parts
            const res = await fetchJSON<{ columns: { name: string; type: string; nullable: string }[] }>(
              `/connections/browse/columns?database=${db}&schema=${schema}&table=${node.name}&environment=${environment}&connection_id=${connectionId || 0}&session_id=${sessionId}`)
            node.children = res.columns.map(c => ({
              type: 'column' as const, name: c.name, colType: c.type, nullable: c.nullable,
            }))
          }
          cacheRef.current[path] = node.children
          node.loaded = true
        } catch { /* ignore */ }
        node.loading = false
      }
      setDatabases([...databases])
    }

    setExpanded(prev => new Set(prev).add(path))
  }

  function renderNode(node: BrowserNode, path: string, depth: number) {
    const isExpanded = expanded.has(path)
    const hasChildren = node.type !== 'column'
    const isTable = node.type === 'table'
    const isColumn = node.type === 'column'

    return (
      <div key={path}>
        <div
          className={`flex items-center gap-1 px-2 py-1 cursor-pointer hover:bg-gray-100 text-xs ${
            isColumn ? 'text-gray-500' : 'text-gray-700'
          }`}
          style={{ paddingLeft: `${depth * 14 + 8}px` }}
          onClick={() => hasChildren ? toggleNode(path, node) : undefined}
          onDoubleClick={() => {
            if (isTable) {
              const parts = path.split('/')
              onInsertTable(`${parts.join('.')} `)
            } else if (isColumn) {
              onInsertTable(`${node.name} `)
            }
          }}
          title={isTable ? 'Double-click to insert table name' : isColumn ? 'Double-click to insert column name' : ''}
        >
          {hasChildren ? (
            isExpanded ? <ChevronDown size={10} className="text-gray-400 flex-shrink-0" />
              : <ChevronRight size={10} className="text-gray-400 flex-shrink-0" />
          ) : <span className="w-2.5" />}

          {node.type === 'database' && <Database size={11} className="text-blue-400 flex-shrink-0" />}
          {node.type === 'schema' && <Columns3 size={11} className="text-amber-500 flex-shrink-0" />}
          {node.type === 'table' && <Table2 size={11} className={node.tableType === 'VIEW' ? 'text-orange-400' : 'text-green-500'} />}

          <span className={`truncate font-mono ${node.type === 'database' ? 'font-semibold' : ''}`}>
            {node.name}
          </span>

          {node.tableCount != null && <span className="text-[9px] text-gray-400 ml-auto">{node.tableCount}</span>}
          {node.tableType === 'VIEW' && <span className="text-[8px] text-orange-400 ml-auto">VIEW</span>}
          {isColumn && node.colType && <span className="text-[9px] text-gray-400 ml-auto font-mono">{node.colType}</span>}
          {node.loading && <Loader2 size={10} className="animate-spin text-gray-400 ml-auto" />}
        </div>

        {isExpanded && node.children && node.children.map(child =>
          renderNode(child, `${path}/${child.name}`, depth + 1)
        )}
      </div>
    )
  }

  return (
    <div className="w-full h-full border-r border-gray-200 overflow-auto bg-white flex flex-col">
      <div className="flex items-center justify-between px-2 py-1.5 border-b border-gray-100 bg-gray-50">
        <span className="text-[10px] font-medium text-gray-500 uppercase">Schema Browser</span>
        <button onClick={loadDatabases} className="text-gray-400 hover:text-gray-600" title="Refresh">
          <RefreshCw size={10} />
        </button>
      </div>
      {error && <div className="px-2 py-1 text-[10px] text-red-500">{error}</div>}
      {loading && <div className="flex items-center justify-center py-4"><Loader2 size={14} className="animate-spin text-gray-400" /></div>}
      <div className="flex-1 overflow-auto">
        {databases.map(db => renderNode(db, db.name, 0))}
        {!loading && databases.length === 0 && !error && (
          <div className="text-center py-4 text-[10px] text-gray-400">
            No databases found. Check connection.
          </div>
        )}
      </div>
    </div>
  )
}
