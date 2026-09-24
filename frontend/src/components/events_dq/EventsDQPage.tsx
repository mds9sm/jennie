import { Fragment, useEffect, useMemo, useState } from 'react'
import { Loader2, AlertCircle, AlertTriangle, Info, X, ArrowRight, ShieldCheck } from 'lucide-react'
import { fetchJSON } from '../../api/client'

interface DayData {
  event_date: string
  critical_count: number
  warning_count: number
  info_count: number
  total_count: number
}

interface HeatmapResponse {
  days: DayData[]
  summary: {
    total_findings: number
    critical_findings: number
    warning_findings: number
    info_findings: number
    active_days: number
  }
  lookback_days: number
}

interface Finding {
  finding_id: string
  event_date: string
  severity: 'critical' | 'warning' | 'info'
  kind: string
  stage: string | null
  event_name: string | null
  platform: string | null
  client_version: string | null
  observed_value: number | null
  expected_low: number | null
  expected_high: number | null
  z_score: number | null
  narrative: string | null
  created_at: string
}

interface DayDetailResponse {
  date: string
  findings: Finding[]
  by_kind: Record<string, Finding[]>
  total: number
}

interface ChainStage {
  path_name: string
  stage: string
  row_count: number | null
  s3_file_count: number | null
  s3_total_bytes: number | null
  source_table: string | null
}

interface ChainFlowResponse {
  date: string
  paths: Record<string, ChainStage[]>
  findings_by_stage: Record<string, { severity: string; kind: string; narrative: string }[]>
}

interface DqSyncRow {
  run_date: string
  dag_id: string
  task_id: string
  state: string
  duration_seconds: number | null
  log_url: string | null
}

interface DqSyncResponse {
  days: number
  summary: { total_runs: number; failed_runs: number; unique_dags: number }
  by_dag: Record<string, DqSyncRow[]>
  rows: DqSyncRow[]
}

function severityColor(d: DayData): string {
  if (!d || d.total_count === 0) return 'bg-gray-100'
  if (d.critical_count > 0) return 'bg-red-500'
  if (d.warning_count > 0) return 'bg-orange-400'
  if (d.info_count > 0) return 'bg-yellow-300'
  return 'bg-gray-100'
}

function severityIcon(severity: string) {
  if (severity === 'critical') return <AlertCircle size={16} className="text-red-600" />
  if (severity === 'warning') return <AlertTriangle size={16} className="text-orange-500" />
  return <Info size={16} className="text-yellow-600" />
}

export default function EventsDQPage() {
  const [heatmap, setHeatmap] = useState<HeatmapResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedDate, setSelectedDate] = useState<string | null>(null)
  const [dayDetail, setDayDetail] = useState<DayDetailResponse | null>(null)
  const [dayLoading, setDayLoading] = useState(false)
  const [chainFlow, setChainFlow] = useState<ChainFlowResponse | null>(null)
  const [dqSync, setDqSync] = useState<DqSyncResponse | null>(null)

  const yesterday = useMemo(() => {
    const d = new Date()
    d.setUTCDate(d.getUTCDate() - 1)
    return d.toISOString().slice(0, 10)
  }, [])

  useEffect(() => {
    setLoading(true)
    Promise.all([
      fetchJSON<HeatmapResponse>('/events-dq/heatmap?days=91'),
      fetchJSON<ChainFlowResponse>(`/events-dq/chain-flow?date=${yesterday}`),
      fetchJSON<DqSyncResponse>('/events-dq/dq-sync-status?days=7'),
    ])
      .then(([h, c, d]) => {
        setHeatmap(h)
        setChainFlow(c)
        setDqSync(d)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [yesterday])

  useEffect(() => {
    if (!selectedDate) return
    setDayLoading(true)
    setDayDetail(null)
    fetchJSON<DayDetailResponse>(`/events-dq/day-detail?date=${selectedDate}`)
      .then((r) => setDayDetail(r))
      .catch((e) => setError(e.message))
      .finally(() => setDayLoading(false))
  }, [selectedDate])

  const dayMap = useMemo(() => {
    const m: Record<string, DayData> = {}
    if (!heatmap) return m
    for (const d of heatmap.days) m[d.event_date] = d
    return m
  }, [heatmap])

  const weeks = useMemo(() => {
    const today = new Date()
    today.setUTCHours(0, 0, 0, 0)
    const totalDays = heatmap?.lookback_days ?? 91
    const result: { date: string; data: DayData | null }[][] = []
    let current: { date: string; data: DayData | null }[] = []
    for (let i = totalDays - 1; i >= 0; i--) {
      const d = new Date(today)
      d.setUTCDate(today.getUTCDate() - i)
      const iso = d.toISOString().slice(0, 10)
      current.push({ date: iso, data: dayMap[iso] || null })
      if (current.length === 7) {
        result.push(current)
        current = []
      }
    }
    if (current.length) result.push(current)
    return result
  }, [heatmap, dayMap])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="animate-spin text-genie-600" size={28} />
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-8 text-red-600">
        <AlertCircle className="inline mr-2" />
        Failed to load events DQ data: {error}
      </div>
    )
  }

  return (
    <div className="flex h-full">
      <div className="flex-1 overflow-auto p-8">
        <h1 className="text-2xl font-semibold mb-2">Events Data Quality</h1>
        <p className="text-gray-500 mb-6">
          Nightly analysis of the ProductApp events pipeline — cross-stage drift, anomaly scoring,
          and release-time platform regressions.
        </p>

        {heatmap && (
          <div className="grid grid-cols-4 gap-4 mb-8">
            <StatCard label="Total findings" value={heatmap.summary.total_findings} />
            <StatCard
              label="Critical"
              value={heatmap.summary.critical_findings}
              accent="text-red-600"
            />
            <StatCard
              label="Warning"
              value={heatmap.summary.warning_findings}
              accent="text-orange-500"
            />
            <StatCard
              label="Info"
              value={heatmap.summary.info_findings}
              accent="text-yellow-600"
            />
          </div>
        )}

        {chainFlow && Object.keys(chainFlow.paths).length > 0 && (
          <div className="mb-8">
            <h2 className="text-lg font-medium mb-3">Pipeline chain flow — {yesterday}</h2>
            <div className="space-y-4">
              {Object.entries(chainFlow.paths).map(([path, stages]) => (
                <div key={path} className="bg-white border border-gray-200 rounded p-4">
                  <div className="text-sm font-medium text-gray-700 mb-3 capitalize">
                    {path.replace(/_/g, ' ')}
                  </div>
                  <div className="flex items-center gap-2 overflow-x-auto pb-2">
                    {stages.map((s, idx) => {
                      const stageFindings = Object.entries(chainFlow.findings_by_stage).flatMap(
                        ([k, v]) => (k.includes(`->${s.stage}`) || k.includes(s.stage)) ? v : []
                      )
                      const worstSev = stageFindings.find(f => f.severity === 'critical')
                        ? 'critical' : stageFindings.find(f => f.severity === 'warning')
                        ? 'warning' : null
                      const borderClass = worstSev === 'critical' ? 'border-red-400 bg-red-50'
                        : worstSev === 'warning' ? 'border-orange-300 bg-orange-50'
                        : 'border-gray-200'
                      const count = s.row_count !== null
                        ? `${(s.row_count / 1_000_000).toFixed(1)}M rows`
                        : s.s3_file_count !== null
                        ? `${s.s3_file_count} files`
                        : '—'
                      return (
                        <Fragment key={s.stage}>
                          <div className={`flex-shrink-0 border rounded p-3 min-w-[160px] ${borderClass}`}>
                            <div className="text-xs font-medium text-gray-700 truncate" title={s.stage}>{s.stage}</div>
                            <div className="text-base font-semibold mt-1">{count}</div>
                            {worstSev && (
                              <div className="text-xs mt-1 text-gray-600 truncate" title={stageFindings[0].narrative}>
                                {stageFindings[0].kind}
                              </div>
                            )}
                          </div>
                          {idx < stages.length - 1 && (
                            <ArrowRight size={20} className="text-gray-400 flex-shrink-0" />
                          )}
                        </Fragment>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {dqSync && dqSync.rows.length > 0 && (
          <div className="mb-8">
            <h2 className="text-lg font-medium mb-3 flex items-center gap-2">
              <ShieldCheck size={18} />
              dq_sync runs (last 7 days)
              <span className="text-sm font-normal text-gray-500">
                {dqSync.summary.total_runs} runs across {dqSync.summary.unique_dags} DAGs · {dqSync.summary.failed_runs} failed
              </span>
            </h2>
            <div className="bg-white border border-gray-200 rounded overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-xs text-gray-600 uppercase tracking-wider">
                  <tr>
                    <th className="px-3 py-2 text-left">DAG</th>
                    <th className="px-3 py-2 text-left">Task</th>
                    <th className="px-3 py-2 text-left">State</th>
                    <th className="px-3 py-2 text-right">Duration</th>
                    <th className="px-3 py-2 text-left">Run date</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {dqSync.rows.slice(0, 30).map((r, i) => (
                    <tr key={i} className={r.state === 'failed' ? 'bg-red-50' : ''}>
                      <td className="px-3 py-1.5 text-xs font-mono text-gray-700">{r.dag_id}</td>
                      <td className="px-3 py-1.5 text-xs font-mono text-gray-600">{r.task_id}</td>
                      <td className="px-3 py-1.5">
                        <span className={`text-xs px-1.5 py-0.5 rounded ${
                          r.state === 'success' ? 'bg-green-100 text-green-800'
                          : r.state === 'failed' ? 'bg-red-100 text-red-800'
                          : 'bg-gray-100 text-gray-700'
                        }`}>{r.state}</span>
                      </td>
                      <td className="px-3 py-1.5 text-xs text-gray-600 text-right">
                        {r.duration_seconds !== null ? `${r.duration_seconds.toFixed(0)}s` : '—'}
                      </td>
                      <td className="px-3 py-1.5 text-xs text-gray-500">{r.run_date}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <h2 className="text-lg font-medium mb-3">Last 91 days</h2>
        <div className="bg-white border border-gray-200 rounded p-4 inline-block">
          <div className="flex gap-1">
            {weeks.map((week, wi) => (
              <div key={wi} className="flex flex-col gap-1">
                {week.map((cell) => (
                  <button
                    key={cell.date}
                    onClick={() => setSelectedDate(cell.date)}
                    title={`${cell.date}: ${cell.data?.total_count ?? 0} findings (${cell.data?.critical_count ?? 0} critical)`}
                    className={`w-3.5 h-3.5 rounded-sm transition-all hover:ring-2 hover:ring-genie-400 ${severityColor(cell.data!)} ${selectedDate === cell.date ? 'ring-2 ring-genie-600' : ''}`}
                  />
                ))}
              </div>
            ))}
          </div>
          <div className="flex items-center gap-3 mt-3 text-xs text-gray-500">
            <span>Severity:</span>
            <span className="flex items-center gap-1"><span className="w-3 h-3 bg-gray-100 rounded-sm" /> none</span>
            <span className="flex items-center gap-1"><span className="w-3 h-3 bg-yellow-300 rounded-sm" /> info</span>
            <span className="flex items-center gap-1"><span className="w-3 h-3 bg-orange-400 rounded-sm" /> warning</span>
            <span className="flex items-center gap-1"><span className="w-3 h-3 bg-red-500 rounded-sm" /> critical</span>
          </div>
        </div>
      </div>

      {selectedDate && (
        <div className="w-[480px] border-l border-gray-200 bg-gray-50 overflow-auto">
          <div className="flex items-center justify-between p-4 border-b border-gray-200 bg-white sticky top-0">
            <div>
              <div className="text-sm text-gray-500">Findings on</div>
              <div className="text-lg font-semibold">{selectedDate}</div>
            </div>
            <button
              onClick={() => setSelectedDate(null)}
              className="p-1 rounded hover:bg-gray-100"
              aria-label="Close"
            >
              <X size={18} />
            </button>
          </div>

          {dayLoading ? (
            <div className="p-8 text-center">
              <Loader2 className="animate-spin inline" />
            </div>
          ) : dayDetail && dayDetail.total === 0 ? (
            <div className="p-8 text-center text-gray-500">No findings — pipeline looked healthy.</div>
          ) : dayDetail ? (
            <div className="p-4 space-y-4">
              {Object.entries(dayDetail.by_kind).map(([kind, findings]) => (
                <div key={kind} className="bg-white border border-gray-200 rounded">
                  <div className="px-3 py-2 border-b border-gray-200 font-medium text-sm capitalize bg-gray-50">
                    {kind.replace(/_/g, ' ')} ({findings.length})
                  </div>
                  <div className="divide-y divide-gray-100">
                    {findings.map((f) => (
                      <div key={f.finding_id} className="p-3 text-sm">
                        <div className="flex items-start gap-2">
                          {severityIcon(f.severity)}
                          <div className="flex-1">
                            <div className="text-gray-900">{f.narrative || `${f.kind} finding`}</div>
                            <div className="text-xs text-gray-500 mt-1 flex flex-wrap gap-x-3">
                              {f.event_name && <span><strong>event:</strong> {f.event_name}</span>}
                              {f.platform && <span><strong>platform:</strong> {f.platform}</span>}
                              {f.client_version && <span><strong>version:</strong> {f.client_version}</span>}
                              {f.stage && <span><strong>stage:</strong> {f.stage}</span>}
                              {f.z_score !== null && <span><strong>z:</strong> {Number(f.z_score).toFixed(2)}</span>}
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value, accent }: { label: string; value: number; accent?: string }) {
  return (
    <div className="bg-white border border-gray-200 rounded p-4">
      <div className="text-xs text-gray-500 uppercase tracking-wider">{label}</div>
      <div className={`text-2xl font-semibold mt-1 ${accent || 'text-gray-900'}`}>{value}</div>
    </div>
  )
}
