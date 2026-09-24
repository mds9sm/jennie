/**
 * Catalog page — lists every table/view in prd_dw (dim, fact, analytics) fetched
 * via the nonprod SSO Redshift connection (np datashare to prd_dw), and lets
 * non-viewer users assign primary owner, secondary owner, and business area
 * per row. Owner/business-area dropdowns autocomplete from existing values and
 * allow free-text creation.
 */

import { Fragment, useEffect, useMemo, useState } from 'react'
import {
  Loader2,
  Search,
  AlertCircle,
  ChevronRight,
  ChevronDown,
  Table as TableIcon,
  Eye,
} from 'lucide-react'
import { fetchJSON } from '../../api/client'
import { useUser } from '../../context/UserContext'
import CreatableCombobox, { ComboOption } from '../common/CreatableCombobox'

interface CatalogRow {
  database: string
  schema: string
  name: string
  type: string
  description: string
  primary_owner: string | null
  secondary_owner: string | null
  business_area: string | null
  updated_at: string | null
  updated_by: string | null
}

interface OwnerOption {
  name: string
  email: string | null
  role: string | null
  source: string
}

interface OptionsResponse {
  owners: OwnerOption[]
  business_areas: string[]
}

interface ColumnRow {
  name: string
  type: string
  position: number
  nullable: string | boolean
}

type SchemaFilter = 'all' | 'dim' | 'fact' | 'analytics'
type TypeFilter = 'all' | 'TABLE' | 'VIEW'
type OwnerField = 'primary_owner' | 'secondary_owner' | 'business_area'

const SCHEMA_BADGE: Record<string, string> = {
  dim: 'bg-blue-50 text-blue-700 border-blue-200',
  fact: 'bg-purple-50 text-purple-700 border-purple-200',
  analytics: 'bg-amber-50 text-amber-700 border-amber-200',
}

function formatRelative(iso: string | null): string {
  if (!iso) return ''
  const ms = Date.now() - new Date(iso).getTime()
  const sec = Math.floor(ms / 1000)
  if (sec < 60) return 'just now'
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}h ago`
  const d = Math.floor(hr / 24)
  if (d < 30) return `${d}d ago`
  return new Date(iso).toLocaleDateString()
}

export default function CatalogBrowser() {
  const { user } = useUser()
  const canEdit = !!user && user.role !== 'viewer'

  const [rows, setRows] = useState<CatalogRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>('')
  const [options, setOptions] = useState<OptionsResponse>({ owners: [], business_areas: [] })

  const [search, setSearch] = useState('')
  const [schemaFilter, setSchemaFilter] = useState<SchemaFilter>('all')
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all')
  const [unownedOnly, setUnownedOnly] = useState(false)

  const [savingKey, setSavingKey] = useState<string>('')
  const [savedKey, setSavedKey] = useState<string>('')

  const [expanded, setExpanded] = useState<string>('')
  const [columnsCache, setColumnsCache] = useState<Record<string, ColumnRow[]>>({})
  const [columnsLoading, setColumnsLoading] = useState<string>('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([
      fetchJSON<{ tables: CatalogRow[]; error?: string }>('/connections/browse/prd-dw-catalog?environment=np'),
      fetchJSON<OptionsResponse>('/table-ownership/options'),
    ])
      .then(([catalog, opts]) => {
        if (cancelled) return
        if (catalog.error) setError(catalog.error)
        setRows(catalog.tables || [])
        setOptions(opts)
      })
      .catch(e => !cancelled && setError(String(e?.message || e)))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return rows.filter(r => {
      if (schemaFilter !== 'all' && r.schema !== schemaFilter) return false
      if (typeFilter !== 'all' && r.type !== typeFilter) return false
      if (unownedOnly && r.primary_owner) return false
      if (q && !r.name.toLowerCase().includes(q) && !(r.description || '').toLowerCase().includes(q)) return false
      return true
    })
  }, [rows, search, schemaFilter, typeFilter, unownedOnly])

  const unownedCount = useMemo(() => rows.filter(r => !r.primary_owner).length, [rows])

  const ownerOptions: ComboOption[] = useMemo(
    () =>
      options.owners.map(o => ({
        label: o.name,
        value: o.name,
        hint: o.email || (o.source === 'free_text' ? 'free text' : ''),
      })),
    [options.owners],
  )
  const areaOptions: ComboOption[] = useMemo(
    () => options.business_areas.map(a => ({ label: a, value: a })),
    [options.business_areas],
  )

  function rowKey(r: CatalogRow): string {
    return `${r.database}.${r.schema}.${r.name}`
  }

  async function saveOwnership(row: CatalogRow, field: OwnerField, newValue: string | null) {
    const key = rowKey(row)
    const prev = { ...row }
    setRows(rs => rs.map(x => (rowKey(x) === key ? { ...x, [field]: newValue } : x)))
    setSavingKey(`${key}:${field}`)
    try {
      const updated = await fetchJSON<CatalogRow>('/table-ownership/', {
        method: 'PUT',
        body: JSON.stringify({
          database: row.database,
          schema_name: row.schema,
          table: row.name,
          primary_owner: field === 'primary_owner' ? newValue : row.primary_owner,
          secondary_owner: field === 'secondary_owner' ? newValue : row.secondary_owner,
          business_area: field === 'business_area' ? newValue : row.business_area,
        }),
      })
      setRows(rs =>
        rs.map(x =>
          rowKey(x) === key
            ? {
                ...x,
                primary_owner: updated.primary_owner,
                secondary_owner: updated.secondary_owner,
                business_area: updated.business_area,
                updated_at: updated.updated_at,
                updated_by: updated.updated_by,
              }
            : x,
        ),
      )
      setSavingKey('')
      setSavedKey(`${key}:${field}`)
      setTimeout(() => setSavedKey(k => (k === `${key}:${field}` ? '' : k)), 1800)

      // If a brand-new value was created, refetch options so it shows up everywhere.
      const isNewOwner =
        (field === 'primary_owner' || field === 'secondary_owner') &&
        newValue &&
        !options.owners.some(o => o.name === newValue)
      const isNewArea =
        field === 'business_area' && newValue && !options.business_areas.includes(newValue)
      if (isNewOwner || isNewArea) {
        fetchJSON<OptionsResponse>('/table-ownership/options').then(setOptions).catch(() => {})
      }
    } catch (e) {
      setRows(rs => rs.map(x => (rowKey(x) === key ? prev : x)))
      setSavingKey('')
      setError(`Save failed: ${(e as Error).message}`)
      setTimeout(() => setError(''), 4000)
    }
  }

  async function toggleColumns(row: CatalogRow) {
    const key = rowKey(row)
    if (expanded === key) {
      setExpanded('')
      return
    }
    setExpanded(key)
    if (columnsCache[key]) return
    setColumnsLoading(key)
    try {
      const res = await fetchJSON<{ columns: ColumnRow[] }>(
        `/connections/browse/columns?database=${encodeURIComponent(row.database)}&schema=${encodeURIComponent(row.schema)}&table=${encodeURIComponent(row.name)}&environment=np`,
      )
      setColumnsCache(c => ({ ...c, [key]: res.columns || [] }))
    } catch {
      setColumnsCache(c => ({ ...c, [key]: [] }))
    } finally {
      setColumnsLoading('')
    }
  }

  return (
    <div className="h-full flex flex-col bg-white">
      <div className="px-6 py-4 border-b border-gray-200">
        <div className="flex items-baseline justify-between">
          <div>
            <h1 className="text-lg font-semibold text-gray-900">Warehouse Catalog</h1>
            <div className="text-xs text-gray-500">
              prd_dw · dim · fact · analytics
              {!loading && (
                <>
                  <span className="mx-2 text-gray-300">·</span>
                  <span>{rows.length} tables</span>
                  <span className="mx-2 text-gray-300">·</span>
                  <span className={unownedCount > 0 ? 'text-amber-600' : 'text-gray-500'}>
                    {unownedCount} unowned
                  </span>
                </>
              )}
            </div>
          </div>
          {!canEdit && user && (
            <div className="text-[11px] text-gray-400">Read-only (viewer role)</div>
          )}
        </div>

        <div className="mt-3 flex items-center gap-2 flex-wrap">
          <div className="relative flex-1 min-w-[240px] max-w-md">
            <Search size={14} className="absolute left-2.5 top-2.5 text-gray-400" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search by name or description…"
              className="w-full pl-8 pr-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-genie-500"
            />
          </div>

          <div className="flex items-center gap-1">
            {(['all', 'dim', 'fact', 'analytics'] as SchemaFilter[]).map(s => (
              <button
                key={s}
                onClick={() => setSchemaFilter(s)}
                className={`px-2.5 py-1 text-xs rounded border transition-colors ${
                  schemaFilter === s
                    ? 'bg-genie-100 border-genie-300 text-genie-800'
                    : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
                }`}
              >
                {s}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-1">
            {(['all', 'TABLE', 'VIEW'] as TypeFilter[]).map(t => (
              <button
                key={t}
                onClick={() => setTypeFilter(t)}
                className={`px-2.5 py-1 text-xs rounded border transition-colors ${
                  typeFilter === t
                    ? 'bg-genie-100 border-genie-300 text-genie-800'
                    : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
                }`}
              >
                {t === 'all' ? 'all' : t.toLowerCase() + 's'}
              </button>
            ))}
          </div>

          <label className="flex items-center gap-1.5 text-xs text-gray-600 ml-2 cursor-pointer">
            <input
              type="checkbox"
              checked={unownedOnly}
              onChange={e => setUnownedOnly(e.target.checked)}
              className="rounded border-gray-300"
            />
            Unowned only
          </label>
        </div>
      </div>

      {error && (
        <div className="px-6 py-2 bg-red-50 border-b border-red-100 flex items-center gap-2 text-xs text-red-700">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      <div className="flex-1 overflow-auto">
        {loading ? (
          <div className="flex items-center justify-center py-16 text-gray-400 text-sm">
            <Loader2 size={16} className="animate-spin mr-2" /> Loading catalog…
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex items-center justify-center py-16 text-gray-400 text-sm">
            No tables match your filters.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-gray-50 border-b border-gray-200 text-xs text-gray-500 uppercase tracking-wide">
              <tr>
                <th className="text-left font-medium px-4 py-2 w-8"></th>
                <th className="text-left font-medium px-3 py-2 w-24">Schema</th>
                <th className="text-left font-medium px-3 py-2">Name</th>
                <th className="text-left font-medium px-3 py-2 w-20">Type</th>
                <th className="text-left font-medium px-3 py-2 w-48">Primary owner</th>
                <th className="text-left font-medium px-3 py-2 w-48">Secondary owner</th>
                <th className="text-left font-medium px-3 py-2 w-48">Business area</th>
                <th className="text-left font-medium px-3 py-2 w-28">Updated</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(r => {
                const key = rowKey(r)
                const isExpanded = expanded === key
                return (
                  <Fragment key={key}>
                    <tr className="border-b border-gray-100 hover:bg-gray-50/60">
                      <td className="px-4 py-1.5 align-top">
                        <button
                          onClick={() => toggleColumns(r)}
                          className="text-gray-400 hover:text-gray-700"
                          title={isExpanded ? 'Hide columns' : 'Show columns'}
                        >
                          {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        </button>
                      </td>
                      <td className="px-3 py-1.5 align-top">
                        <span
                          className={`inline-block px-2 py-0.5 text-[10px] font-medium border rounded ${
                            SCHEMA_BADGE[r.schema] || 'bg-gray-50 text-gray-700 border-gray-200'
                          }`}
                        >
                          {r.schema}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 align-top">
                        <div className="font-mono text-xs text-gray-800 truncate max-w-md" title={r.name}>
                          {r.name}
                        </div>
                        {r.description && (
                          <div className="text-[11px] text-gray-400 truncate max-w-md" title={r.description}>
                            {r.description}
                          </div>
                        )}
                      </td>
                      <td className="px-3 py-1.5 align-top">
                        <span
                          className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] rounded ${
                            r.type === 'VIEW'
                              ? 'bg-emerald-50 text-emerald-700'
                              : 'bg-gray-100 text-gray-600'
                          }`}
                        >
                          {r.type === 'VIEW' ? <Eye size={10} /> : <TableIcon size={10} />}
                          {r.type}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 align-top">
                        <CreatableCombobox
                          value={r.primary_owner}
                          options={ownerOptions}
                          onChange={v => saveOwnership(r, 'primary_owner', v)}
                          placeholder="—"
                          disabled={!canEdit}
                          saving={savingKey === `${key}:primary_owner`}
                          saved={savedKey === `${key}:primary_owner`}
                        />
                      </td>
                      <td className="px-3 py-1.5 align-top">
                        <CreatableCombobox
                          value={r.secondary_owner}
                          options={ownerOptions}
                          onChange={v => saveOwnership(r, 'secondary_owner', v)}
                          placeholder="—"
                          disabled={!canEdit}
                          saving={savingKey === `${key}:secondary_owner`}
                          saved={savedKey === `${key}:secondary_owner`}
                        />
                      </td>
                      <td className="px-3 py-1.5 align-top">
                        <CreatableCombobox
                          value={r.business_area}
                          options={areaOptions}
                          onChange={v => saveOwnership(r, 'business_area', v)}
                          placeholder="—"
                          disabled={!canEdit}
                          saving={savingKey === `${key}:business_area`}
                          saved={savedKey === `${key}:business_area`}
                        />
                      </td>
                      <td className="px-3 py-1.5 align-top text-[11px] text-gray-500" title={r.updated_by || ''}>
                        {formatRelative(r.updated_at)}
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr className="bg-gray-50/40 border-b border-gray-100">
                        <td></td>
                        <td colSpan={7} className="px-3 py-3">
                          {columnsLoading === key ? (
                            <div className="text-xs text-gray-400 flex items-center gap-2">
                              <Loader2 size={12} className="animate-spin" /> Loading columns…
                            </div>
                          ) : (columnsCache[key] || []).length === 0 ? (
                            <div className="text-xs text-gray-400">No columns returned.</div>
                          ) : (
                            <div className="grid grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-1 text-xs">
                              {(columnsCache[key] || []).map(c => (
                                <div key={c.name} className="flex items-center justify-between gap-2 border-b border-gray-100 py-0.5">
                                  <span className="font-mono text-gray-800 truncate">{c.name}</span>
                                  <span className="text-gray-400 text-[10px] uppercase shrink-0">{c.type}</span>
                                </div>
                              ))}
                            </div>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
