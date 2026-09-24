import { useState } from 'react'
import { Sparkles, Loader2, Check } from 'lucide-react'
import { fetchJSON } from '../../api/client'
import type { UserSettings } from './SettingsPage'

interface Props {
  settings: UserSettings
  onUpdate: (partial: Partial<UserSettings>) => void
}

export default function UserContextTab({ settings, onUpdate }: Props) {
  const [optimizing, setOptimizing] = useState(false)
  const [optimizeResult, setOptimizeResult] = useState<{
    savings_pct: number
    original_words: number
    optimized_words: number
  } | null>(null)

  async function handleOptimize() {
    if (!settings.user_context.trim()) return
    setOptimizing(true)
    setOptimizeResult(null)
    try {
      const res = await fetchJSON<{
        optimized: string
        savings_pct: number
        original_words: number
        optimized_words: number
      }>('/settings/optimize-context', {
        method: 'POST',
        body: JSON.stringify({ user_context: settings.user_context }),
      })
      onUpdate({ user_context_optimized: res.optimized })
      setOptimizeResult({
        savings_pct: res.savings_pct,
        original_words: res.original_words,
        optimized_words: res.optimized_words,
      })
    } catch (err) {
      alert('Optimization failed: ' + (err instanceof Error ? err.message : 'Unknown error'))
    } finally {
      setOptimizing(false)
    }
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h3 className="text-base font-medium text-gray-900 mb-1">Your Context</h3>
        <p className="text-sm text-gray-500 mb-4">
          Tell Genie about yourself — your team, current focus, domain expertise, or anything
          that helps it give better answers. This context is included in every AI call.
        </p>
      </div>

      {/* User Context Input */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Personal context (write naturally)
        </label>
        <textarea
          value={settings.user_context}
          onChange={(e) => {
            onUpdate({ user_context: e.target.value, user_context_optimized: '' })
            setOptimizeResult(null)
          }}
          rows={8}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-genie-500 resize-y"
          placeholder={`Example:\nI'm a data engineer on the Engagement team (Pillar 2). I mostly work on the engagement_user_daily_dimensions pipeline and the cohort analysis tables. I'm currently investigating why return rates dropped in the last 2 weeks — might be a data quality issue in firehose_v3_enriched. I'm familiar with Redshift, Airflow, and our transform DAG patterns, but I'm new to the personalization tables.`}
        />
        <div className="flex items-center justify-between mt-2">
          <p className="text-xs text-gray-400">
            {settings.user_context.split(/\s+/).filter(Boolean).length} words
          </p>
        </div>
      </div>

      {/* Optimize Button */}
      <div className="border border-dashed border-gray-300 rounded-lg p-4 bg-gray-50">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h4 className="text-sm font-medium text-gray-700">Optimize for tokens</h4>
            <p className="text-xs text-gray-500 mt-0.5">
              AI compresses your context to use fewer tokens while preserving all meaning.
              The optimized version is what Genie actually sends to the AI — saving you cost on every call.
            </p>
          </div>
          <button
            onClick={handleOptimize}
            disabled={optimizing || !settings.user_context.trim()}
            className="flex items-center gap-2 px-4 py-2 bg-amber-500 text-white rounded-lg text-sm font-medium hover:bg-amber-600 disabled:opacity-50 whitespace-nowrap"
          >
            {optimizing ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Sparkles size={16} />
            )}
            Optimize for Tokens
          </button>
        </div>

        {/* Optimization result */}
        {optimizeResult && (
          <div className="mt-3 flex items-center gap-2 text-xs">
            <Check size={14} className="text-green-500" />
            <span className="text-green-700">
              Compressed: {optimizeResult.original_words} → {optimizeResult.optimized_words} words
              ({optimizeResult.savings_pct}% smaller)
            </span>
          </div>
        )}
      </div>

      {/* Optimized Version (read-only display) */}
      {settings.user_context_optimized && (
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Optimized version (sent to AI)
          </label>
          <div className="border border-gray-200 rounded-lg px-3 py-2 bg-white text-sm text-gray-700 whitespace-pre-wrap min-h-[80px]">
            {settings.user_context_optimized}
          </div>
          <p className="text-xs text-gray-400 mt-1">
            {settings.user_context_optimized.split(/\s+/).filter(Boolean).length} words —
            edit the original above and re-optimize to update
          </p>
        </div>
      )}
    </div>
  )
}
