// API base path — resolved at runtime for K8s flexibility
// Priority: window.__ENV__ (runtime injection) > VITE_API_BASE (build-time) > /api (default)
const API_BASE = (window as unknown as Record<string, Record<string, string>>).__ENV__?.VITE_API_BASE
  || import.meta.env.VITE_API_BASE
  || '/api'

export async function fetchJSON<T>(path: string, options?: RequestInit): Promise<T> {
  const token = localStorage.getItem('genie_auth_token') || ''
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { 'X-Auth-Token': token } : {}),
      ...(options?.headers || {}),
    },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Request failed')
  }
  return res.json()
}

export interface ExtractedFile {
  filename: string
  size: number
  extracted_length: number
  content: string
  truncated: boolean
}

// Multipart upload — can't go through fetchJSON (which forces a JSON content type),
// but must still honour API_BASE: the K8s frontend serves the API under /genie/api.
export async function extractChatFile(file: File): Promise<ExtractedFile> {
  const token = localStorage.getItem('genie_auth_token') || ''
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${API_BASE}/chat/extract-file`, {
    method: 'POST',
    body: formData,
    headers: token ? { 'X-Auth-Token': token } : {},
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'File extraction failed')
  }
  return res.json()
}

export interface ChatAttachmentInput {
  filename: string
  content: string
  size: number
  isImage?: boolean
  mediaType?: string
  base64?: string
}

export async function* streamChat(
  message: string,
  conversationHistory: { role: string; content: string }[],
  pillar: string | null,
  environment: string,
  attachments?: ChatAttachmentInput[],
  sessionId?: string,
): AsyncGenerator<{ event: string; data: unknown }> {
  const token = localStorage.getItem('genie_auth_token') || ''
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { 'X-Auth-Token': token } : {}),
    },
    body: JSON.stringify({
      message,
      conversation_history: conversationHistory,
      pillar,
      environment,
      // Without this the backend can't persist the answer when the client
      // disconnects mid-stream, and the "response ready" notification never fires.
      session_id: sessionId ?? null,
      attachments: (attachments || []).map(a => (
        a.isImage && a.base64
          ? { filename: a.filename, content: '', is_image: true, media_type: a.mediaType, base64: a.base64 }
          : { filename: a.filename, content: a.content }
      )),
    }),
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Chat request failed')
  }

  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    let currentEvent = 'message'
    for (const line of lines) {
      if (line.startsWith('event:')) {
        currentEvent = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        const dataStr = line.slice(5).trim()
        if (dataStr) {
          try {
            yield { event: currentEvent, data: JSON.parse(dataStr) }
          } catch {
            // skip malformed JSON
          }
        }
      }
    }
  }
}

export async function generateSQL(question: string, pillar: string | null, environment: string) {
  return fetchJSON<{ sql: string; environment: string }>('/sql/generate', {
    method: 'POST',
    body: JSON.stringify({ question, pillar, environment }),
  })
}

export async function executeSQL(sql: string, environment: string, sessionId?: string) {
  return fetchJSON<{
    columns: string[]
    rows: unknown[][]
    row_count: number
    execution_time_ms: number
    environment: string
    truncated: boolean
    query_id: string
  }>('/sql/execute', {
    method: 'POST',
    body: JSON.stringify({ sql, environment, session_id: sessionId }),
  })
}

export async function optimizeSQL(sql: string, pillar: string | null) {
  return fetchJSON<{ analysis: string }>('/sql/optimize', {
    method: 'POST',
    body: JSON.stringify({ sql, pillar }),
  })
}

export async function generatePipeline(description: string, pillar: string | null) {
  return fetchJSON<{ yaml_config: string; sql_files: Record<string, string>; explanation: string }>(
    '/pipeline/generate',
    {
      method: 'POST',
      body: JSON.stringify({ description, pillar }),
    },
  )
}

export async function searchGlossary(query: string) {
  return fetchJSON<{ results: unknown[]; count: number }>(`/glossary/search?q=${encodeURIComponent(query)}`)
}

export async function analyzeImpact(changeDescription: string, pillar: string | null) {
  return fetchJSON<{ report: string }>('/impact/analyze', {
    method: 'POST',
    body: JSON.stringify({ change_description: changeDescription, pillar }),
  })
}

// ── History ──────────────────────────────────────────────────────────────────

export async function saveSession(sessionId: string, messages: { role: string; content: string }[], pillar?: string | null) {
  return fetchJSON<{ session_id: string }>('/chat/sessions', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, messages, pillar }),
  })
}

export async function getSession(sessionId: string) {
  return fetchJSON<{ id: string; messages: { role: string; content: string }[]; title: string; pillar: string | null }>(
    `/chat/sessions/${sessionId}`
  )
}

export async function getSharedSession(sessionId: string) {
  return fetchJSON<{
    id: string; messages: { role: string; content: string }[]; title: string;
    pillar: string | null; owner_name: string; owner_email: string; shared: boolean
  }>(`/chat/shared/${sessionId}`)
}

export async function getRecentSessions() {
  return fetchJSON<
    { id: string; pillar: string | null; title: string; created_at: string; updated_at: string }[]
  >('/chat/sessions')
}

export async function getRecentQueries(sessionId?: string) {
  const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''
  return fetchJSON<
    { id: number; query_text: string; environment: string; execution_time_ms: number | null; created_at: string }[]
  >(`/history/queries${qs}`)
}

// ── Glossary contribution / review ───────────────────────────────────────────

export async function getGlossaryFeedback() {
  return fetchJSON<
    { id: number; term: string; correction: string; submitted_by: string; status: string; created_at: string }[]
  >('/glossary/feedback')
}

export async function updateGlossaryFeedback(id: number, status: string) {
  return fetchJSON<{ id: number; status: string }>(`/glossary/feedback/${id}`, {
    method: 'PUT',
    body: JSON.stringify({ status }),
  })
}

export async function getAllGlossaryTerms() {
  return fetchJSON<{ results: unknown[]; count: number }>('/glossary/all')
}

export async function submitGlossaryCorrection(term: string, correction: string, submittedBy?: string) {
  return fetchJSON<{ status: string; term: string }>('/glossary/correct', {
    method: 'POST',
    body: JSON.stringify({ term, correction, submitted_by: submittedBy || 'local-dev' }),
  })
}

// ── Pillars / Usage ──────────────────────────────────────────────────────────

export async function getPillars() {
  return fetchJSON<{ id: string; name: string; key_tables: string[]; key_metrics: string[] }[]>('/pillars')
}

export async function getUsageSummary() {
  return fetchJSON<{ today: unknown[]; totals: { call_count: number; total_cost: number } }>('/usage/summary')
}
