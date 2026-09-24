import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell, Clock, Flag, BookOpen, UserPlus, AlertCircle, AtSign, MessageSquare, KeyRound } from 'lucide-react'
import { fetchJSON } from '../../api/client'

interface Notification {
  id: number
  type: string
  title: string
  link: string | null
  read: boolean
  created_at: string
}

function notificationIcon(type: string) {
  switch (type) {
    case 'scheduled_report':
      return <Clock size={14} className="text-blue-500" />
    case 'feedback_assigned':
    case 'task_assigned':
      return <Flag size={14} className="text-red-500" />
    case 'glossary_assigned':
      return <BookOpen size={14} className="text-purple-500" />
    case 'registration_request':
      return <UserPlus size={14} className="text-amber-500" />
    case 'password_reset_request':
      return <KeyRound size={14} className="text-blue-500" />
    case 'password_reset':
      return <KeyRound size={14} className="text-green-500" />
    case 'kb_gap':
      return <AlertCircle size={14} className="text-orange-500" />
    case 'glossary_correction':
      return <BookOpen size={14} className="text-amber-500" />
    case 'glossary_merged':
      return <BookOpen size={14} className="text-green-500" />
    case 'glossary_rejected':
      return <BookOpen size={14} className="text-red-500" />
    case 'mention':
      return <AtSign size={14} className="text-blue-500" />
    case 'chat_complete':
      return <MessageSquare size={14} className="text-green-500" />
    default:
      return <Bell size={14} className="text-gray-400" />
  }
}

function relativeTime(dateStr: string): string {
  const now = Date.now()
  const then = new Date(dateStr).getTime()
  const diffMs = now - then
  const diffSec = Math.floor(diffMs / 1000)
  if (diffSec < 60) return 'just now'
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 7) return `${diffDay}d ago`
  return new Date(dateStr).toLocaleDateString()
}

export default function NotificationBell() {
  const navigate = useNavigate()
  const [unreadCount, setUnreadCount] = useState(0)
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Poll unread count
  const pollCount = useCallback(() => {
    fetchJSON<{ count: number }>('/notifications/unread-count')
      .then(r => setUnreadCount(r.count))
      .catch(() => {})
  }, [])

  useEffect(() => {
    pollCount()
    const id = setInterval(pollCount, 30_000)
    return () => clearInterval(id)
  }, [pollCount])

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    if (open) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [open])

  // Load notifications when dropdown opens
  useEffect(() => {
    if (open) {
      setLoading(true)
      fetchJSON<Notification[]>('/notifications')
        .then(r => { setNotifications(r); setLoading(false) })
        .catch(() => setLoading(false))
    }
  }, [open])

  async function handleMarkAllRead() {
    try {
      await fetchJSON('/notifications/read-all', { method: 'POST' })
      setNotifications(prev => prev.map(n => ({ ...n, read: true })))
      setUnreadCount(0)
    } catch { /* ignore */ }
  }

  async function handleClickNotification(n: Notification) {
    if (!n.read) {
      try {
        await fetchJSON(`/notifications/${n.id}/read`, { method: 'POST' })
        setNotifications(prev => prev.map(x => x.id === n.id ? { ...x, read: true } : x))
        setUnreadCount(prev => Math.max(0, prev - 1))
      } catch { /* ignore */ }
    }
    setOpen(false)
    if (n.link) {
      // For chat links with session params, use window.location to ensure full reload
      if (n.link.includes('session=')) {
        window.location.href = n.link
      } else {
        navigate(n.link)
      }
    }
  }

  return (
    <div className="relative" ref={dropdownRef} data-tour="notifications">
      <button
        onClick={() => setOpen(prev => !prev)}
        className="relative p-1 rounded hover:bg-gray-100"
        title="Notifications"
      >
        <Bell size={16} className={unreadCount > 0 ? 'text-genie-600' : 'text-gray-400'} />
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[16px] h-4 flex items-center justify-center bg-red-500 text-white text-[10px] font-bold rounded-full px-0.5">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 w-80 bg-white border border-gray-200 rounded-lg shadow-lg z-50 max-h-96 flex flex-col">
          {/* Header */}
          <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100">
            <span className="text-sm font-medium text-gray-700">Notifications</span>
            {unreadCount > 0 && (
              <button
                onClick={handleMarkAllRead}
                className="text-xs text-genie-600 hover:text-genie-700 font-medium"
              >
                Mark all read
              </button>
            )}
          </div>

          {/* List */}
          <div className="flex-1 overflow-auto">
            {loading ? (
              <div className="p-4 text-center text-sm text-gray-400">Loading...</div>
            ) : notifications.length === 0 ? (
              <div className="p-4 text-center text-sm text-gray-400">No notifications</div>
            ) : (
              notifications.map(n => (
                <button
                  key={n.id}
                  onClick={() => handleClickNotification(n)}
                  className={`w-full text-left px-3 py-2.5 flex items-start gap-2.5 hover:bg-gray-50 transition-colors border-b border-gray-50 ${
                    n.read ? 'opacity-60' : ''
                  }`}
                >
                  <div className="mt-0.5 flex-shrink-0">
                    {notificationIcon(n.type)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className={`text-sm leading-tight ${n.read ? 'text-gray-500' : 'text-gray-900 font-medium'}`}>
                      {n.title}
                    </p>
                    <p className="text-[11px] text-gray-400 mt-0.5">
                      {relativeTime(n.created_at)}
                    </p>
                  </div>
                  {!n.read && (
                    <span className="w-2 h-2 bg-genie-500 rounded-full flex-shrink-0 mt-1.5" />
                  )}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
