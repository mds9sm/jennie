import { useState } from 'react'
import {
  X,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Sparkles,
  Check,
  Send,
} from 'lucide-react'
import { fetchJSON } from '../../api/client'
import { useAuth } from '../../context/AuthContext'

interface WizardQuestion {
  id: number
  text: string
  type: 'select' | 'yes_no' | 'yes_no_text' | 'text'
  options?: string[]
  follow_up_on?: string
  placeholder?: string
}

interface SynthesizedEntry {
  term: string
  definition: string
  formula: string | null
  source_table: string | null
  pillar: string | null
  notes: string | null
}

interface GlossaryWizardProps {
  initialTerm?: string
  triggerReason?: string
  onClose: () => void
}

export default function GlossaryWizard({
  initialTerm,
  triggerReason = 'user_initiated',
  onClose,
}: GlossaryWizardProps) {
  const { sessionId } = useAuth()
  const [step, setStep] = useState<'loading' | 'questions' | 'preview' | 'submitted'>('loading')
  const [wizardId, setWizardId] = useState('')
  const [questions, setQuestions] = useState<WizardQuestion[]>([])
  const [currentQ, setCurrentQ] = useState(0)
  const [answers, setAnswers] = useState<Record<number, string>>({})
  const [synthesized, setSynthesized] = useState<SynthesizedEntry | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  // Term input for when no initial term is provided
  const [termInput, setTermInput] = useState(initialTerm || '')
  const [showTermPrompt, setShowTermPrompt] = useState(!initialTerm)

  async function startWizard() {
    setStep('loading')
    setError('')
    try {
      const res = await fetchJSON<{ wizard_id: string; questions: WizardQuestion[] }>(
        '/glossary/wizard/start',
        {
          method: 'POST',
          body: JSON.stringify({
            term: termInput || null,
            session_id: sessionId,
            trigger_reason: triggerReason,
          }),
        },
      )
      setWizardId(res.wizard_id)
      setQuestions(res.questions)
      setCurrentQ(0)
      setAnswers({})
      setStep('questions')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start wizard')
      setStep('loading')
    }
  }

  async function submitAnswers() {
    setSubmitting(true)
    setError('')
    try {
      const answerList = Object.entries(answers).map(([qid, value]) => ({
        question_id: parseInt(qid),
        value,
      }))
      const res = await fetchJSON<{ entry: SynthesizedEntry; status: string }>(
        '/glossary/wizard/submit',
        {
          method: 'POST',
          body: JSON.stringify({
            wizard_id: wizardId,
            answers: answerList,
            session_id: sessionId,
          }),
        },
      )
      setSynthesized(res.entry)
      setStep('preview')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to submit answers')
    } finally {
      setSubmitting(false)
    }
  }

  function setAnswer(questionId: number, value: string) {
    setAnswers((prev) => ({ ...prev, [questionId]: value }))
  }

  function handleNext() {
    if (currentQ < questions.length - 1) {
      setCurrentQ((prev) => prev + 1)
    } else {
      submitAnswers()
    }
  }

  function handleBack() {
    if (currentQ > 0) {
      setCurrentQ((prev) => prev - 1)
    }
  }

  // Render question input based on type
  function renderQuestionInput(q: WizardQuestion) {
    const value = answers[q.id] || ''

    switch (q.type) {
      case 'select':
        return (
          <div className="space-y-2 mt-4">
            {(q.options || []).map((opt) => (
              <button
                key={opt}
                onClick={() => setAnswer(q.id, opt)}
                className={`w-full text-left px-4 py-3 rounded-lg border text-sm transition-colors ${
                  value === opt
                    ? 'border-genie-600 bg-genie-50 text-genie-800 font-medium'
                    : 'border-gray-200 text-gray-700 hover:border-gray-300 hover:bg-gray-50'
                }`}
              >
                {opt}
              </button>
            ))}
          </div>
        )

      case 'yes_no':
        return (
          <div className="flex gap-3 mt-4">
            {['Yes', 'No'].map((opt) => (
              <button
                key={opt}
                onClick={() => setAnswer(q.id, opt.toLowerCase())}
                className={`flex-1 px-4 py-3 rounded-lg border text-sm font-medium transition-colors ${
                  value === opt.toLowerCase()
                    ? 'border-genie-600 bg-genie-50 text-genie-800'
                    : 'border-gray-200 text-gray-700 hover:border-gray-300 hover:bg-gray-50'
                }`}
              >
                {opt}
              </button>
            ))}
          </div>
        )

      case 'yes_no_text': {
        const yesNo = value.startsWith('yes:') ? 'yes' : value === 'no' ? 'no' : ''
        const textPart = value.startsWith('yes:') ? value.slice(4) : ''
        return (
          <div className="mt-4 space-y-3">
            <div className="flex gap-3">
              {['Yes', 'No'].map((opt) => (
                <button
                  key={opt}
                  onClick={() =>
                    setAnswer(q.id, opt.toLowerCase() === 'yes' ? 'yes:' : 'no')
                  }
                  className={`flex-1 px-4 py-3 rounded-lg border text-sm font-medium transition-colors ${
                    yesNo === opt.toLowerCase()
                      ? 'border-genie-600 bg-genie-50 text-genie-800'
                      : 'border-gray-200 text-gray-700 hover:border-gray-300 hover:bg-gray-50'
                  }`}
                >
                  {opt}
                </button>
              ))}
            </div>
            {yesNo === 'yes' && (
              <textarea
                value={textPart}
                onChange={(e) => setAnswer(q.id, `yes:${e.target.value}`)}
                rows={3}
                placeholder={q.placeholder || 'Please provide details...'}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-genie-500"
              />
            )}
          </div>
        )
      }

      case 'text':
        return (
          <textarea
            value={value}
            onChange={(e) => setAnswer(q.id, e.target.value)}
            rows={4}
            placeholder={q.placeholder || 'Type your answer...'}
            className="w-full mt-4 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-genie-500"
          />
        )

      default:
        return null
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg mx-4 max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <div className="flex items-center gap-2">
            <Sparkles size={18} className="text-genie-600" />
            <h2 className="text-base font-semibold text-gray-900">Glossary Wizard</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto px-6 py-5">
          {/* Term prompt (before starting) */}
          {showTermPrompt && step === 'loading' && !error && (
            <div className="space-y-4">
              <p className="text-sm text-gray-600">
                What term would you like to define or contribute?
              </p>
              <input
                type="text"
                value={termInput}
                onChange={(e) => setTermInput(e.target.value)}
                placeholder="e.g., Activation Rate, DAU, Churn..."
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-genie-500"
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && termInput.trim()) {
                    setShowTermPrompt(false)
                    startWizard()
                  }
                }}
              />
              <button
                onClick={() => {
                  setShowTermPrompt(false)
                  startWizard()
                }}
                disabled={!termInput.trim()}
                className="bg-genie-600 text-white rounded-lg px-4 py-2 text-sm hover:bg-genie-700 disabled:opacity-50 flex items-center gap-2"
              >
                <Sparkles size={14} />
                Start Wizard
              </button>
            </div>
          )}

          {/* Loading state (after starting) */}
          {step === 'loading' && !showTermPrompt && !error && (
            <div className="flex flex-col items-center justify-center py-12">
              <Loader2 size={32} className="animate-spin text-genie-600 mb-3" />
              <p className="text-sm text-gray-500">Generating smart questions...</p>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
              {error}
              <button
                onClick={() => {
                  setError('')
                  setShowTermPrompt(true)
                  setStep('loading')
                }}
                className="ml-2 underline text-red-700"
              >
                Try again
              </button>
            </div>
          )}

          {/* Questions */}
          {step === 'questions' && questions.length > 0 && (
            <div>
              {/* Progress */}
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium text-gray-500">
                  Step {currentQ + 1} of {questions.length}
                </span>
                <span className="text-xs text-gray-400">
                  {Math.round(((currentQ + 1) / questions.length) * 100)}%
                </span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-1.5 mb-6">
                <div
                  className="bg-genie-600 h-1.5 rounded-full transition-all duration-300"
                  style={{ width: `${((currentQ + 1) / questions.length) * 100}%` }}
                />
              </div>

              {/* Question */}
              <h3 className="text-sm font-medium text-gray-900">
                {questions[currentQ].text}
              </h3>
              {renderQuestionInput(questions[currentQ])}
            </div>
          )}

          {/* Preview synthesized entry */}
          {step === 'preview' && synthesized && (
            <div className="space-y-4">
              <div className="flex items-center gap-2 mb-2">
                <Check size={18} className="text-green-600" />
                <h3 className="text-sm font-semibold text-gray-900">
                  Here is your synthesized glossary entry:
                </h3>
              </div>

              <div className="border border-gray-200 rounded-lg p-4 space-y-3">
                <div>
                  <span className="text-xs font-medium text-gray-500 uppercase">Term</span>
                  <p className="text-base font-semibold text-gray-900">{synthesized.term}</p>
                </div>
                <div>
                  <span className="text-xs font-medium text-gray-500 uppercase">Definition</span>
                  <p className="text-sm text-gray-700">{synthesized.definition}</p>
                </div>
                {synthesized.formula && (
                  <div>
                    <span className="text-xs font-medium text-gray-500 uppercase">Formula</span>
                    <p className="text-sm font-mono bg-gray-50 rounded px-2 py-1 mt-0.5">
                      {synthesized.formula}
                    </p>
                  </div>
                )}
                {synthesized.source_table && (
                  <div>
                    <span className="text-xs font-medium text-gray-500 uppercase">Source Table</span>
                    <p className="text-sm font-mono text-pink-600">{synthesized.source_table}</p>
                  </div>
                )}
                {synthesized.pillar && (
                  <div>
                    <span className="text-xs font-medium text-gray-500 uppercase">Pillar</span>
                    <span className="inline-block text-xs bg-genie-100 text-genie-800 px-2 py-0.5 rounded-full mt-0.5">
                      {synthesized.pillar}
                    </span>
                  </div>
                )}
                {synthesized.notes && (
                  <div>
                    <span className="text-xs font-medium text-gray-500 uppercase">Notes</span>
                    <p className="text-sm text-gray-600 italic">{synthesized.notes}</p>
                  </div>
                )}
              </div>

              <p className="text-xs text-gray-400">
                This entry has been submitted for review. Thank you for contributing!
              </p>
            </div>
          )}

          {/* Submitted confirmation */}
          {step === 'submitted' && (
            <div className="flex flex-col items-center justify-center py-12">
              <div className="w-12 h-12 rounded-full bg-green-100 flex items-center justify-center mb-3">
                <Check size={24} className="text-green-600" />
              </div>
              <h3 className="text-base font-semibold text-gray-900 mb-1">Submitted!</h3>
              <p className="text-sm text-gray-500 text-center">
                Your glossary contribution has been submitted for review.
              </p>
            </div>
          )}
        </div>

        {/* Footer navigation */}
        {step === 'questions' && (
          <div className="flex items-center justify-between px-6 py-4 border-t border-gray-200">
            <button
              onClick={handleBack}
              disabled={currentQ === 0}
              className="flex items-center gap-1.5 text-sm text-gray-600 hover:text-gray-900 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronLeft size={16} />
              Back
            </button>
            <button
              onClick={handleNext}
              disabled={!answers[questions[currentQ]?.id] || submitting}
              className="flex items-center gap-1.5 bg-genie-600 text-white rounded-lg px-4 py-2 text-sm hover:bg-genie-700 disabled:opacity-50 transition-colors"
            >
              {submitting ? (
                <>
                  <Loader2 size={14} className="animate-spin" />
                  Synthesizing...
                </>
              ) : currentQ < questions.length - 1 ? (
                <>
                  Next
                  <ChevronRight size={16} />
                </>
              ) : (
                <>
                  <Send size={14} />
                  Finish
                </>
              )}
            </button>
          </div>
        )}

        {step === 'preview' && (
          <div className="flex items-center justify-end px-6 py-4 border-t border-gray-200">
            <button
              onClick={() => {
                setStep('submitted')
              }}
              className="flex items-center gap-1.5 bg-genie-600 text-white rounded-lg px-4 py-2 text-sm hover:bg-genie-700 transition-colors"
            >
              <Check size={14} />
              Done
            </button>
          </div>
        )}

        {step === 'submitted' && (
          <div className="flex items-center justify-end px-6 py-4 border-t border-gray-200">
            <button
              onClick={onClose}
              className="flex items-center gap-1.5 bg-genie-600 text-white rounded-lg px-4 py-2 text-sm hover:bg-genie-700 transition-colors"
            >
              Close
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
