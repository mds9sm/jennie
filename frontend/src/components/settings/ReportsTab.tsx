import { useState, useEffect } from 'react'
import { Loader2, Play, Trash2, Eye, EyeOff, Clock, Edit3, Save, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { fetchJSON } from '../../api/client'

interface ScheduledReport {
  id: number
  title: string
  chat_question: string
  context: string
  cron_expression: string
  enabled: boolean
  last_run_at: string | null
  last_status: string | null
  last_output: string | null
  created_at: string
}

function cronToHuman(cron: string): string {
  const parts = cron.split(' ')
  if (parts.length !== 5) return cron

  const [min, hour, , , dow] = parts

  const timeStr = `${hour.padStart(2, '0')}:${min.padStart(2, '0')}`

  if (dow === '*' || dow === '?') {
    return `Daily at ${timeStr}`
  }
  const days: Record<string, string> = {
    '0': 'Sunday', '1': 'Monday', '2': 'Tuesday', '3': 'Wednesday',
    '4': 'Thursday', '5': 'Friday', '6': 'Saturday', '7': 'Sunday',
  }
  const dayName = days[dow] || dow
  return `Every ${dayName} at ${timeStr}`
}

export default function ReportsTab() {
  const [reports, setReports] = useState<ScheduledReport[]>([])
  const [loading, setLoading] = useState(true)
  const [viewingOutput, setViewingOutput] = useState<number | null>(null)
  const [runningId, setRunningId] = useState<number | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [expandedOutput, setExpandedOutput] = useState<string>('')
  const [editTitle, setEditTitle] = useState('')
  const [editQuestion, setEditQuestion] = useState('')
  const [editContext, setEditContext] = useState('')
  const [editCron, setEditCron] = useState('')

  useEffect(() => {
    loadReports()
  }, [])

  async function loadReports() {
    setLoading(true)
    try {
      const data = await fetchJSON<ScheduledReport[]>('/scheduled-reports')
      setReports(data)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  async function handleToggle(report: ScheduledReport) {
    try {
      await fetchJSON(`/scheduled-reports/${report.id}`, {
        method: 'PUT',
        body: JSON.stringify({ enabled: !report.enabled }),
      })
      setReports(prev =>
        prev.map(r => r.id === report.id ? { ...r, enabled: !r.enabled } : r)
      )
    } catch { /* ignore */ }
  }

  async function handleRunNow(id: number) {
    setRunningId(id)
    try {
      await fetchJSON(`/scheduled-reports/${id}/run-now`, { method: 'POST' })
      // Reload to get updated last_run_at / last_status
      await loadReports()
    } catch (err) {
      alert('Failed to run: ' + (err instanceof Error ? err.message : 'Unknown error'))
    } finally {
      setRunningId(null)
    }
  }

  async function handleDelete(id: number) {
    if (!window.confirm('Delete this scheduled report?')) return
    try {
      await fetchJSON(`/scheduled-reports/${id}`, { method: 'DELETE' })
      setReports(prev => prev.filter(r => r.id !== id))
      if (viewingOutput === id) setViewingOutput(null)
    } catch { /* ignore */ }
  }

  async function handleSaveEdit(id: number) {
    try {
      await fetchJSON(`/scheduled-reports/${id}`, {
        method: 'PUT',
        body: JSON.stringify({ title: editTitle, chat_question: editQuestion, context: editContext, cron_expression: editCron }),
      })
      setEditingId(null)
      await loadReports()
    } catch { /* ignore */ }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 size={24} className="animate-spin text-gray-400" />
      </div>
    )
  }

  return (
    <div className="h-full overflow-auto px-6 py-5">
      <div className="max-w-4xl space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-gray-900 mb-1">Scheduled Reports</h2>
        <p className="text-sm text-gray-500">
          Reports that run on a schedule and deliver results as notifications.
          Schedule any chat question using the clock icon on assistant responses.
        </p>
      </div>

      {reports.length === 0 ? (
        <div className="text-center py-12 text-gray-400">
          <Clock size={32} className="mx-auto mb-2 opacity-50" />
          <p className="text-sm">No scheduled reports yet.</p>
          <p className="text-xs mt-1">Use the clock icon on any assistant response to schedule it.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {reports.map(report => (
            <div key={report.id} className="border border-gray-200 rounded-lg bg-white">
              <div className="px-4 py-3 flex items-start gap-3">
                {/* Enable toggle */}
                <button
                  onClick={() => handleToggle(report)}
                  className={`mt-1 relative inline-flex h-5 w-9 flex-shrink-0 rounded-full transition-colors ${
                    report.enabled ? 'bg-genie-600' : 'bg-gray-300'
                  }`}
                  title={report.enabled ? 'Disable' : 'Enable'}
                >
                  <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform mt-0.5 ${
                    report.enabled ? 'translate-x-4.5 ml-0.5' : 'translate-x-0.5'
                  }`} />
                </button>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  {editingId === report.id ? (
                    <div className="space-y-2">
                      <div>
                        <label className="text-[10px] text-gray-500 block mb-0.5">Title</label>
                        <input value={editTitle} onChange={e => setEditTitle(e.target.value)}
                          className="w-full text-sm border border-gray-300 rounded px-2 py-1.5 font-medium" placeholder="Report title" />
                      </div>
                      <div>
                        <label className="text-[10px] text-gray-500 block mb-0.5">Question (what the AI will answer each run)</label>
                        <textarea value={editQuestion} onChange={e => setEditQuestion(e.target.value)} rows={2}
                          className="w-full text-xs border border-gray-300 rounded px-2 py-1.5 font-mono" placeholder="e.g. Show me pipeline failures from last night" />
                      </div>
                      <div>
                        <label className="text-[10px] text-gray-500 block mb-0.5">Additional context (optional — instructions for the AI)</label>
                        <textarea value={editContext} onChange={e => setEditContext(e.target.value)} rows={2}
                          className="w-full text-xs border border-gray-300 rounded px-2 py-1.5" placeholder="e.g. Focus on onboarding pillar. Include row counts. Flag anything running > 30 min." />
                      </div>
                      <div>
                        <label className="text-[10px] text-gray-500 block mb-0.5">Schedule</label>
                      <select value={editCron} onChange={e => setEditCron(e.target.value)}
                        className="text-xs border border-gray-300 rounded px-2 py-1.5 bg-white">
                        <option value="0 7 * * *">Daily 7am</option>
                        <option value="0 9 * * *">Daily 9am</option>
                        <option value="0 7 * * 1">Weekly Monday 7am</option>
                      </select>
                      </div>
                      <div className="flex gap-1">
                        <button onClick={() => handleSaveEdit(report.id)}
                          className="text-xs px-2 py-1 bg-genie-600 text-white rounded hover:bg-genie-700 flex items-center gap-1">
                          <Save size={11} /> Save
                        </button>
                        <button onClick={() => setEditingId(null)}
                          className="text-xs px-2 py-1 text-gray-500 hover:text-gray-700 flex items-center gap-1">
                          <X size={11} /> Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="flex items-center gap-2">
                        <h4 className={`text-sm font-medium truncate ${report.enabled ? 'text-gray-900' : 'text-gray-400'}`}>
                          {report.title}
                        </h4>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded-full flex-shrink-0 ${
                          report.enabled ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                        }`}>
                          {report.enabled ? 'Active' : 'Paused'}
                        </span>
                      </div>
                      <p className="text-xs text-gray-500 mt-0.5 truncate" title={report.chat_question}>
                        {report.chat_question}
                      </p>
                      {report.context && (
                        <p className="text-[11px] text-gray-400 mt-0.5 italic truncate" title={report.context}>
                          Context: {report.context}
                        </p>
                      )}
                    </>
                  )}
                  <div className="flex items-center gap-3 mt-1 text-[11px] text-gray-400">
                    {editingId !== report.id && <span>{cronToHuman(report.cron_expression)}</span>}
                    {report.last_run_at && (
                      <>
                        <span>Last run: {new Date(report.last_run_at).toLocaleString()}</span>
                        <button
                          onClick={async () => {
                            if (expandedId === report.id) {
                              setExpandedId(null)
                            } else {
                              try {
                                const res = await fetchJSON<{ last_output: string }>(`/scheduled-reports/${report.id}/output`)
                                setExpandedOutput(res.last_output || '(no output)')
                              } catch { setExpandedOutput('(could not load output)') }
                              setExpandedId(report.id)
                            }
                          }}
                          className={`font-medium underline cursor-pointer ${
                            report.last_status === 'success' ? 'text-green-600 hover:text-green-700' :
                            report.last_status === 'error' ? 'text-red-500 hover:text-red-600' : 'text-gray-400'
                          }`}
                        >
                          {report.last_status} {expandedId === report.id ? '▲' : '▼'}
                        </button>
                      </>
                    )}
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-1 flex-shrink-0">
                  {editingId !== report.id && (
                    <button
                      onClick={() => { setEditingId(report.id); setEditTitle(report.title); setEditQuestion(report.chat_question); setEditContext(report.context || ''); setEditCron(report.cron_expression) }}
                      className="text-gray-400 hover:text-gray-600 p-1.5 rounded hover:bg-gray-100 transition-colors"
                      title="Edit"
                    >
                      <Edit3 size={14} />
                    </button>
                  )}
                  <button
                    onClick={() => handleRunNow(report.id)}
                    disabled={runningId === report.id}
                    className="text-gray-400 hover:text-genie-600 p-1.5 rounded hover:bg-gray-100 transition-colors disabled:opacity-50"
                    title="Run now"
                  >
                    {runningId === report.id ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                  </button>
                  {report.last_output && (
                    <button
                      onClick={() => setViewingOutput(viewingOutput === report.id ? null : report.id)}
                      className="text-gray-400 hover:text-blue-500 p-1.5 rounded hover:bg-blue-50 transition-colors"
                      title="View output"
                    >
                      {viewingOutput === report.id ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                  )}
                  <button
                    onClick={() => handleDelete(report.id)}
                    className="text-gray-400 hover:text-red-500 p-1.5 rounded hover:bg-red-50 transition-colors"
                    title="Delete report"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>

              {/* Expandable output panel */}
              {expandedId === report.id && (
                <div className="border-t border-gray-100 px-4 py-3 bg-gray-50">
                  <div className="text-xs font-medium text-gray-500 mb-2">
                    {report.last_status === 'error' ? 'Error Details' : 'Last Output'}
                  </div>
                  <div className={`text-sm rounded p-3 max-h-80 overflow-auto ${
                    report.last_status === 'error'
                      ? 'bg-red-50 border border-red-200 text-red-700 font-mono text-xs'
                      : 'bg-white border border-gray-200 prose prose-sm max-w-none'
                  }`}>
                    {report.last_status === 'error' ? (
                      <pre className="whitespace-pre-wrap">{expandedOutput}</pre>
                    ) : (
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {expandedOutput}
                      </ReactMarkdown>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      </div>
    </div>
  )
}
