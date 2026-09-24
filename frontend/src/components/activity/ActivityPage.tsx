import { useState, useEffect, useMemo } from 'react'
import { Loader2, Flame, Calendar, Zap, BarChart3, Clock, X } from 'lucide-react'
import { fetchJSON } from '../../api/client'
import { useAuth } from '../../context/AuthContext'

interface DayData {
  date: string
  count: number
  capabilities: Record<string, number>
}

interface HeatmapResponse {
  days: DayData[]
  total_interactions: number
  streak_days: number
  most_active_capability: string | null
  active_days: number
}

interface StatsResponse {
  total_queries: number
  total_tokens_used: number
  total_cost: number
  favorite_pillar: string | null
  top_capabilities: { capability: string; count: number }[]
  member_since: string | null
}

interface DayDetailEvent {
  capability: string
  model: string
  input_tokens: number
  output_tokens: number
  estimated_cost: number
  created_at: string
}

interface DayDetailResponse {
  date: string
  summary: {
    count: number
    total_input: number
    total_output: number
    total_cost: number
  }
  events: DayDetailEvent[]
}

function getColor(count: number): string {
  if (count === 0) return 'bg-gray-100'
  if (count <= 3) return 'bg-green-200'
  if (count <= 7) return 'bg-green-400'
  return 'bg-green-600'
}

function getMonthLabels(weeks: string[][]): { label: string; col: number }[] {
  const labels: { label: string; col: number }[] = []
  const months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ]
  let lastMonth = -1
  for (let w = 0; w < weeks.length; w++) {
    // Use the first date in the week
    const date = weeks[w].find((d) => d !== '')
    if (!date) continue
    const month = new Date(date).getMonth()
    if (month !== lastMonth) {
      labels.push({ label: months[month], col: w })
      lastMonth = month
    }
  }
  return labels
}

export default function ActivityPage() {
  const { sessionId } = useAuth()
  const [heatmap, setHeatmap] = useState<HeatmapResponse | null>(null)
  const [stats, setStats] = useState<StatsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [tooltip, setTooltip] = useState<{ x: number; y: number; date: string; count: number } | null>(null)
  const [selectedDay, setSelectedDay] = useState<string | null>(null)
  const [dayDetail, setDayDetail] = useState<DayDetailResponse | null>(null)
  const [dayDetailLoading, setDayDetailLoading] = useState(false)

  useEffect(() => {
    async function load() {
      setLoading(true)
      try {
        const [h, s] = await Promise.all([
          fetchJSON<HeatmapResponse>(`/activity/heatmap?session_id=${encodeURIComponent(sessionId)}&days=90`),
          fetchJSON<StatsResponse>(`/activity/stats?session_id=${encodeURIComponent(sessionId)}`),
        ])
        setHeatmap(h)
        setStats(s)
      } catch {
        // silent
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [sessionId])

  // Fetch day detail when a day is selected
  useEffect(() => {
    if (!selectedDay) {
      setDayDetail(null)
      return
    }
    let cancelled = false
    async function fetchDetail() {
      setDayDetailLoading(true)
      try {
        const detail = await fetchJSON<DayDetailResponse>(
          `/activity/day-detail?date=${encodeURIComponent(selectedDay!)}`
        )
        if (!cancelled) setDayDetail(detail)
      } catch {
        if (!cancelled) setDayDetail(null)
      } finally {
        if (!cancelled) setDayDetailLoading(false)
      }
    }
    fetchDetail()
    return () => { cancelled = true }
  }, [selectedDay])

  // Build 13-week x 7-day grid
  const { weeks, dayCountMap } = useMemo(() => {
    const map: Record<string, number> = {}
    if (heatmap) {
      for (const d of heatmap.days) {
        map[d.date] = d.count
      }
    }

    const today = new Date()
    const grid: string[][] = []
    // Find the last Saturday (end of week) — weeks start on Sunday
    const todayDay = today.getDay() // 0=Sun
    const endDate = new Date(today)
    endDate.setDate(endDate.getDate() + (6 - todayDay)) // go to Saturday
    const startDate = new Date(endDate)
    startDate.setDate(startDate.getDate() - 13 * 7 + 1)

    const current = new Date(startDate)
    let week: string[] = []
    while (current <= endDate) {
      const dateStr = current.toISOString().split('T')[0]
      const isFuture = current > today
      week.push(isFuture ? '' : dateStr)
      if (week.length === 7) {
        grid.push(week)
        week = []
      }
      current.setDate(current.getDate() + 1)
    }
    if (week.length > 0) {
      while (week.length < 7) week.push('')
      grid.push(week)
    }

    return { weeks: grid, dayCountMap: map }
  }, [heatmap])

  const monthLabels = useMemo(() => getMonthLabels(weeks), [weeks])
  const dayLabels = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 size={32} className="animate-spin text-genie-600" />
      </div>
    )
  }

  const maxCapCount = stats?.top_capabilities?.[0]?.count || 1

  return (
    <div className="h-full overflow-auto p-6">
      <h2 className="text-lg font-semibold text-gray-900 mb-6">Activity</h2>

      {/* Heatmap */}
      <div className="border border-gray-200 rounded-lg p-5 mb-6 bg-white">
        <h3 className="text-sm font-semibold text-gray-900 mb-4">Contribution Heatmap</h3>

        {/* Month labels */}
        <div className="flex ml-10">
          {monthLabels.map((m, i) => (
            <div
              key={i}
              className="text-[10px] text-gray-400"
              style={{
                position: 'relative',
                left: `${m.col * 16}px`,
                marginRight: i < monthLabels.length - 1
                  ? `${((monthLabels[i + 1]?.col || m.col) - m.col) * 16 - 24}px`
                  : '0px',
              }}
            >
              {m.label}
            </div>
          ))}
        </div>

        {/* Grid */}
        <div className="flex gap-0.5 mt-1 relative">
          {/* Day labels */}
          <div className="flex flex-col gap-0.5 mr-1.5 pt-0.5">
            {dayLabels.map((d, i) => (
              <div
                key={i}
                className="h-[14px] flex items-center text-[10px] text-gray-400 leading-none"
                style={{ visibility: i % 2 === 1 ? 'visible' : 'hidden' }}
              >
                {d}
              </div>
            ))}
          </div>

          {/* Week columns */}
          {weeks.map((week, wi) => (
            <div key={wi} className="flex flex-col gap-0.5">
              {week.map((dateStr, di) => {
                const count = dateStr ? (dayCountMap[dateStr] || 0) : 0
                const isEmpty = dateStr === ''
                return (
                  <div
                    key={di}
                    className={`w-[14px] h-[14px] rounded-sm ${isEmpty ? '' : getColor(count)} ${
                      isEmpty ? '' : 'cursor-pointer'
                    } ${selectedDay === dateStr ? 'ring-2 ring-genie-600 ring-offset-1' : ''}`}
                    onClick={() => {
                      if (isEmpty) return
                      setSelectedDay(selectedDay === dateStr ? null : dateStr)
                    }}
                    onMouseEnter={(e) => {
                      if (isEmpty) return
                      const rect = e.currentTarget.getBoundingClientRect()
                      setTooltip({
                        x: rect.left + rect.width / 2,
                        y: rect.top - 8,
                        date: dateStr,
                        count,
                      })
                    }}
                    onMouseLeave={() => setTooltip(null)}
                  />
                )
              })}
            </div>
          ))}
        </div>

        {/* Legend */}
        <div className="flex items-center gap-1.5 mt-3 text-[10px] text-gray-400">
          <span>Less</span>
          <div className="w-[14px] h-[14px] rounded-sm bg-gray-100" />
          <div className="w-[14px] h-[14px] rounded-sm bg-green-200" />
          <div className="w-[14px] h-[14px] rounded-sm bg-green-400" />
          <div className="w-[14px] h-[14px] rounded-sm bg-green-600" />
          <span>More</span>
        </div>
      </div>

      {/* Day Detail Panel */}
      {selectedDay && (
        <div className="border border-gray-200 rounded-lg p-5 mb-6 bg-white">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-gray-900">
              Activity for{' '}
              {new Date(selectedDay + 'T12:00:00').toLocaleDateString('en-US', {
                weekday: 'long',
                month: 'long',
                day: 'numeric',
                year: 'numeric',
              })}
            </h3>
            <button
              onClick={() => setSelectedDay(null)}
              className="text-gray-400 hover:text-gray-600 p-1 rounded"
            >
              <X size={16} />
            </button>
          </div>

          {dayDetailLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 size={20} className="animate-spin text-genie-600" />
            </div>
          ) : dayDetail ? (
            <>
              {/* Summary cards */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
                <div className="bg-gray-50 rounded-lg p-3">
                  <span className="text-[10px] text-gray-500 uppercase">Interactions</span>
                  <p className="text-lg font-bold text-gray-900">{dayDetail.summary.count}</p>
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <span className="text-[10px] text-gray-500 uppercase">Input Tokens</span>
                  <p className="text-lg font-bold text-gray-900">
                    {(dayDetail.summary.total_input || 0) >= 1000
                      ? `${((dayDetail.summary.total_input || 0) / 1000).toFixed(1)}K`
                      : dayDetail.summary.total_input || 0}
                  </p>
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <span className="text-[10px] text-gray-500 uppercase">Output Tokens</span>
                  <p className="text-lg font-bold text-gray-900">
                    {(dayDetail.summary.total_output || 0) >= 1000
                      ? `${((dayDetail.summary.total_output || 0) / 1000).toFixed(1)}K`
                      : dayDetail.summary.total_output || 0}
                  </p>
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <span className="text-[10px] text-gray-500 uppercase">Estimated Cost</span>
                  <p className="text-lg font-bold text-gray-900">
                    ${(dayDetail.summary.total_cost || 0).toFixed(4)}
                  </p>
                </div>
              </div>

              {/* Capability breakdown */}
              {(() => {
                const capBreakdown: Record<string, number> = {}
                for (const ev of dayDetail.events) {
                  capBreakdown[ev.capability] = (capBreakdown[ev.capability] || 0) + 1
                }
                const caps = Object.entries(capBreakdown).sort((a, b) => b[1] - a[1])
                if (caps.length === 0) return null
                return (
                  <div className="mb-5">
                    <h4 className="text-xs font-semibold text-gray-700 mb-2 uppercase">By Capability</h4>
                    <div className="flex flex-wrap gap-2">
                      {caps.map(([cap, cnt]) => (
                        <span
                          key={cap}
                          className="inline-flex items-center gap-1 bg-genie-50 text-genie-700 text-xs font-medium px-2.5 py-1 rounded-full"
                        >
                          {cap}
                          <span className="bg-genie-200 text-genie-800 text-[10px] px-1.5 py-0.5 rounded-full">
                            {cnt}
                          </span>
                        </span>
                      ))}
                    </div>
                  </div>
                )
              })()}

              {/* Model breakdown badges */}
              {(() => {
                const modelBreakdown: Record<string, { calls: number; cost: number }> = {}
                for (const ev of dayDetail.events) {
                  const m = (ev.model || '').toLowerCase()
                  const family = m.includes('opus') ? 'Opus' : m.includes('haiku') ? 'Haiku' : 'Sonnet'
                  if (!modelBreakdown[family]) modelBreakdown[family] = { calls: 0, cost: 0 }
                  modelBreakdown[family].calls += 1
                  modelBreakdown[family].cost += ev.estimated_cost || 0
                }
                const models = Object.entries(modelBreakdown).sort((a, b) => b[1].cost - a[1].cost)
                if (models.length === 0) return null
                const colors: Record<string, string> = { Opus: '#8b5cf6', Sonnet: '#3b82f6', Haiku: '#22c55e' }
                return (
                  <div className="mb-5">
                    <h4 className="text-xs font-semibold text-gray-700 mb-2 uppercase">By Model</h4>
                    <div className="flex flex-wrap gap-2">
                      {models.map(([model, stats]) => (
                        <span
                          key={model}
                          className="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full"
                          style={{ backgroundColor: colors[model] + '15', color: colors[model] }}
                        >
                          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: colors[model] }} />
                          {model}
                          <span className="text-[10px] opacity-70">{stats.calls} calls · ${stats.cost.toFixed(3)}</span>
                        </span>
                      ))}
                    </div>
                  </div>
                )
              })()}

              {/* Events table */}
              <div>
                <h4 className="text-xs font-semibold text-gray-700 mb-2 uppercase">
                  Interactions {dayDetail.events.length >= 50 ? '(showing last 50)' : `(${dayDetail.events.length})`}
                </h4>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-gray-200">
                        <th className="text-left py-2 pr-3 text-gray-500 font-medium">Time</th>
                        <th className="text-left py-2 pr-3 text-gray-500 font-medium">Capability</th>
                        <th className="text-left py-2 pr-3 text-gray-500 font-medium">Model</th>
                        <th className="text-right py-2 pr-3 text-gray-500 font-medium">Input</th>
                        <th className="text-right py-2 pr-3 text-gray-500 font-medium">Output</th>
                        <th className="text-right py-2 text-gray-500 font-medium">Cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dayDetail.events.slice(0, 20).map((ev, i) => (
                        <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                          <td className="py-1.5 pr-3 text-gray-600 whitespace-nowrap">
                            <div className="flex items-center gap-1">
                              <Clock size={12} className="text-gray-400" />
                              {new Date(ev.created_at).toLocaleTimeString('en-US', {
                                hour: '2-digit',
                                minute: '2-digit',
                                second: '2-digit',
                              })}
                            </div>
                          </td>
                          <td className="py-1.5 pr-3">
                            <span className="bg-gray-100 text-gray-700 px-1.5 py-0.5 rounded text-[11px]">
                              {ev.capability}
                            </span>
                          </td>
                          <td className="py-1.5 pr-3">
                            <div className="flex items-center gap-1.5">
                              <div
                                className="w-2 h-2 rounded-full flex-shrink-0"
                                style={{
                                  backgroundColor: (ev.model || '').toLowerCase().includes('opus')
                                    ? '#8b5cf6'
                                    : (ev.model || '').toLowerCase().includes('haiku')
                                      ? '#22c55e'
                                      : '#3b82f6',
                                }}
                              />
                              <span className="text-[11px] text-gray-700 font-medium">
                                {(ev.model || '').toLowerCase().includes('opus')
                                  ? 'Opus'
                                  : (ev.model || '').toLowerCase().includes('haiku')
                                    ? 'Haiku'
                                    : 'Sonnet'}
                              </span>
                            </div>
                          </td>
                          <td className="py-1.5 pr-3 text-right text-gray-600 tabular-nums">
                            {(ev.input_tokens || 0).toLocaleString()}
                          </td>
                          <td className="py-1.5 pr-3 text-right text-gray-600 tabular-nums">
                            {(ev.output_tokens || 0).toLocaleString()}
                          </td>
                          <td className="py-1.5 text-right text-gray-600 tabular-nums">
                            ${(ev.estimated_cost || 0).toFixed(4)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          ) : (
            <p className="text-sm text-gray-500 py-4 text-center">No data for this day.</p>
          )}
        </div>
      )}

      {/* Tooltip */}
      {tooltip && (
        <div
          className="fixed z-50 bg-gray-900 text-white text-xs rounded-lg px-3 py-1.5 pointer-events-none shadow-lg"
          style={{
            left: tooltip.x,
            top: tooltip.y,
            transform: 'translate(-50%, -100%)',
          }}
        >
          <strong>{tooltip.count}</strong> interaction{tooltip.count !== 1 ? 's' : ''} on{' '}
          {new Date(tooltip.date + 'T12:00:00').toLocaleDateString('en-US', {
            weekday: 'short',
            month: 'short',
            day: 'numeric',
          })}
        </div>
      )}

      {/* Stats cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="border border-gray-200 rounded-lg p-4 bg-white">
          <div className="flex items-center gap-2 mb-2">
            <BarChart3 size={16} className="text-genie-600" />
            <span className="text-xs font-medium text-gray-500 uppercase">Total Interactions</span>
          </div>
          <p className="text-2xl font-bold text-gray-900">{heatmap?.total_interactions ?? 0}</p>
        </div>

        <div className="border border-gray-200 rounded-lg p-4 bg-white">
          <div className="flex items-center gap-2 mb-2">
            <Calendar size={16} className="text-genie-600" />
            <span className="text-xs font-medium text-gray-500 uppercase">Active Days</span>
          </div>
          <p className="text-2xl font-bold text-gray-900">{heatmap?.active_days ?? 0}</p>
        </div>

        <div className="border border-gray-200 rounded-lg p-4 bg-white">
          <div className="flex items-center gap-2 mb-2">
            <Flame size={16} className="text-orange-500" />
            <span className="text-xs font-medium text-gray-500 uppercase">Current Streak</span>
          </div>
          <p className="text-2xl font-bold text-gray-900">
            {heatmap?.streak_days ?? 0} <span className="text-sm font-normal text-gray-500">days</span>
          </p>
        </div>

        <div className="border border-gray-200 rounded-lg p-4 bg-white">
          <div className="flex items-center gap-2 mb-2">
            <Zap size={16} className="text-yellow-500" />
            <span className="text-xs font-medium text-gray-500 uppercase">Most Used</span>
          </div>
          <p className="text-lg font-bold text-gray-900 truncate">
            {heatmap?.most_active_capability ?? 'N/A'}
          </p>
        </div>
      </div>

      {/* Capability breakdown */}
      {stats && stats.top_capabilities.length > 0 && (
        <div className="border border-gray-200 rounded-lg p-5 bg-white mb-6">
          <h3 className="text-sm font-semibold text-gray-900 mb-4">Capability Breakdown</h3>
          <div className="space-y-3">
            {stats.top_capabilities.map((cap) => (
              <div key={cap.capability}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm text-gray-700">{cap.capability}</span>
                  <span className="text-xs text-gray-500">{cap.count}</span>
                </div>
                <div className="w-full bg-gray-100 rounded-full h-2">
                  <div
                    className="bg-genie-600 h-2 rounded-full transition-all duration-500"
                    style={{ width: `${(cap.count / maxCapCount) * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Additional stats */}
      {stats && (
        <div className="border border-gray-200 rounded-lg p-5 bg-white">
          <h3 className="text-sm font-semibold text-gray-900 mb-4">Usage Summary</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-xs text-gray-500 uppercase">Total Queries</span>
              <p className="text-lg font-semibold text-gray-900">{stats.total_queries}</p>
            </div>
            <div>
              <span className="text-xs text-gray-500 uppercase">Tokens Used</span>
              <p className="text-lg font-semibold text-gray-900">
                {stats.total_tokens_used >= 1_000_000
                  ? `${(stats.total_tokens_used / 1_000_000).toFixed(1)}M`
                  : stats.total_tokens_used >= 1_000
                    ? `${(stats.total_tokens_used / 1_000).toFixed(1)}K`
                    : stats.total_tokens_used}
              </p>
            </div>
            <div>
              <span className="text-xs text-gray-500 uppercase">Estimated Cost</span>
              <p className="text-lg font-semibold text-gray-900">${stats.total_cost.toFixed(2)}</p>
            </div>
            <div>
              <span className="text-xs text-gray-500 uppercase">Favorite Pillar</span>
              <p className="text-lg font-semibold text-gray-900">{stats.favorite_pillar ?? 'N/A'}</p>
            </div>
          </div>
          {stats.member_since && (
            <p className="mt-4 text-xs text-gray-400">
              Member since {new Date(stats.member_since).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
