import { useState, useEffect } from 'react'
import { fetchJSON } from '../../api/client'
import type { UserSettings } from './SettingsPage'

interface Persona {
  id: string
  name: string
  description: string
  default_system_rules: string
}

interface Props {
  settings: UserSettings
  onUpdate: (partial: Partial<UserSettings>) => void
}

export default function PersonaTab({ settings, onUpdate }: Props) {
  const [personas, setPersonas] = useState<Persona[]>([])

  useEffect(() => {
    fetchJSON<Persona[]>('/settings/personas').then(setPersonas).catch(() => {})
  }, [])

  return (
    <div className="max-w-2xl space-y-4">
      <div>
        <h3 className="text-base font-medium text-gray-900 mb-1">Your Role</h3>
        <p className="text-sm text-gray-500 mb-3">
          Your persona controls how Genie adapts its responses to you.
        </p>
        <div className="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2.5 mb-4">
          <p className="text-xs text-blue-800 font-medium mb-1">How Genie's AI works</p>
          <p className="text-xs text-blue-700 leading-relaxed">
            <strong>System prompt</strong> defines who Genie is — a senior analytics engineer who thinks downstream-first, checks DOMO aggregates before querying raw tables, and delegates to specialist sub-agents.
            <br />
            <strong>Your persona</strong> tells Genie who's asking — an engineer gets SQL and distkey details, an analyst gets business context and charts, an exec gets impact summaries. Same knowledge, different depth.
          </p>
        </div>
      </div>

      <div className="grid gap-3">
        {personas.map((p) => (
          <label
            key={p.id}
            className={`flex items-start gap-3 border rounded-lg p-4 cursor-pointer transition-colors ${
              settings.persona === p.id
                ? 'border-genie-500 bg-genie-50 ring-1 ring-genie-500'
                : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
            }`}
          >
            <input
              type="radio"
              name="persona"
              checked={settings.persona === p.id}
              onChange={() => onUpdate({ persona: p.id })}
              className="mt-1 text-genie-600 focus:ring-genie-500"
            />
            <div>
              <div className="font-medium text-gray-900 text-sm">{p.name}</div>
              <div className="text-xs text-gray-500 mt-0.5">{p.description}</div>
              <div className="text-xs text-gray-400 mt-2 italic">
                AI behavior: {p.default_system_rules}
              </div>
            </div>
          </label>
        ))}
      </div>
    </div>
  )
}
