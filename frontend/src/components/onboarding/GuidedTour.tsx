import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  MessageSquare,
  Database,
  BookOpen,
  GitBranch,
  CalendarClock,
  Bell,
  Settings,
  Sparkles,
  Rocket,
  ChevronLeft,
  ChevronRight,
  X,
} from 'lucide-react'

const STORAGE_KEY = 'genie_tour_completed'

interface TourStep {
  title: string
  description: string
  icon: React.ComponentType<{ size?: number; className?: string }>
  target?: string // CSS selector to highlight, or undefined for centered
  position?: 'center' | 'right' // card position relative to target
}

const STEPS: TourStep[] = [
  {
    title: 'Welcome to Jennie!',
    description:
      'Your AI-powered data engineering assistant. Let me give you a quick tour of the key features.',
    icon: Sparkles,
    position: 'center',
  },
  {
    title: 'Chat',
    description:
      'Ask anything about the organization\'s data platform -- tables, pipelines, metrics, or business definitions. AI specialist agents give grounded, source-backed answers.',
    icon: MessageSquare,
    target: '[data-tour="chat"]',
    position: 'right',
  },
  {
    title: 'Workbench',
    description:
      'A full SQL IDE with schema browser, repo file management, and Git integration. Edit, run, commit, and push -- all in one place.',
    icon: Database,
    target: '[data-tour="workbench"]',
    position: 'right',
  },
  {
    title: 'Glossary',
    description:
      'Business term definitions with a PR-style review workflow. Upload documents, use the AI wizard, or create entries manually.',
    icon: BookOpen,
    target: '[data-tour="glossary"]',
    position: 'right',
  },
  {
    title: 'Lineage',
    description:
      'Trace data dependencies -- see what tables feed a pipeline and what breaks if something changes.',
    icon: GitBranch,
    target: '[data-tour="lineage"]',
    position: 'right',
  },
  {
    title: 'Reports',
    description:
      'Schedule any chat question to run automatically. Get a notification when your daily pipeline report is ready.',
    icon: CalendarClock,
    target: '[data-tour="reports"]',
    position: 'right',
  },
  {
    title: 'Notifications',
    description:
      'The bell icon shows notifications -- scheduled reports, assigned reviews, and task assignments.',
    icon: Bell,
    target: '[data-tour="notifications"]',
    position: 'right',
  },
  {
    title: 'Settings',
    description:
      'Configure your persona, system prompt, and Git identity. Admins can manage connections, knowledge base, and users.',
    icon: Settings,
    target: '[data-tour="settings"]',
    position: 'right',
  },
  {
    title: "You're all set!",
    description:
      'Start by asking a question in Chat, or explore the sidebar to find what you need.',
    icon: Rocket,
    position: 'center',
  },
]

interface Props {
  visible: boolean
  onClose: () => void
}

export default function GuidedTour({ visible, onClose }: Props) {
  const [step, setStep] = useState(0)
  const [targetRect, setTargetRect] = useState<DOMRect | null>(null)
  const navigate = useNavigate()

  const current = STEPS[step]

  const measureTarget = useCallback(() => {
    if (!current.target) {
      setTargetRect(null)
      return
    }
    const el = document.querySelector(current.target)
    if (el) {
      setTargetRect(el.getBoundingClientRect())
    } else {
      setTargetRect(null)
    }
  }, [current.target])

  useEffect(() => {
    if (!visible) return
    measureTarget()
    window.addEventListener('resize', measureTarget)
    return () => window.removeEventListener('resize', measureTarget)
  }, [visible, measureTarget])

  useEffect(() => {
    if (!visible) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') handleSkip()
      if (e.key === 'ArrowRight') handleNext()
      if (e.key === 'ArrowLeft') handleBack()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, step])

  if (!visible) return null

  function handleNext() {
    if (step < STEPS.length - 1) {
      setStep(step + 1)
    } else {
      handleFinish()
    }
  }

  function handleBack() {
    if (step > 0) setStep(step - 1)
  }

  function handleSkip() {
    localStorage.setItem(STORAGE_KEY, 'true')
    setStep(0)
    onClose()
  }

  function handleFinish() {
    localStorage.setItem(STORAGE_KEY, 'true')
    setStep(0)
    onClose()
    navigate('/')
  }

  function handleStartChatting() {
    localStorage.setItem(STORAGE_KEY, 'true')
    setStep(0)
    onClose()
    navigate('/')
  }

  // Card positioning
  const isCentered = current.position === 'center' || !targetRect

  const CARD_HEIGHT = 220 // approximate card height
  const CARD_WIDTH = 380

  const cardStyle: React.CSSProperties = isCentered
    ? {
        position: 'fixed',
        top: '50%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
      }
    : {
        position: 'fixed',
        // Clamp top so card stays within viewport
        top: Math.min(
          Math.max(8, targetRect!.top - 12),
          window.innerHeight - CARD_HEIGHT - 16
        ),
        // Position to the right of sidebar, but clamp to viewport
        left: Math.min(targetRect!.right + 16, window.innerWidth - CARD_WIDTH - 16),
      }

  const Icon = current.icon

  return (
    <div className="fixed inset-0 z-[9999]">
      {/* Overlay */}
      <div
        className="absolute inset-0 bg-black/50 transition-opacity duration-300"
        onClick={handleSkip}
      />

      {/* Spotlight cutout on target element */}
      {targetRect && !isCentered && (
        <div
          className="absolute rounded-lg ring-4 ring-genie-500/60 bg-transparent pointer-events-none"
          style={{
            top: targetRect.top - 4,
            left: targetRect.left - 4,
            width: targetRect.width + 8,
            height: targetRect.height + 8,
            boxShadow: '0 0 0 9999px rgba(0,0,0,0.5)',
            zIndex: 10000,
          }}
        />
      )}

      {/* Card */}
      <div
        className="bg-white rounded-xl shadow-2xl border border-gray-200 w-[380px] max-w-[90vw] p-6 transition-all duration-300"
        style={{ ...cardStyle, zIndex: 10001 }}
      >
        {/* Close button */}
        <button
          onClick={handleSkip}
          className="absolute top-3 right-3 text-gray-400 hover:text-gray-600 transition-colors"
          title="Skip tour"
        >
          <X size={18} />
        </button>

        {/* Icon + Title */}
        <div className="flex items-center gap-3 mb-3">
          <div className="w-10 h-10 rounded-lg bg-genie-100 flex items-center justify-center shrink-0">
            <Icon size={22} className="text-genie-600" />
          </div>
          <h3 className="text-lg font-semibold text-gray-900">{current.title}</h3>
        </div>

        {/* Description */}
        <p className="text-sm text-gray-600 leading-relaxed mb-5">{current.description}</p>

        {/* Final step: action buttons */}
        {step === STEPS.length - 1 && (
          <div className="flex gap-2 mb-4">
            <button
              onClick={handleStartChatting}
              className="flex-1 px-4 py-2 bg-genie-600 text-white rounded-lg text-sm font-medium hover:bg-genie-700 transition-colors"
            >
              Start Chatting
            </button>
          </div>
        )}

        {/* Progress + Nav */}
        <div className="flex items-center justify-between">
          {/* Progress dots */}
          <div className="flex items-center gap-1.5">
            {STEPS.map((_, i) => (
              <div
                key={i}
                className={`w-2 h-2 rounded-full transition-colors ${
                  i === step ? 'bg-genie-600' : i < step ? 'bg-genie-300' : 'bg-gray-200'
                }`}
              />
            ))}
          </div>

          {/* Step counter + buttons */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-400 mr-1">
              {step + 1} / {STEPS.length}
            </span>

            {step > 0 && (
              <button
                onClick={handleBack}
                className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
                title="Previous"
              >
                <ChevronLeft size={18} />
              </button>
            )}

            {step < STEPS.length - 1 ? (
              <button
                onClick={handleNext}
                className="flex items-center gap-1 px-3 py-1.5 bg-genie-600 text-white rounded-lg text-sm font-medium hover:bg-genie-700 transition-colors"
              >
                Next
                <ChevronRight size={16} />
              </button>
            ) : (
              <button
                onClick={handleFinish}
                className="px-3 py-1.5 bg-gray-100 text-gray-600 rounded-lg text-sm font-medium hover:bg-gray-200 transition-colors"
              >
                Done
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

/** Check if user has completed the tour */
export function isTourCompleted(): boolean {
  return localStorage.getItem(STORAGE_KEY) === 'true'
}

/** Reset tour so it shows again */
export function resetTour(): void {
  localStorage.removeItem(STORAGE_KEY)
}
