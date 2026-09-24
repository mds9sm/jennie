import { useState, useEffect, useCallback } from 'react'
import {
  Download, Printer, Loader2, RefreshCw,
  CheckCircle, Clock, Plus, AlertCircle, MessageSquare, Users,
} from 'lucide-react'
import { fetchJSON } from '../../api/client'

interface Task {
  id: number
  title: string
  status: string
  priority: string
  task_type: string
  assigned_to: string | null
  due_date: string | null
  created_at: string
  updated_at: string
}

interface Comment {
  id: number
  ticket_id: number
  task_title: string
  task_status: string
  task_priority: string
  author: string
  comment: string
  created_at: string | null
}

interface Digest {
  period_days: number
  period_start: string
  period_end: string
  generated_at: string
  summary: {
    completed_count: number
    in_progress_count: number
    newly_opened_count: number
    recently_updated_count: number
    overdue_count: number
    comments_count: number
    by_status: Record<string, number>
    by_priority: Record<string, number>
    by_type: Record<string, number>
    top_assignees: { assignee: string; count: number }[]
  }
  completed: Task[]
  in_progress: Task[]
  newly_opened: Task[]
  recently_updated: Task[]
  overdue: Task[]
  comments: Comment[]
}

const PRIORITY_BADGE: Record<string, string> = {
  critical: 'bg-red-100 text-red-700',
  high: 'bg-orange-100 text-orange-700',
  medium: 'bg-yellow-100 text-yellow-700',
  low: 'bg-blue-100 text-blue-700',
}

const STATUS_BADGE: Record<string, string> = {
  open: 'bg-red-100 text-red-700',
  in_progress: 'bg-yellow-100 text-yellow-700',
  resolved: 'bg-green-100 text-green-700',
  closed: 'bg-gray-100 text-gray-500',
}

function TaskList({ tasks, emptyMsg }: { tasks: Task[]; emptyMsg: string }) {
  if (!tasks.length) {
    return <div className="text-sm text-gray-400 italic px-3 py-3">{emptyMsg}</div>
  }
  return (
    <div className="divide-y divide-gray-100">
      {tasks.map((t) => (
        <div key={t.id} className="px-3 py-2 flex items-center gap-3 text-sm">
          <span className="font-mono text-xs text-gray-400 w-12 shrink-0">#{t.id}</span>
          <span className="flex-1 text-gray-900 truncate" title={t.title}>{t.title}</span>
          <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide shrink-0 ${PRIORITY_BADGE[t.priority] || 'bg-gray-100 text-gray-600'}`}>{t.priority}</span>
          <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide shrink-0 ${STATUS_BADGE[t.status] || 'bg-gray-100 text-gray-600'}`}>{t.status.replace('_', ' ')}</span>
          {t.due_date && (
            <span className="text-xs text-gray-500 shrink-0">due {t.due_date}</span>
          )}
          <span className="text-xs text-gray-500 w-36 truncate text-right shrink-0">{t.assigned_to || 'Unassigned'}</span>
        </div>
      ))}
    </div>
  )
}

function Section({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <div className="mb-5 border border-gray-200 rounded-md overflow-hidden bg-white">
      <div className="bg-gray-50 px-3 py-2 border-b border-gray-200 text-sm font-semibold text-gray-900">
        {title} <span className="text-gray-500 font-normal">({count})</span>
      </div>
      {children}
    </div>
  )
}

function StatCard({ icon, label, value, color }: { icon: React.ReactNode; label: string; value: number; color: string }) {
  return (
    <div className="bg-white rounded-md border border-gray-200 p-4 flex flex-col items-center">
      <div className={`flex items-center gap-2 ${color}`}>
        {icon}
        <span className="text-3xl font-bold leading-none">{value}</span>
      </div>
      <span className="text-xs text-gray-500 uppercase tracking-wide mt-2">{label}</span>
    </div>
  )
}

export default function TaskDigestPage() {
  const [days, setDays] = useState(7)
  const [digest, setDigest] = useState<Digest | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const d = await fetchJSON<Digest>(`/task-digest/weekly?days=${days}`)
      setDigest(d)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load digest')
    } finally {
      setLoading(false)
    }
  }, [days])

  useEffect(() => { load() }, [load])

  async function downloadHTML() {
    const env = (window as unknown as Record<string, Record<string, string>>).__ENV__
    const API_BASE = env?.VITE_API_BASE || import.meta.env.VITE_API_BASE || '/api'
    const token = localStorage.getItem('genie_auth_token') || ''
    try {
      const res = await fetch(`${API_BASE}/task-digest/weekly.html?days=${days}`, {
        headers: token ? { 'X-Auth-Token': token } : {},
      })
      if (!res.ok) {
        setError('Download failed')
        return
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const today = new Date().toISOString().slice(0, 10)
      a.download = `task-digest-${today}.html`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Download failed')
    }
  }

  if (loading && !digest) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        <Loader2 className="animate-spin mr-2" size={20} /> Loading digest...
      </div>
    )
  }

  if (error && !digest) {
    return <div className="p-8 text-red-600">Error: {error}</div>
  }

  if (!digest) return null

  const periodStart = digest.period_start.slice(0, 10)
  const periodEnd = digest.period_end.slice(0, 10)
  const s = digest.summary

  return (
    <div className="h-full overflow-auto bg-gray-50">
      <div className="max-w-5xl mx-auto p-6">
        <div className="flex items-start justify-between mb-6 flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Weekly Task Digest</h1>
            <p className="text-sm text-gray-500 mt-1">{periodStart} → {periodEnd} · Jennie</p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <select
              value={days}
              onChange={(e) => setDays(parseInt(e.target.value, 10))}
              className="text-sm border border-gray-300 rounded-md px-2 py-1.5 bg-white"
            >
              <option value={7}>Last 7 days</option>
              <option value={14}>Last 14 days</option>
              <option value={30}>Last 30 days</option>
            </select>
            <button
              onClick={load}
              className="px-3 py-1.5 text-sm border border-gray-300 rounded-md bg-white hover:bg-gray-50 flex items-center gap-1.5"
              title="Refresh"
            >
              <RefreshCw size={14} /> Refresh
            </button>
            <button
              onClick={() => window.print()}
              className="px-3 py-1.5 text-sm border border-gray-300 rounded-md bg-white hover:bg-gray-50 flex items-center gap-1.5"
            >
              <Printer size={14} /> Print
            </button>
            <button
              onClick={downloadHTML}
              className="px-3 py-1.5 text-sm bg-genie-600 text-white rounded-md hover:bg-genie-700 flex items-center gap-1.5"
            >
              <Download size={14} /> Download HTML
            </button>
          </div>
        </div>

        {error && (
          <div className="mb-4 px-3 py-2 bg-red-50 border border-red-200 text-red-700 text-sm rounded-md">
            {error}
          </div>
        )}

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <StatCard icon={<CheckCircle size={18} />} label="Completed" value={s.completed_count} color="text-green-600" />
          <StatCard icon={<Clock size={18} />} label="In Progress" value={s.in_progress_count} color="text-yellow-600" />
          <StatCard icon={<Plus size={18} />} label="Newly Opened" value={s.newly_opened_count} color="text-blue-600" />
          <StatCard icon={<AlertCircle size={18} />} label="Overdue" value={s.overdue_count} color="text-red-600" />
        </div>

        <Section title="Completed This Week" count={digest.completed.length}>
          <TaskList tasks={digest.completed} emptyMsg="No tasks completed in this window." />
        </Section>
        <Section title="In Progress" count={digest.in_progress.length}>
          <TaskList tasks={digest.in_progress} emptyMsg="No tasks in progress." />
        </Section>
        <Section title="Newly Opened" count={digest.newly_opened.length}>
          <TaskList tasks={digest.newly_opened} emptyMsg="No new tasks this week." />
        </Section>
        <Section title="Recently Updated" count={digest.recently_updated.length}>
          <TaskList tasks={digest.recently_updated} emptyMsg="No updates this week." />
        </Section>
        <Section title="Overdue" count={digest.overdue.length}>
          <TaskList tasks={digest.overdue} emptyMsg="No overdue tasks." />
        </Section>

        {digest.comments.length > 0 && (
          <div className="mb-5 border border-gray-200 rounded-md overflow-hidden bg-white">
            <div className="bg-gray-50 px-3 py-2 border-b border-gray-200 text-sm font-semibold text-gray-900 flex items-center gap-2">
              <MessageSquare size={14} /> Discussion Activity <span className="text-gray-500 font-normal">({digest.comments.length})</span>
            </div>
            <div className="divide-y divide-gray-100">
              {digest.comments.slice(0, 15).map((c) => (
                <div key={c.id} className="px-3 py-2 text-sm">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="font-mono text-xs text-gray-400">#{c.ticket_id}</span>
                    <span className="text-gray-900 truncate">{c.task_title}</span>
                  </div>
                  <div className="text-xs text-gray-600">
                    <span className="text-gray-500">{c.author}: </span>
                    {c.comment.length > 240 ? c.comment.slice(0, 240) + '...' : c.comment}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {s.top_assignees.length > 0 && (
          <div className="mb-5 border border-gray-200 rounded-md overflow-hidden bg-white">
            <div className="bg-gray-50 px-3 py-2 border-b border-gray-200 text-sm font-semibold text-gray-900 flex items-center gap-2">
              <Users size={14} /> Active Tasks by Owner
            </div>
            <div className="divide-y divide-gray-100">
              {s.top_assignees.map((a) => (
                <div key={a.assignee} className="px-3 py-1.5 text-sm flex justify-between">
                  <span className="text-gray-900">{a.assignee}</span>
                  <span className="text-gray-500">{a.count} active</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <p className="text-center text-xs text-gray-400 mt-6 mb-2">
          Generated {digest.generated_at.slice(0, 19).replace('T', ' ')} UTC
        </p>
      </div>
    </div>
  )
}
