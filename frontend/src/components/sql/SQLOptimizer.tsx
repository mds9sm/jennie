import { useState } from 'react'
import { Zap, Loader2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { optimizeSQL } from '../../api/client'
import { usePillar } from '../../context/PillarContext'

export default function SQLOptimizer() {
  const [sql, setSql] = useState('')
  const [analysis, setAnalysis] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const { pillar } = usePillar()

  async function handleOptimize() {
    if (!sql.trim()) return
    setLoading(true)
    setError('')
    try {
      const res = await optimizeSQL(sql, pillar)
      setAnalysis(res.analysis)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Optimization failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="h-full flex flex-col p-6 overflow-auto">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">SQL Optimizer</h2>

      <div className="grid grid-cols-2 gap-4 flex-1">
        {/* Input */}
        <div className="flex flex-col">
          <label className="text-sm font-medium text-gray-700 mb-1">Paste your SQL</label>
          <textarea
            value={sql}
            onChange={(e) => setSql(e.target.value)}
            className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono bg-gray-50 focus:outline-none focus:ring-2 focus:ring-genie-500 resize-none"
            placeholder="Paste Redshift SQL here..."
          />
          <button
            onClick={handleOptimize}
            disabled={!sql.trim() || loading}
            className="mt-2 bg-genie-600 text-white rounded-lg px-4 py-2 text-sm hover:bg-genie-700 disabled:opacity-50 flex items-center gap-2 self-start"
          >
            {loading ? <Loader2 size={16} className="animate-spin" /> : <Zap size={16} />}
            Optimize
          </button>
        </div>

        {/* Output */}
        <div className="flex flex-col">
          <label className="text-sm font-medium text-gray-700 mb-1">Optimization Report</label>
          <div className="flex-1 border border-gray-200 rounded-lg p-4 overflow-auto bg-white">
            {error && <p className="text-red-600 text-sm">{error}</p>}
            {analysis ? (
              <div className="prose prose-sm max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{analysis}</ReactMarkdown>
              </div>
            ) : (
              <p className="text-gray-400 text-sm">Optimization suggestions will appear here.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
