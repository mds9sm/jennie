import { useState } from 'react'
import { AlertTriangle, Loader2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { analyzeImpact } from '../../api/client'
import { usePillar } from '../../context/PillarContext'

export default function ImpactAnalysis() {
  const [change, setChange] = useState('')
  const [report, setReport] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const { pillar } = usePillar()

  async function handleAnalyze() {
    if (!change.trim()) return
    setLoading(true)
    setError('')
    try {
      const res = await analyzeImpact(change, pillar)
      setReport(res.report)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="h-full flex flex-col p-6 overflow-auto">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">Impact Analysis</h2>

      {/* Input */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 mb-1">Describe the change</label>
        <textarea
          value={change}
          onChange={(e) => setChange(e.target.value)}
          rows={3}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-genie-500"
          placeholder="e.g., What breaks if we remove custom_fields from events.firehose_v3?"
        />
        <button
          onClick={handleAnalyze}
          disabled={!change.trim() || loading}
          className="mt-2 bg-genie-600 text-white rounded-lg px-4 py-2 text-sm hover:bg-genie-700 disabled:opacity-50 flex items-center gap-2"
        >
          {loading ? <Loader2 size={16} className="animate-spin" /> : <AlertTriangle size={16} />}
          Analyze Impact
        </button>
      </div>

      {error && <div className="mb-4 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3">{error}</div>}

      {/* Report */}
      {report && (
        <div className="flex-1 overflow-auto border border-gray-200 rounded-lg p-4">
          <div className="prose prose-sm max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{report}</ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  )
}
