import React, { useState, useEffect } from 'react'
import MentionInput from '../common/MentionInput'
import {
  CheckCircle, XCircle, AlertTriangle, Clock, Edit3, Save,
  MessageSquare, Search, ChevronDown, ChevronRight,
  UserPlus, User, GitPullRequest, GitMerge, Send, Plus, Bot, UserCircle, Upload, Loader2,
  Trash2, SquareCheck, Square
} from 'lucide-react'
import { fetchJSON } from '../../api/client'

interface GlossaryEntry {
  id: number
  term_key: string
  term: string
  definition: string
  formula: string | null
  source_tables: string[]
  dimensions: string[]
  dag: string | null
  domo_dataset_id: string | null
  view_name: string | null
  confidence: number | null
  workflow_state: string
  created_by: string | null
  created_by_type: string | null
  assigned_to: string | null
  reviewed_by: string | null
  expert_notes: string | null
  auto_generated: boolean
  sources?: { type: string; label: string; detail: string }[]
  comments?: Comment[]
  history?: HistoryItem[]
  created_at: string
  updated_at: string
}

interface Comment {
  id: number
  author: string
  comment: string
  action: string
  created_at: string
}

interface HistoryItem {
  id: number
  action: string
  actor: string
  old_value: string | null
  new_value: string | null
  created_at: string
}

interface Stats {
  total: number
  by_state: Record<string, number>
  by_source: Record<string, number>
}

const STATE_STYLES: Record<string, { bg: string; text: string; icon: any; label: string }> = {
  draft: { bg: 'bg-gray-100', text: 'text-gray-600', icon: Clock, label: 'Draft' },
  in_review: { bg: 'bg-blue-100', text: 'text-blue-700', icon: GitPullRequest, label: 'In Review' },
  changes_requested: { bg: 'bg-orange-100', text: 'text-orange-700', icon: AlertTriangle, label: 'Changes Requested' },
  approved: { bg: 'bg-green-100', text: 'text-green-700', icon: CheckCircle, label: 'Approved' },
  merged: { bg: 'bg-purple-100', text: 'text-purple-700', icon: GitMerge, label: 'Merged' },
  rejected: { bg: 'bg-red-100', text: 'text-red-600', icon: XCircle, label: 'Rejected' },
}

export default function GlossaryReview() {
  const [entries, setEntries] = useState<GlossaryEntry[]>([])
  const [stats, setStats] = useState<Stats>({ total: 0, by_state: {}, by_source: {} })
  const [loading, setLoading] = useState(true)
  const [stateFilter, setStateFilter] = useState('')
  const [sourceFilter, setSourceFilter] = useState('')
  const [reviewerFilter, setReviewerFilter] = useState('')
  const [search, setSearch] = useState('')
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [expandedEntry, setExpandedEntry] = useState<GlossaryEntry | null>(null)
  const [actorName, setActorName] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [showWizard, setShowWizard] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadStatus, setUploadStatus] = useState('')
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [bulkProcessing, setBulkProcessing] = useState(false)

  useEffect(() => { loadAll() }, [])

  async function loadAll() {
    setLoading(true)
    try {
      const [e, s] = await Promise.all([
        fetchJSON<GlossaryEntry[]>('/glossary-review/entries'),
        fetchJSON<Stats>('/glossary-review/stats'),
      ])
      setEntries(e)
      setStats(s)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  async function loadEntry(id: number) {
    const entry = await fetchJSON<GlossaryEntry>(`/glossary-review/entries/${id}`)
    setExpandedEntry(entry)
    setExpandedId(id)
  }

  async function assignReviewer(entryId: number, reviewer: string) {
    await fetchJSON('/glossary-review/entries/assign', {
      method: 'POST',
      body: JSON.stringify({ entry_ids: [entryId], assigned_to: reviewer }),
    })
    await loadAll()
    await loadEntry(entryId)
  }

  async function doAction(id: number, action: string, comment?: string) {
    const actor = actorName || 'reviewer'
    await fetchJSON(`/glossary-review/entries/${id}/${action}`, {
      method: 'POST',
      body: JSON.stringify({ actor, comment }),
    })
    await loadAll()
    if (expandedId === id) await loadEntry(id)
  }

  async function updateEntry(id: number, updates: Record<string, unknown>) {
    await fetchJSON(`/glossary-review/entries/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ ...updates, updated_by: actorName || 'reviewer' }),
    })
    await loadAll()
    await loadEntry(id)
  }

  async function addComment(id: number, comment: string) {
    await fetchJSON(`/glossary-review/entries/${id}/comments`, {
      method: 'POST',
      body: JSON.stringify({ author: actorName || 'reviewer', comment }),
    })
    await loadEntry(id)
  }

  function toggleSelection(id: number) {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function selectAllFiltered() {
    if (selectedIds.size === filtered.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(filtered.map(e => e.id)))
    }
  }

  async function handleBulkAction(action: string) {
    if (selectedIds.size === 0) return
    setBulkProcessing(true)
    try {
      await fetchJSON('/glossary-review/entries/bulk-action', {
        method: 'POST',
        body: JSON.stringify({
          entry_ids: [...selectedIds],
          action,
          actor: actorName || 'reviewer',
        }),
      })
      setSelectedIds(new Set())
      await loadAll()
    } catch (err) {
      alert('Bulk action failed: ' + (err instanceof Error ? err.message : 'Unknown'))
    } finally {
      setBulkProcessing(false)
    }
  }

  async function handleMerge() {
    const ids = [...selectedIds]
    if (ids.length < 2) { alert('Select at least 2 entries to merge'); return }
    const primary = expandedId && selectedIds.has(expandedId) ? expandedId : ids[0]
    const mergeIds = ids.filter(id => id !== primary)
    const primaryEntry = entries.find(e => e.id === primary)
    if (!confirm(`Merge ${mergeIds.length} entries into "${primaryEntry?.term || '#' + primary}"? The other entries will be rejected.`)) return
    setBulkProcessing(true)
    try {
      await fetchJSON('/glossary-review/entries/merge', {
        method: 'POST',
        body: JSON.stringify({
          primary_id: primary,
          merge_ids: mergeIds,
          actor: actorName || 'reviewer',
        }),
      })
      setSelectedIds(new Set())
      await loadAll()
      await loadEntry(primary)
    } catch (err) {
      alert('Merge failed: ' + (err instanceof Error ? err.message : 'Unknown'))
    } finally {
      setBulkProcessing(false)
    }
  }

  // Get unique reviewers for filter dropdown
  const reviewers = [...new Set(entries.map(e => e.assigned_to).filter(Boolean))] as string[]

  const filtered = entries.filter(e => {
    if (stateFilter && e.workflow_state !== stateFilter) return false
    if (sourceFilter && e.created_by_type !== sourceFilter) return false
    if (reviewerFilter && e.assigned_to !== reviewerFilter) return false
    if (search && !`${e.term} ${e.definition} ${e.term_key}`.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  if (loading) {
    return <div className="flex items-center justify-center h-full text-gray-400">Loading...</div>
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="border-b border-gray-200 px-6 pt-5 pb-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Glossary</h2>
            <p className="text-sm text-gray-500">Business definitions — auto-generated from KB or manually created. PR-style review workflow.</p>
          </div>
          <div className="flex gap-2">
            <label className={`flex items-center gap-1.5 px-3 py-2 text-sm rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 cursor-pointer ${uploading ? 'opacity-50 pointer-events-none' : ''}`}>
              {uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
              {uploading ? uploadStatus : 'Upload Doc'}
              {!uploading && <span className="text-[9px] text-gray-400 ml-0.5">(.docx .pdf .txt .csv .md .yaml)</span>}
              <input type="file" className="hidden"
                accept=".txt,.md,.csv,.json,.yaml,.yml,.pdf,.docx"
                disabled={uploading}
                onChange={async (e) => {
                  const file = e.target.files?.[0]
                  if (!file) return
                  setUploading(true)
                  setUploadStatus(`Uploading ${file.name}...`)
                  const formData = new FormData()
                  formData.append('file', file)
                  formData.append('uploaded_by', 'user')
                  try {
                    setUploadStatus('AI extracting terms...')
                    const res = await fetch(`${(window as unknown as Record<string, Record<string, string>>).__ENV__?.VITE_API_BASE || import.meta.env.VITE_API_BASE || '/api'}/glossary-review/upload-document`, {
                      method: 'POST',
                      headers: { 'X-Auth-Token': localStorage.getItem('genie_auth_token') || '' },
                      body: formData,
                    })
                    const data = await res.json()
                    if (!res.ok) throw new Error(data.detail || 'Upload failed')
                    alert(`Extracted ${data.created_count} terms from ${file.name}. Review ticket created.${data.skipped_count ? ` (${data.skipped_count} duplicates skipped)` : ''}`)
                    loadAll()
                  } catch (err) {
                    alert('Upload failed: ' + (err instanceof Error ? err.message : 'Unknown error'))
                  } finally {
                    setUploading(false)
                    setUploadStatus('')
                  }
                  e.target.value = ''
                }}
              />
            </label>
            <button onClick={() => { setShowWizard(!showWizard); setShowCreate(false) }}
              className="flex items-center gap-1.5 px-3 py-2 text-sm rounded-lg border border-genie-600 text-genie-600 hover:bg-genie-50">
              <Bot size={14} /> Create with AI
            </button>
            <button onClick={() => { setShowCreate(!showCreate); setShowWizard(false) }}
              className="flex items-center gap-1.5 px-3 py-2 text-sm rounded-lg bg-genie-600 text-white hover:bg-genie-700">
              <Plus size={14} /> New Definition
            </button>
          </div>
        </div>

        {/* State pills */}
        <div className="flex gap-2 mb-3 flex-wrap">
          <button onClick={() => setStateFilter('')}
            className={`text-xs px-3 py-1.5 rounded-full border ${!stateFilter ? 'border-genie-500 bg-genie-50 text-genie-700 font-medium' : 'border-gray-200 text-gray-600 hover:bg-gray-50'}`}>
            All ({stats.total})
          </button>
          {Object.entries(STATE_STYLES).map(([state, style]) => {
            const count = stats.by_state[state] || 0
            if (!count && state !== 'merged') return null
            const Icon = style.icon
            return (
              <button key={state} onClick={() => setStateFilter(stateFilter === state ? '' : state)}
                className={`text-xs px-3 py-1.5 rounded-full border inline-flex items-center gap-1 ${stateFilter === state ? `${style.bg} ${style.text} font-medium border-current` : 'border-gray-200 text-gray-600 hover:bg-gray-50'}`}>
                <Icon size={10} /> {style.label} ({count})
              </button>
            )
          })}
          <div className="border-l border-gray-300 h-5 self-center" />
          <button onClick={() => setSourceFilter(sourceFilter === 'agent' ? '' : 'agent')}
            className={`text-xs px-3 py-1.5 rounded-full border inline-flex items-center gap-1 ${sourceFilter === 'agent' ? 'bg-blue-50 text-blue-700 border-blue-300 font-medium' : 'border-gray-200 text-gray-600 hover:bg-gray-50'}`}>
            <Bot size={10} /> KB Agent ({stats.by_source.agent || 0})
          </button>
          <button onClick={() => setSourceFilter(sourceFilter === 'user' ? '' : 'user')}
            className={`text-xs px-3 py-1.5 rounded-full border inline-flex items-center gap-1 ${sourceFilter === 'user' ? 'bg-indigo-50 text-indigo-700 border-indigo-300 font-medium' : 'border-gray-200 text-gray-600 hover:bg-gray-50'}`}>
            <UserCircle size={10} /> User ({stats.by_source.user || 0})
          </button>
          <button onClick={() => setSourceFilter(sourceFilter === 'document' ? '' : 'document')}
            className={`text-xs px-3 py-1.5 rounded-full border inline-flex items-center gap-1 ${sourceFilter === 'document' ? 'bg-amber-50 text-amber-700 border-amber-300 font-medium' : 'border-gray-200 text-gray-600 hover:bg-gray-50'}`}>
            <Upload size={10} /> Document ({stats.by_source.document || 0})
          </button>
        </div>

        {/* Search + Reviewer filter + Identity */}
        <div className="flex items-center gap-3">
          <div className="relative flex-1 max-w-sm">
            <Search size={14} className="absolute left-2.5 top-2.5 text-gray-400" />
            <input value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Search terms, definitions..."
              className="w-full pl-8 pr-3 py-2 text-sm border border-gray-300 rounded-lg" />
          </div>
          {reviewers.length > 0 && (
            <select value={reviewerFilter} onChange={e => setReviewerFilter(e.target.value)}
              className={`text-sm border rounded-lg px-2 py-2 ${reviewerFilter ? 'border-genie-400 bg-genie-50 text-genie-700' : 'border-gray-300 text-gray-600'}`}>
              <option value="">All reviewers</option>
              {reviewers.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          )}
          <input value={actorName} onChange={e => setActorName(e.target.value)}
            placeholder="Your name/email"
            className="text-sm border border-gray-300 rounded-lg px-2 py-2 w-40" />
        </div>
      </div>

      {/* Bulk action bar */}
      {selectedIds.size > 0 && (
        <div className="flex items-center gap-3 px-6 py-2 bg-genie-50 border-b border-genie-200">
          <span className="text-xs font-medium text-genie-700">{selectedIds.size} selected</span>
          <div className="flex gap-1.5">
            <button onClick={() => handleBulkAction('approve')} disabled={bulkProcessing}
              className="text-[11px] px-2.5 py-1 rounded bg-green-600 text-white hover:bg-green-700 disabled:opacity-50 flex items-center gap-1">
              <CheckCircle size={10} /> Approve
            </button>
            <button onClick={() => handleBulkAction('submit-for-review')} disabled={bulkProcessing}
              className="text-[11px] px-2.5 py-1 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1">
              <Send size={10} /> Submit
            </button>
            <button onClick={() => handleBulkAction('reject')} disabled={bulkProcessing}
              className="text-[11px] px-2.5 py-1 rounded bg-red-50 text-red-600 hover:bg-red-100 disabled:opacity-50 flex items-center gap-1">
              <XCircle size={10} /> Reject
            </button>
            {selectedIds.size >= 2 && (
              <button onClick={handleMerge} disabled={bulkProcessing}
                className="text-[11px] px-2.5 py-1 rounded bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-50 flex items-center gap-1">
                <GitMerge size={10} /> Merge ({selectedIds.size})
              </button>
            )}
            <button onClick={() => { if (confirm(`Delete ${selectedIds.size} entries?`)) handleBulkAction('delete') }} disabled={bulkProcessing}
              className="text-[11px] px-2.5 py-1 rounded bg-gray-100 text-red-600 hover:bg-red-50 disabled:opacity-50 flex items-center gap-1">
              <Trash2 size={10} /> Delete
            </button>
          </div>
          <button onClick={() => setSelectedIds(new Set())} className="text-[11px] text-gray-500 hover:text-gray-700 ml-auto">
            Clear selection
          </button>
          {bulkProcessing && <Loader2 size={12} className="animate-spin text-genie-500" />}
        </div>
      )}

      {/* Create forms */}
      {showWizard && <WizardForm onCreated={() => { setShowWizard(false); loadAll() }} />}
      {showCreate && <CreateForm onCreated={() => { setShowCreate(false); loadAll() }} author={actorName} />}

      {/* Split view: list + detail */}
      <div className="flex-1 flex overflow-hidden">
        {/* Entry list */}
        <div className={`${expandedId ? 'w-1/2' : 'w-full'} border-r border-gray-200 overflow-auto`}>
          {/* Select all header */}
          <div className="flex items-center gap-2 px-4 py-1.5 bg-gray-50 border-b border-gray-200 text-[10px] text-gray-500">
            <button onClick={selectAllFiltered} className="flex items-center gap-1 hover:text-gray-700">
              {selectedIds.size > 0 && selectedIds.size === filtered.length
                ? <SquareCheck size={12} className="text-genie-600" />
                : <Square size={12} />}
              {selectedIds.size > 0 ? `${selectedIds.size} of ${filtered.length}` : `Select all (${filtered.length})`}
            </button>
          </div>

          {filtered.map(entry => {
            const style = STATE_STYLES[entry.workflow_state] || STATE_STYLES.draft
            const Icon = style.icon
            const isAgent = entry.created_by_type === 'agent'
            const isSelected = selectedIds.has(entry.id)
            return (
              <div key={entry.id}
                className={`flex items-center gap-3 px-4 py-3 border-b border-gray-50 cursor-pointer hover:bg-gray-50 ${expandedId === entry.id ? 'bg-genie-50' : ''} ${isSelected ? 'bg-blue-50/50' : ''}`}>
                <button onClick={e => { e.stopPropagation(); toggleSelection(entry.id) }}
                  className="flex-shrink-0">
                  {isSelected
                    ? <SquareCheck size={14} className="text-genie-600" />
                    : <Square size={14} className="text-gray-300 hover:text-gray-500" />}
                </button>
                <div className="flex-1 min-w-0" onClick={() => loadEntry(entry.id)}>
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm text-gray-900 truncate">{entry.term}</span>
                    <span className={`inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded-full ${style.bg} ${style.text}`}>
                      <Icon size={9} /> {style.label}
                    </span>
                    {isAgent ? (
                      <span title="Auto-generated by KB agent"><Bot size={12} className="text-blue-400" /></span>
                    ) : (
                      <span title={`Created by ${entry.created_by}`}><UserCircle size={12} className="text-indigo-400" /></span>
                    )}
                    {entry.assigned_to && (
                      <span className="text-[10px] text-gray-500 flex items-center gap-0.5 bg-gray-100 px-1.5 py-0.5 rounded-full">
                        <User size={9} /> {entry.assigned_to}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 truncate mt-0.5">{entry.definition}</p>
                </div>
              </div>
            )
          })}
          {filtered.length === 0 && (
            <div className="text-center py-12 text-sm text-gray-400">
              No entries match filter. {entries.length === 0 && 'Run KB build to auto-generate from view SQL.'}
            </div>
          )}
        </div>

        {/* Detail panel */}
        {expandedId && expandedEntry && (
          <EntryDetail
            entry={expandedEntry}
            actor={actorName || 'reviewer'}
            onAction={doAction}
            onComment={addComment}
            onAssign={assignReviewer}
            onUpdate={updateEntry}
            onClose={() => { setExpandedId(null); setExpandedEntry(null) }}
          />
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Entry Detail Panel (right side)
// ---------------------------------------------------------------------------

interface UserInfo {
  id: number
  email: string
  name: string
  role: string
}

function EntryDetail({ entry, actor, onAction, onComment, onAssign, onUpdate, onClose }: {
  entry: GlossaryEntry
  actor: string
  onAction: (id: number, action: string, comment?: string) => void
  onComment: (id: number, comment: string) => void
  onAssign: (entryId: number, reviewer: string) => void
  onUpdate: (id: number, updates: Record<string, unknown>) => void
  onClose: () => void
}) {
  const [newComment, setNewComment] = useState('')
  const [changeComment, setChangeComment] = useState('')
  const [users, setUsers] = useState<UserInfo[]>([])
  const [showReviewerDropdown, setShowReviewerDropdown] = useState(false)
  const [assigningReviewer, setAssigningReviewer] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editDef, setEditDef] = useState(entry.definition)
  const [editFormula, setEditFormula] = useState(entry.formula || '')
  const [editSources, setEditSources] = useState((entry.source_tables || []).join(', '))
  const [editDims, setEditDims] = useState((entry.dimensions || []).join(', '))
  const [saving, setSaving] = useState(false)
  const style = STATE_STYLES[entry.workflow_state] || STATE_STYLES.draft
  const Icon = style.icon
  const isAgent = entry.created_by_type === 'agent'
  const canEdit = !['merged', 'rejected'].includes(entry.workflow_state)

  useEffect(() => {
    fetchJSON<UserInfo[]>('/users/users').then(setUsers).catch(() => {})
  }, [])

  // Reset edit fields when entry changes
  useEffect(() => {
    setEditDef(entry.definition)
    setEditFormula(entry.formula || '')
    setEditSources((entry.source_tables || []).join(', '))
    setEditDims((entry.dimensions || []).join(', '))
    setEditing(false)
  }, [entry.id])

  async function handleSaveEdit() {
    setSaving(true)
    try {
      await onUpdate(entry.id, {
        definition: editDef,
        formula: editFormula || null,
        source_tables: editSources.split(',').map(s => s.trim()).filter(Boolean),
        dimensions: editDims.split(',').map(s => s.trim()).filter(Boolean),
      })
      setEditing(false)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="w-1/2 overflow-auto flex flex-col">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-gray-900">{entry.term}</h3>
          <div className="flex items-center gap-2 mt-1">
            <span className={`inline-flex items-center gap-0.5 text-xs px-2 py-0.5 rounded-full ${style.bg} ${style.text}`}>
              <Icon size={10} /> {style.label}
            </span>
            {isAgent ? (
              <span className="text-xs text-blue-500 flex items-center gap-0.5"><Bot size={10} /> KB Agent</span>
            ) : (
              <span className="text-xs text-indigo-500 flex items-center gap-0.5"><UserCircle size={10} /> {entry.created_by}</span>
            )}
            {entry.confidence != null && <span className="text-[10px] text-gray-400">confidence: {entry.confidence}</span>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {canEdit && !editing && (
            <button onClick={() => setEditing(true)}
              className="text-xs text-genie-600 hover:text-genie-700 flex items-center gap-1">
              <Edit3 size={12} /> Edit
            </button>
          )}
          {editing && (
            <>
              <button onClick={handleSaveEdit} disabled={saving}
                className="text-xs text-green-600 hover:text-green-700 flex items-center gap-1 disabled:opacity-50">
                {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />} Save
              </button>
              <button onClick={() => { setEditing(false); setEditDef(entry.definition); setEditFormula(entry.formula || ''); setEditSources((entry.source_tables || []).join(', ')); setEditDims((entry.dimensions || []).join(', ')) }}
                className="text-xs text-gray-400 hover:text-gray-600">Cancel</button>
            </>
          )}
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xs">Close</button>
        </div>
      </div>

      {/* Reviewers (PR-style) */}
      <div className="px-4 py-3 border-b border-gray-200">
        <label className="text-[10px] text-gray-400 uppercase mb-1.5 block">Reviewers</label>
        {entry.assigned_to ? (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 rounded-full bg-genie-100 flex items-center justify-center text-[10px] text-genie-700 font-medium">
                {entry.assigned_to[0]?.toUpperCase()}
              </div>
              <span className="text-sm text-gray-800">{entry.assigned_to}</span>
              <span className="text-[10px] text-green-600 bg-green-50 px-1.5 py-0.5 rounded-full">assigned</span>
            </div>
            {canEdit && (
              <button
                onClick={async () => {
                  setAssigningReviewer(true)
                  try {
                    await onAssign(entry.id, '')
                  } finally {
                    setAssigningReviewer(false)
                  }
                }}
                className="text-[10px] text-gray-400 hover:text-red-500"
                title="Remove reviewer"
              >
                <XCircle size={12} />
              </button>
            )}
          </div>
        ) : (
          <p className="text-xs text-gray-400 mb-1.5">No reviewer assigned</p>
        )}
        {canEdit && (
          <div className="mt-2 relative">
            <button
              onClick={() => setShowReviewerDropdown(!showReviewerDropdown)}
              className="text-xs text-genie-600 hover:text-genie-700 flex items-center gap-1"
            >
              <UserPlus size={12} /> {entry.assigned_to ? 'Change reviewer' : 'Add reviewer'}
            </button>
            {showReviewerDropdown && (
              <div className="absolute top-6 left-0 z-10 bg-white border border-gray-200 rounded-lg shadow-lg py-1 w-56 max-h-48 overflow-auto">
                {users.length === 0 && (
                  <div className="px-3 py-2 text-xs text-gray-400">No users found</div>
                )}
                {users.filter(u => u.name !== entry.assigned_to && u.email !== entry.assigned_to).map(u => (
                  <button
                    key={u.id}
                    onClick={async () => {
                      setShowReviewerDropdown(false)
                      setAssigningReviewer(true)
                      try {
                        await onAssign(entry.id, u.email || u.name)
                      } finally {
                        setAssigningReviewer(false)
                      }
                    }}
                    className="w-full text-left px-3 py-1.5 text-xs hover:bg-gray-50 flex items-center gap-2"
                  >
                    <div className="w-5 h-5 rounded-full bg-gray-200 flex items-center justify-center text-[9px] text-gray-500">
                      {u.name?.[0]?.toUpperCase() || u.email?.[0]?.toUpperCase()}
                    </div>
                    <div>
                      <div className="text-gray-800">{u.name || u.email}</div>
                      {u.name && u.email && <div className="text-[10px] text-gray-400">{u.email}</div>}
                    </div>
                  </button>
                ))}
              </div>
            )}
            {assigningReviewer && (
              <span className="text-[10px] text-gray-400 ml-2">Assigning...</span>
            )}
          </div>
        )}
      </div>

      {/* Content — toggleable edit mode */}
      <div className="px-4 py-3 space-y-3 flex-1 overflow-auto">
        {/* Sources */}
        {entry.sources && entry.sources.length > 0 && (
          <div>
            <label className="text-[10px] text-gray-400 uppercase">Sources</label>
            <div className="flex flex-wrap gap-1.5 mt-1">
              {entry.sources.map((s, i) => (
                <span key={i} title={s.detail}
                  className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
                    s.type === 'view_sql' ? 'bg-blue-50 text-blue-600' :
                    s.type === 'redshift' ? 'bg-green-50 text-green-600' :
                    s.type === 'repo' ? 'bg-orange-50 text-orange-600' :
                    s.type === 'domo' ? 'bg-purple-50 text-purple-600' :
                    'bg-gray-50 text-gray-600'
                  }`}>
                  {s.label}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Definition */}
        <div>
          <label className="text-[10px] text-gray-400 uppercase">Definition</label>
          {editing ? (
            <textarea value={editDef} onChange={e => setEditDef(e.target.value)}
              rows={3} className="w-full text-sm border border-genie-300 rounded px-2 py-1.5 mt-0.5 focus:outline-none focus:ring-1 focus:ring-genie-400" />
          ) : (
            <p className="text-sm text-gray-800 mt-0.5">{entry.definition}</p>
          )}
        </div>

        {/* Formula */}
        <div>
          <label className="text-[10px] text-gray-400 uppercase">Formula</label>
          {editing ? (
            <input value={editFormula} onChange={e => setEditFormula(e.target.value)}
              placeholder="e.g., COUNT(DISTINCT user_id) WHERE ..."
              className="w-full text-xs font-mono border border-genie-300 rounded px-2 py-1.5 mt-0.5 focus:outline-none focus:ring-1 focus:ring-genie-400" />
          ) : entry.formula ? (
            <p className="text-xs font-mono text-gray-700 bg-gray-50 p-2 rounded mt-0.5">{entry.formula}</p>
          ) : (
            <p className="text-xs text-gray-300 mt-0.5 italic">No formula</p>
          )}
        </div>

        {/* Source Tables */}
        <div>
          <label className="text-[10px] text-gray-400 uppercase">Source Tables</label>
          {editing ? (
            <input value={editSources} onChange={e => setEditSources(e.target.value)}
              placeholder="Comma-separated: prd_dw.fact.table1, prd_dw.dim.table2"
              className="w-full text-xs font-mono border border-genie-300 rounded px-2 py-1.5 mt-0.5 focus:outline-none focus:ring-1 focus:ring-genie-400" />
          ) : entry.source_tables?.length > 0 ? (
            <div className="flex flex-wrap gap-1 mt-0.5">
              {entry.source_tables.map(t => (
                <span key={t} className="text-[10px] font-mono bg-gray-100 px-1.5 py-0.5 rounded">{t}</span>
              ))}
            </div>
          ) : (
            <p className="text-xs text-gray-300 mt-0.5 italic">No source tables</p>
          )}
        </div>

        {/* Dimensions */}
        <div>
          <label className="text-[10px] text-gray-400 uppercase">Dimensions</label>
          {editing ? (
            <input value={editDims} onChange={e => setEditDims(e.target.value)}
              placeholder="Comma-separated: platform, country, pillar"
              className="w-full text-xs border border-genie-300 rounded px-2 py-1.5 mt-0.5 focus:outline-none focus:ring-1 focus:ring-genie-400" />
          ) : entry.dimensions?.length > 0 ? (
            <div className="flex flex-wrap gap-1 mt-0.5">
              {entry.dimensions.map(d => (
                <span key={d} className="text-[10px] bg-cyan-50 text-cyan-700 px-1.5 py-0.5 rounded">{d}</span>
              ))}
            </div>
          ) : (
            <p className="text-xs text-gray-300 mt-0.5 italic">No dimensions</p>
          )}
        </div>

        <div className="flex flex-wrap gap-3 text-[10px] text-gray-400">
          {entry.dag && <span>DAG: <span className="font-mono">{entry.dag}</span></span>}
          {entry.view_name && <span>View: <span className="font-mono">{entry.view_name}</span></span>}
          {entry.domo_dataset_id && <span>DOMO: <span className="font-mono">{entry.domo_dataset_id.slice(0, 8)}...</span></span>}
        </div>

        {/* Actions */}
        <div className="border-t border-gray-200 pt-3">
          <div className="flex gap-2 flex-wrap">
            {entry.workflow_state === 'draft' && (
              <button onClick={() => onAction(entry.id, 'submit-for-review')}
                className="text-xs px-3 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-700 flex items-center gap-1">
                <Send size={12} /> Submit for Review
              </button>
            )}
            {['draft', 'in_review', 'changes_requested'].includes(entry.workflow_state) && (
              <button onClick={() => onAction(entry.id, 'approve')}
                className="text-xs px-3 py-1.5 rounded bg-green-600 text-white hover:bg-green-700 flex items-center gap-1">
                <CheckCircle size={12} /> Approve
              </button>
            )}
            {entry.workflow_state === 'in_review' && (
              <button onClick={() => {
                if (!changeComment) { alert('Add a comment explaining what needs to change'); return }
                onAction(entry.id, 'request-changes', changeComment)
                setChangeComment('')
              }}
                className="text-xs px-3 py-1.5 rounded bg-orange-500 text-white hover:bg-orange-600 flex items-center gap-1">
                <AlertTriangle size={12} /> Request Changes
              </button>
            )}
            {entry.workflow_state === 'approved' && (
              <button onClick={() => onAction(entry.id, 'merge')}
                className="text-xs px-3 py-1.5 rounded bg-purple-600 text-white hover:bg-purple-700 flex items-center gap-1">
                <GitMerge size={12} /> Merge to Live
              </button>
            )}
            {canEdit && (
              <button onClick={() => onAction(entry.id, 'reject')}
                className="text-xs px-3 py-1.5 rounded bg-red-50 text-red-600 hover:bg-red-100 flex items-center gap-1">
                <XCircle size={12} /> Reject
              </button>
            )}
          </div>
          {entry.workflow_state === 'in_review' && (
            <textarea value={changeComment} onChange={e => setChangeComment(e.target.value)}
              placeholder="Describe what needs to change..."
              rows={2}
              className="mt-2 w-full text-sm border border-gray-300 rounded-lg px-3 py-2 resize-y focus:outline-none focus:ring-1 focus:ring-orange-400" />
          )}
        </div>

        {/* Conversation Thread */}
        <div className="border-t border-gray-200 pt-3">
          <h4 className="text-xs font-medium text-gray-700 mb-2 flex items-center gap-1">
            <MessageSquare size={12} /> Conversation ({entry.comments?.length || 0})
          </h4>
          <div className="space-y-2 mb-3">
            {(entry.comments || []).map(c => (
              <div key={c.id} className="flex gap-2">
                <div className="w-6 h-6 rounded-full bg-gray-200 flex items-center justify-center text-[10px] text-gray-500 flex-shrink-0 mt-0.5">
                  {c.author[0]?.toUpperCase()}
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-gray-700">{c.author}</span>
                    {c.action && c.action !== 'comment' && (
                      <span className={`text-[9px] px-1 py-0.5 rounded ${
                        c.action === 'approve' ? 'bg-green-100 text-green-700' :
                        c.action === 'request_changes' ? 'bg-orange-100 text-orange-700' :
                        c.action === 'reject' ? 'bg-red-100 text-red-600' :
                        c.action === 'merge' ? 'bg-purple-100 text-purple-700' :
                        'bg-gray-100 text-gray-600'
                      }`}>{c.action.replace('_', ' ')}</span>
                    )}
                    <span className="text-[10px] text-gray-400">
                      {new Date(c.created_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                  <p className="text-xs text-gray-600 mt-0.5">{c.comment}</p>
                </div>
              </div>
            ))}
          </div>
          <div className="space-y-2">
            <MentionInput value={newComment} onChange={setNewComment}
              placeholder="Add a comment... (type @ to mention)"
              rows={3}
              className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-genie-400 focus:border-genie-400 resize-y" />
            <div className="flex justify-end">
              <button onClick={() => { if (newComment.trim()) { onComment(entry.id, newComment); setNewComment('') } }}
                disabled={!newComment.trim()}
                className="text-xs px-4 py-1.5 rounded-lg bg-genie-600 text-white hover:bg-genie-700 disabled:opacity-50 disabled:bg-gray-200 disabled:text-gray-400 flex items-center gap-1">
                <Send size={10} /> Comment
              </button>
            </div>
          </div>
        </div>

        {/* History Timeline */}
        {entry.history && entry.history.length > 0 && (
          <div className="border-t border-gray-200 pt-3">
            <h4 className="text-xs font-medium text-gray-700 mb-2">History</h4>
            <div className="space-y-1">
              {entry.history.map(h => (
                <div key={h.id} className="text-[10px] text-gray-400 flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-gray-300" />
                  <span className="font-medium text-gray-600">{h.actor}</span>
                  <span>{h.action}</span>
                  {h.new_value && <span className="font-mono">→ {h.new_value}</span>}
                  <span className="ml-auto">{new Date(h.created_at).toLocaleDateString()}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Create Form
// ---------------------------------------------------------------------------

function CreateForm({ onCreated, author }: { onCreated: () => void; author: string }) {
  const [termKey, setTermKey] = useState('')
  const [term, setTerm] = useState('')
  const [definition, setDefinition] = useState('')
  const [formula, setFormula] = useState('')
  const [saving, setSaving] = useState(false)

  async function handleCreate() {
    setSaving(true)
    try {
      await fetchJSON('/glossary-review/entries', {
        method: 'POST',
        body: JSON.stringify({
          term_key: termKey || term.toLowerCase().replace(/\s+/g, '_'),
          term, definition, formula: formula || null,
          created_by: author || 'anonymous',
        }),
      })
      onCreated()
    } catch (err) {
      alert('Failed: ' + (err instanceof Error ? err.message : 'Unknown'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="border-b border-gray-200 px-6 py-4 bg-gray-50">
      <h4 className="text-sm font-medium text-gray-700 mb-2">New Definition</h4>
      <div className="grid grid-cols-2 gap-2 mb-2">
        <input value={term} onChange={e => setTerm(e.target.value)} placeholder="Term (e.g., Activation Rate)"
          className="text-sm border border-gray-300 rounded px-2 py-1.5" />
        <input value={termKey} onChange={e => setTermKey(e.target.value)}
          placeholder={`Key (auto: ${term.toLowerCase().replace(/\s+/g, '_') || '...'})`}
          className="text-sm border border-gray-300 rounded px-2 py-1.5 font-mono" />
      </div>
      <textarea value={definition} onChange={e => setDefinition(e.target.value)} placeholder="Definition..."
        rows={2} className="w-full text-sm border border-gray-300 rounded px-2 py-1.5 mb-2" />
      <input value={formula} onChange={e => setFormula(e.target.value)} placeholder="Formula (optional)"
        className="w-full text-sm border border-gray-300 rounded px-2 py-1.5 font-mono mb-2" />
      <div className="flex gap-2">
        <button onClick={handleCreate} disabled={saving || !term || !definition}
          className="text-xs px-3 py-1.5 rounded bg-genie-600 text-white hover:bg-genie-700 disabled:opacity-50">
          Create as Draft
        </button>
        <button onClick={onCreated} className="text-xs px-3 py-1.5 rounded text-gray-500 hover:text-gray-700">
          Cancel
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// AI Wizard Form
// ---------------------------------------------------------------------------

interface WizardQuestion {
  id: number
  text: string
  type: 'select' | 'yes_no' | 'yes_no_text' | 'text'
  options?: string[]
  placeholder?: string
  follow_up_on?: string
}

function WizardForm({ onCreated }: { onCreated: () => void }) {
  const [term, setTerm] = useState('')
  const [persona, setPersona] = useState('engineer')
  const [phase, setPhase] = useState<'input' | 'loading' | 'questions' | 'submitting' | 'done' | 'error'>('input')
  const [questions, setQuestions] = useState<WizardQuestion[]>([])
  const [answers, setAnswers] = useState<Record<number, string>>({})
  const [wizardId, setWizardId] = useState('')
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState('')

  async function handleStart() {
    setPhase('loading')
    try {
      const res = await fetchJSON<{ wizard_id: string; questions: WizardQuestion[] }>('/glossary/wizard/start', {
        method: 'POST',
        body: JSON.stringify({ term: term || null, persona, trigger_reason: 'user_initiated' }),
      })
      setWizardId(res.wizard_id)
      setQuestions(res.questions)
      setPhase('questions')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start wizard')
      setPhase('error')
    }
  }

  async function handleSubmit() {
    setPhase('submitting')
    try {
      const answerList = Object.entries(answers).map(([qid, val]) => ({
        question_id: parseInt(qid),
        value: val,
      }))
      const res = await fetchJSON<{ entry: any; status: string }>('/glossary/wizard/submit', {
        method: 'POST',
        body: JSON.stringify({ wizard_id: wizardId, answers: answerList }),
      })
      setResult(res.entry)
      setPhase('done')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed')
      setPhase('error')
    }
  }

  return (
    <div className="border-b border-gray-200 px-6 py-4 bg-blue-50">
      <h4 className="text-sm font-medium text-gray-700 mb-2 flex items-center gap-1.5">
        <Bot size={14} className="text-blue-500" /> AI Glossary Wizard
      </h4>

      {phase === 'input' && (
        <div className="flex gap-2 items-end flex-wrap">
          <div className="flex-1">
            <label className="text-[10px] text-gray-500 block mb-0.5">Term to define</label>
            <input value={term} onChange={e => setTerm(e.target.value)}
              placeholder="e.g., Activation Rate (optional — AI will ask)"
              className="w-full text-sm border border-gray-300 rounded px-2 py-1.5" />
          </div>
          <div>
            <label className="text-[10px] text-gray-500 block mb-0.5">Your role</label>
            <select value={persona} onChange={e => setPersona(e.target.value)}
              className="text-sm border border-gray-300 rounded px-2 py-1.5">
              <option value="engineer">Data Engineer</option>
              <option value="analytics_engineer">Analytics Engineer</option>
              <option value="analyst">Data Analyst</option>
              <option value="ml_engineer">ML Engineer</option>
              <option value="executive">Executive / Business Leader</option>
              <option value="new_member">New Team Member</option>
            </select>
          </div>
          <button onClick={handleStart}
            className="text-xs px-3 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-700">
            Start Wizard
          </button>
          <button onClick={onCreated} className="text-xs text-gray-500 hover:text-gray-700">Cancel</button>
        </div>
      )}

      {phase === 'loading' && (
        <div className="flex items-center gap-2 text-sm text-blue-600">
          <div className="animate-spin h-4 w-4 border-2 border-blue-400 border-t-transparent rounded-full" />
          AI is generating questions...
        </div>
      )}

      {phase === 'questions' && (
        <div className="space-y-3">
          {questions.map(q => (
            <div key={q.id}>
              <label className="text-xs font-medium text-gray-700 block mb-1">
                {q.id}. {q.text}
              </label>
              {q.type === 'select' && q.options && (
                <select value={answers[q.id] || ''} onChange={e => setAnswers(prev => ({ ...prev, [q.id]: e.target.value }))}
                  className="w-full text-sm border border-gray-300 rounded px-2 py-1.5">
                  <option value="">Select...</option>
                  {q.options.map(o => <option key={o} value={o}>{o}</option>)}
                </select>
              )}
              {q.type === 'yes_no' && (
                <div className="flex gap-3">
                  {['Yes', 'No'].map(v => (
                    <label key={v} className="flex items-center gap-1 text-sm cursor-pointer">
                      <input type="radio" name={`q${q.id}`} value={v.toLowerCase()}
                        checked={answers[q.id] === v.toLowerCase()}
                        onChange={e => setAnswers(prev => ({ ...prev, [q.id]: e.target.value }))} />
                      {v}
                    </label>
                  ))}
                </div>
              )}
              {q.type === 'yes_no_text' && (
                <div className="space-y-1">
                  <div className="flex gap-3">
                    {['Yes', 'No'].map(v => (
                      <label key={v} className="flex items-center gap-1 text-sm cursor-pointer">
                        <input type="radio" name={`q${q.id}`} value={v.toLowerCase()}
                          checked={(answers[q.id] || '').startsWith(v.toLowerCase())}
                          onChange={e => setAnswers(prev => ({ ...prev, [q.id]: e.target.value }))} />
                        {v}
                      </label>
                    ))}
                  </div>
                  {(answers[q.id] || '').startsWith('yes') && (
                    <input value={(answers[q.id] || '').replace('yes:', '').replace('yes', '')}
                      onChange={e => setAnswers(prev => ({ ...prev, [q.id]: `yes:${e.target.value}` }))}
                      placeholder="Please elaborate..."
                      className="w-full text-sm border border-gray-300 rounded px-2 py-1.5" />
                  )}
                </div>
              )}
              {q.type === 'text' && (
                <input value={answers[q.id] || ''} onChange={e => setAnswers(prev => ({ ...prev, [q.id]: e.target.value }))}
                  placeholder={q.placeholder || 'Your answer...'}
                  className="w-full text-sm border border-gray-300 rounded px-2 py-1.5" />
              )}
            </div>
          ))}
          <div className="flex gap-2 pt-2">
            <button onClick={handleSubmit}
              disabled={Object.keys(answers).length < questions.length}
              className="text-xs px-3 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">
              Submit Answers
            </button>
            <button onClick={onCreated} className="text-xs text-gray-500 hover:text-gray-700">Cancel</button>
          </div>
        </div>
      )}

      {phase === 'submitting' && (
        <div className="flex items-center gap-2 text-sm text-blue-600">
          <div className="animate-spin h-4 w-4 border-2 border-blue-400 border-t-transparent rounded-full" />
          AI is synthesizing your definition...
        </div>
      )}

      {phase === 'done' && result && (
        <div className="bg-white rounded-lg p-3 border border-green-200">
          <div className="flex items-center gap-1.5 mb-2">
            <CheckCircle size={14} className="text-green-600" />
            <span className="text-sm font-medium text-green-700">Definition created as draft!</span>
          </div>
          <p className="text-xs text-gray-700"><strong>{result.term}:</strong> {result.definition}</p>
          {result.formula && <p className="text-xs font-mono text-gray-500 mt-1">Formula: {result.formula}</p>}
          <button onClick={onCreated} className="text-xs text-genie-600 mt-2 hover:underline">Close</button>
        </div>
      )}

      {phase === 'error' && (
        <div className="text-xs text-red-600">
          {error}
          <button onClick={() => setPhase('input')} className="ml-2 underline">Try again</button>
          <button onClick={onCreated} className="ml-2 text-gray-500">Cancel</button>
        </div>
      )}
    </div>
  )
}
