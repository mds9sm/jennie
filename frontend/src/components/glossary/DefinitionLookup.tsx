import { useState, useEffect } from 'react'
import {
  Search,
  Loader2,
  Plus,
  Check,
  X,
  ChevronDown,
  ChevronUp,
  Send,
  Sparkles,
} from 'lucide-react'
import {
  searchGlossary,
  getGlossaryFeedback,
  updateGlossaryFeedback,
  submitGlossaryCorrection,
} from '../../api/client'
import type { GlossaryEntry, GlossaryFeedbackItem } from '../../types'
import GlossaryWizard from './GlossaryWizard'

type SubTab = 'search' | 'contribute'

const PILLAR_OPTIONS = [
  'Growth',
  'Engagement',
  'Monetization',
  'Platform',
  'Content',
  'Operations',
]

// ── Inline correction form shown on each search-result card ──────────────────

function CorrectionForm({
  entry,
  onSubmitted,
}: {
  entry: GlossaryEntry
  onSubmitted: () => void
}) {
  const [correction, setCorrection] = useState(entry.definition)
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)

  async function handleSubmit() {
    if (!correction.trim()) return
    setSubmitting(true)
    try {
      await submitGlossaryCorrection(entry.term, correction)
      setSubmitted(true)
      onSubmitted()
    } catch {
      // silent
    } finally {
      setSubmitting(false)
    }
  }

  if (submitted) {
    return (
      <div className="mt-3 bg-green-50 border border-green-200 text-green-700 text-xs rounded-lg px-3 py-2 flex items-center gap-2">
        <Check size={14} />
        Correction submitted. Thank you!
      </div>
    )
  }

  return (
    <div className="mt-3 border border-gray-200 rounded-lg p-3 bg-gray-50">
      <label className="block text-xs font-medium text-gray-700 mb-1">
        Suggest a correction for &ldquo;{entry.term}&rdquo;
      </label>
      <textarea
        value={correction}
        onChange={(e) => setCorrection(e.target.value)}
        rows={3}
        className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-genie-500"
      />
      <button
        onClick={handleSubmit}
        disabled={!correction.trim() || submitting}
        className="mt-2 bg-genie-600 text-white rounded-lg px-3 py-1.5 text-xs hover:bg-genie-700 disabled:opacity-50 flex items-center gap-1.5"
      >
        {submitting ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
        Submit Correction
      </button>
    </div>
  )
}

// ── Definition card with correction toggle ───────────────────────────────────

function DefinitionCard({ entry }: { entry: GlossaryEntry }) {
  const [showCorrection, setShowCorrection] = useState(false)
  const [correctionSubmitted, setCorrectionSubmitted] = useState(false)

  return (
    <div className="border border-gray-200 rounded-lg p-4">
      <div className="flex items-center gap-2 mb-2">
        <h3 className="text-base font-semibold text-gray-900">{entry.term}</h3>
        {entry.pillar && (
          <span className="text-xs bg-genie-100 text-genie-800 px-2 py-0.5 rounded-full">
            {entry.pillar}
          </span>
        )}
      </div>
      <p className="text-sm text-gray-700 mb-3">{entry.definition}</p>
      {entry.formula && (
        <div className="mb-2">
          <span className="text-xs font-medium text-gray-500 uppercase">Formula</span>
          <p className="text-sm font-mono bg-gray-50 rounded px-2 py-1 mt-0.5">{entry.formula}</p>
        </div>
      )}
      <div className="flex gap-4 text-xs text-gray-500">
        {entry.source_table && (
          <span>
            Source: <code className="text-pink-600">{entry.source_table}</code>
          </span>
        )}
        {entry.dag && (
          <span>
            DAG: <code className="text-blue-600">{entry.dag}</code>
          </span>
        )}
      </div>
      {entry.notes && <p className="text-xs text-gray-400 mt-2 italic">{entry.notes}</p>}

      {/* Suggest correction toggle */}
      {!correctionSubmitted && (
        <button
          onClick={() => setShowCorrection(!showCorrection)}
          className="mt-3 text-xs text-genie-600 hover:text-genie-800 flex items-center gap-1 transition-colors"
        >
          {showCorrection ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          Suggest Correction
        </button>
      )}
      {showCorrection && !correctionSubmitted && (
        <CorrectionForm
          entry={entry}
          onSubmitted={() => {
            setCorrectionSubmitted(true)
            setShowCorrection(false)
          }}
        />
      )}
    </div>
  )
}

// ── Search sub-tab ───────────────────────────────────────────────────────────

function SearchTab() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<GlossaryEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)

  async function handleSearch() {
    if (!query.trim()) return
    setLoading(true)
    try {
      const res = await searchGlossary(query)
      setResults(res.results as GlossaryEntry[])
      setSearched(true)
    } catch {
      setResults([])
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      {/* Search */}
      <div className="flex gap-2 mb-6">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          placeholder="Search for a term: activation rate, churn, DAU..."
          className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-genie-500"
        />
        <button
          onClick={handleSearch}
          disabled={!query.trim() || loading}
          className="bg-genie-600 text-white rounded-lg px-4 py-2 text-sm hover:bg-genie-700 disabled:opacity-50 flex items-center gap-2"
        >
          {loading ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
          Search
        </button>
      </div>

      {/* Results */}
      <div className="flex-1 overflow-auto space-y-4">
        {searched && results.length === 0 && (
          <p className="text-gray-400 text-sm">No definitions found for &ldquo;{query}&rdquo;</p>
        )}
        {results.map((entry, i) => (
          <DefinitionCard key={i} entry={entry} />
        ))}
      </div>
    </>
  )
}

// ── Contribute sub-tab ───────────────────────────────────────────────────────

function ContributeTab() {
  // New-term form state
  const [term, setTerm] = useState('')
  const [definition, setDefinition] = useState('')
  const [formula, setFormula] = useState('')
  const [sourceTable, setSourceTable] = useState('')
  const [pillar, setPillar] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitSuccess, setSubmitSuccess] = useState(false)

  // Pending reviews
  const [feedback, setFeedback] = useState<GlossaryFeedbackItem[]>([])
  const [loadingFeedback, setLoadingFeedback] = useState(false)
  const [actionStates, setActionStates] = useState<Record<number, string>>({})

  async function fetchFeedback() {
    setLoadingFeedback(true)
    try {
      const data = await getGlossaryFeedback()
      setFeedback(data)
    } catch {
      // silent
    } finally {
      setLoadingFeedback(false)
    }
  }

  useEffect(() => {
    fetchFeedback()
  }, [])

  async function handleSubmitTerm() {
    if (!term.trim() || !definition.trim()) return
    setSubmitting(true)
    try {
      const correctionText = [
        `Definition: ${definition}`,
        formula ? `Formula: ${formula}` : null,
        sourceTable ? `Source table: ${sourceTable}` : null,
        pillar ? `Pillar: ${pillar}` : null,
      ]
        .filter(Boolean)
        .join('\n')

      await submitGlossaryCorrection(term, correctionText)
      setSubmitSuccess(true)
      setTerm('')
      setDefinition('')
      setFormula('')
      setSourceTable('')
      setPillar('')
      // refresh feedback list
      fetchFeedback()
      setTimeout(() => setSubmitSuccess(false), 3000)
    } catch {
      // silent
    } finally {
      setSubmitting(false)
    }
  }

  async function handleFeedbackAction(id: number, status: 'approved' | 'rejected') {
    setActionStates((prev) => ({ ...prev, [id]: 'loading' }))
    try {
      await updateGlossaryFeedback(id, status)
      setActionStates((prev) => ({ ...prev, [id]: status }))
      // remove from list after a brief delay
      setTimeout(() => {
        setFeedback((prev) => prev.filter((f) => f.id !== id))
        setActionStates((prev) => {
          const next = { ...prev }
          delete next[id]
          return next
        })
      }, 1500)
    } catch {
      setActionStates((prev) => ({ ...prev, [id]: 'error' }))
    }
  }

  return (
    <div className="space-y-8">
      {/* Contribution form */}
      <div className="border border-gray-200 rounded-lg p-5">
        <h3 className="text-sm font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Plus size={16} />
          Submit a New Term or Correction
        </h3>

        <div className="grid grid-cols-2 gap-4">
          <div className="col-span-2 sm:col-span-1">
            <label className="block text-xs font-medium text-gray-700 mb-1">Term Name *</label>
            <input
              type="text"
              value={term}
              onChange={(e) => setTerm(e.target.value)}
              placeholder="e.g., Activation Rate"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-genie-500"
            />
          </div>

          <div className="col-span-2 sm:col-span-1">
            <label className="block text-xs font-medium text-gray-700 mb-1">Pillar</label>
            <select
              value={pillar}
              onChange={(e) => setPillar(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-genie-500 bg-white"
            >
              <option value="">-- Select pillar --</option>
              {PILLAR_OPTIONS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>

          <div className="col-span-2">
            <label className="block text-xs font-medium text-gray-700 mb-1">Definition *</label>
            <textarea
              value={definition}
              onChange={(e) => setDefinition(e.target.value)}
              rows={3}
              placeholder="A clear, concise business definition..."
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-genie-500"
            />
          </div>

          <div className="col-span-2 sm:col-span-1">
            <label className="block text-xs font-medium text-gray-700 mb-1">Formula</label>
            <input
              type="text"
              value={formula}
              onChange={(e) => setFormula(e.target.value)}
              placeholder="e.g., activated_users / total_users"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-genie-500"
            />
          </div>

          <div className="col-span-2 sm:col-span-1">
            <label className="block text-xs font-medium text-gray-700 mb-1">Source Table</label>
            <input
              type="text"
              value={sourceTable}
              onChange={(e) => setSourceTable(e.target.value)}
              placeholder="e.g., analytics.dim_users"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-genie-500"
            />
          </div>
        </div>

        <div className="mt-4 flex items-center gap-3">
          <button
            onClick={handleSubmitTerm}
            disabled={!term.trim() || !definition.trim() || submitting}
            className="bg-genie-600 text-white rounded-lg px-4 py-2 text-sm hover:bg-genie-700 disabled:opacity-50 flex items-center gap-2"
          >
            {submitting ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
            Submit
          </button>
          {submitSuccess && (
            <span className="text-sm text-green-600 flex items-center gap-1">
              <Check size={14} /> Submitted successfully
            </span>
          )}
        </div>
      </div>

      {/* Pending Reviews */}
      <div>
        <h3 className="text-sm font-semibold text-gray-900 mb-3">Pending Reviews</h3>

        {loadingFeedback && (
          <div className="flex items-center gap-2 text-sm text-gray-500">
            <Loader2 size={14} className="animate-spin" />
            Loading...
          </div>
        )}

        {!loadingFeedback && feedback.length === 0 && (
          <p className="text-sm text-gray-400">No pending reviews</p>
        )}

        <div className="space-y-3">
          {feedback.map((item) => {
            const state = actionStates[item.id]

            return (
              <div
                key={item.id}
                className={`border rounded-lg p-4 transition-colors ${
                  state === 'approved'
                    ? 'border-green-300 bg-green-50'
                    : state === 'rejected'
                      ? 'border-red-300 bg-red-50'
                      : 'border-gray-200'
                }`}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-medium text-sm text-gray-900">{item.term}</span>
                      <span className="text-[10px] text-gray-400">
                        by {item.submitted_by}
                      </span>
                      <span className="text-[10px] text-gray-400">
                        {new Date(item.created_at).toLocaleDateString()}
                      </span>
                    </div>
                    <p className="text-sm text-gray-700 whitespace-pre-wrap">{item.correction}</p>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    {state === 'approved' ? (
                      <span className="text-green-600 flex items-center gap-1 text-xs font-medium">
                        <Check size={14} /> Approved
                      </span>
                    ) : state === 'rejected' ? (
                      <span className="text-red-600 flex items-center gap-1 text-xs font-medium">
                        <X size={14} /> Rejected
                      </span>
                    ) : state === 'loading' ? (
                      <Loader2 size={14} className="animate-spin text-gray-400" />
                    ) : (
                      <>
                        <button
                          onClick={() => handleFeedbackAction(item.id, 'approved')}
                          className="p-1.5 rounded-lg bg-green-100 text-green-700 hover:bg-green-200 transition-colors"
                          title="Approve"
                        >
                          <Check size={14} />
                        </button>
                        <button
                          onClick={() => handleFeedbackAction(item.id, 'rejected')}
                          className="p-1.5 rounded-lg bg-red-100 text-red-700 hover:bg-red-200 transition-colors"
                          title="Reject"
                        >
                          <X size={14} />
                        </button>
                      </>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── Main component ───────────────────────────────────────────────────────────

export default function DefinitionLookup() {
  const [activeTab, setActiveTab] = useState<SubTab>('search')
  const [wizardOpen, setWizardOpen] = useState(false)

  return (
    <div className="h-full flex flex-col p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-gray-900">Business Definitions</h2>
        <button
          onClick={() => setWizardOpen(true)}
          className="flex items-center gap-2 bg-genie-600 text-white rounded-lg px-4 py-2 text-sm hover:bg-genie-700 transition-colors shadow-sm"
        >
          <Sparkles size={16} />
          Add Term
        </button>
      </div>

      {/* Sub-tabs */}
      <div className="flex gap-1 mb-6 border-b border-gray-200">
        <button
          onClick={() => setActiveTab('search')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'search'
              ? 'border-genie-600 text-genie-800'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          <span className="flex items-center gap-1.5">
            <Search size={14} />
            Search
          </span>
        </button>
        <button
          onClick={() => setActiveTab('contribute')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'contribute'
              ? 'border-genie-600 text-genie-800'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          <span className="flex items-center gap-1.5">
            <Plus size={14} />
            Contribute
          </span>
        </button>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-auto">
        {activeTab === 'search' ? <SearchTab /> : <ContributeTab />}
      </div>

      {/* Glossary Wizard Modal */}
      {wizardOpen && <GlossaryWizard onClose={() => setWizardOpen(false)} />}
    </div>
  )
}
