import { useState, useRef, Component, type ErrorInfo, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Copy, Check, Flag, Clock, Loader2, ChevronDown, ChevronRight, Bug, AlertCircle, FileText, Database, GitBranch, BookOpen, Code, Search, BarChart3, Download } from 'lucide-react'
import { fetchJSON } from '../../api/client'
import type { Message, ActionCard } from '../../types'
import SQLCard from './SQLCard'
import DefinitionCard from './DefinitionCard'
import PipelineCard from './PipelineCard'
import ImpactCard from './ImpactCard'
import LineageCard from './LineageCard'
import TableDetailCard from './TableDetailCard'
import CodeResultCard from './CodeResultCard'

const SCHEDULE_OPTIONS = [
  { label: 'Daily 7am', cron: '0 7 * * *' },
  { label: 'Daily 9am', cron: '0 9 * * *' },
  { label: 'Weekly Monday 7am', cron: '0 7 * * 1' },
  { label: 'Custom', cron: '' },
]

interface CreateTaskOption {
  label: string
  taskType: string
  icon: React.ElementType
}

const TASK_OPTIONS: CreateTaskOption[] = [
  { label: 'Create Task', taskType: 'task', icon: FileText },
  { label: 'Request Support', taskType: 'support', icon: AlertCircle },
]

interface Props {
  message: Message
  onTableClick?: (tableName: string) => void
  onFlagResponse?: (messageContent: string) => void
  onCreateTask?: (messageContent: string, taskType: string) => void
  onSchedule?: string  // the user question text that preceded this assistant response
}

function extractSQLBlocks(content: string): string[] {
  const sqlBlockRegex = /```sql\s*\n([\s\S]*?)```/gi
  const blocks: string[] = []
  let match
  while ((match = sqlBlockRegex.exec(content)) !== null) {
    blocks.push(match[1].trim())
  }
  return blocks
}

class CardErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  constructor(props: { children: ReactNode }) {
    super(props)
    this.state = { hasError: false }
  }
  static getDerivedStateFromError() { return { hasError: true } }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.warn('Card render error:', error.message, info.componentStack?.slice(0, 200))
  }
  render() {
    if (this.state.hasError) {
      return null  // silently hide broken cards
    }
    return this.props.children
  }
}

function ActionCardRenderer({ card, onTableClick }: { card: ActionCard; onTableClick?: (name: string) => void }) {
  switch (card.type) {
    case 'sql': {
      const d = card.data as { sql?: string; columns?: string[]; rows?: unknown[][]; row_count?: number; execution_time_ms?: number; environment?: string; truncated?: boolean }
      const sql = d.sql || ''
      const queryResult = d.columns ? { columns: d.columns, rows: d.rows || [], row_count: d.row_count || 0, execution_time_ms: d.execution_time_ms || 0, environment: d.environment || 'np', truncated: d.truncated || false } : undefined
      return <SQLCard sql={sql} queryResult={queryResult} />
    }
    case 'definition':
      return <DefinitionCard data={card.data as Record<string, unknown>} />
    case 'pipeline':
      return <PipelineCard data={card.data as Record<string, unknown>} />
    case 'impact':
      return <ImpactCard data={card.data as Record<string, unknown>} />
    case 'lineage':
      return <LineageCard data={card.data as Record<string, unknown>} onTableClick={onTableClick} />
    case 'table':
      return <TableDetailCard data={card.data as Record<string, unknown>} onTableClick={onTableClick} />
    case 'code':
      return <CodeResultCard data={card.data as Record<string, unknown>} />
    default:
      return null
  }
}

const CARD_META: Record<string, { icon: React.ElementType; label: string; color: string }> = {
  sql: { icon: BarChart3, label: 'Query Results', color: 'text-blue-600 bg-blue-50' },
  table: { icon: Database, label: 'Table', color: 'text-green-600 bg-green-50' },
  definition: { icon: BookOpen, label: 'Definition', color: 'text-purple-600 bg-purple-50' },
  pipeline: { icon: GitBranch, label: 'Pipeline', color: 'text-orange-600 bg-orange-50' },
  lineage: { icon: GitBranch, label: 'Lineage', color: 'text-cyan-600 bg-cyan-50' },
  code: { icon: Code, label: 'Code', color: 'text-gray-600 bg-gray-100' },
  impact: { icon: AlertCircle, label: 'Impact', color: 'text-red-600 bg-red-50' },
}

function getCardSummary(card: ActionCard): string {
  const d = card.data as Record<string, unknown>
  switch (card.type) {
    case 'sql': return d.row_count ? `${d.row_count} rows` : d.sql ? 'SQL query' : 'Query'
    case 'table': return d.name || d.table_name ? `${d.schema || ''}.${d.name || d.table_name}` : (d.results as unknown[])?.length ? `${(d.results as unknown[]).length} tables` : 'Table'
    case 'definition': return (d.term as string) || 'Glossary'
    case 'pipeline': return (d.dag_id as string) || (d.name as string) || 'Pipeline'
    case 'lineage': return (d.table as string) || 'Lineage'
    case 'code': return d.file_count ? `${d.file_count} files` : 'Code search'
    default: return ''
  }
}

function CollapsibleCard({ card, onTableClick, defaultExpanded = false }: { card: ActionCard; onTableClick?: (name: string) => void; defaultExpanded?: boolean }) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const meta = CARD_META[card.type] || { icon: Search, label: card.type, color: 'text-gray-500 bg-gray-50' }
  const Icon = meta.icon
  const summary = getCardSummary(card)

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className={`w-full flex items-center gap-2 px-3 py-2 text-xs font-medium transition-colors ${
          expanded ? 'bg-gray-50 border-b border-gray-200' : 'hover:bg-gray-50'
        }`}
      >
        <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium ${meta.color}`}>
          <Icon size={10} />
          {meta.label}
        </span>
        <span className="text-gray-500 truncate flex-1 text-left">{summary}</span>
        {expanded ? <ChevronDown size={12} className="text-gray-400" /> : <ChevronRight size={12} className="text-gray-400" />}
      </button>
      {expanded && (
        <div className="max-h-96 overflow-auto">
          <CardErrorBoundary>
            <ActionCardRenderer card={card} onTableClick={onTableClick} />
          </CardErrorBoundary>
        </div>
      )}
    </div>
  )
}

export default function MessageBubble({ message, onTableClick, onFlagResponse, onCreateTask, onSchedule }: Props) {
  const isUser = message.role === 'user'
  const [copied, setCopied] = useState(false)
  const [showTaskMenu, setShowTaskMenu] = useState(false)
  const [showScheduleForm, setShowScheduleForm] = useState(false)
  const [scheduleTitle, setScheduleTitle] = useState('')
  const [selectedCron, setSelectedCron] = useState(SCHEDULE_OPTIONS[0].cron)
  const [customCron, setCustomCron] = useState('')
  const [scheduling, setScheduling] = useState(false)
  const [scheduleSuccess, setScheduleSuccess] = useState(false)

  const msgRef = useRef<HTMLDivElement>(null)

  function handleExportPDF() {
    if (!msgRef.current) return
    const timestamp = new Date().toLocaleString()

    // Clone the full message bubble HTML (text + charts + tables + cards)
    const clone = msgRef.current.cloneNode(true) as HTMLElement
    // Remove action buttons from export
    clone.querySelectorAll('[data-export-hide]').forEach(el => el.remove())

    const printWindow = window.open('', '_blank')
    if (!printWindow) return

    // Copy stylesheets for proper rendering
    const styles = Array.from(document.styleSheets).map(s => {
      try { return s.href ? '<link rel="stylesheet" href="' + s.href + '">' : '<style>' + Array.from(s.cssRules).map(r => r.cssText).join('') + '</style>' }
      catch { return '' }
    }).join('\n')

    const html = [
      '<html><head><title>Genie Report</title>',
      styles,
      '<style>@media print { body { margin: 20px; } .max-h-96, .max-h-\\[500px\\] { max-height: none !important; overflow: visible !important; } }</style>',
      '</head><body>',
      '<div style="max-width:800px;margin:0 auto;padding:20px">',
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:16px">',
      '<img src="/logo.png" style="height:24px;width:24px;border-radius:4px">',
      '<strong style="color:#16a34a">Jennie</strong>',
      '<span style="color:#9ca3af;font-size:12px;margin-left:auto">' + timestamp + '</span>',
      '</div>',
      clone.innerHTML,
      '</div></body></html>',
    ].join('\n')

    printWindow.document.write(html)
    printWindow.document.close()
    setTimeout(() => { printWindow.print() }, 800)
  }

  function handleCopy() {
    navigator.clipboard.writeText(message.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  const sqlBlocks = !isUser ? extractSQLBlocks(message.content) : []

  // Deduplicate: if an action card already covers a SQL block, don't auto-create one
  const existingSqlCards = (message.actionCards || []).filter((c) => c.type === 'sql')
  const existingSqlStrings = new Set(existingSqlCards.map((c) => {
    const d = c.data as { sql?: string }
    return d.sql
  }))

  const autoSqlCards: ActionCard[] = sqlBlocks
    .filter((sql) => !existingSqlStrings.has(sql))
    .map((sql) => ({ type: 'sql' as const, data: { sql } }))

  const allCards = [...(message.actionCards || []), ...autoSqlCards]

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} max-w-4xl mx-auto`}>
      <div
        ref={isUser ? undefined : msgRef}
        className={`max-w-[80%] rounded-lg px-4 py-3 text-sm ${
          isUser ? 'bg-genie-600 text-white' : 'bg-gray-50 text-gray-900 border border-gray-200'
        }`}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <>
            <div className="prose prose-sm max-w-none prose-pre:bg-gray-900 prose-pre:text-gray-100 prose-pre:rounded-md prose-pre:p-3 prose-code:text-pink-600 prose-code:before:content-none prose-code:after:content-none">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  pre({ children }) {
                    return (
                      <div className="relative group">
                        <pre className="overflow-x-auto">{children}</pre>
                        <button
                          onClick={() => {
                            const code = (children as any)?.props?.children
                            if (code) navigator.clipboard.writeText(code)
                          }}
                          className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 bg-gray-700 text-gray-200 text-xs px-2 py-1 rounded transition-opacity"
                        >
                          Copy
                        </button>
                      </div>
                    )
                  },
                }}
              >
                {message.content}
              </ReactMarkdown>
            </div>

            {/* Query result cards FIRST (chart is the answer), then other cards */}
            {allCards.length > 0 && (() => {
              const sqlCards = allCards.filter(c => c.type === 'sql' && (c.data as Record<string, unknown>)?.columns)
              const otherCards = allCards.filter(c => c.type !== 'sql' || !(c.data as Record<string, unknown>)?.columns)
              return (
                <div className="mt-2 space-y-1">
                  {sqlCards.map((card, i) => (
                    <div key={`sql-${i}`} className="border border-gray-200 rounded-lg overflow-hidden">
                      <div className="max-h-[500px] overflow-auto">
                        <CardErrorBoundary>
                          <ActionCardRenderer card={card} onTableClick={onTableClick} />
                        </CardErrorBoundary>
                      </div>
                    </div>
                  ))}
                  {otherCards.map((card, i) => (
                    <CollapsibleCard key={`other-${i}`} card={card} onTableClick={onTableClick} />
                  ))}
                </div>
              )
            })()}

            {/* Action buttons */}
            {message.content && (
              <div data-export-hide className="flex items-center gap-1 mt-2 pt-1.5 border-t border-gray-100">
                <button onClick={handleCopy}
                  className="text-gray-400 hover:text-gray-600 p-1 rounded hover:bg-gray-100 transition-colors"
                  title="Copy response">
                  {copied ? <Check size={13} className="text-green-500" /> : <Copy size={13} />}
                </button>
                <button onClick={handleExportPDF}
                  className="text-gray-400 hover:text-gray-600 p-1 rounded hover:bg-gray-100 transition-colors"
                  title="Export as PDF">
                  <Download size={13} />
                </button>
                {(onCreateTask || onFlagResponse) && (
                  <div className="relative">
                    <button
                      onClick={() => setShowTaskMenu(!showTaskMenu)}
                      className="text-gray-400 hover:text-genie-600 p-1 rounded hover:bg-genie-50 transition-colors flex items-center gap-0.5"
                      title="Create task from this response"
                    >
                      <Flag size={13} />
                      <ChevronDown size={9} />
                    </button>
                    {showTaskMenu && (
                      <div className="absolute bottom-full left-0 mb-1 bg-white border border-gray-200 rounded-lg shadow-lg py-1 z-10 min-w-[180px]">
                        {TASK_OPTIONS.map(opt => (
                          <button
                            key={opt.taskType}
                            onClick={() => {
                              setShowTaskMenu(false)
                              if (onCreateTask) {
                                onCreateTask(message.content, opt.taskType)
                              } else if (onFlagResponse) {
                                onFlagResponse(message.content)
                              }
                            }}
                            className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50 transition-colors"
                          >
                            <opt.icon size={12} className="text-gray-400" />
                            {opt.label}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                {onSchedule && (
                  <button
                    onClick={() => {
                      if (!showScheduleForm) {
                        setScheduleTitle(onSchedule.slice(0, 50))
                        setScheduleSuccess(false)
                      }
                      setShowScheduleForm(prev => !prev)
                    }}
                    className="text-gray-400 hover:text-blue-500 p-1 rounded hover:bg-blue-50 transition-colors"
                    title="Schedule this as a recurring report"
                  >
                    <Clock size={13} />
                  </button>
                )}
              </div>
            )}

            {/* Schedule inline form */}
            {showScheduleForm && onSchedule && (
              <div className="mt-2 p-3 bg-blue-50 border border-blue-200 rounded-lg space-y-2">
                {scheduleSuccess ? (
                  <p className="text-sm text-green-700 font-medium">
                    Scheduled! You'll get a notification when it runs.
                  </p>
                ) : (
                  <>
                    <div>
                      <label className="text-xs font-medium text-gray-600 block mb-0.5">Report title</label>
                      <input
                        value={scheduleTitle}
                        onChange={e => setScheduleTitle(e.target.value)}
                        className="w-full text-xs border border-gray-300 rounded px-2 py-1.5 bg-white"
                        placeholder="Report title"
                      />
                    </div>
                    <div>
                      <label className="text-xs font-medium text-gray-600 block mb-0.5">Schedule</label>
                      <select
                        value={selectedCron}
                        onChange={e => setSelectedCron(e.target.value)}
                        className="w-full text-xs border border-gray-300 rounded px-2 py-1.5 bg-white"
                      >
                        {SCHEDULE_OPTIONS.map(opt => (
                          <option key={opt.label} value={opt.cron}>{opt.label}</option>
                        ))}
                      </select>
                    </div>
                    {selectedCron === '' && (
                      <div>
                        <label className="text-xs font-medium text-gray-600 block mb-0.5">Custom cron expression</label>
                        <input
                          value={customCron}
                          onChange={e => setCustomCron(e.target.value)}
                          className="w-full text-xs border border-gray-300 rounded px-2 py-1.5 bg-white font-mono"
                          placeholder="0 7 * * *"
                        />
                      </div>
                    )}
                    <button
                      onClick={async () => {
                        setScheduling(true)
                        try {
                          const cron = selectedCron || customCron
                          await fetchJSON('/scheduled-reports', {
                            method: 'POST',
                            body: JSON.stringify({
                              title: scheduleTitle,
                              chat_question: onSchedule,
                              cron_expression: cron,
                            }),
                          })
                          setScheduleSuccess(true)
                        } catch (err) {
                          alert('Failed to schedule: ' + (err instanceof Error ? err.message : 'Unknown error'))
                        } finally {
                          setScheduling(false)
                        }
                      }}
                      disabled={scheduling || (!selectedCron && !customCron.trim()) || !scheduleTitle.trim()}
                      className="flex items-center gap-1.5 text-xs font-medium bg-genie-600 text-white px-3 py-1.5 rounded hover:bg-genie-700 disabled:opacity-50 transition-colors"
                    >
                      {scheduling ? <Loader2 size={12} className="animate-spin" /> : <Clock size={12} />}
                      Schedule Report
                    </button>
                  </>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
