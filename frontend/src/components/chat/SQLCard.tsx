import { useState } from 'react'
import { Play, Pencil, Zap, Copy, Check } from 'lucide-react'
import { executeSQL, optimizeSQL } from '../../api/client'
import { useAuth } from '../../context/AuthContext'
import { useEnvironment } from '../../context/EnvironmentContext'
import { usePillar } from '../../context/PillarContext'
import ResultsTable from '../common/ResultsTable'
import ResultChart from './ResultChart'

interface Props {
  sql: string
  queryResult?: {
    columns: string[]
    rows: unknown[][]
    row_count: number
    execution_time_ms: number
    environment: string
    truncated: boolean
  }
}

export default function SQLCard({ sql: initialSql, queryResult: initialResult }: Props) {
  const { sessionId } = useAuth()
  const { environment } = useEnvironment()
  const { pillar } = usePillar()
  const [sql, setSql] = useState(initialSql)
  const [editing, setEditing] = useState(false)
  const [running, setRunning] = useState(false)
  const [optimizing, setOptimizing] = useState(false)
  const [result, setResult] = useState(initialResult || null)
  const [optimizationReport, setOptimizationReport] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const envLabel = environment === 'prd' ? 'prod' : 'nonprod'
  const envColor = environment === 'prd' ? 'text-red-500' : 'text-green-500'
  const envDot = environment === 'prd' ? 'bg-red-500' : 'bg-green-500'

  async function handleRun() {
    setRunning(true)
    setError(null)
    try {
      const res = await executeSQL(sql, environment, sessionId)
      setResult(res)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Query execution failed')
    } finally {
      setRunning(false)
    }
  }

  async function handleOptimize() {
    setOptimizing(true)
    setError(null)
    try {
      const res = await optimizeSQL(sql, pillar)
      setOptimizationReport(res.analysis)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Optimization failed')
    } finally {
      setOptimizing(false)
    }
  }

  function handleCopy() {
    navigator.clipboard.writeText(sql)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="mt-3 border border-gray-200 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 bg-gray-50 border-b border-gray-200">
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <span className="font-medium text-gray-700">SQL</span>
          <span className={`inline-flex items-center gap-1 ${envColor}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${envDot}`} />
            {envLabel}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={handleCopy}
            className="p-1.5 text-gray-400 hover:text-gray-600 rounded transition-colors"
            title="Copy SQL"
          >
            {copied ? <Check size={14} /> : <Copy size={14} />}
          </button>
        </div>
      </div>

      {/* SQL Code Block */}
      <div className="relative">
        {editing ? (
          <textarea
            value={sql}
            onChange={(e) => setSql(e.target.value)}
            className="w-full bg-gray-900 text-gray-100 text-xs font-mono p-3 min-h-[120px] focus:outline-none focus:ring-2 focus:ring-inset focus:ring-genie-500 resize-y"
            spellCheck={false}
          />
        ) : (
          <pre className="bg-gray-900 text-gray-100 text-xs font-mono p-3 overflow-x-auto whitespace-pre-wrap">
            {sql}
          </pre>
        )}
      </div>

      {/* Action Buttons */}
      <div className="flex items-center gap-2 px-3 py-2 bg-gray-50 border-t border-gray-200">
        <button
          onClick={handleRun}
          disabled={running}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-genie-600 rounded hover:bg-genie-700 disabled:opacity-50 transition-colors"
        >
          <Play size={12} />
          {running ? 'Running...' : 'Run'}
        </button>
        <button
          onClick={() => setEditing(!editing)}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded transition-colors ${
            editing
              ? 'text-white bg-amber-500 hover:bg-amber-600'
              : 'text-gray-600 bg-white border border-gray-300 hover:bg-gray-50'
          }`}
        >
          <Pencil size={12} />
          {editing ? 'Done' : 'Edit'}
        </button>
        <button
          onClick={handleOptimize}
          disabled={optimizing}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-600 bg-white border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50 transition-colors"
        >
          <Zap size={12} />
          {optimizing ? 'Optimizing...' : 'Optimize'}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="px-3 py-2 bg-red-50 text-red-700 text-xs border-t border-red-200">
          {error}
        </div>
      )}

      {/* Query Results */}
      {result && (
        <div className="border-t border-gray-200">
          <div className="px-3 py-1.5 bg-gray-50 text-xs text-gray-500 flex items-center gap-2">
            <span>{result.row_count} rows in {result.execution_time_ms}ms</span>
            <span className={`inline-flex items-center gap-1 ${envColor}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${envDot}`} />
              {envLabel}
            </span>
            {result.truncated && <span className="text-amber-500">(truncated)</span>}
          </div>
          <ResultsTable columns={result.columns} rows={result.rows} />
          <ResultChart columns={result.columns} rows={result.rows} />
        </div>
      )}

      {/* Optimization Report */}
      {optimizationReport && (
        <div className="border-t border-gray-200 px-3 py-3 bg-blue-50">
          <div className="text-xs font-medium text-blue-700 mb-1">Optimization Report</div>
          <pre className="text-xs text-blue-900 whitespace-pre-wrap font-mono">
            {optimizationReport}
          </pre>
        </div>
      )}
    </div>
  )
}
