import { useState } from 'react'
import { Download, Copy, Check, Workflow, Clock, CheckCircle2, XCircle, ChevronDown, ChevronRight, ArrowRight, Calendar } from 'lucide-react'

interface TaskInfo {
  task_id?: string
  duration_seconds?: number
  status?: string
  operator?: string
}

interface RunInfo {
  run_id?: string
  state?: string
  execution_date?: string
  duration_seconds?: number
}

interface PipelineData {
  // Transform detail data from get_transform_detail
  dag_id?: string
  dag_name?: string
  schedule?: string
  schedule_interval?: string
  owner?: string
  owners?: string[]
  tags?: string[]
  last_run_status?: string
  last_run_date?: string
  tasks?: TaskInfo[]
  source_tables?: string[]
  target_table?: string
  target_tables?: string[]
  rendered_sql?: string
  run_history?: RunInfo[]
  description?: string
  // Search results from search_transforms
  results?: PipelineData[]
  // Pipeline builder output
  yaml_config?: string
  sql_files?: Record<string, string>
  explanation?: string
  error?: string
}

interface Props {
  data: PipelineData
}

function StatusBadge({ status }: { status: string }) {
  const normalized = (status || '').toLowerCase()
  if (normalized === 'success' || normalized === 'running') {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-green-100 text-green-700">
        <CheckCircle2 size={9} /> {status}
      </span>
    )
  }
  if (normalized === 'failed' || normalized === 'error') {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-red-100 text-red-700">
        <XCircle size={9} /> {status}
      </span>
    )
  }
  return (
    <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-600">
      {status}
    </span>
  )
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
}

function RunHistoryBars({ runs }: { runs: RunInfo[] }) {
  const recent = runs.slice(0, 20)
  return (
    <div className="flex items-end gap-0.5 h-5">
      {recent.map((run, i) => {
        const state = (run.state || '').toLowerCase()
        const color = state === 'success' ? 'bg-green-500' :
                      state === 'failed' ? 'bg-red-500' :
                      state === 'running' ? 'bg-blue-500' :
                      'bg-gray-300'
        const height = run.duration_seconds
          ? Math.max(4, Math.min(20, (run.duration_seconds / 300) * 20))
          : 8
        return (
          <div
            key={i}
            className={`w-1.5 rounded-t ${color}`}
            style={{ height: `${height}px` }}
            title={`${run.execution_date || ''} - ${run.state || 'unknown'}${run.duration_seconds ? ` (${formatDuration(run.duration_seconds)})` : ''}`}
          />
        )
      })}
    </div>
  )
}

function MiniLineage({ sources, targets }: { sources: string[]; targets: string[] }) {
  if (sources.length === 0 && targets.length === 0) return null
  return (
    <div className="flex items-center gap-2 text-[11px] py-1.5 overflow-x-auto">
      {sources.length > 0 && (
        <div className="flex flex-col gap-0.5">
          {sources.slice(0, 5).map((t, i) => (
            <span key={i} className="font-mono text-gray-600 bg-blue-50 px-1.5 py-0.5 rounded text-[10px] whitespace-nowrap">
              {t}
            </span>
          ))}
          {sources.length > 5 && (
            <span className="text-[10px] text-gray-400">+{sources.length - 5} more</span>
          )}
        </div>
      )}
      {sources.length > 0 && targets.length > 0 && (
        <ArrowRight size={12} className="text-gray-400 flex-shrink-0" />
      )}
      {targets.length > 0 && (
        <div className="flex flex-col gap-0.5">
          {targets.slice(0, 5).map((t, i) => (
            <span key={i} className="font-mono text-gray-800 bg-green-50 px-1.5 py-0.5 rounded text-[10px] font-medium whitespace-nowrap">
              {t}
            </span>
          ))}
          {targets.length > 5 && (
            <span className="text-[10px] text-gray-400">+{targets.length - 5} more</span>
          )}
        </div>
      )}
    </div>
  )
}

function TransformDetailCard({ data }: { data: PipelineData }) {
  const [showTasks, setShowTasks] = useState(false)
  const [showSQL, setShowSQL] = useState(false)

  const dagName = data.dag_id || data.dag_name || 'Unknown Pipeline'
  const schedule = data.schedule || data.schedule_interval
  const sources = data.source_tables || []
  const targets = data.target_tables || (data.target_table ? [data.target_table] : [])
  const tasks = data.tasks || []
  const runs = data.run_history || []

  return (
    <div className="mt-3 border border-gray-200 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="px-3 py-2.5 bg-gray-50 border-b border-gray-200">
        <div className="flex items-center gap-2">
          <Workflow size={14} className="text-genie-600 flex-shrink-0" />
          <span className="text-sm font-semibold text-gray-900 truncate" title={dagName}>
            {dagName}
          </span>
          {data.last_run_status && (
            <span className="ml-auto flex-shrink-0">
              <StatusBadge status={data.last_run_status} />
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 mt-1 text-[11px] text-gray-500">
          {schedule && (
            <span className="flex items-center gap-1">
              <Calendar size={10} /> {schedule}
            </span>
          )}
          {data.last_run_date && (
            <span className="flex items-center gap-1">
              <Clock size={10} /> {data.last_run_date}
            </span>
          )}
          {(data.owner || (data.owners && data.owners.length > 0)) && (
            <span>{data.owner || data.owners?.join(', ')}</span>
          )}
          {data.tags && data.tags.length > 0 && (
            <div className="flex items-center gap-1">
              {data.tags.map((tag, i) => (
                <span key={i} className="text-[9px] px-1.5 py-0.5 rounded bg-genie-50 text-genie-600 font-medium">
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Description */}
      {data.description && (
        <div className="px-3 py-2 text-xs text-gray-700 border-b border-gray-100">
          {data.description}
        </div>
      )}

      {/* Mini Lineage */}
      {(sources.length > 0 || targets.length > 0) && (
        <div className="px-3 py-1.5 border-b border-gray-100">
          <MiniLineage sources={sources} targets={targets} />
        </div>
      )}

      {/* Tasks */}
      {tasks.length > 0 && (
        <div className="border-b border-gray-100">
          <button
            onClick={() => setShowTasks(!showTasks)}
            className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-gray-50 transition-colors"
          >
            {showTasks ? <ChevronDown size={12} className="text-gray-400" /> : <ChevronRight size={12} className="text-gray-400" />}
            <span className="text-[11px] font-medium text-gray-600">Tasks ({tasks.length})</span>
          </button>
          {showTasks && (
            <div className="px-3 pb-2 space-y-0.5">
              {tasks.map((task, i) => (
                <div key={i} className="flex items-center gap-2 py-0.5 text-xs">
                  <span className="font-mono text-gray-700 truncate flex-1">{task.task_id || `Task ${i + 1}`}</span>
                  {task.operator && (
                    <span className="text-[10px] text-gray-400 flex-shrink-0">{task.operator}</span>
                  )}
                  {task.duration_seconds != null && (
                    <span className="text-[10px] text-gray-500 flex-shrink-0">
                      {formatDuration(task.duration_seconds)}
                    </span>
                  )}
                  {task.status && (
                    <StatusBadge status={task.status} />
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Rendered SQL */}
      {data.rendered_sql && (
        <div className="border-b border-gray-100">
          <button
            onClick={() => setShowSQL(!showSQL)}
            className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-gray-50 transition-colors"
          >
            {showSQL ? <ChevronDown size={12} className="text-gray-400" /> : <ChevronRight size={12} className="text-gray-400" />}
            <span className="text-[11px] font-medium text-gray-600">Rendered SQL</span>
          </button>
          {showSQL && (
            <pre className="bg-gray-900 text-gray-100 text-xs font-mono px-3 py-2 overflow-x-auto max-h-64 whitespace-pre-wrap">
              {data.rendered_sql}
            </pre>
          )}
        </div>
      )}

      {/* Run history bars */}
      {runs.length > 0 && (
        <div className="px-3 py-2 bg-gray-50 flex items-center gap-2">
          <span className="text-[10px] text-gray-400 flex-shrink-0">Runs</span>
          <RunHistoryBars runs={runs} />
        </div>
      )}
    </div>
  )
}

function SearchResultCard({ data }: { data: PipelineData }) {
  const results = data.results || []
  if (results.length === 0) {
    return (
      <div className="mt-3 border border-gray-200 rounded-lg px-3 py-2.5 bg-gray-50 text-xs text-gray-500">
        No pipelines found.
      </div>
    )
  }

  // If single result with detail, render full card
  if (results.length === 1 && (results[0].tasks || results[0].rendered_sql || results[0].source_tables)) {
    return <TransformDetailCard data={results[0]} />
  }

  return (
    <div className="mt-3 border border-gray-200 rounded-lg overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 bg-gray-50 border-b border-gray-200">
        <Workflow size={14} className="text-genie-600" />
        <span className="text-xs font-medium text-gray-700">
          {results.length} pipeline{results.length !== 1 ? 's' : ''} found
        </span>
      </div>
      <div>
        {results.map((r, i) => {
          const name = r.dag_id || r.dag_name || `Pipeline ${i + 1}`
          const schedule = r.schedule || r.schedule_interval
          return (
            <div
              key={i}
              className="flex items-center gap-2 px-3 py-2 border-b border-gray-100 last:border-b-0 hover:bg-gray-50 transition-colors"
            >
              <Workflow size={12} className="text-gray-400 flex-shrink-0" />
              <span className="text-xs font-mono font-medium text-gray-800 truncate">
                {name}
              </span>
              <span className="ml-auto flex items-center gap-2 flex-shrink-0">
                {schedule && (
                  <span className="text-[10px] text-gray-400">{schedule}</span>
                )}
                {r.last_run_status && <StatusBadge status={r.last_run_status} />}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// Legacy pipeline builder output
function PipelineBuilderCard({ data }: { data: PipelineData }) {
  const tabs: { key: string; label: string; content: string }[] = []

  if (data.yaml_config) {
    tabs.push({ key: 'yaml', label: 'YAML Config', content: data.yaml_config })
  }
  if (data.sql_files) {
    for (const [filename, sql] of Object.entries(data.sql_files)) {
      tabs.push({ key: filename, label: filename, content: sql })
    }
  }

  const [activeTab, setActiveTab] = useState(tabs[0]?.key || '')
  const [copiedTab, setCopiedTab] = useState<string | null>(null)

  const activeContent = tabs.find((t) => t.key === activeTab)?.content || ''

  function handleCopy(key: string, content: string) {
    navigator.clipboard.writeText(content)
    setCopiedTab(key)
    setTimeout(() => setCopiedTab(null), 2000)
  }

  function handleDownload(filename: string, content: string) {
    const blob = new Blob([content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  function handleDownloadAll() {
    if (data.yaml_config) {
      handleDownload('pipeline_config.yaml', data.yaml_config)
    }
    if (data.sql_files) {
      for (const [filename, sql] of Object.entries(data.sql_files)) {
        setTimeout(() => handleDownload(filename, sql), 100)
      }
    }
  }

  if (tabs.length === 0) return null

  return (
    <div className="mt-3 border border-gray-200 rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 bg-gray-50 border-b border-gray-200">
        <div className="flex items-center gap-2">
          <Workflow size={14} className="text-genie-600" />
          <span className="text-xs font-medium text-gray-700">Pipeline Config</span>
        </div>
        <button
          onClick={handleDownloadAll}
          className="inline-flex items-center gap-1.5 px-2 py-1 text-[11px] font-medium text-gray-600 bg-white border border-gray-300 rounded hover:bg-gray-50 transition-colors"
        >
          <Download size={12} />
          Download All
        </button>
      </div>

      <div className="flex border-b border-gray-200 bg-gray-50 overflow-x-auto">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-3 py-1.5 text-[11px] font-medium whitespace-nowrap border-b-2 transition-colors ${
              activeTab === tab.key
                ? 'border-genie-600 text-genie-700 bg-white'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="relative">
        <pre className="bg-gray-900 text-gray-100 text-xs font-mono p-3 overflow-x-auto whitespace-pre-wrap max-h-80">
          {activeContent}
        </pre>
        <button
          onClick={() => handleCopy(activeTab, activeContent)}
          className="absolute top-2 right-2 inline-flex items-center gap-1 px-2 py-1 text-[10px] bg-gray-700 text-gray-200 rounded hover:bg-gray-600 transition-colors"
        >
          {copiedTab === activeTab ? <Check size={10} /> : <Copy size={10} />}
          {copiedTab === activeTab ? 'Copied' : 'Copy'}
        </button>
      </div>

      {data.explanation && (
        <div className="px-3 py-2 border-t border-gray-200 text-xs text-gray-600 bg-gray-50">
          {data.explanation}
        </div>
      )}
    </div>
  )
}

export default function PipelineCard({ data }: Props) {
  // Error
  if (data.error) {
    return (
      <div className="mt-3 border border-amber-200 rounded-lg px-3 py-2 bg-amber-50 text-xs text-amber-700">
        {data.error}
      </div>
    )
  }

  // Pipeline builder output (has yaml_config or sql_files)
  if (data.yaml_config || data.sql_files) {
    return <PipelineBuilderCard data={data} />
  }

  // Search results (from search_transforms)
  if (data.results) {
    return <SearchResultCard data={data} />
  }

  // Single transform detail (from get_transform_detail)
  return <TransformDetailCard data={data} />
}
