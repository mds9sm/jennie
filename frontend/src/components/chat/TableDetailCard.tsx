import { useState } from 'react'
import { Database, ChevronDown, ChevronUp, Search, Table2, Layers } from 'lucide-react'

interface ColumnInfo {
  column_name?: string
  name?: string
  data_type?: string
  type?: string
  description?: string
  classification?: string
}

interface TableResult {
  schema?: string
  name?: string
  table_name?: string
  description?: string
  columns?: ColumnInfo[]
  column_count?: number
  row_count?: number
  row_count_estimate?: number
  dag?: string
  schedule?: string
  distkey?: string
  sortkey?: string
  classification?: string
  knowledge_sources?: string[]
}

interface TableSearchData {
  results?: TableResult[]
  error?: string
}

interface Props {
  data: TableSearchData & TableResult
  onTableClick?: (tableName: string) => void
}

const TYPE_COLORS: Record<string, string> = {
  bigint: 'bg-blue-100 text-blue-700',
  integer: 'bg-blue-100 text-blue-700',
  int: 'bg-blue-100 text-blue-700',
  smallint: 'bg-blue-100 text-blue-700',
  int4: 'bg-blue-100 text-blue-700',
  int8: 'bg-blue-100 text-blue-700',
  numeric: 'bg-blue-100 text-blue-700',
  decimal: 'bg-blue-100 text-blue-700',
  float: 'bg-blue-100 text-blue-700',
  double: 'bg-blue-100 text-blue-700',
  'double precision': 'bg-blue-100 text-blue-700',
  real: 'bg-blue-100 text-blue-700',

  varchar: 'bg-green-100 text-green-700',
  'character varying': 'bg-green-100 text-green-700',
  text: 'bg-green-100 text-green-700',
  char: 'bg-green-100 text-green-700',
  nvarchar: 'bg-green-100 text-green-700',
  bpchar: 'bg-green-100 text-green-700',

  date: 'bg-amber-100 text-amber-700',
  timestamp: 'bg-amber-100 text-amber-700',
  'timestamp without time zone': 'bg-amber-100 text-amber-700',
  'timestamp with time zone': 'bg-amber-100 text-amber-700',
  timestamptz: 'bg-amber-100 text-amber-700',

  boolean: 'bg-gray-100 text-gray-600',
  bool: 'bg-gray-100 text-gray-600',

  super: 'bg-purple-100 text-purple-700',
  json: 'bg-purple-100 text-purple-700',
  jsonb: 'bg-purple-100 text-purple-700',
}

const CLASSIFICATION_COLORS: Record<string, string> = {
  primary_key: 'bg-yellow-100 text-yellow-800',
  pk: 'bg-yellow-100 text-yellow-800',
  foreign_key: 'bg-orange-100 text-orange-800',
  fk: 'bg-orange-100 text-orange-800',
  metric: 'bg-indigo-100 text-indigo-700',
  dimension: 'bg-teal-100 text-teal-700',
  date: 'bg-amber-100 text-amber-700',
  flag: 'bg-gray-100 text-gray-600',
}

const CLASSIFICATION_LABELS: Record<string, string> = {
  primary_key: 'PK',
  pk: 'PK',
  foreign_key: 'FK',
  fk: 'FK',
  metric: 'Metric',
  dimension: 'Dim',
  date: 'Date',
  flag: 'Flag',
}

const SOURCE_COLORS: Record<string, string> = {
  platform: 'bg-blue-50 text-blue-600',
  database: 'bg-green-50 text-green-600',
  code: 'bg-purple-50 text-purple-600',
  ai_generated: 'bg-pink-50 text-pink-600',
  mwaa: 'bg-orange-50 text-orange-600',
  repo: 'bg-gray-100 text-gray-600',
}

function formatRowCount(count: number): string {
  if (count >= 1_000_000_000) return `${(count / 1_000_000_000).toFixed(1)}B`
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`
  if (count >= 1_000) return `${(count / 1_000).toFixed(1)}K`
  return count.toLocaleString()
}

function getTypeColor(dataType: string): string {
  const normalized = (dataType || '').toLowerCase().replace(/\(.*\)/, '').trim()
  return TYPE_COLORS[normalized] || 'bg-gray-100 text-gray-600'
}

function getShortType(dataType: string): string {
  const normalized = (dataType || '').toLowerCase()
  if (normalized.includes('character varying') || normalized.includes('varchar') || normalized.includes('nvarchar')) {
    const match = normalized.match(/\((\d+)\)/)
    return match ? `varchar(${match[1]})` : 'varchar'
  }
  if (normalized.includes('timestamp')) return 'timestamp'
  if (normalized.includes('double')) return 'double'
  return normalized.replace(/\(.*\)/, '').trim()
}

function SingleTableCard({ table, onTableClick }: { table: TableResult; onTableClick?: (name: string) => void }) {
  const [expanded, setExpanded] = useState(false)
  const columns = table.columns || []
  const colCount = table.column_count || columns.length
  const rowCount = table.row_count ?? table.row_count_estimate
  const tableName = table.table_name || table.name || 'Unknown'
  const fullName = table.schema ? `${table.schema}.${tableName}` : tableName
  const classification = table.classification
  const INITIAL_SHOW = 8

  const visibleColumns = expanded ? columns : columns.slice(0, INITIAL_SHOW)
  const hasMore = columns.length > INITIAL_SHOW

  return (
    <div className="mt-3 border border-gray-200 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="px-3 py-2.5 bg-gray-50 border-b border-gray-200">
        <div className="flex items-center gap-2">
          <Database size={14} className="text-genie-600 flex-shrink-0" />
          <button
            onClick={() => onTableClick?.(fullName)}
            className="text-sm font-semibold text-gray-900 hover:text-genie-600 transition-colors truncate"
            title={fullName}
          >
            {fullName}
          </button>
          {classification && (
            <span className={`ml-auto text-[10px] font-medium px-2 py-0.5 rounded-full flex-shrink-0 ${
              classification.toLowerCase() === 'fact' ? 'bg-indigo-100 text-indigo-700' :
              classification.toLowerCase() === 'dimension' ? 'bg-teal-100 text-teal-700' :
              'bg-gray-100 text-gray-600'
            }`}>
              {classification}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 mt-1 text-[11px] text-gray-500">
          {rowCount != null && (
            <span>{formatRowCount(rowCount)} rows</span>
          )}
          {rowCount != null && colCount > 0 && <span className="text-gray-300">·</span>}
          {colCount > 0 && <span>{colCount} columns</span>}
          {table.knowledge_sources && table.knowledge_sources.length > 0 && (
            <>
              <span className="text-gray-300">·</span>
              {table.knowledge_sources.map((src, i) => (
                <span key={i} className={`text-[9px] font-medium px-1.5 py-0.5 rounded ${SOURCE_COLORS[src] || 'bg-gray-100 text-gray-500'}`}>
                  {src}
                </span>
              ))}
            </>
          )}
        </div>
      </div>

      {/* Description */}
      {table.description && (
        <div className="px-3 py-2 text-xs text-gray-700 border-b border-gray-100">
          {table.description}
        </div>
      )}

      {/* Columns */}
      {columns.length > 0 && (
        <div className="px-3 py-2">
          <div className="text-[11px] font-medium text-gray-500 mb-1.5">
            Columns{colCount > 0 ? ` (${colCount})` : ''}
          </div>
          <div className="space-y-0.5">
            {visibleColumns.map((col, i) => {
              const colName = col.column_name || col.name || ''
              const colType = col.data_type || col.type || ''
              const colClass = col.classification
              return (
                <div key={i} className="flex items-center gap-2 py-0.5 group">
                  <span className="text-xs font-mono text-gray-800 truncate min-w-0 flex-1" title={colName}>
                    {colName}
                  </span>
                  <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded flex-shrink-0 ${getTypeColor(colType)}`}>
                    {getShortType(colType)}
                  </span>
                  {colClass && CLASSIFICATION_LABELS[colClass.toLowerCase()] && (
                    <span className={`text-[9px] font-bold px-1 py-0.5 rounded flex-shrink-0 ${
                      CLASSIFICATION_COLORS[colClass.toLowerCase()] || 'bg-gray-100 text-gray-600'
                    }`}>
                      {CLASSIFICATION_LABELS[colClass.toLowerCase()]}
                    </span>
                  )}
                  {col.description && (
                    <span className="text-[10px] text-gray-400 truncate hidden group-hover:inline max-w-[200px]" title={col.description}>
                      {col.description}
                    </span>
                  )}
                </div>
              )
            })}
          </div>
          {hasMore && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="mt-1.5 flex items-center gap-1 text-[11px] text-genie-600 hover:text-genie-700 font-medium transition-colors"
            >
              {expanded ? (
                <>
                  <ChevronUp size={12} />
                  Show fewer columns
                </>
              ) : (
                <>
                  <ChevronDown size={12} />
                  Show all {columns.length} columns
                </>
              )}
            </button>
          )}
        </div>
      )}

      {/* Footer metadata */}
      {(table.dag || table.schedule || table.distkey || table.sortkey) && (
        <div className="px-3 py-2 bg-gray-50 border-t border-gray-100 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-gray-500">
          {table.dag && (
            <span className="flex items-center gap-1">
              <Layers size={10} className="text-gray-400" />
              {table.dag}
            </span>
          )}
          {table.schedule && (
            <span>{table.schedule}</span>
          )}
          {table.distkey && (
            <span>distkey: <code className="text-gray-700">{table.distkey}</code></span>
          )}
          {table.sortkey && (
            <span>sortkey: <code className="text-gray-700">{table.sortkey}</code></span>
          )}
        </div>
      )}
    </div>
  )
}

function SearchResultRow({ table, onTableClick }: { table: TableResult; onTableClick?: (name: string) => void }) {
  const tableName = table.table_name || table.name || 'Unknown'
  const fullName = table.schema ? `${table.schema}.${tableName}` : tableName
  const rowCount = table.row_count ?? table.row_count_estimate
  const colCount = table.column_count || (table.columns?.length ?? 0)

  return (
    <button
      onClick={() => onTableClick?.(fullName)}
      className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-gray-50 transition-colors group border-b border-gray-100 last:border-b-0"
    >
      <Table2 size={12} className="text-gray-400 flex-shrink-0 group-hover:text-genie-600 transition-colors" />
      <span className="text-xs font-mono font-medium text-gray-800 group-hover:text-genie-600 transition-colors truncate">
        {fullName}
      </span>
      <span className="ml-auto flex items-center gap-2 text-[10px] text-gray-400 flex-shrink-0">
        {rowCount != null && <span>{formatRowCount(rowCount)} rows</span>}
        {colCount > 0 && <span>{colCount} cols</span>}
        {table.classification && (
          <span className={`font-medium px-1.5 py-0.5 rounded ${
            table.classification.toLowerCase() === 'fact' ? 'bg-indigo-50 text-indigo-600' :
            table.classification.toLowerCase() === 'dimension' ? 'bg-teal-50 text-teal-600' :
            'bg-gray-50 text-gray-500'
          }`}>
            {table.classification}
          </span>
        )}
      </span>
    </button>
  )
}

export default function TableDetailCard({ data, onTableClick }: Props) {
  // Error state
  if (data.error) {
    return (
      <div className="mt-3 border border-amber-200 rounded-lg px-3 py-2 bg-amber-50 text-xs text-amber-700">
        {data.error}
      </div>
    )
  }

  // Search results (multiple tables)
  if (data.results && Array.isArray(data.results)) {
    if (data.results.length === 0) {
      return (
        <div className="mt-3 border border-gray-200 rounded-lg px-3 py-2.5 bg-gray-50 text-xs text-gray-500">
          No tables found.
        </div>
      )
    }

    // If only one result with columns, render as a detail card
    if (data.results.length === 1 && data.results[0].columns && data.results[0].columns.length > 0) {
      return <SingleTableCard table={data.results[0]} onTableClick={onTableClick} />
    }

    return (
      <div className="mt-3 border border-gray-200 rounded-lg overflow-hidden">
        <div className="flex items-center gap-2 px-3 py-2 bg-gray-50 border-b border-gray-200">
          <Search size={14} className="text-genie-600" />
          <span className="text-xs font-medium text-gray-700">
            {data.results.length} table{data.results.length !== 1 ? 's' : ''} found
          </span>
        </div>
        <div>
          {data.results.map((table, i) => (
            <SearchResultRow key={i} table={table} onTableClick={onTableClick} />
          ))}
        </div>
      </div>
    )
  }

  // Single table detail
  return <SingleTableCard table={data as TableResult} onTableClick={onTableClick} />
}
