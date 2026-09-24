import { useState, useEffect, useCallback, useMemo } from 'react'
import { X, Lightbulb } from 'lucide-react'

interface Tip {
  id: string
  text: string
  pages: string[] // route paths this tip applies to; empty = all pages
}

const ALL_TIPS: Tip[] = [
  // Chat
  { id: 'chat-schedule', text: 'You can schedule any response as a recurring report using the clock icon', pages: ['/chat', '/'] },
  { id: 'chat-flag', text: 'Click the flag icon to create a task or request support from your team', pages: ['/chat', '/'] },
  { id: 'chat-citations', text: 'Responses include source citations \u2014 check the bottom for referenced tables and DAGs', pages: ['/chat', '/'] },
  { id: 'chat-sessions', text: 'Your conversations are saved automatically. Find them in the sidebar under Chats', pages: ['/chat', '/'] },

  // Workbench
  { id: 'workbench-rightclick', text: 'Right-click files in the repo browser for rename, delete, and new file options', pages: ['/workbench'] },
  { id: 'workbench-shortcuts', text: 'Press Cmd+Enter to run your query, Cmd+S to save repo files', pages: ['/workbench'] },
  { id: 'workbench-isolation', text: 'Each user gets their own git workspace \u2014 your branch won\'t affect others', pages: ['/workbench'] },

  // Glossary
  { id: 'glossary-upload', text: 'Upload documents (.docx, .pdf, .txt) to auto-extract business terms', pages: ['/glossary'] },
  { id: 'glossary-reviewers', text: 'Assign reviewers to individual entries, like PR reviewers on GitHub', pages: ['/glossary'] },

  // Tasks
  { id: 'tasks-chat', text: 'Create tasks directly from chat using the flag icon on any response', pages: ['/tasks'] },
  { id: 'tasks-glossary', text: 'Glossary review tickets auto-update as entries get approved', pages: ['/tasks'] },

  // Lineage
  { id: 'lineage-depth', text: 'Use depth controls (+/-) to expand or collapse the dependency graph', pages: ['/lineage'] },

  // Reports
  { id: 'reports-schedule', text: 'Schedule any chat question to run daily \u2014 get notified when results are ready', pages: ['/reports'] },

  // General (any page)
  { id: 'general-notifications', text: 'Check the notification bell for assigned tasks, scheduled reports, and review requests', pages: [] },
  { id: 'general-tour', text: 'Click \'Tour\' at the bottom of the sidebar for a guided walkthrough', pages: [] },
]

const STORAGE_KEY = 'genie-dismissed-tips'
const SESSION_KEY = 'genie-session-dismissed-tips'

function getPermanentlyDismissed(): Set<string> {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored ? new Set(JSON.parse(stored)) : new Set()
  } catch {
    return new Set()
  }
}

function savePermanentlyDismissed(ids: Set<string>) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...ids]))
}

function getSessionDismissed(): Set<string> {
  try {
    const stored = sessionStorage.getItem(SESSION_KEY)
    return stored ? new Set(JSON.parse(stored)) : new Set()
  } catch {
    return new Set()
  }
}

function saveSessionDismissed(ids: Set<string>) {
  sessionStorage.setItem(SESSION_KEY, JSON.stringify([...ids]))
}

interface FeatureTipsProps {
  currentPath: string
}

export default function FeatureTips({ currentPath }: FeatureTipsProps) {
  const [permanentlyDismissed, setPermanentlyDismissed] = useState<Set<string>>(getPermanentlyDismissed)
  const [sessionDismissed, setSessionDismissed] = useState<Set<string>>(getSessionDismissed)
  const [currentTipIndex, setCurrentTipIndex] = useState(0)
  const [visible, setVisible] = useState(true)

  // Normalize path: strip trailing slash, treat empty as /
  const normalizedPath = currentPath === '' ? '/' : currentPath.replace(/\/$/, '') || '/'

  // Filter tips relevant to current page and not dismissed
  const availableTips = useMemo(() => {
    return ALL_TIPS.filter(tip => {
      if (permanentlyDismissed.has(tip.id) || sessionDismissed.has(tip.id)) return false
      // General tips (empty pages array) show on any page
      if (tip.pages.length === 0) return true
      // Page-specific tips: check if current path starts with any of the tip's pages
      return tip.pages.some(page => normalizedPath === page || normalizedPath.startsWith(page + '/'))
    })
  }, [normalizedPath, permanentlyDismissed, sessionDismissed])

  // Reset index when available tips change
  useEffect(() => {
    setCurrentTipIndex(0)
    setVisible(true)
  }, [normalizedPath])

  // Auto-rotate every 30 seconds
  useEffect(() => {
    if (availableTips.length <= 1) return
    const interval = setInterval(() => {
      setCurrentTipIndex(prev => (prev + 1) % availableTips.length)
      setVisible(true)
    }, 30000)
    return () => clearInterval(interval)
  }, [availableTips.length])

  const handleDismiss = useCallback(() => {
    if (availableTips.length === 0) return
    const tipId = availableTips[currentTipIndex]?.id
    if (!tipId) return

    const newSessionDismissed = new Set(sessionDismissed)
    newSessionDismissed.add(tipId)
    setSessionDismissed(newSessionDismissed)
    saveSessionDismissed(newSessionDismissed)

    // Move to next tip or hide
    if (availableTips.length <= 1) {
      setVisible(false)
    } else {
      setCurrentTipIndex(prev => prev % (availableTips.length - 1))
    }
  }, [availableTips, currentTipIndex, sessionDismissed])

  const handleDontShowAgain = useCallback(() => {
    if (availableTips.length === 0) return
    const tipId = availableTips[currentTipIndex]?.id
    if (!tipId) return

    const newPermanentlyDismissed = new Set(permanentlyDismissed)
    newPermanentlyDismissed.add(tipId)
    setPermanentlyDismissed(newPermanentlyDismissed)
    savePermanentlyDismissed(newPermanentlyDismissed)

    // Move to next tip or hide
    if (availableTips.length <= 1) {
      setVisible(false)
    } else {
      setCurrentTipIndex(prev => prev % (availableTips.length - 1))
    }
  }, [availableTips, currentTipIndex, permanentlyDismissed])

  // Don't render if no tips or not visible
  if (!visible || availableTips.length === 0) return null

  const currentTip = availableTips[currentTipIndex % availableTips.length]
  if (!currentTip) return null

  return (
    <div className="mx-4 mb-3 px-4 py-2.5 bg-blue-50 border border-blue-200 rounded-lg flex items-center gap-3 text-sm animate-in fade-in duration-300">
      <Lightbulb className="w-4 h-4 text-blue-500 flex-shrink-0" />
      <span className="text-blue-800 flex-1">{currentTip.text}</span>
      <button
        onClick={handleDontShowAgain}
        className="text-xs text-blue-400 hover:text-blue-600 whitespace-nowrap flex-shrink-0"
        title="Don't show this tip again"
      >
        Don't show again
      </button>
      <button
        onClick={handleDismiss}
        className="text-blue-400 hover:text-blue-600 flex-shrink-0"
        title="Dismiss"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}
