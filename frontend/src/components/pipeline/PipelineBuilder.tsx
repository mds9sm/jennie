import { useState } from 'react'
import { GitBranch, Loader2, Download } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { generatePipeline } from '../../api/client'
import { usePillar } from '../../context/PillarContext'

export default function PipelineBuilder() {
  const [description, setDescription] = useState('')
  const [yamlConfig, setYamlConfig] = useState('')
  const [sqlFiles, setSqlFiles] = useState<Record<string, string>>({})
  const [explanation, setExplanation] = useState('')
  const [activeTab, setActiveTab] = useState('yaml')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const { pillar } = usePillar()

  async function handleGenerate() {
    if (!description.trim()) return
    setLoading(true)
    setError('')
    try {
      const res = await generatePipeline(description, pillar)
      setYamlConfig(res.yaml_config)
      setSqlFiles(res.sql_files || {})
      setExplanation(res.explanation || '')
      setActiveTab('yaml')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Generation failed')
    } finally {
      setLoading(false)
    }
  }

  const tabs = [
    { id: 'yaml', label: 'YAML Config' },
    ...Object.keys(sqlFiles).map((name) => ({ id: name, label: name })),
  ]

  const activeContent = activeTab === 'yaml' ? yamlConfig : sqlFiles[activeTab] || ''

  return (
    <div className="h-full flex flex-col p-6 overflow-auto">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">Pipeline Builder</h2>

      {/* Description Input */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 mb-1">Describe your pipeline</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-genie-500"
          placeholder="e.g., Build a daily transform that counts unique cutting users per day from firehose_v3_enriched, filtering for CutProjectCompleted events. Target: analytics.daily_cutting_users. Board metric — 45 day lookback."
        />
        <button
          onClick={handleGenerate}
          disabled={!description.trim() || loading}
          className="mt-2 bg-genie-600 text-white rounded-lg px-4 py-2 text-sm hover:bg-genie-700 disabled:opacity-50 flex items-center gap-2"
        >
          {loading ? <Loader2 size={16} className="animate-spin" /> : <GitBranch size={16} />}
          Generate Pipeline
        </button>
      </div>

      {error && <div className="mb-4 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3">{error}</div>}

      {/* Output */}
      {(yamlConfig || Object.keys(sqlFiles).length > 0) && (
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Explanation */}
          {explanation && (
            <div className="mb-3 bg-blue-50 border border-blue-200 rounded-lg p-3">
              <div className="prose prose-sm max-w-none text-blue-900">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{explanation}</ReactMarkdown>
              </div>
            </div>
          )}

          {/* Tabs */}
          <div className="flex gap-1 border-b border-gray-200 mb-2">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-3 py-1.5 text-sm rounded-t-md ${
                  activeTab === tab.id
                    ? 'bg-gray-100 text-gray-900 font-medium border border-gray-200 border-b-white -mb-px'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Content */}
          <pre className="flex-1 overflow-auto bg-gray-900 text-gray-100 rounded-lg p-4 text-sm font-mono">
            {activeContent}
          </pre>
        </div>
      )}
    </div>
  )
}
