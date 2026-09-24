import type { UserSettings } from './SettingsPage'

interface Props {
  settings: UserSettings
  onUpdate: (partial: Partial<UserSettings>) => void
}

const PRESET_RULES = [
  {
    label: 'No destructive SQL',
    rule: '- NEVER generate DELETE, DROP, TRUNCATE, INSERT, UPDATE, or CREATE statements',
  },
  {
    label: 'SELECT/EXPLAIN only',
    rule: '- All generated SQL must be SELECT or EXPLAIN only',
  },
  {
    label: 'Nonprod default',
    rule: '- Default to nonprod (np_) for all queries unless prod is explicitly required',
  },
  {
    label: 'Prod for MWAA logs',
    rule: '- Use prod for MWAA/Airflow log queries when debugging prod pipelines',
  },
  {
    label: 'Prod for EXPLAIN',
    rule: '- Use prod for EXPLAIN plans since accurate stats require prod node count and data distribution',
  },
  {
    label: 'Prod for profiling',
    rule: '- Use prod for data profiling (row counts, distributions) since statistics are not available via datashare',
  },
  {
    label: 'Explain prod usage',
    rule: '- When routing to prod, always explain WHY prod is needed before executing',
  },
  {
    label: 'Fully qualified names',
    rule: '- Always use fully qualified table names: {prefix}dw.{schema}.{table}',
  },
  {
    label: 'Wrap DML in transactions',
    rule: '- Generated DML must be wrapped in BEGIN TRANSACTION / END TRANSACTION',
  },
]

export default function SystemPromptTab({ settings, onUpdate }: Props) {
  function addRule(rule: string) {
    const current = settings.system_prompt.trim()
    if (current.includes(rule)) return
    onUpdate({ system_prompt: current ? `${current}\n${rule}` : rule })
  }

  return (
    <div className="max-w-3xl space-y-4">
      <div>
        <h3 className="text-base font-medium text-gray-900 mb-1">System Prompt Rules</h3>
        <p className="text-sm text-gray-500 mb-3">
          Custom rules that Genie follows in every interaction, on top of its built-in behavior.
        </p>
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2.5 mb-4">
          <p className="text-xs text-amber-800 font-medium mb-1">System prompt vs User prompt</p>
          <div className="text-xs text-amber-700 leading-relaxed space-y-1">
            <p><strong>System prompt</strong> (built-in + your rules below) = permanent instructions Genie always follows. Defines identity, safety constraints, environment routing. Applied to every question.</p>
            <p><strong>User prompt</strong> = your actual question in chat. Changes every message. Genie combines the system prompt context with your question to generate a response.</p>
            <p><strong>Your rules below</strong> are appended to the system prompt — use them for team-specific constraints (e.g., "never query prod directly", "always explain prod usage").</p>
          </div>
        </div>
      </div>

      {/* Quick-add presets */}
      <div>
        <h4 className="text-sm font-medium text-gray-700 mb-2">Quick-add rules</h4>
        <div className="flex flex-wrap gap-2">
          {PRESET_RULES.map((preset) => {
            const isActive = settings.system_prompt.includes(preset.rule)
            return (
              <button
                key={preset.label}
                onClick={() => addRule(preset.rule)}
                disabled={isActive}
                className={`text-xs px-2.5 py-1.5 rounded-full border transition-colors ${
                  isActive
                    ? 'bg-genie-50 border-genie-300 text-genie-700'
                    : 'border-gray-300 text-gray-600 hover:bg-gray-50 hover:border-gray-400'
                }`}
              >
                {isActive ? '+ ' : ''}{preset.label}
              </button>
            )
          })}
        </div>
      </div>

      {/* Editor */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Custom system prompt
        </label>
        <textarea
          value={settings.system_prompt}
          onChange={(e) => onUpdate({ system_prompt: e.target.value })}
          rows={14}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono bg-gray-50 focus:outline-none focus:ring-2 focus:ring-genie-500 resize-y"
          placeholder="Add rules that Genie will follow in every interaction..."
        />
        <p className="text-xs text-gray-400 mt-1">
          These rules are injected into every AI call alongside Genie's built-in persona (senior analytics engineer),
          your selected persona, active pillar, and environment. They override defaults when there's a conflict.
        </p>
      </div>
    </div>
  )
}
