import { useState, useEffect, useCallback } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  MessageSquare,
  Database,
  GitBranch,
  BookOpen,
  FileText,
  CalendarClock,
  ClipboardList,
  Newspaper,
  Settings,
  ChevronDown,
  ChevronRight,
  Clock,
  HelpCircle,
  Table2,
  ShieldCheck,
  X,
  Link,
} from 'lucide-react'
import { getRecentSessions, fetchJSON } from '../../api/client'
import { resetTour } from '../onboarding/GuidedTour'
import type { ChatSession } from '../../types'

const NAV_ITEMS = [
  { to: '/', icon: MessageSquare, label: 'Chat', tourId: 'chat' },
  { to: '/query', icon: Database, label: 'Workbench', tourId: 'workbench' },
  { to: '/catalog', icon: Table2, label: 'Catalog', tourId: 'catalog' },
  { to: '/glossary', icon: BookOpen, label: 'Glossary', tourId: 'glossary' },
  { to: '/lineage', icon: GitBranch, label: 'Lineage', tourId: 'lineage' },
  { to: '/events-dq', icon: ShieldCheck, label: 'Events DQ', tourId: 'events-dq' },
  { to: '/docs', icon: FileText, label: 'Docs', tourId: 'docs' },
  { to: '/tasks', icon: ClipboardList, label: 'Tasks', tourId: 'tasks' },
  { to: '/task-digest', icon: Newspaper, label: 'Digest', tourId: 'task-digest' },
  { to: '/reports', icon: CalendarClock, label: 'Reports', tourId: 'reports' },
]

function relativeTime(dateStr: string): string {
  const now = Date.now()
  const then = new Date(dateStr).getTime()
  const diffMs = now - then
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 7) return `${diffDay}d ago`
  return new Date(dateStr).toLocaleDateString()
}

interface SidebarProps {
  onStartTour?: () => void
}

export default function Sidebar({ onStartTour }: SidebarProps) {
  const [recentOpen, setRecentOpen] = useState(true)
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [appVersion, setAppVersion] = useState('')
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [copiedShareId, setCopiedShareId] = useState<string | null>(null)
  const navigate = useNavigate()

  const fetchRecent = useCallback(async () => {
    try {
      const sess = await getRecentSessions()
      setSessions(sess.slice(0, 15))
    } catch {
      // silently ignore — history is supplementary
    }
  }, [])

  useEffect(() => {
    fetchRecent()
    const interval = setInterval(fetchRecent, 30000)
    fetchJSON<{ version: string }>('/version').then(r => setAppVersion(r.version)).catch(() => {})
    return () => clearInterval(interval)
  }, [fetchRecent])

  function handleSessionClick(id: string) {
    navigate(`/?session=${id}`)
  }

  function handleNewChat() {
    // Client-side navigation — ChatView resets itself when it lands on / with
    // no session param (the old full-page reload threw away the SPA state).
    navigate('/')
  }

  function handleTakeTour() {
    resetTour()
    onStartTour?.()
  }

  return (
    <aside className="w-56 bg-gray-50 border-r border-gray-200 flex flex-col">
      <nav className="py-3">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            data-tour={item.tourId}
            className={({ isActive }) =>
              `flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                isActive
                  ? 'bg-genie-100 text-genie-800 font-medium border-r-2 border-genie-600'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
              }`
            }
          >
            <item.icon size={18} />
            {item.label}
          </NavLink>
        ))}
      </nav>

      {/* Chat sessions */}
      <div className="flex-1 overflow-auto border-t border-gray-200">
        <div className="flex items-center justify-between px-4 py-2">
          <button
            onClick={() => setRecentOpen(!recentOpen)}
            className="flex items-center gap-2 text-xs font-semibold text-gray-500 uppercase tracking-wider hover:text-gray-700 transition-colors"
          >
            {recentOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            Chats
          </button>
          <button
            onClick={handleNewChat}
            className="text-gray-400 hover:text-genie-600 transition-colors"
            title="New chat"
          >
            <MessageSquare size={14} />
          </button>
        </div>

        {recentOpen && (
          <div className="px-2 pb-2 space-y-0.5">
            {sessions.map((s) => (
              <div key={s.id} className="flex items-center group">
                {renamingId === s.id ? (
                  <input
                    value={renameValue}
                    onChange={e => setRenameValue(e.target.value)}
                    onKeyDown={async e => {
                      if (e.key === 'Enter' && renameValue.trim()) {
                        await fetchJSON(`/chat/sessions/${s.id}/title`, {
                          method: 'PUT', body: JSON.stringify({ title: renameValue.trim() })
                        })
                        setSessions(prev => prev.map(x => x.id === s.id ? { ...x, title: renameValue.trim() } : x))
                        setRenamingId(null)
                      }
                      if (e.key === 'Escape') setRenamingId(null)
                    }}
                    onBlur={() => setRenamingId(null)}
                    className="flex-1 text-xs border border-genie-400 rounded px-2 py-1 mx-1 bg-white"
                    autoFocus
                  />
                ) : (
                  <button
                    onClick={() => handleSessionClick(s.id)}
                    onDoubleClick={(e) => {
                      e.preventDefault()
                      setRenamingId(s.id)
                      setRenameValue(s.title || '')
                    }}
                    className="flex items-center gap-2 flex-1 px-2 py-1.5 text-xs text-gray-600 hover:bg-gray-100 rounded-l transition-colors text-left min-w-0"
                    title={`${s.title || 'Untitled'} (double-click to rename)`}
                  >
                    <Clock size={12} className="shrink-0 text-gray-400" />
                    <span className="truncate flex-1">
                      {s.title && s.title.length > 30 ? s.title.slice(0, 30) + '...' : s.title || 'Untitled'}
                    </span>
                    <span className="shrink-0 text-[10px] text-gray-400">
                      {relativeTime(s.updated_at)}
                    </span>
                  </button>
                )}
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    const shareUrl = `${window.location.origin}/?shared=${s.id}`
                    navigator.clipboard.writeText(shareUrl).then(() => {
                      setCopiedShareId(s.id)
                      setTimeout(() => setCopiedShareId(null), 1000)
                    }).catch(() => {
                      window.prompt('Copy this link:', shareUrl)
                    })
                  }}
                  className={`opacity-0 group-hover:opacity-100 p-1 transition-all shrink-0 ${
                    copiedShareId === s.id ? 'text-green-500 opacity-100' : 'text-gray-300 hover:text-blue-500'
                  }`}
                  title={copiedShareId === s.id ? 'Link copied!' : 'Share chat'}
                >
                  <Link size={12} />
                </button>
                <button
                  onClick={async (e) => {
                    e.stopPropagation()
                    if (!window.confirm('Delete this chat?')) return
                    try {
                      await fetchJSON(`/chat/sessions/${s.id}`, { method: 'DELETE' })
                      setSessions(prev => prev.filter(x => x.id !== s.id))
                    } catch { /* ignore */ }
                  }}
                  className="opacity-0 group-hover:opacity-100 p-1 text-gray-300 hover:text-red-500 transition-all shrink-0"
                  title="Delete chat"
                >
                  <X size={12} />
                </button>
              </div>
            ))}
            {sessions.length === 0 && (
              <p className="px-2 py-2 text-xs text-gray-400">No chats yet</p>
            )}
          </div>
        )}
      </div>

      {/* Bottom nav */}
      <div className="border-t border-gray-200">
        <NavLink
          to="/settings"
          data-tour="settings"
          className={({ isActive }) =>
            `flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
              isActive
                ? 'bg-genie-100 text-genie-800 font-medium'
                : 'text-gray-500 hover:bg-gray-100 hover:text-gray-900'
            }`
          }
        >
          <Settings size={18} />
          Settings
        </NavLink>
        <div className="flex items-center justify-between px-4 pb-3">
          <span className="text-xs text-gray-400" title={appVersion || ''}>Genie {appVersion ? `v${appVersion}` : 'v1.0.0'}</span>
          <button
            onClick={handleTakeTour}
            className="flex items-center gap-1 text-xs text-gray-400 hover:text-genie-600 transition-colors"
            title="Take a guided tour"
          >
            <HelpCircle size={14} />
            Tour
          </button>
        </div>
      </div>
    </aside>
  )
}
