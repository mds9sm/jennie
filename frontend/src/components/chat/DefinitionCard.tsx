import { useState } from 'react'
import { BookOpen, ChevronDown, ChevronUp, Send } from 'lucide-react'
import { submitGlossaryCorrection } from '../../api/client'

interface GlossaryData {
  term?: string
  definition?: string
  formula?: string
  source_table?: string
  dag?: string
  pillar?: string
  notes?: string
  matches?: GlossaryData[]
  error?: string
}

interface Props {
  data: GlossaryData
}

export default function DefinitionCard({ data }: Props) {
  const [showCorrection, setShowCorrection] = useState(false)
  const [correction, setCorrection] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  // If it's a multi-match result, render each entry
  if (data.matches) {
    return (
      <div className="mt-3 space-y-2">
        {data.matches.map((entry, i) => (
          <DefinitionCard key={i} data={entry} />
        ))}
      </div>
    )
  }

  if (data.error) {
    return (
      <div className="mt-3 border border-amber-200 rounded-lg px-3 py-2 bg-amber-50 text-xs text-amber-700">
        {data.error}
      </div>
    )
  }

  async function handleSubmitCorrection() {
    if (!correction.trim() || !data.term) return
    setSubmitting(true)
    try {
      await submitGlossaryCorrection(data.term, correction)
      setSubmitted(true)
    } catch {
      // silently fail
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="mt-3 border border-gray-200 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 bg-gray-50 border-b border-gray-200">
        <BookOpen size={14} className="text-genie-600" />
        <span className="text-xs font-medium text-gray-700">{data.term || 'Glossary Entry'}</span>
        {data.pillar && (
          <span className="ml-auto text-[10px] font-medium px-2 py-0.5 rounded-full bg-genie-100 text-genie-700">
            {data.pillar}
          </span>
        )}
      </div>

      {/* Body */}
      <div className="px-3 py-2 space-y-2 text-xs">
        {data.definition && (
          <div>
            <span className="font-medium text-gray-500">Definition: </span>
            <span className="text-gray-800">{data.definition}</span>
          </div>
        )}
        {data.formula && (
          <div>
            <span className="font-medium text-gray-500">Formula: </span>
            <code className="text-pink-600 bg-gray-100 px-1 py-0.5 rounded text-[11px]">{data.formula}</code>
          </div>
        )}
        {data.source_table && (
          <div>
            <span className="font-medium text-gray-500">Source Table: </span>
            <code className="text-blue-600 bg-gray-100 px-1 py-0.5 rounded text-[11px]">{data.source_table}</code>
          </div>
        )}
        {data.dag && (
          <div>
            <span className="font-medium text-gray-500">DAG: </span>
            <span className="text-gray-800">{data.dag}</span>
          </div>
        )}
        {data.notes && (
          <div>
            <span className="font-medium text-gray-500">Notes: </span>
            <span className="text-gray-600 italic">{data.notes}</span>
          </div>
        )}
      </div>

      {/* Suggest Correction */}
      <div className="px-3 py-2 border-t border-gray-100">
        {!submitted ? (
          <>
            <button
              onClick={() => setShowCorrection(!showCorrection)}
              className="inline-flex items-center gap-1 text-[11px] text-gray-400 hover:text-gray-600 transition-colors"
            >
              {showCorrection ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              Suggest Correction
            </button>
            {showCorrection && (
              <div className="mt-2 flex gap-2">
                <input
                  type="text"
                  value={correction}
                  onChange={(e) => setCorrection(e.target.value)}
                  placeholder="Describe the correction..."
                  className="flex-1 text-xs border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-genie-500"
                />
                <button
                  onClick={handleSubmitCorrection}
                  disabled={submitting || !correction.trim()}
                  className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-genie-600 text-white rounded hover:bg-genie-700 disabled:opacity-50"
                >
                  <Send size={10} />
                  {submitting ? '...' : 'Send'}
                </button>
              </div>
            )}
          </>
        ) : (
          <span className="text-[11px] text-green-600">Correction submitted. Thank you!</span>
        )}
      </div>
    </div>
  )
}
