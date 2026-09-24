import { useState, useRef, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Send, Loader2, PlusCircle, Share2, Check, Paperclip, X, FileText } from 'lucide-react'
import GenieThinking, { type ThinkingStep } from './GenieThinking'
import { streamChat, saveSession, getSession, getSharedSession, fetchJSON, extractChatFile } from '../../api/client'
import type { ChatAttachmentInput } from '../../api/client'
import { usePillar } from '../../context/PillarContext'
import { useEnvironment } from '../../context/EnvironmentContext'
import MessageBubble from './MessageBubble'
import type { Message, ActionCard } from '../../types'

const STARTER_QUESTIONS = [
  {
    label: 'Show me daily cutting users by platform this week',
    icon: '\u2702\uFE0F',
    description: 'Cut metrics from DOMO aggregates or Redshift',
  },
  {
    label: 'How is engagement depth calculated?',
    icon: '\u{1F4CA}',
    description: 'Metric definition + DOMO dashboard + source tables',
  },
  {
    label: 'What experiments are running on the onboarding funnel?',
    icon: '\u{1F9EA}',
    description: 'Statsig experiments + exposure data',
  },
  {
    label: 'Show me subscription churn rate trend for last 30 days',
    icon: '\u{1F4C9}',
    description: 'Subscription metrics from DOMO or Redshift',
  },
  {
    label: 'What tables and pipelines feed the Exec Dashboard in DOMO?',
    icon: '\u{1F517}',
    description: 'Lineage + DOMO dashboards + refresh status',
  },
  {
    label: 'Compare activation rate definition across pillars',
    icon: '\u{1F4D6}',
    description: 'Cross-pillar glossary with view SQL logic',
  },
  {
    label: 'What events does ProductApp fire for image search?',
    icon: '\u{1F50D}',
    description: 'Swagger event schemas + payload fields',
  },
  {
    label: 'Is CutSessionsMasterDAG healthy? Any recent failures?',
    icon: '\u{1F6E0}\uFE0F',
    description: 'Pipeline status + MWAA run history',
  },
  {
    label: 'What breaks if we change the user_profile table schema?',
    icon: '\u26A0\uFE0F',
    description: 'Impact analysis across downstream tables + DOMO',
  },
]

function toolToCardType(toolName: string): ActionCard['type'] | null {
  switch (toolName) {
    case 'glossary_lookup':
    case 'get_view_detail':
      return 'definition'
    case 'execute_query':
      return 'sql'
    case 'search_tables':
    case 'get_table_detail':
      return 'table'
    case 'get_table_lineage':
      return 'lineage'
    case 'get_transform_detail':
    case 'search_transforms':
      return 'pipeline'
    case 'repo_search':
      return 'code'
    default:
      return null
  }
}

function generateId(): string {
  return crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)
}

export default function ChatView() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [chatSessionId, setChatSessionId] = useState<string>(() => generateId())
  const [contextInfo, setContextInfo] = useState<{ total_messages: number; sent_messages: number; summarized: boolean } | null>(null)
  const [lastUsage, setLastUsage] = useState<{ input_tokens: number; output_tokens: number; elapsed_seconds: number } | null>(null)
  const [thinkingSteps, setThinkingSteps] = useState<ThinkingStep[]>([])
  const [isSharedView, setIsSharedView] = useState(false)
  const [sharedOwner, setSharedOwner] = useState<{ name: string; email: string } | null>(null)
  const [shareCopied, setShareCopied] = useState(false)
  const [attachments, setAttachments] = useState<ChatAttachmentInput[]>([])
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const { pillar } = usePillar()
  const { environment } = useEnvironment()
  const [searchParams, setSearchParams] = useSearchParams()

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // No blocking warning — chat continues in background and notifies when done

  // Load session from URL param (?session= or ?shared=)
  useEffect(() => {
    const sharedId = searchParams.get('shared')
    if (sharedId) {
      setIsSharedView(true)
      setChatSessionId(sharedId)
      getSharedSession(sharedId)
        .then(data => {
          if (data.messages && !('error' in data)) {
            setMessages(data.messages as Message[])
            setSharedOwner({ name: data.owner_name, email: data.owner_email })
          }
        })
        .catch(() => {})
      return
    }

    const sid = searchParams.get('session')
    if (sid && sid !== chatSessionId) {
      setIsSharedView(false)
      setSharedOwner(null)
      setChatSessionId(sid)
      getSession(sid)
        .then(data => {
          if (data.messages && !('error' in data)) {
            setMessages(data.messages as Message[])
          }
        })
        .catch(() => {})
    }

    // Handle ?q= param (from Workbench optimize, etc.) — auto-send
    const question = searchParams.get('q')
    if (question && messages.length === 0) {
      setSearchParams({})  // clear q param
      setTimeout(() => handleSend(decodeURIComponent(question)), 500)
      return
    }

    // Landed on / with no session — that's "New chat" from the sidebar.
    // Start a fresh conversation instead of keeping the previous one on screen.
    if (!sid && !question && messages.length > 0 && !isStreaming) {
      setChatSessionId(generateId())
      setMessages([])
      setContextInfo(null)
      setLastUsage(null)
      setIsSharedView(false)
      setSharedOwner(null)
    }
  }, [searchParams])

  // Persist session after each assistant reply
  const persistSession = useCallback(
    (msgs: Message[]) => {
      if (msgs.length === 0) return
      const plain = msgs.map(m => ({
        role: m.role,
        content: m.content,
        ...(m.actionCards && m.actionCards.length > 0 ? { actionCards: m.actionCards } : {}),
      }))
      saveSession(chatSessionId, plain, pillar).catch(() => {})
    },
    [chatSessionId, pillar],
  )

  async function handleFlagResponse(responseContent: string) {
    // Legacy handler — delegates to handleCreateTask with ai_quality type
    await handleCreateTask(responseContent, 'ai_quality')
  }

  async function handleCreateTask(responseContent: string, taskType: string) {
    const typeLabels: Record<string, string> = {
      task: 'What are you tracking?',
      support: 'What do you need help with?',
    }
    const title = window.prompt(typeLabels[taskType] || 'Task title:')
    if (!title) return
    try {
      const res = await fetchJSON<{ id: number; assigned_to: string }>('/feedback/from-chat', {
        method: 'POST',
        body: JSON.stringify({
          title,
          description: `From chat response:\n${responseContent.slice(0, 500)}`,
          task_type: taskType,
          chat_session_id: chatSessionId,
        }),
      })
      alert(`Task #${res.id} created and assigned to ${res.assigned_to || 'admin'}. View it in Tasks.`)
    } catch (err) {
      alert('Failed to create task: ' + (err instanceof Error ? err.message : 'Unknown error'))
    }
  }

  function handleNewChat() {
    const newId = generateId()
    setChatSessionId(newId)
    setMessages([])
    setInput('')
    setContextInfo(null)
    setLastUsage(null)
    setIsSharedView(false)
    setSharedOwner(null)
    setSearchParams({})
  }

  async function handleFileAttach(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files
    if (!files || files.length === 0) return
    setUploading(true)
    try {
      for (const file of Array.from(files)) {
        const isImage = file.type.startsWith('image/')

        if (isImage) {
          // Images: read as base64 for multimodal AI
          const reader = new FileReader()
          const base64 = await new Promise<string>((resolve) => {
            reader.onload = () => resolve((reader.result as string).split(',')[1] || '')
            reader.readAsDataURL(file)
          })
          setAttachments(prev => [...prev, {
            filename: file.name,
            content: `[image:${file.type}:${base64.slice(0, 50)}...]`,
            size: file.size,
            isImage: true,
            mediaType: file.type,
            base64,
          }])
        } else {
          // Documents: extract text server-side
          const data = await extractChatFile(file)
          setAttachments(prev => [...prev, {
            filename: data.filename,
            content: data.content,
            size: data.size,
          }])
        }
      }
    } catch { /* ignore */ }
    finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  function removeAttachment(idx: number) {
    setAttachments(prev => prev.filter((_, i) => i !== idx))
  }

  function handleShareChat() {
    const shareUrl = `${window.location.origin}/?shared=${chatSessionId}`
    navigator.clipboard.writeText(shareUrl).then(() => {
      setShareCopied(true)
      setTimeout(() => setShareCopied(false), 2000)
    }).catch(() => {
      // Fallback for non-HTTPS
      window.prompt('Copy this link:', shareUrl)
    })
  }

  function handleTableClick(tableName: string) {
    setInput(`Tell me about the table ${tableName}`)
  }

  async function handleSend(overrideInput?: string) {
    const msg = overrideInput ?? input
    if ((!msg.trim() && attachments.length === 0) || isStreaming) return

    const userMessage: Message = { role: 'user', content: msg }
    const updatedMessages = [...messages, userMessage]
    setMessages(updatedMessages)
    setInput('')
    setIsStreaming(true)
    setAttachments([])
    setThinkingSteps([{ id: 'init', label: 'Analyzing your question', status: 'running', timestamp: Date.now() }])

    // Update URL to include session id
    if (!searchParams.get('session')) {
      setSearchParams({ session: chatSessionId })
    }

    const history = messages.map((m) => ({ role: m.role, content: m.content }))
    let assistantContent = ''
    const collectedCards: ActionCard[] = []

    try {
      const assistantMsg: Message = { role: 'assistant', content: '', actionCards: [] }
      setMessages((prev) => [...prev, assistantMsg])

      for await (const event of streamChat(msg, history, pillar, environment, attachments, chatSessionId)) {
        if (event.event === 'context') {
          setContextInfo(event.data as { total_messages: number; sent_messages: number; summarized: boolean })
        } else if (event.event === 'status') {
          const data = event.data as { content: string }
          const stepId = `status-${Date.now()}`
          setThinkingSteps(prev => {
            // Mark all running steps as done, add new status step
            const updated = prev.map(s => s.status === 'running' ? { ...s, status: 'done' as const } : s)
            return [...updated, { id: stepId, label: data.content, status: 'running', timestamp: Date.now() }]
          })
        } else if (event.event === 'tool_call') {
          const data = event.data as { tool: string; input?: Record<string, unknown> }
          const toolLabels: Record<string, string> = {
            'ask_data_expert': 'Consulting Data Expert',
            'ask_redshift_expert': 'Consulting Redshift Expert',
            'ask_knowledge_expert': 'Consulting Knowledge Expert',
            'execute_query': 'Running SQL query',
            'aws_lookup': 'Checking AWS',
            'github_file': 'Reading file',
            'search_transforms': 'Searching pipelines',
            'get_transform_detail': 'Loading pipeline details',
            'get_table_lineage': 'Tracing lineage',
            'get_view_detail': 'Loading view definition',
            'glossary_lookup': 'Looking up glossary',
            'search_tables': 'Searching tables',
            'repo_search': 'Searching code',
          }
          // Extract a human-readable detail from tool input
          const input = data.input || {}
          let detail = ''
          if (input.keyword) detail = String(input.keyword)
          else if (input.term) detail = String(input.term)
          else if (input.table_name) detail = String(input.table_name)
          else if (input.dag_id) detail = String(input.dag_id)
          else if (input.view_name) detail = String(input.view_name)
          else if (input.sql) detail = String(input.sql).slice(0, 60).replace(/\n/g, ' ')
          else if (input.pattern) detail = String(input.pattern)
          else if (input.question) detail = String(input.question).slice(0, 50)
          else if (input.service) detail = String(input.service)

          const stepId = `tool-${data.tool}-${Date.now()}`
          setThinkingSteps(prev => {
            // Mark previous running steps as done
            const updated = prev.map(s => s.status === 'running' ? { ...s, status: 'done' as const } : s)
            return [...updated, {
              id: stepId,
              label: toolLabels[data.tool] || `Using ${data.tool}`,
              detail: detail || undefined,
              tool: data.tool,
              status: 'running',
              timestamp: Date.now(),
            }]
          })
        } else if (event.event === 'text') {
          // Mark all steps as done when text starts streaming (but keep visible)
          setThinkingSteps(prev => prev.map(s => s.status === 'running' ? { ...s, status: 'done' as const } : s))
          const data = event.data as { content: string }
          assistantContent += data.content
          setMessages((prev) => {
            const updated = [...prev]
            updated[updated.length - 1] = {
              ...updated[updated.length - 1],
              content: assistantContent,
              actionCards: [...collectedCards],
            }
            return updated
          })
        } else if (event.event === 'tool_result') {
          const data = event.data as { tool: string; result: unknown }
          const cardType = toolToCardType(data.tool)
          if (cardType && data.result) {
            const res = data.result as Record<string, unknown>

            // Skip empty or error results — don't show broken/useless cards
            if (res.error) continue
            if (res.count === 0 || (Array.isArray(res.results) && res.results.length === 0)) continue
            if (cardType === 'sql' && !res.columns) continue
            if (cardType === 'table' && !res.results && !res.name && !res.columns) continue

            let cardData = data.result

            if (cardType === 'sql') {
              if (res.columns) {
                cardData = { ...res }
              }
            }

            if (cardType === 'sql') {
              // Keep only the latest SQL result — replace previous query cards
              const idx = collectedCards.findIndex(c => c.type === 'sql')
              if (idx >= 0) {
                collectedCards[idx] = { type: cardType, data: cardData }
              } else {
                collectedCards.push({ type: cardType, data: cardData })
              }
            } else {
              collectedCards.push({ type: cardType, data: cardData })
            }
            setMessages((prev) => {
              const updated = [...prev]
              updated[updated.length - 1] = {
                ...updated[updated.length - 1],
                content: assistantContent,
                actionCards: [...collectedCards],
              }
              return updated
            })
          }
        } else if (event.event === 'done') {
          const data = event.data as { input_tokens: number; output_tokens: number; elapsed_seconds: number }
          setLastUsage(data)
        }
      }

      // Final update
      const finalMessages = [...updatedMessages, { role: 'assistant' as const, content: assistantContent, actionCards: [...collectedCards] }]
      setMessages(finalMessages)

      // Persist to backend
      persistSession(finalMessages)
    } catch (err) {
      const partialContent = assistantContent || ''
      // With background processing, the response is likely still being generated
      const continueNote = partialContent
        ? `${partialContent}\n\n---\n*The response is still being prepared in the background. You'll be notified when it's ready, or check back in a moment.*`
        : `*Genie is working on your request in the background. You'll receive a notification when the response is ready.*`
      setMessages((prev) => {
        const updated = [...prev]
        updated[updated.length - 1] = {
          role: 'assistant',
          content: continueNote,
        }
        return updated
      })
    } finally {
      setIsStreaming(false)
      setThinkingSteps([])
    }
  }

  return (
    <div className="h-full flex flex-col">
      {/* Shared session banner */}
      {isSharedView && sharedOwner && (
        <div className="bg-blue-50 border-b border-blue-200 px-4 py-2 flex items-center gap-2 text-sm text-blue-700">
          <Share2 size={14} />
          <span>Shared by <strong>{sharedOwner.name || sharedOwner.email}</strong></span>
          <span className="text-blue-400 mx-1">&#183;</span>
          <span className="text-blue-500">Read-only view</span>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-gray-400">
            <img src="/logo.png" alt="Genie" className="h-16 w-16 rounded-lg mb-2" />
            <h2 className="text-xl font-semibold text-gray-600 mb-2">Jennie</h2>
            <p className="text-sm max-w-md text-center mb-8">
              Ask me about your data platform — tables, metrics, pipelines, or business definitions.
              I can also generate SQL, build pipeline configs, and analyze impact.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 max-w-3xl w-full">
              {STARTER_QUESTIONS.map((q) => (
                <button
                  key={q.label}
                  onClick={() => handleSend(q.label)}
                  className="text-left px-4 py-3 border border-gray-200 rounded-lg hover:bg-gray-50 hover:border-genie-300 transition-colors group"
                >
                  <div className="flex items-start gap-2.5">
                    <span className="text-lg mt-0.5">{q.icon}</span>
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-gray-700 group-hover:text-genie-700 transition-colors leading-snug">
                        {q.label}
                      </div>
                      <div className="text-[11px] text-gray-400 mt-1 leading-tight">
                        {q.description}
                      </div>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => {
          // Find the preceding user message for schedule context
          let userQuestion: string | undefined
          if (msg.role === 'assistant') {
            for (let j = i - 1; j >= 0; j--) {
              if (messages[j].role === 'user') {
                userQuestion = messages[j].content
                break
              }
            }
          }
          return (
            <MessageBubble key={i} message={msg} onTableClick={handleTableClick}
              onFlagResponse={msg.role === 'assistant' ? handleFlagResponse : undefined}
              onCreateTask={msg.role === 'assistant' ? handleCreateTask : undefined}
              onSchedule={userQuestion} />
          )
        })}
        {thinkingSteps.length > 0 && <GenieThinking steps={thinkingSteps} />}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="border-t border-gray-200 p-4">
        {/* Context indicator */}
        {messages.length > 0 && (
          <div className="flex justify-center gap-3 mb-2">
            <span className={`text-[10px] px-2 py-0.5 rounded-full ${
              contextInfo?.summarized
                ? 'bg-amber-50 text-amber-600'
                : 'bg-gray-50 text-gray-400'
            }`}>
              {contextInfo?.summarized
                ? `${contextInfo.total_messages} messages (${contextInfo.total_messages - contextInfo.sent_messages + 2} summarized)`
                : `${messages.length} messages in context`}
            </span>
            {lastUsage && (
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-gray-50 text-gray-400">
                {lastUsage.input_tokens.toLocaleString()} in · {lastUsage.output_tokens.toLocaleString()} out · {lastUsage.elapsed_seconds}s
                {' · ~$' + ((lastUsage.input_tokens * 0.003 + lastUsage.output_tokens * 0.015) / 1000).toFixed(3)}
              </span>
            )}
          </div>
        )}
        {/* Attachment chips */}
        {attachments.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-2 max-w-4xl mx-auto">
            {attachments.map((att, i) => (
              <span key={i} className="inline-flex items-center gap-1.5 bg-genie-50 text-genie-700 text-xs font-medium px-2.5 py-1 rounded-full border border-genie-200">
                {att.isImage ? (
                  <img src={`data:${att.mediaType};base64,${att.base64}`}
                    className="h-5 w-5 rounded object-cover" alt="" />
                ) : (
                  <FileText size={12} />
                )}
                {att.filename}
                <span className="text-[10px] text-genie-400">({(att.size / 1024).toFixed(0)}KB)</span>
                <button onClick={() => removeAttachment(i)} className="text-genie-400 hover:text-red-500 ml-0.5">
                  <X size={12} />
                </button>
              </span>
            ))}
          </div>
        )}

        <div className="flex gap-2 max-w-4xl mx-auto">
          <button
            onClick={handleNewChat}
            className="p-2.5 text-gray-400 hover:text-genie-600 rounded-lg hover:bg-gray-100 transition-colors"
            title="New chat"
          >
            <PlusCircle size={20} />
          </button>
          {messages.length > 0 && !isSharedView && (
            <button
              onClick={handleShareChat}
              className={`p-2.5 rounded-lg transition-colors ${
                shareCopied
                  ? 'text-green-600 bg-green-50'
                  : 'text-gray-400 hover:text-genie-600 hover:bg-gray-100'
              }`}
              title={shareCopied ? 'Link copied!' : 'Share chat'}
            >
              {shareCopied ? <Check size={20} /> : <Share2 size={20} />}
            </button>
          )}
          {/* Attach file button */}
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isStreaming || isSharedView || uploading}
            className="p-2.5 text-gray-400 hover:text-genie-600 rounded-lg hover:bg-gray-100 transition-colors disabled:opacity-50"
            title="Attach file (.pdf, .docx, .md, .txt, .csv, .yaml)"
          >
            {uploading ? <Loader2 size={20} className="animate-spin" /> : <Paperclip size={20} />}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".pdf,.docx,.doc,.txt,.md,.csv,.json,.yaml,.yml,.png,.jpg,.jpeg,.gif,.webp,.svg"
            onChange={handleFileAttach}
            className="hidden"
          />
          <input
            type="text"
            value={isSharedView ? '' : input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
            placeholder={isSharedView ? 'This is a shared read-only chat' : attachments.length > 0 ? 'Ask about the attached file(s)...' : 'Ask Genie anything about the organization\'s data platform...'}
            className="flex-1 border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-genie-500 focus:border-transparent disabled:bg-gray-50 disabled:text-gray-400"
            disabled={isStreaming || isSharedView}
          />
          <button
            onClick={() => handleSend()}
            disabled={(!input.trim() && attachments.length === 0) || isStreaming || isSharedView}
            className="bg-genie-600 text-white rounded-lg px-4 py-2.5 hover:bg-genie-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isStreaming ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
          </button>
        </div>
      </div>
    </div>
  )
}
