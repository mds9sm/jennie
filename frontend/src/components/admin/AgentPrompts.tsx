import { useState, useEffect } from 'react'
import { Bot, Save, Loader2, RotateCcw, ChevronDown, ChevronRight } from 'lucide-react'
import { fetchJSON } from '../../api/client'

interface AgentInfo {
  id: string
  label: string
  prompt: string
  char_count: number
  is_overridden?: boolean
}

export default function AgentPrompts() {
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editPrompt, setEditPrompt] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<string | null>(null)

  useEffect(() => { loadAgents() }, [])

  async function loadAgents() {
    setLoading(true)
    try {
      const res = await fetchJSON<AgentInfo[]>('/agent-prompts')
      setAgents(res)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  function startEdit(agent: AgentInfo) {
    setEditingId(agent.id)
    setEditPrompt(agent.prompt)
  }

  async function handleSave(agentId: string) {
    setSaving(true)
    try {
      await fetchJSON(`/agent-prompts/${agentId}`, {
        method: 'PUT',
        body: JSON.stringify({ prompt: editPrompt }),
      })
      setSaved(agentId)
      setEditingId(null)
      await loadAgents()
      setTimeout(() => setSaved(null), 3000)
    } catch { /* ignore */ }
    finally { setSaving(false) }
  }

  if (loading) return <div className="flex items-center justify-center py-12"><Loader2 className="animate-spin text-gray-400" /></div>

  return (
    <div className="max-w-4xl space-y-3">
      <div>
        <h3 className="text-base font-medium text-gray-900">Agent Prompts</h3>
        <p className="text-xs text-gray-500 mb-2">
          View and edit the system prompts that define each agent's persona and expertise.
        </p>
        <div className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 text-xs text-gray-600 leading-relaxed">
          <p className="font-medium text-gray-700 mb-1">Architecture: Persona-based agents</p>
          <p>Each agent has a <strong>persona</strong> (who they are) rather than an instruction manual (what to do). A senior analytics engineer doesn't need rules about checking aggregates — they just do it.</p>
          <p className="mt-1"><strong>Principal</strong> (Sonnet): routes questions, handles data queries directly, delegates complex work. <strong>Sub-agents</strong> (Sonnet): specialists with deep domain knowledge. <strong>Opus</strong>: only used for complex synthesis when limits are hit.</p>
        </div>
      </div>

      {agents.map(agent => {
        const isEditing = editingId === agent.id
        const justSaved = saved === agent.id
        const isPrincipal = agent.id === 'principal'

        return (
          <div key={agent.id} className={`border rounded-lg ${isPrincipal ? 'border-genie-300' : 'border-gray-200'}`}>
            {/* Header */}
            <div
              className={`flex items-center justify-between px-4 py-2.5 cursor-pointer hover:bg-gray-50 ${isPrincipal ? 'bg-genie-50' : ''}`}
              onClick={() => isEditing ? setEditingId(null) : startEdit(agent)}
            >
              <div className="flex items-center gap-2">
                <Bot size={14} className={isPrincipal ? 'text-genie-600' : 'text-gray-400'} />
                <span className="text-sm font-medium text-gray-900">{agent.label}</span>
                <span className="text-[10px] text-gray-400">{agent.char_count.toLocaleString()} chars</span>
                {agent.is_overridden && <span className="text-[9px] bg-amber-100 text-amber-700 px-1 py-0.5 rounded">customized</span>}
                {justSaved && <span className="text-[10px] text-green-600">Saved!</span>}
              </div>
              <div className="flex items-center gap-1">
                {isEditing ? <ChevronDown size={14} className="text-gray-400" /> : <ChevronRight size={14} className="text-gray-400" />}
              </div>
            </div>

            {/* Editor */}
            {isEditing && (
              <div className="px-4 pb-4 border-t border-gray-100">
                <textarea
                  value={editPrompt}
                  onChange={e => setEditPrompt(e.target.value)}
                  rows={Math.min(25, Math.max(8, editPrompt.split('\n').length + 2))}
                  className="w-full mt-3 border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono bg-gray-50 focus:bg-white focus:ring-genie-500 focus:border-genie-500"
                  spellCheck={false}
                />
                <div className="flex items-center gap-2 mt-2">
                  <button onClick={() => handleSave(agent.id)} disabled={saving}
                    className="flex items-center gap-1 px-3 py-1.5 text-xs rounded bg-genie-600 text-white hover:bg-genie-700 disabled:opacity-50">
                    {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                    Save
                  </button>
                  <button onClick={() => setEditingId(null)} className="text-xs text-gray-500 hover:text-gray-700">
                    Cancel
                  </button>
                  {agent.is_overridden && (
                    <button onClick={async () => {
                      await fetchJSON(`/agent-prompts/${agent.id}/reset`, { method: 'POST' })
                      setEditingId(null)
                      await loadAgents()
                    }} className="text-xs text-amber-600 hover:text-amber-800 flex items-center gap-0.5">
                      <RotateCcw size={10} /> Reset to default
                    </button>
                  )}
                  <span className="text-[10px] text-gray-400 ml-auto">{editPrompt.length.toLocaleString()} chars</span>
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
