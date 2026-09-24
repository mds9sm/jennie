import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { fetchJSON } from '../../api/client'
import {
  MessageSquare, User, Clock, ArrowRight, Plus, X, Loader2,
  AlertCircle, Bug, Zap, Brain, BookOpen, HelpCircle, FileText,
  Tag, Calendar, ChevronDown, ChevronUp, Trash2, ExternalLink,
  Search, Filter, Send,
} from 'lucide-react'
import { useUser } from '../../context/UserContext'
import CreatableCombobox from '../common/CreatableCombobox'

interface Task {
  id: number
  title: string
  description: string
  status: string
  priority: string
  category: string
  task_type: string
  created_by: string
  assigned_to: string | null
  chat_session_id: string | null
  chat_messages: unknown[] | null
  resolution: string | null
  due_date: string | null
  tags: string[]
  created_at: string
  updated_at: string
}

const STATUS_COLS = [
  { key: 'open', label: 'Open', bg: 'bg-red-50', border: 'border-red-200', badge: 'bg-red-100 text-red-700', headerBg: 'bg-red-100' },
  { key: 'in_progress', label: 'In Progress', bg: 'bg-yellow-50', border: 'border-yellow-200', badge: 'bg-yellow-100 text-yellow-700', headerBg: 'bg-yellow-100' },
  { key: 'resolved', label: 'Resolved', bg: 'bg-green-50', border: 'border-green-200', badge: 'bg-green-100 text-green-700', headerBg: 'bg-green-100' },
  { key: 'closed', label: 'Closed', bg: 'bg-gray-50', border: 'border-gray-200', badge: 'bg-gray-100 text-gray-500', headerBg: 'bg-gray-100' },
]

const PRIORITY_DOT: Record<string, string> = {
  critical: 'bg-red-500',
  high: 'bg-orange-400',
  medium: 'bg-yellow-400',
  low: 'bg-blue-400',
}

const PRIORITY_LABEL: Record<string, string> = {
  critical: 'Critical',
  high: 'High',
  medium: 'Medium',
  low: 'Low',
}

const TASK_TYPES = [
  { key: 'investigation', label: 'Investigation', icon: Bug, color: 'bg-indigo-100 text-indigo-700' },
  { key: 'data_issue', label: 'Data Issue', icon: AlertCircle, color: 'bg-red-100 text-red-700' },
  { key: 'dag_failure', label: 'DAG Failure', icon: Zap, color: 'bg-orange-100 text-orange-700' },
  { key: 'ai_quality', label: 'AI Quality', icon: Brain, color: 'bg-purple-100 text-purple-700' },
  { key: 'kb_gap', label: 'KB Gap', icon: HelpCircle, color: 'bg-amber-100 text-amber-700' },
  { key: 'glossary', label: 'Glossary', icon: BookOpen, color: 'bg-teal-100 text-teal-700' },
  { key: 'request', label: 'Request', icon: FileText, color: 'bg-blue-100 text-blue-700' },
  { key: 'general', label: 'General', icon: Tag, color: 'bg-gray-100 text-gray-600' },
]

const TASK_TYPE_MAP: Record<string, typeof TASK_TYPES[0]> = Object.fromEntries(
  TASK_TYPES.map(t => [t.key, t])
)

function relativeTime(dateStr: string): string {
  const now = Date.now()
  const then = new Date(dateStr).getTime()
  const diffMin = Math.floor((now - then) / 60000)
  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 7) return `${diffDay}d ago`
  return new Date(dateStr).toLocaleDateString()
}

// Parse a date-only string ("YYYY-MM-DD") as LOCAL midnight. Passing it to
// `new Date()` parses it as UTC midnight, which renders as the previous day in
// any timezone behind UTC (off-by-one due date bug).
function parseLocalDate(dateStr: string): Date {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(dateStr)
  if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  return new Date(dateStr)
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return ''
  const d = parseLocalDate(dateStr)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function isOverdue(dateStr: string | null): boolean {
  if (!dateStr) return false
  return parseLocalDate(dateStr) < new Date(new Date().toDateString())
}

interface FilterState {
  search: string
  assignees: string[]
  statuses: string[]
  priorities: string[]
  types: string[]
  tags: string[]
  mineOnly: boolean
}

const EMPTY_FILTERS: FilterState = {
  search: '',
  assignees: [],
  statuses: [],
  priorities: [],
  types: [],
  tags: [],
  mineOnly: false,
}

export default function TaskBoard() {
  const [tasks, setTasks] = useState<Task[]>([])
  const [selected, setSelected] = useState<Task | null>(null)
  const [loading, setLoading] = useState(true)
  const [users, setUsers] = useState<{ id: number; email: string; name: string; role: string }[]>([])
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS)
  const [allTags, setAllTags] = useState<string[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const { user } = useUser()
  const isAdmin = user?.role === 'admin'

  useEffect(() => {
    loadTasks()
    fetchJSON<{ id: number; email: string; name: string; role: string }[]>('/users/users')
      .then(setUsers).catch(() => {})
    fetchJSON<{ tags: string[] }>('/feedback/tags/distinct')
      .then(r => setAllTags(r.tags || [])).catch(() => {})
  }, [])

  // Scroll selected card into view in its column so it stays visible when
  // the detail panel opens. block:nearest avoids jumpy scrolling.
  useEffect(() => {
    if (!selected) return
    const el = document.querySelector<HTMLElement>(`[data-task-id="${selected.id}"]`)
    el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [selected?.id])

  async function loadTasks() {
    setLoading(true)
    try {
      const res = await fetchJSON<Task[]>('/feedback')
      setTasks(res)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  function refreshTagOptions() {
    fetchJSON<{ tags: string[] }>('/feedback/tags/distinct')
      .then(r => setAllTags(r.tags || [])).catch(() => {})
  }

  const filteredTasks = useMemo(() => {
    const q = filters.search.trim().toLowerCase()
    const myEmail = user?.email
    return tasks.filter(t => {
      if (filters.statuses.length && !filters.statuses.includes(t.status)) return false
      if (filters.priorities.length && !filters.priorities.includes(t.priority)) return false
      if (filters.types.length && !filters.types.includes(t.task_type)) return false
      if (filters.assignees.length && (!t.assigned_to || !filters.assignees.includes(t.assigned_to))) return false
      if (filters.mineOnly && (!myEmail || t.assigned_to !== myEmail)) return false
      if (filters.tags.length && !filters.tags.some(tag => (t.tags || []).includes(tag))) return false
      if (q) {
        const hay = `${t.title} ${t.description || ''}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
  }, [tasks, filters, user])

  const visibleStatuses = filters.statuses.length ? filters.statuses : STATUS_COLS.map(c => c.key)

  const activeFilterCount =
    (filters.search ? 1 : 0) +
    filters.assignees.length +
    filters.statuses.length +
    filters.priorities.length +
    filters.types.length +
    filters.tags.length +
    (filters.mineOnly ? 1 : 0)

  function toggleInList(list: string[], value: string): string[] {
    return list.includes(value) ? list.filter(x => x !== value) : [...list, value]
  }

  async function moveTask(id: number, newStatus: string) {
    await fetchJSON(`/feedback/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ status: newStatus }),
    })
    setTasks(prev => prev.map(t => t.id === id ? { ...t, status: newStatus, updated_at: new Date().toISOString() } : t))
    if (selected?.id === id) setSelected({ ...selected, status: newStatus, updated_at: new Date().toISOString() })
  }

  async function assignTask(id: number, email: string) {
    await fetchJSON(`/feedback/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ assigned_to: email }),
    })
    setTasks(prev => prev.map(t => t.id === id ? { ...t, assigned_to: email } : t))
    if (selected?.id === id) setSelected({ ...selected, assigned_to: email })
  }

  async function deleteTask(id: number) {
    if (!confirm('Delete this task? This cannot be undone.')) return
    try {
      await fetchJSON(`/feedback/${id}`, { method: 'DELETE' })
      setTasks(prev => prev.filter(t => t.id !== id))
      if (selected?.id === id) setSelected(null)
    } catch (err) {
      alert('Failed to delete: ' + (err instanceof Error ? err.message : 'Unknown'))
    }
  }

  async function handleCreate(data: CreateTaskData) {
    try {
      const res = await fetchJSON<{ id: number; assigned_to: string }>('/feedback', {
        method: 'POST',
        body: JSON.stringify(data),
      })
      setShowCreate(false)
      loadTasks()
      return res
    } catch (err) {
      alert('Failed to create task: ' + (err instanceof Error ? err.message : 'Unknown'))
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="animate-spin text-gray-400" size={24} />
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Tasks</h2>
          <p className="text-xs text-gray-500 mt-0.5">{tasks.length} total tasks</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 bg-genie-600 text-white text-sm font-medium rounded-lg hover:bg-genie-700 transition-colors"
        >
          <Plus size={16} />
          Create Task
        </button>
      </div>

      {/* Filter bar */}
      <div className="space-y-2 mb-3 pb-3 border-b border-gray-200">
        {/* Row 1: search + multi-selects + quick toggles */}
        <div className="flex items-center gap-2 flex-wrap">
          <div className="relative flex-1 min-w-[200px] max-w-md">
            <Search size={13} className="absolute left-2.5 top-2 text-gray-400" />
            <input
              value={filters.search}
              onChange={e => setFilters(f => ({ ...f, search: e.target.value }))}
              placeholder="Search title or description…"
              className="w-full pl-8 pr-3 py-1.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-genie-400"
            />
          </div>

          <MultiSelectFilter
            label="Assignee"
            options={users.map(u => ({ value: u.email, label: u.name || u.email.split('@')[0], hint: u.role }))}
            selected={filters.assignees}
            onChange={vals => setFilters(f => ({ ...f, assignees: vals }))}
          />

          <MultiSelectFilter
            label="Tags"
            options={allTags.map(t => ({ value: t, label: t }))}
            selected={filters.tags}
            onChange={vals => setFilters(f => ({ ...f, tags: vals }))}
            emptyLabel="No tags yet"
          />

          <label className="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer ml-1">
            <input
              type="checkbox"
              checked={filters.mineOnly}
              onChange={e => setFilters(f => ({ ...f, mineOnly: e.target.checked }))}
              className="rounded border-gray-300"
            />
            Mine only
          </label>

          {activeFilterCount > 0 && (
            <button
              onClick={() => setFilters(EMPTY_FILTERS)}
              className="text-xs text-gray-500 hover:text-gray-800 underline ml-auto"
            >
              Clear all ({activeFilterCount})
            </button>
          )}
        </div>

        {/* Row 2: chip groups (status, priority, type) */}
        <div className="flex items-center gap-3 flex-wrap text-xs">
          <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Status</span>
          {STATUS_COLS.map(col => {
            const active = filters.statuses.includes(col.key)
            return (
              <button
                key={col.key}
                onClick={() => setFilters(f => ({ ...f, statuses: toggleInList(f.statuses, col.key) }))}
                className={`px-2 py-0.5 rounded-full text-[11px] transition-colors border ${
                  active ? `${col.headerBg} ${col.border} text-gray-800 font-medium` : 'bg-white border-gray-200 text-gray-500 hover:bg-gray-50'
                }`}
              >
                {col.label}
              </button>
            )
          })}

          <span className="text-gray-200">|</span>

          <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Priority</span>
          {(['critical', 'high', 'medium', 'low'] as const).map(p => {
            const active = filters.priorities.includes(p)
            return (
              <button
                key={p}
                onClick={() => setFilters(f => ({ ...f, priorities: toggleInList(f.priorities, p) }))}
                className={`px-2 py-0.5 rounded-full text-[11px] transition-colors border flex items-center gap-1 ${
                  active ? 'bg-gray-900 text-white border-gray-900' : 'bg-white border-gray-200 text-gray-500 hover:bg-gray-50'
                }`}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${PRIORITY_DOT[p]}`} />
                {PRIORITY_LABEL[p]}
              </button>
            )
          })}

          <span className="text-gray-200">|</span>

          <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Type</span>
          {TASK_TYPES.map(tt => {
            const count = tasks.filter(t => t.task_type === tt.key).length
            if (count === 0 && !filters.types.includes(tt.key)) return null
            const active = filters.types.includes(tt.key)
            return (
              <button
                key={tt.key}
                onClick={() => setFilters(f => ({ ...f, types: toggleInList(f.types, tt.key) }))}
                className={`px-2 py-0.5 rounded-full text-[11px] font-medium transition-colors flex items-center gap-1 border ${
                  active ? 'bg-gray-900 text-white border-gray-900' : `${tt.color} border-transparent hover:opacity-80`
                }`}
              >
                <tt.icon size={10} />
                {tt.label}
                <span className="opacity-70">{count}</span>
              </button>
            )
          })}
        </div>
      </div>

      {/* Kanban columns */}
      <div className="flex-1 flex gap-3 overflow-x-auto min-h-0">
        {STATUS_COLS.filter(c => visibleStatuses.includes(c.key)).map(col => {
          const colTasks = filteredTasks.filter(t => t.status === col.key)
          return (
            <div key={col.key} className={`flex-1 min-w-[240px] rounded-lg ${col.bg} border ${col.border} flex flex-col`}>
              <div className={`flex items-center justify-between px-3 py-2 ${col.headerBg} rounded-t-lg`}>
                <span className="text-xs font-semibold text-gray-700">{col.label}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-bold ${col.badge}`}>{colTasks.length}</span>
              </div>
              <div className="flex-1 p-2 space-y-2 overflow-auto">
                {colTasks.map(task => {
                  const tt = TASK_TYPE_MAP[task.task_type] || TASK_TYPE_MAP.general
                  const TypeIcon = tt.icon
                  return (
                    <div
                      key={task.id}
                      data-task-id={task.id}
                      onClick={() => setSelected(task)}
                      className={`bg-white rounded-lg border border-gray-200 p-2.5 cursor-pointer hover:shadow-md transition-all ${
                        selected?.id === task.id ? 'ring-2 ring-genie-400' : ''
                      }`}
                    >
                      {/* Title + priority dot */}
                      <div className="flex items-start gap-1.5">
                        <span className={`w-2 h-2 rounded-full shrink-0 mt-1 ${PRIORITY_DOT[task.priority] || 'bg-gray-300'}`} />
                        <span className="text-xs font-medium text-gray-800 line-clamp-2 flex-1">{task.title}</span>
                      </div>

                      {/* Type badge */}
                      <div className="flex items-center gap-1 mt-1.5">
                        <span className={`text-[9px] px-1.5 py-0.5 rounded font-medium inline-flex items-center gap-0.5 ${tt.color}`}>
                          <TypeIcon size={9} />
                          {tt.label}
                        </span>
                        {task.priority === 'critical' && (
                          <span className="text-[9px] px-1 py-0.5 rounded font-bold bg-red-500 text-white">CRITICAL</span>
                        )}
                      </div>

                      {/* Tags */}
                      {task.tags && task.tags.length > 0 && (
                        <div className="flex flex-wrap gap-0.5 mt-1">
                          {task.tags.slice(0, 3).map(tag => (
                            <span key={tag} className="text-[8px] px-1 py-0.5 rounded bg-gray-100 text-gray-500">{tag}</span>
                          ))}
                          {task.tags.length > 3 && (
                            <span className="text-[8px] text-gray-400">+{task.tags.length - 3}</span>
                          )}
                        </div>
                      )}

                      {/* Meta row */}
                      <div className="flex items-center gap-2 mt-1.5 text-[10px] text-gray-400">
                        {task.assigned_to && (
                          <span className="flex items-center gap-0.5">
                            <User size={9} />
                            {task.assigned_to.split('@')[0]}
                          </span>
                        )}
                        {task.due_date && (
                          <span className={`flex items-center gap-0.5 ${isOverdue(task.due_date) ? 'text-red-500 font-medium' : ''}`}>
                            <Calendar size={9} />
                            {formatDate(task.due_date)}
                          </span>
                        )}
                        <span className="flex items-center gap-0.5 ml-auto">
                          <Clock size={9} />
                          {relativeTime(task.created_at)}
                        </span>
                      </div>

                      {/* Chat link indicator */}
                      {task.chat_session_id && (
                        <span className="text-[9px] text-blue-400 flex items-center gap-0.5 mt-1">
                          <MessageSquare size={9} /> Chat linked
                        </span>
                      )}
                    </div>
                  )
                })}
                {colTasks.length === 0 && (
                  <div className="text-center py-6 text-[10px] text-gray-400">No tasks</div>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* Detail panel (slide up) */}
      {selected && (
        <TaskDetailPanel
          task={selected}
          users={users}
          allTags={allTags}
          onTagsChanged={refreshTagOptions}
          isAdmin={isAdmin}
          onClose={() => setSelected(null)}
          onMove={moveTask}
          onAssign={assignTask}
          onDelete={deleteTask}
          onUpdate={(updated) => {
            setTasks(prev => prev.map(t => t.id === updated.id ? updated : t))
            setSelected(updated)
          }}
        />
      )}

      {/* Create modal */}
      {showCreate && (
        <CreateTaskModal
          users={users}
          onClose={() => setShowCreate(false)}
          onCreate={handleCreate}
        />
      )}
    </div>
  )
}

/* ---- Detail Panel ---- */
interface DetailPanelProps {
  task: Task
  users: { id: number; email: string; name: string; role: string }[]
  allTags: string[]
  onTagsChanged: () => void
  isAdmin: boolean
  onClose: () => void
  onMove: (id: number, status: string) => Promise<void>
  onAssign: (id: number, email: string) => Promise<void>
  onDelete: (id: number) => Promise<void>
  onUpdate: (task: Task) => void
}

interface Comment {
  id: number
  ticket_id: number
  author: string
  author_name: string | null
  comment: string
  created_at: string
}

function TaskDetailPanel({ task, users, allTags, onTagsChanged, isAdmin, onClose, onMove, onAssign, onDelete, onUpdate }: DetailPanelProps) {
  const [expanded, setExpanded] = useState(true)
  const [editing, setEditing] = useState(false)
  const [editTitle, setEditTitle] = useState(task.title)
  const [editDesc, setEditDesc] = useState(task.description || '')
  const [saving, setSaving] = useState(false)
  const [showAddTag, setShowAddTag] = useState(false)
  const [comments, setComments] = useState<Comment[]>([])
  const [commentsLoading, setCommentsLoading] = useState(false)
  const [newComment, setNewComment] = useState('')
  const [postingComment, setPostingComment] = useState(false)
  const commentsEndRef = useRef<HTMLDivElement>(null)
  const tt = TASK_TYPE_MAP[task.task_type] || TASK_TYPE_MAP.general
  const TypeIcon = tt.icon

  // Reset editor state and (re-)load comments whenever a different task is selected.
  useEffect(() => {
    setEditing(false)
    setEditTitle(task.title)
    setEditDesc(task.description || '')
    setShowAddTag(false)
    setNewComment('')
    setCommentsLoading(true)
    fetchJSON<Comment[]>(`/feedback/${task.id}/comments`)
      .then(setComments)
      .catch(() => setComments([]))
      .finally(() => setCommentsLoading(false))
  }, [task.id])

  // Keep latest comment visible whenever the comments list grows.
  useEffect(() => {
    if (commentsEndRef.current && comments.length > 0) {
      commentsEndRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [comments.length])

  async function handleSave() {
    setSaving(true)
    try {
      await fetchJSON(`/feedback/${task.id}`, {
        method: 'PUT',
        body: JSON.stringify({ title: editTitle, description: editDesc }),
      })
      onUpdate({ ...task, title: editTitle, description: editDesc })
      setEditing(false)
    } catch { /* ignore */ }
    finally { setSaving(false) }
  }

  async function handlePriorityChange(newPriority: string) {
    if (newPriority === task.priority) return
    const previous = task.priority
    onUpdate({ ...task, priority: newPriority })
    try {
      await fetchJSON(`/feedback/${task.id}`, {
        method: 'PUT',
        body: JSON.stringify({ priority: newPriority }),
      })
    } catch {
      onUpdate({ ...task, priority: previous })
    }
  }

  async function handleTypeChange(newType: string) {
    if (newType === task.task_type) return
    const previous = task.task_type
    onUpdate({ ...task, task_type: newType })
    try {
      await fetchJSON(`/feedback/${task.id}`, {
        method: 'PUT',
        body: JSON.stringify({ task_type: newType }),
      })
    } catch {
      onUpdate({ ...task, task_type: previous })
    }
  }

  async function handleDueDateChange(newDate: string) {
    const previous = task.due_date
    const value = newDate || null
    if (value === previous) return
    onUpdate({ ...task, due_date: value })
    try {
      await fetchJSON(`/feedback/${task.id}`, {
        method: 'PUT',
        body: JSON.stringify({ due_date: value }),
      })
    } catch {
      onUpdate({ ...task, due_date: previous })
    }
  }

  async function handleTagsChange(newTags: string[]) {
    const previous = task.tags || []
    onUpdate({ ...task, tags: newTags })
    try {
      await fetchJSON(`/feedback/${task.id}`, {
        method: 'PUT',
        body: JSON.stringify({ tags: newTags }),
      })
      onTagsChanged()
    } catch {
      onUpdate({ ...task, tags: previous })
    }
  }

  async function handlePostComment() {
    const text = newComment.trim()
    if (!text || postingComment) return
    setPostingComment(true)
    try {
      const created = await fetchJSON<Comment>(`/feedback/${task.id}/comments`, {
        method: 'POST',
        body: JSON.stringify({ comment: text }),
      })
      setComments(prev => [...prev, created])
      setNewComment('')
    } catch { /* ignore */ }
    finally { setPostingComment(false) }
  }

  return (
    <div className="mt-3 border-t border-gray-200 pt-3 flex flex-col min-h-0 max-h-[55vh] shrink-0">
      <div className="flex items-start justify-between shrink-0">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${PRIORITY_DOT[task.priority] || 'bg-gray-300'}`} />
            {editing ? (
              <input value={editTitle} onChange={e => setEditTitle(e.target.value)}
                className="flex-1 text-sm font-semibold border border-gray-300 rounded px-2 py-1" />
            ) : (
              <h4 className="font-semibold text-gray-900 truncate">{task.title}</h4>
            )}
            <label className={`text-[10px] inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-medium ${tt.color}`} title="Change type">
              <TypeIcon size={10} />
              <select
                value={task.task_type}
                onChange={e => handleTypeChange(e.target.value)}
                className="text-[10px] bg-transparent border-0 focus:outline-none cursor-pointer font-medium"
              >
                {TASK_TYPES.map(t => (
                  <option key={t.key} value={t.key}>{t.label}</option>
                ))}
              </select>
            </label>
            <label className="text-[10px] flex items-center gap-1" title="Change priority">
              <span className={`w-2 h-2 rounded-full ${PRIORITY_DOT[task.priority] || 'bg-gray-300'}`} />
              <select
                value={task.priority}
                onChange={e => handlePriorityChange(e.target.value)}
                className="text-[10px] border border-gray-200 rounded px-1 py-0.5 bg-white focus:outline-none focus:ring-1 focus:ring-genie-400"
              >
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </label>
          </div>
        </div>
        <div className="flex items-center gap-1 ml-2 shrink-0">
          {editing ? (
            <>
              <button onClick={handleSave} disabled={saving}
                className="text-xs px-2 py-1 bg-genie-600 text-white rounded hover:bg-genie-700 disabled:opacity-50">
                {saving ? 'Saving...' : 'Save'}
              </button>
              <button onClick={() => { setEditing(false); setEditTitle(task.title); setEditDesc(task.description || '') }}
                className="text-xs text-gray-400 hover:text-gray-600 px-2 py-1">Cancel</button>
            </>
          ) : (
            <button onClick={() => setEditing(true)}
              className="text-xs text-gray-400 hover:text-genie-600 px-2 py-1">Edit</button>
          )}
          <button onClick={() => setExpanded(!expanded)} className="text-gray-400 hover:text-gray-600 p-1">
            {expanded ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
          </button>
          <button onClick={onClose} className="text-xs text-gray-400 hover:text-gray-600 px-2 py-1">Close</button>
        </div>
      </div>

      {expanded && (
        <div className="flex-1 min-h-0 overflow-y-auto pr-1 mt-1">
          {/* Description with highlighted @mentions */}
          {editing ? (
            <div className="mt-2">
              <MentionTextarea
                value={editDesc}
                onChange={setEditDesc}
                users={users}
                placeholder="Description... use @ to mention people"
                rows={4}
              />
            </div>
          ) : task.description ? (
            <div className="mt-2 text-xs text-gray-600 bg-white rounded-lg border border-gray-200 p-3 whitespace-pre-wrap max-h-32 overflow-auto">
              <HighlightMentions text={task.description} />
            </div>
          ) : null}

          {/* Metadata row */}
          <div className="flex flex-wrap items-center gap-3 mt-3 text-[11px]">
            <span className="text-gray-500">Created by: <strong>{task.created_by?.split('@')[0]}</strong></span>
            <span className="text-gray-500">{relativeTime(task.created_at)}</span>

            <span className="text-gray-500 flex items-center gap-1">
              Assign:
              <select
                value={task.assigned_to || ''}
                onChange={e => onAssign(task.id, e.target.value)}
                className="text-[11px] border border-gray-200 rounded px-1.5 py-0.5 bg-white"
              >
                <option value="">Unassigned</option>
                {users.map(u => (
                  <option key={u.id} value={u.email}>{u.name || u.email.split('@')[0]} ({u.role})</option>
                ))}
              </select>
            </span>

            <label className={`flex items-center gap-1 ${isOverdue(task.due_date) ? 'text-red-500 font-medium' : 'text-gray-500'}`} title="Set due date">
              <Calendar size={11} />
              Due:
              <input
                type="date"
                value={task.due_date ? task.due_date.slice(0, 10) : ''}
                onChange={e => handleDueDateChange(e.target.value)}
                className="text-[11px] border border-gray-200 rounded px-1 py-0.5 bg-white focus:outline-none focus:ring-1 focus:ring-genie-400"
              />
              {task.due_date && (
                <button
                  type="button"
                  onClick={() => handleDueDateChange('')}
                  className="text-gray-400 hover:text-red-500"
                  title="Clear due date"
                >
                  <X size={10} />
                </button>
              )}
              {isOverdue(task.due_date) && <span className="text-[10px]">(overdue)</span>}
            </label>

            {task.chat_session_id && (
              <a href={`/?shared=${task.chat_session_id}`}
                className="text-blue-500 hover:underline flex items-center gap-0.5">
                <ExternalLink size={11} /> View Chat
              </a>
            )}
          </div>

          {/* Tags (editable) */}
          <div className="flex flex-wrap items-center gap-1 mt-2">
            <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mr-1">Tags</span>
            {(task.tags || []).map(tag => (
              <span key={tag} className="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-700 border border-gray-200 inline-flex items-center gap-0.5">
                <Tag size={8} />
                {tag}
                <button
                  onClick={() => handleTagsChange((task.tags || []).filter(t => t !== tag))}
                  className="ml-0.5 text-gray-400 hover:text-red-500"
                  title={`Remove "${tag}"`}
                >
                  <X size={9} />
                </button>
              </span>
            ))}
            {showAddTag ? (
              <div className="w-48">
                <CreatableCombobox
                  value=""
                  options={allTags
                    .filter(t => !(task.tags || []).includes(t))
                    .map(t => ({ label: t, value: t }))}
                  placeholder="Type tag…"
                  allowCreate
                  onChange={val => {
                    const next = (val || '').trim()
                    if (next && !(task.tags || []).includes(next)) {
                      handleTagsChange([...(task.tags || []), next])
                    }
                    setShowAddTag(false)
                  }}
                />
              </div>
            ) : (
              <button
                onClick={() => setShowAddTag(true)}
                className="text-[10px] px-1.5 py-0.5 rounded-full border border-dashed border-gray-300 text-gray-500 hover:bg-gray-50 inline-flex items-center gap-0.5"
              >
                <Plus size={9} /> Add tag
              </button>
            )}
          </div>

          {/* Move actions */}
          <div className="flex items-center gap-1 mt-3">
            <span className="text-[10px] text-gray-500 mr-1">Move to:</span>
            {STATUS_COLS.filter(c => c.key !== task.status).map(col => (
              <button key={col.key}
                onClick={() => onMove(task.id, col.key)}
                className="text-[10px] px-2 py-1 rounded border border-gray-200 hover:bg-gray-50 flex items-center gap-0.5 transition-colors">
                <ArrowRight size={9} /> {col.label}
              </button>
            ))}
            {isAdmin && (
              <button
                onClick={() => onDelete(task.id)}
                className="text-[10px] px-2 py-1 rounded border border-red-200 text-red-500 hover:bg-red-50 flex items-center gap-0.5 ml-auto transition-colors"
              >
                <Trash2 size={9} /> Delete
              </button>
            )}
          </div>

          {/* Resolution */}
          {task.resolution && (
            <div className="mt-2 text-xs text-gray-600 bg-green-50 rounded p-2 border border-green-200">
              <span className="font-medium">Resolution:</span> {task.resolution}
            </div>
          )}

          {/* Comments */}
          <div className="mt-4 border-t border-gray-100 pt-3">
            <div className="flex items-center gap-1.5 mb-2">
              <MessageSquare size={12} className="text-gray-400" />
              <span className="text-xs font-semibold text-gray-700">Comments</span>
              <span className="text-[10px] text-gray-400">({comments.length})</span>
            </div>

            {commentsLoading ? (
              <div className="text-[11px] text-gray-400 py-2 flex items-center gap-1">
                <Loader2 size={11} className="animate-spin" /> Loading…
              </div>
            ) : comments.length === 0 ? (
              <div className="text-[11px] text-gray-400 italic py-1">No comments yet.</div>
            ) : (
              <div className="space-y-2">
                {comments.map(c => {
                  const displayName = c.author_name || c.author?.split('@')[0] || 'unknown'
                  const initial = displayName.charAt(0).toUpperCase()
                  return (
                    <div key={c.id} className="flex gap-2">
                      <div className="w-6 h-6 rounded-full bg-genie-100 text-genie-700 text-[10px] font-bold flex items-center justify-center shrink-0">
                        {initial}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-baseline gap-2">
                          <span className="text-xs font-medium text-gray-800">{displayName}</span>
                          <span className="text-[10px] text-gray-400">{relativeTime(c.created_at)}</span>
                        </div>
                        <div className="text-xs text-gray-700 whitespace-pre-wrap break-words">
                          <HighlightMentions text={c.comment} />
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}

            {/* Anchor used to scroll the latest comment into view */}
            <div ref={commentsEndRef} />

            {/* Composer */}
            <div className="mt-3">
              <MentionTextarea
                value={newComment}
                onChange={setNewComment}
                users={users}
                placeholder="Add a comment… use @ to mention people"
                rows={2}
              />
              <div className="flex justify-end mt-1.5">
                <button
                  onClick={handlePostComment}
                  disabled={!newComment.trim() || postingComment}
                  className="flex items-center gap-1 px-3 py-1 bg-genie-600 text-white text-xs rounded hover:bg-genie-700 disabled:opacity-50 transition-colors"
                >
                  {postingComment ? <Loader2 size={11} className="animate-spin" /> : <Send size={11} />}
                  {postingComment ? 'Posting…' : 'Post'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/* ---- Create Modal ---- */
interface CreateTaskData {
  title: string
  description: string
  task_type: string
  priority: string
  assigned_to?: string
  due_date?: string
  tags: string[]
  chat_session_id?: string
}

interface CreateModalProps {
  users: { id: number; email: string; name: string; role: string }[]
  onClose: () => void
  onCreate: (data: CreateTaskData) => Promise<unknown>
}

function CreateTaskModal({ users, onClose, onCreate }: CreateModalProps) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [taskType, setTaskType] = useState('general')
  const [priority, setPriority] = useState('medium')
  const [assignedTo, setAssignedTo] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [tagsInput, setTagsInput] = useState('')
  const [chatSessionId, setChatSessionId] = useState('')
  const [creating, setCreating] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!title.trim()) return
    setCreating(true)
    const tags = tagsInput.split(',').map(t => t.trim()).filter(Boolean)
    await onCreate({
      title: title.trim(),
      description: description.trim(),
      task_type: taskType,
      priority,
      assigned_to: assignedTo || undefined,
      due_date: dueDate || undefined,
      tags,
      chat_session_id: chatSessionId || undefined,
    })
    setCreating(false)
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
          <h3 className="text-base font-semibold text-gray-900">Create Task</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={18} /></button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4 max-h-[70vh] overflow-auto">
          {/* Title */}
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Title *</label>
            <input
              value={title} onChange={e => setTitle(e.target.value)}
              placeholder="What needs to be done?"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-genie-400 focus:border-transparent"
              autoFocus
            />
          </div>

          {/* Description with @mention autocomplete */}
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Description <span className="text-gray-400 font-normal">(type @ to mention)</span></label>
            <MentionTextarea
              value={description}
              onChange={setDescription}
              users={users}
              placeholder="Details, context, steps to reproduce... Use @name to mention someone."
              rows={3}
            />
          </div>

          {/* Type + Priority row */}
          <div className="flex gap-3">
            <div className="flex-1">
              <label className="text-xs font-medium text-gray-700 block mb-1">Type</label>
              <select
                value={taskType} onChange={e => setTaskType(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white"
              >
                {TASK_TYPES.map(tt => (
                  <option key={tt.key} value={tt.key}>{tt.label}</option>
                ))}
              </select>
            </div>
            <div className="flex-1">
              <label className="text-xs font-medium text-gray-700 block mb-1">Priority</label>
              <select
                value={priority} onChange={e => setPriority(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white"
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
            </div>
          </div>

          {/* Assign + Due date row */}
          <div className="flex gap-3">
            <div className="flex-1">
              <label className="text-xs font-medium text-gray-700 block mb-1">Assign to</label>
              <select
                value={assignedTo} onChange={e => setAssignedTo(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white"
              >
                <option value="">Auto-assign to admin</option>
                {users.map(u => (
                  <option key={u.id} value={u.email}>{u.name || u.email.split('@')[0]}</option>
                ))}
              </select>
            </div>
            <div className="flex-1">
              <label className="text-xs font-medium text-gray-700 block mb-1">Due date</label>
              <input
                type="date" value={dueDate} onChange={e => setDueDate(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
              />
            </div>
          </div>

          {/* Tags */}
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Tags (comma-separated)</label>
            <input
              value={tagsInput} onChange={e => setTagsInput(e.target.value)}
              placeholder="pillar:onboard, dag:cuts_session, urgent"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
            />
          </div>

          {/* Chat session link */}
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Link to chat session (optional)</label>
            <input
              value={chatSessionId} onChange={e => setChatSessionId(e.target.value)}
              placeholder="Session ID"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono"
            />
          </div>

          {/* Submit */}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose}
              className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 transition-colors">
              Cancel
            </button>
            <button type="submit" disabled={!title.trim() || creating}
              className="flex items-center gap-2 px-4 py-2 bg-genie-600 text-white text-sm font-medium rounded-lg hover:bg-genie-700 disabled:opacity-50 transition-colors">
              {creating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              Create Task
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

/* ---- @Mention Textarea with Autocomplete ---- */
interface MentionTextareaProps {
  value: string
  onChange: (value: string) => void
  users: { id: number; email: string; name: string; role: string }[]
  placeholder?: string
  rows?: number
}

function MentionTextarea({ value, onChange, users, placeholder, rows = 3 }: MentionTextareaProps) {
  const [showDropdown, setShowDropdown] = useState(false)
  const [mentionQuery, setMentionQuery] = useState('')
  const [cursorPos, setCursorPos] = useState(0)
  const [mentionStart, setMentionStart] = useState(-1)
  const [selectedIdx, setSelectedIdx] = useState(0)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const filteredUsers = useMemo(() => {
    if (!mentionQuery) return users.slice(0, 8)
    const q = mentionQuery.toLowerCase()
    return users.filter(u =>
      u.name.toLowerCase().includes(q) ||
      u.email.toLowerCase().includes(q)
    ).slice(0, 8)
  }, [users, mentionQuery])

  const handleInput = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newValue = e.target.value
    const pos = e.target.selectionStart || 0
    onChange(newValue)
    setCursorPos(pos)

    // Check if we're in a mention context
    const textBefore = newValue.slice(0, pos)
    const atIdx = textBefore.lastIndexOf('@')
    if (atIdx >= 0) {
      const charBefore = atIdx > 0 ? textBefore[atIdx - 1] : ' '
      const textAfterAt = textBefore.slice(atIdx + 1)
      // Only trigger if @ is at start or preceded by whitespace, and no space after @
      if ((charBefore === ' ' || charBefore === '\n' || atIdx === 0) && !/\s/.test(textAfterAt)) {
        setMentionStart(atIdx)
        setMentionQuery(textAfterAt)
        setShowDropdown(true)
        setSelectedIdx(0)
        return
      }
    }
    setShowDropdown(false)
    setMentionStart(-1)
  }, [onChange])

  function insertMention(userEmail: string) {
    if (mentionStart < 0) return
    const before = value.slice(0, mentionStart)
    const after = value.slice(cursorPos)
    const newValue = `${before}@${userEmail} ${after}`
    onChange(newValue)
    setShowDropdown(false)
    setMentionStart(-1)
    // Focus back on textarea
    setTimeout(() => {
      if (textareaRef.current) {
        const newPos = mentionStart + userEmail.length + 2 // @email + space
        textareaRef.current.focus()
        textareaRef.current.setSelectionRange(newPos, newPos)
      }
    }, 0)
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (!showDropdown || filteredUsers.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIdx(prev => Math.min(prev + 1, filteredUsers.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIdx(prev => Math.max(prev - 1, 0))
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault()
      insertMention(filteredUsers[selectedIdx].email)
    } else if (e.key === 'Escape') {
      setShowDropdown(false)
    }
  }

  return (
    <div className="relative">
      <textarea
        ref={textareaRef}
        value={value}
        onChange={handleInput}
        onKeyDown={handleKeyDown}
        onBlur={() => setTimeout(() => setShowDropdown(false), 150)}
        placeholder={placeholder}
        rows={rows}
        className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm resize-none focus:ring-2 focus:ring-genie-400 focus:border-transparent"
      />
      {showDropdown && filteredUsers.length > 0 && (
        <div className="absolute left-0 right-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg z-50 max-h-48 overflow-auto">
          {filteredUsers.map((u, idx) => (
            <button
              key={u.id}
              type="button"
              onMouseDown={(e) => { e.preventDefault(); insertMention(u.email) }}
              className={`w-full text-left px-3 py-2 flex items-center gap-2 text-sm hover:bg-blue-50 transition-colors ${
                idx === selectedIdx ? 'bg-blue-50' : ''
              }`}
            >
              <User size={14} className="text-gray-400 shrink-0" />
              <span className="font-medium text-gray-800">{u.name || u.email.split('@')[0]}</span>
              <span className="text-gray-400 text-xs truncate">{u.email}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/* ---- Multi-select dropdown for filter bar ---- */
interface MultiSelectFilterProps {
  label: string
  options: { value: string; label: string; hint?: string }[]
  selected: string[]
  onChange: (vals: string[]) => void
  emptyLabel?: string
}

function MultiSelectFilter({ label, options, selected, onChange, emptyLabel }: MultiSelectFilterProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const wrapperRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function handleClick(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false); setQuery('')
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return options
    return options.filter(o =>
      o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q)
    )
  }, [options, query])

  function toggle(value: string) {
    if (selected.includes(value)) onChange(selected.filter(v => v !== value))
    else onChange([...selected, value])
  }

  return (
    <div ref={wrapperRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className={`flex items-center gap-1 px-2 py-1 text-xs border rounded-lg transition-colors ${
          selected.length > 0
            ? 'bg-genie-50 border-genie-300 text-genie-800'
            : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
        }`}
      >
        <Filter size={11} />
        {label}
        {selected.length > 0 && (
          <span className="ml-0.5 px-1 rounded bg-genie-600 text-white text-[10px]">{selected.length}</span>
        )}
        <ChevronDown size={11} className="text-gray-400" />
      </button>
      {open && (
        <div className="absolute z-30 left-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg w-64 max-h-72 overflow-auto">
          <div className="sticky top-0 bg-white border-b border-gray-100 p-1 flex items-center gap-1">
            <input
              autoFocus
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder={`Filter ${label.toLowerCase()}…`}
              className="flex-1 px-2 py-1 text-xs border-0 focus:outline-none"
            />
            {selected.length > 0 && (
              <button
                onClick={() => onChange([])}
                className="text-[10px] text-gray-400 hover:text-gray-700 px-1"
              >
                Clear
              </button>
            )}
          </div>
          {filtered.length === 0 ? (
            <div className="px-3 py-3 text-xs text-gray-400 text-center">
              {emptyLabel || 'No matches'}
            </div>
          ) : (
            filtered.map(opt => (
              <label
                key={opt.value}
                className="flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-gray-50 cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={selected.includes(opt.value)}
                  onChange={() => toggle(opt.value)}
                  className="rounded border-gray-300"
                />
                <span className="flex-1 truncate text-gray-700">{opt.label}</span>
                {opt.hint && <span className="text-[9px] text-gray-400 truncate">{opt.hint}</span>}
              </label>
            ))
          )}
        </div>
      )}
    </div>
  )
}


/* ---- Highlight @mentions in displayed text ---- */
function HighlightMentions({ text }: { text: string }) {
  const parts = text.split(/(@[\w.]+@example\.com|@[\w.]+)/g)
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith('@') ? (
          <span key={i} className="text-blue-600 font-medium bg-blue-50 rounded px-0.5">{part}</span>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  )
}
