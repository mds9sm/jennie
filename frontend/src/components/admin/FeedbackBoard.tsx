import { useState, useEffect } from 'react'
import { fetchJSON } from '../../api/client'
import { MessageSquare, User, Clock, ChevronRight, AlertCircle, CheckCircle, Loader2, ArrowRight } from 'lucide-react'

interface Ticket {
  id: number
  title: string
  description: string
  status: string
  priority: string
  category: string
  created_by: string
  assigned_to: string | null
  chat_session_id: string | null
  resolution: string | null
  created_at: string
  updated_at: string
}

const STATUS_COLS = [
  { key: 'open', label: 'Open', bg: 'bg-red-50', border: 'border-red-200', badge: 'bg-red-100 text-red-700' },
  { key: 'in_progress', label: 'In Progress', bg: 'bg-yellow-50', border: 'border-yellow-200', badge: 'bg-yellow-100 text-yellow-700' },
  { key: 'resolved', label: 'Resolved', bg: 'bg-green-50', border: 'border-green-200', badge: 'bg-green-100 text-green-700' },
  { key: 'closed', label: 'Closed', bg: 'bg-gray-50', border: 'border-gray-200', badge: 'bg-gray-100 text-gray-500' },
]

const PRIORITY_COLORS: Record<string, string> = {
  high: 'bg-red-100 text-red-600',
  medium: 'bg-amber-100 text-amber-600',
  low: 'bg-blue-100 text-blue-600',
}

const CATEGORY_STYLES: Record<string, { bg: string; label: string }> = {
  chat: { bg: 'bg-blue-50 text-blue-600', label: 'Chat' },
  glossary: { bg: 'bg-purple-50 text-purple-600', label: 'Glossary' },
  kb_gap: { bg: 'bg-orange-50 text-orange-600', label: 'KB Gap' },
  data: { bg: 'bg-green-50 text-green-600', label: 'Data' },
  pipeline: { bg: 'bg-cyan-50 text-cyan-600', label: 'Pipeline' },
  other: { bg: 'bg-gray-50 text-gray-600', label: 'Other' },
}

function relativeTime(dateStr: string): string {
  const now = Date.now()
  const then = new Date(dateStr).getTime()
  const diffMin = Math.floor((now - then) / 60000)
  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  return `${diffDay}d ago`
}

export default function FeedbackBoard() {
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [selected, setSelected] = useState<Ticket | null>(null)
  const [loading, setLoading] = useState(true)
  const [users, setUsers] = useState<{ id: number; email: string; name: string; role: string }[]>([])

  useEffect(() => {
    loadTickets()
    fetchJSON<{ id: number; email: string; name: string; role: string }[]>('/users/users')
      .then(setUsers).catch(() => {})
  }, [])

  async function loadTickets() {
    setLoading(true)
    try {
      const res = await fetchJSON<Ticket[]>('/feedback')
      setTickets(res)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  async function moveTicket(id: number, newStatus: string) {
    await fetchJSON(`/feedback/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ status: newStatus }),
    })
    setTickets(prev => prev.map(t => t.id === id ? { ...t, status: newStatus } : t))
    if (selected?.id === id) setSelected({ ...selected, status: newStatus })
  }

  async function assignTicket(id: number, email: string) {
    await fetchJSON(`/feedback/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ assigned_to: email }),
    })
    setTickets(prev => prev.map(t => t.id === id ? { ...t, assigned_to: email } : t))
  }

  if (loading) {
    return <div className="flex items-center justify-center py-12"><Loader2 className="animate-spin text-gray-400" size={24} /></div>
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-base font-medium text-gray-900">Feedback Board</h3>
        <span className="text-xs text-gray-400">{tickets.length} tickets</span>
      </div>

      <div className="flex-1 flex gap-3 overflow-x-auto">
        {STATUS_COLS.map(col => {
          const colTickets = tickets.filter(t => t.status === col.key)
          return (
            <div key={col.key} className={`flex-1 min-w-[220px] rounded-lg ${col.bg} border ${col.border} p-2 flex flex-col`}>
              <div className="flex items-center justify-between mb-2 px-1">
                <span className="text-xs font-semibold text-gray-600">{col.label}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${col.badge}`}>{colTickets.length}</span>
              </div>
              <div className="flex-1 space-y-2 overflow-auto">
                {colTickets.map(ticket => (
                  <div key={ticket.id}
                    onClick={() => setSelected(ticket)}
                    className="bg-white rounded-lg border border-gray-200 p-2.5 cursor-pointer hover:shadow-sm transition-shadow">
                    <div className="flex items-start justify-between gap-1">
                      <span className="text-xs font-medium text-gray-800 line-clamp-2">{ticket.title}</span>
                      <span className={`text-[9px] px-1 py-0.5 rounded font-medium shrink-0 ${PRIORITY_COLORS[ticket.priority] || ''}`}>
                        {ticket.priority}
                      </span>
                    </div>
                    <div className="flex items-center gap-1 mt-1">
                      <span className={`text-[9px] px-1.5 py-0.5 rounded font-medium ${CATEGORY_STYLES[ticket.category]?.bg || 'bg-gray-50 text-gray-500'}`}>
                        {CATEGORY_STYLES[ticket.category]?.label || ticket.category}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 mt-1.5 text-[10px] text-gray-400">
                      <span className="flex items-center gap-0.5"><User size={9} /> {ticket.created_by?.split('@')[0]}</span>
                      <span className="flex items-center gap-0.5"><Clock size={9} /> {relativeTime(ticket.created_at)}</span>
                    </div>
                    {ticket.chat_session_id && (
                      <span className="text-[9px] text-blue-400 flex items-center gap-0.5 mt-1">
                        <MessageSquare size={9} /> Chat linked
                      </span>
                    )}
                  </div>
                ))}
                {colTickets.length === 0 && (
                  <div className="text-center py-4 text-[10px] text-gray-400">No tickets</div>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* Detail panel */}
      {selected && (
        <div className="mt-3 border-t border-gray-200 pt-3">
          <div className="flex items-start justify-between">
            <div>
              <h4 className="font-medium text-gray-900">{selected.title}</h4>
              <p className="text-xs text-gray-500 mt-0.5">{selected.description || 'No description'}</p>
            </div>
            <button onClick={() => setSelected(null)} className="text-xs text-gray-400 hover:text-gray-600">Close</button>
          </div>
          <div className="flex flex-wrap items-center gap-2 mt-2 text-[10px]">
            <span className="text-gray-500">By: {selected.created_by}</span>
            <span className="text-gray-500 flex items-center gap-1">
              Assign:
              <select
                value={selected.assigned_to || ''}
                onChange={e => {
                  const email = e.target.value
                  assignTicket(selected.id, email)
                  setSelected({ ...selected, assigned_to: email })
                }}
                className="text-[10px] border border-gray-200 rounded px-1 py-0.5 bg-white"
              >
                <option value="">Unassigned</option>
                {users.map(u => (
                  <option key={u.id} value={u.email}>{u.name} ({u.role})</option>
                ))}
              </select>
            </span>
            <span className={`px-1.5 py-0.5 rounded font-medium ${CATEGORY_STYLES[selected.category]?.bg || 'bg-gray-50 text-gray-500'}`}>
              {CATEGORY_STYLES[selected.category]?.label || selected.category}
            </span>
            {selected.chat_session_id && (
              <a href={`/?session=${selected.chat_session_id}`}
                className="text-blue-500 hover:underline flex items-center gap-0.5">
                <MessageSquare size={9} /> View chat
              </a>
            )}
          </div>
          {/* Move actions */}
          <div className="flex gap-1 mt-2">
            {STATUS_COLS.filter(c => c.key !== selected.status).map(col => (
              <button key={col.key}
                onClick={() => moveTicket(selected.id, col.key)}
                className="text-[10px] px-2 py-1 rounded border border-gray-200 hover:bg-gray-50 flex items-center gap-0.5">
                <ArrowRight size={9} /> {col.label}
              </button>
            ))}
          </div>
          {selected.resolution && (
            <div className="mt-2 text-xs text-gray-600 bg-green-50 rounded p-2">
              <span className="font-medium">Resolution:</span> {selected.resolution}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
