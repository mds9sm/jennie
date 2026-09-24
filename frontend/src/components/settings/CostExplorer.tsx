import { useState, useEffect, useMemo } from 'react'
import { Loader2, DollarSign, Activity, Users, Cpu } from 'lucide-react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from 'recharts'
import { fetchJSON } from '../../api/client'

interface TimelineBucket {
  period: string
  call_count: number
  input_tokens: number
  output_tokens: number
  total_cost: number
  unique_users: number
}

interface ModelTimelineBucket {
  period: string
  opus: number
  sonnet: number
  haiku: number
  opus_calls: number
  sonnet_calls: number
  haiku_calls: number
}

interface UserBreakdown {
  user_id: string
  user_name?: string
  calls: number
  cost: number
  tokens: number
}

interface ModelBreakdown {
  model: string
  calls: number
  cost: number
  input_tokens: number
  output_tokens: number
}

interface Totals {
  total_calls: number
  total_input: number
  total_output: number
  total_cost: number
}

interface CostExplorerResponse {
  period: string
  days: number
  timeline: TimelineBucket[]
  model_timeline: ModelTimelineBucket[]
  by_user: UserBreakdown[]
  by_model: ModelBreakdown[]
  totals: Totals
}

const PERIODS = [
  { id: 'daily', label: 'Daily' },
  { id: 'weekly', label: 'Weekly' },
  { id: 'monthly', label: 'Monthly' },
] as const

const DATE_RANGES = [
  { value: 7, label: 'Last 7 days' },
  { value: 30, label: 'Last 30 days' },
  { value: 90, label: 'Last 90 days' },
  { value: 365, label: 'Last 365 days' },
] as const

const MODEL_COLORS: Record<string, string> = {
  opus: '#8b5cf6',
  sonnet: '#3b82f6',
  haiku: '#22c55e',
}

const MODEL_LABELS: Record<string, string> = {
  opus: 'Opus',
  sonnet: 'Sonnet',
  haiku: 'Haiku',
}

function getModelFamily(model: string): string {
  const lower = (model || '').toLowerCase()
  if (lower.includes('opus')) return 'opus'
  if (lower.includes('haiku')) return 'haiku'
  return 'sonnet'
}

function getModelColor(model: string): string {
  return MODEL_COLORS[getModelFamily(model)] || MODEL_COLORS.sonnet
}

function getModelLabel(model: string): string {
  const family = getModelFamily(model)
  return MODEL_LABELS[family] || 'Unknown'
}

const TOKEN_COLORS = ['#6366f1', '#f59e0b']

function formatCost(val: number): string {
  if (val >= 1) return `$${val.toFixed(2)}`
  if (val >= 0.01) return `$${val.toFixed(3)}`
  return `$${val.toFixed(4)}`
}

function formatTokens(val: number): string {
  if (val >= 1_000_000) return `${(val / 1_000_000).toFixed(1)}M`
  if (val >= 1_000) return `${(val / 1_000).toFixed(1)}K`
  return String(val)
}

function formatPeriodLabel(iso: string, period: string): string {
  const d = new Date(iso)
  if (period === 'daily') {
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  }
  if (period === 'weekly') {
    return `Wk ${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`
  }
  return d.toLocaleDateString('en-US', { month: 'short', year: '2-digit' })
}

export default function CostExplorer() {
  const [period, setPeriod] = useState<string>('daily')
  const [days, setDays] = useState<number>(30)
  const [userFilter, setUserFilter] = useState<string>('')
  const [modelFilter, setModelFilter] = useState<string>('')
  const [data, setData] = useState<CostExplorerResponse | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      try {
        const params = new URLSearchParams({ period, days: String(days) })
        if (userFilter) params.set('user_id', userFilter)
        const res = await fetchJSON<CostExplorerResponse>(
          `/activity/cost-explorer?${params.toString()}`
        )
        if (!cancelled) setData(res)
      } catch {
        // silent
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [period, days, userFilter])

  // Model timeline chart data with labels
  const modelChartData = useMemo(() => {
    if (!data?.model_timeline) return []
    return data.model_timeline.map((t) => ({
      ...t,
      label: formatPeriodLabel(t.period, data.period),
    }))
  }, [data])

  // Token pie data
  const tokenPieData = useMemo(() => {
    if (!data) return []
    return [
      { name: 'Input Tokens', value: data.totals.total_input || 0 },
      { name: 'Output Tokens', value: data.totals.total_output || 0 },
    ]
  }, [data])

  // Model pie data for cost split
  const modelPieData = useMemo(() => {
    if (!data) return []
    // Aggregate by model family
    const families: Record<string, number> = {}
    for (const m of data.by_model) {
      const fam = getModelFamily(m.model)
      families[fam] = (families[fam] || 0) + m.cost
    }
    return Object.entries(families)
      .filter(([, v]) => v > 0)
      .map(([k, v]) => ({ name: MODEL_LABELS[k] || k, value: v, family: k }))
  }, [data])

  // Filtered totals based on model filter
  const filteredModels = useMemo(() => {
    if (!data) return []
    if (!modelFilter) return data.by_model
    return data.by_model.filter(m => getModelFamily(m.model) === modelFilter)
  }, [data, modelFilter])

  const totalCost = data?.totals?.total_cost || 0
  const totalCalls = data?.totals?.total_calls || 0
  const avgCostPerCall = totalCalls > 0 ? totalCost / totalCalls : 0

  // Distinct model families present
  const modelFamilies = useMemo(() => {
    if (!data) return []
    const families = new Set(data.by_model.map(m => getModelFamily(m.model)))
    return Array.from(families)
  }, [data])

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-base font-medium text-gray-900 mb-1">Cost Explorer</h3>
        <p className="text-sm text-gray-500">
          Analyze AI usage costs by model, time period, and user.
        </p>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-4">
        {/* Period toggle */}
        <div className="flex bg-gray-100 rounded-lg p-0.5">
          {PERIODS.map((p) => (
            <button
              key={p.id}
              onClick={() => setPeriod(p.id)}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                period === p.id
                  ? 'bg-white text-gray-900 font-medium shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>

        {/* Date range */}
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm bg-white"
        >
          {DATE_RANGES.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>

        {/* Model filter */}
        {modelFamilies.length > 1 && (
          <select
            value={modelFilter}
            onChange={(e) => setModelFilter(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm bg-white"
          >
            <option value="">All models</option>
            {modelFamilies.map((f) => (
              <option key={f} value={f}>
                {MODEL_LABELS[f] || f}
              </option>
            ))}
          </select>
        )}

        {/* User filter */}
        {data && data.by_user.length > 1 && (
          <select
            value={userFilter}
            onChange={(e) => setUserFilter(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm bg-white"
          >
            <option value="">All users</option>
            {data.by_user.map((u) => (
              <option key={u.user_id} value={u.user_id}>
                {u.user_name || u.user_id}
              </option>
            ))}
          </select>
        )}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 size={24} className="animate-spin text-genie-600" />
        </div>
      ) : data ? (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="border border-gray-200 rounded-lg p-4 bg-white">
              <div className="flex items-center gap-2 mb-2">
                <DollarSign size={16} className="text-green-600" />
                <span className="text-xs font-medium text-gray-500 uppercase">Total Cost</span>
              </div>
              <p className="text-2xl font-bold text-gray-900">{formatCost(totalCost)}</p>
            </div>
            <div className="border border-gray-200 rounded-lg p-4 bg-white">
              <div className="flex items-center gap-2 mb-2">
                <Cpu size={16} className="text-indigo-600" />
                <span className="text-xs font-medium text-gray-500 uppercase">Total Tokens</span>
              </div>
              <p className="text-2xl font-bold text-gray-900">
                {formatTokens((data.totals.total_input || 0) + (data.totals.total_output || 0))}
              </p>
            </div>
            <div className="border border-gray-200 rounded-lg p-4 bg-white">
              <div className="flex items-center gap-2 mb-2">
                <Activity size={16} className="text-blue-600" />
                <span className="text-xs font-medium text-gray-500 uppercase">Total Calls</span>
              </div>
              <p className="text-2xl font-bold text-gray-900">{totalCalls.toLocaleString()}</p>
            </div>
            <div className="border border-gray-200 rounded-lg p-4 bg-white">
              <div className="flex items-center gap-2 mb-2">
                <DollarSign size={16} className="text-orange-500" />
                <span className="text-xs font-medium text-gray-500 uppercase">Avg Cost/Call</span>
              </div>
              <p className="text-2xl font-bold text-gray-900">{formatCost(avgCostPerCall)}</p>
            </div>
          </div>

          {/* Cost by Model Timeline — stacked bar chart */}
          {modelChartData.length > 0 && (
            <div className="border border-gray-200 rounded-lg p-5 bg-white">
              <h4 className="text-sm font-semibold text-gray-900 mb-1">Cost by Model</h4>
              <p className="text-xs text-gray-400 mb-4">Stacked by model family — hover for detail</p>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={modelChartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis
                    dataKey="label"
                    tick={{ fontSize: 11, fill: '#6b7280' }}
                    interval="preserveStartEnd"
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: '#6b7280' }}
                    tickFormatter={(v) => `$${v}`}
                  />
                  <Tooltip
                    formatter={(value: number, name: string) => [
                      formatCost(value),
                      MODEL_LABELS[name] || name,
                    ]}
                    labelStyle={{ fontWeight: 600 }}
                    contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
                  />
                  <Legend
                    formatter={(value: string) => MODEL_LABELS[value] || value}
                  />
                  <Bar
                    dataKey="opus"
                    name="opus"
                    stackId="cost"
                    fill={MODEL_COLORS.opus}
                    radius={[0, 0, 0, 0]}
                    maxBarSize={40}
                  />
                  <Bar
                    dataKey="sonnet"
                    name="sonnet"
                    stackId="cost"
                    fill={MODEL_COLORS.sonnet}
                    radius={[0, 0, 0, 0]}
                    maxBarSize={40}
                  />
                  <Bar
                    dataKey="haiku"
                    name="haiku"
                    stackId="cost"
                    fill={MODEL_COLORS.haiku}
                    radius={[4, 4, 0, 0]}
                    maxBarSize={40}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Model cost pie + Token breakdown side by side */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Model cost pie chart */}
            <div className="border border-gray-200 rounded-lg p-5 bg-white">
              <h4 className="text-sm font-semibold text-gray-900 mb-4">Cost Split by Model</h4>
              {modelPieData.length > 0 ? (
                <>
                  <ResponsiveContainer width="100%" height={200}>
                    <PieChart>
                      <Pie
                        data={modelPieData}
                        cx="50%"
                        cy="50%"
                        innerRadius={50}
                        outerRadius={80}
                        dataKey="value"
                        label={({ name, percent }) =>
                          `${name}: ${(percent * 100).toFixed(0)}%`
                        }
                        labelLine={false}
                      >
                        {modelPieData.map((entry) => (
                          <Cell key={entry.family} fill={MODEL_COLORS[entry.family] || '#94a3b8'} />
                        ))}
                      </Pie>
                      <Tooltip formatter={(v: number) => formatCost(v)} />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="flex justify-center gap-4 mt-2 text-xs text-gray-600">
                    {modelPieData.map((m) => (
                      <div key={m.family} className="flex items-center gap-1.5">
                        <div className="w-3 h-3 rounded-sm" style={{ background: MODEL_COLORS[m.family] }} />
                        {m.name}: {formatCost(m.value)}
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <p className="text-sm text-gray-400 text-center py-8">No model data</p>
              )}
            </div>

            {/* Token pie chart */}
            <div className="border border-gray-200 rounded-lg p-5 bg-white">
              <h4 className="text-sm font-semibold text-gray-900 mb-4">Token Breakdown</h4>
              {(data.totals.total_input || 0) + (data.totals.total_output || 0) > 0 ? (
                <>
                  <ResponsiveContainer width="100%" height={200}>
                    <PieChart>
                      <Pie
                        data={tokenPieData}
                        cx="50%"
                        cy="50%"
                        innerRadius={50}
                        outerRadius={80}
                        dataKey="value"
                        label={({ name, percent }) =>
                          `${name}: ${(percent * 100).toFixed(0)}%`
                        }
                        labelLine={false}
                      >
                        {tokenPieData.map((_entry, index) => (
                          <Cell key={`cell-${index}`} fill={TOKEN_COLORS[index]} />
                        ))}
                      </Pie>
                      <Tooltip formatter={(v: number) => formatTokens(v)} />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="flex justify-center gap-6 mt-2 text-xs text-gray-600">
                    <div className="flex items-center gap-1.5">
                      <div className="w-3 h-3 rounded-sm" style={{ background: TOKEN_COLORS[0] }} />
                      Input: {formatTokens(data.totals.total_input || 0)}
                    </div>
                    <div className="flex items-center gap-1.5">
                      <div className="w-3 h-3 rounded-sm" style={{ background: TOKEN_COLORS[1] }} />
                      Output: {formatTokens(data.totals.total_output || 0)}
                    </div>
                  </div>
                </>
              ) : (
                <p className="text-sm text-gray-400 text-center py-8">No token data</p>
              )}
            </div>
          </div>

          {/* Model breakdown detail table */}
          {filteredModels.length > 0 && (
            <div className="border border-gray-200 rounded-lg p-5 bg-white">
              <h4 className="text-sm font-semibold text-gray-900 mb-4">
                <Cpu size={14} className="inline mr-1.5 text-gray-500" />
                Model Usage Detail
              </h4>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200">
                      <th className="text-left py-2 pr-4 text-gray-500 font-medium text-xs uppercase">Model</th>
                      <th className="text-right py-2 pr-4 text-gray-500 font-medium text-xs uppercase">Calls</th>
                      <th className="text-right py-2 pr-4 text-gray-500 font-medium text-xs uppercase">Input Tokens</th>
                      <th className="text-right py-2 pr-4 text-gray-500 font-medium text-xs uppercase">Output Tokens</th>
                      <th className="text-right py-2 pr-4 text-gray-500 font-medium text-xs uppercase">Cost</th>
                      <th className="text-right py-2 text-gray-500 font-medium text-xs uppercase">% of Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredModels.map((m) => {
                      const pct = totalCost > 0 ? (m.cost / totalCost) * 100 : 0
                      const family = getModelFamily(m.model)
                      return (
                        <tr key={m.model || 'unknown'} className="border-b border-gray-100 hover:bg-gray-50">
                          <td className="py-2.5 pr-4">
                            <div className="flex items-center gap-2">
                              <div
                                className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                                style={{ backgroundColor: MODEL_COLORS[family] }}
                              />
                              <div>
                                <span className="text-gray-900 font-medium">{getModelLabel(m.model)}</span>
                                <span className="text-[10px] text-gray-400 ml-2 font-mono">{m.model || 'unknown'}</span>
                              </div>
                            </div>
                          </td>
                          <td className="py-2.5 pr-4 text-right text-gray-600 tabular-nums">
                            {m.calls.toLocaleString()}
                          </td>
                          <td className="py-2.5 pr-4 text-right text-gray-600 tabular-nums">
                            {formatTokens(m.input_tokens || 0)}
                          </td>
                          <td className="py-2.5 pr-4 text-right text-gray-600 tabular-nums">
                            {formatTokens(m.output_tokens || 0)}
                          </td>
                          <td className="py-2.5 pr-4 text-right text-gray-900 tabular-nums font-medium">
                            {formatCost(m.cost)}
                          </td>
                          <td className="py-2.5 text-right">
                            <div className="flex items-center justify-end gap-2">
                              <div className="w-16 bg-gray-100 rounded-full h-1.5">
                                <div
                                  className="h-1.5 rounded-full transition-all duration-500"
                                  style={{ width: `${pct}%`, backgroundColor: MODEL_COLORS[family] }}
                                />
                              </div>
                              <span className="text-gray-500 tabular-nums text-xs w-10 text-right">
                                {pct.toFixed(1)}%
                              </span>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* User breakdown table */}
          {data.by_user.length > 0 && (
            <div className="border border-gray-200 rounded-lg p-5 bg-white">
              <h4 className="text-sm font-semibold text-gray-900 mb-4">
                <Users size={14} className="inline mr-1.5 text-gray-500" />
                User Breakdown
              </h4>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200">
                      <th className="text-left py-2 pr-4 text-gray-500 font-medium text-xs uppercase">User</th>
                      <th className="text-right py-2 pr-4 text-gray-500 font-medium text-xs uppercase">Calls</th>
                      <th className="text-right py-2 pr-4 text-gray-500 font-medium text-xs uppercase">Tokens</th>
                      <th className="text-right py-2 pr-4 text-gray-500 font-medium text-xs uppercase">Cost</th>
                      <th className="text-right py-2 text-gray-500 font-medium text-xs uppercase">% of Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_user.map((u) => {
                      const pct = totalCost > 0 ? (u.cost / totalCost) * 100 : 0
                      return (
                        <tr key={u.user_id} className="border-b border-gray-100 hover:bg-gray-50">
                          <td className="py-2 pr-4 text-gray-900 font-medium">{u.user_name || u.user_id}</td>
                          <td className="py-2 pr-4 text-right text-gray-600 tabular-nums">
                            {u.calls.toLocaleString()}
                          </td>
                          <td className="py-2 pr-4 text-right text-gray-600 tabular-nums">
                            {formatTokens(u.tokens)}
                          </td>
                          <td className="py-2 pr-4 text-right text-gray-900 tabular-nums font-medium">
                            {formatCost(u.cost)}
                          </td>
                          <td className="py-2 text-right text-gray-500 tabular-nums">
                            {pct.toFixed(1)}%
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      ) : (
        <p className="text-sm text-gray-500 text-center py-8">No cost data available.</p>
      )}
    </div>
  )
}
