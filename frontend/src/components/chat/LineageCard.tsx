import { GitBranch, ArrowRight, ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'

interface LineageData {
  table_name?: string
  upstream?: string[]
  downstream?: string[]
  upstream_details?: { name: string; schema?: string; type?: string }[]
  downstream_details?: { name: string; schema?: string; type?: string }[]
  depth?: number
  error?: string
}

interface Props {
  data: LineageData
  onTableClick?: (tableName: string) => void
}

function TableNode({ name, type, onClick }: { name: string; type?: string; onClick?: () => void }) {
  return (
    <button
      onClick={onClick}
      className="group flex items-center gap-1.5 px-2 py-1 rounded border border-gray-200 bg-white hover:border-genie-300 hover:bg-genie-50 transition-all text-left min-w-0"
    >
      <span className="text-xs font-mono text-gray-800 group-hover:text-genie-700 truncate transition-colors">
        {name}
      </span>
      {type && (
        <span className={`text-[9px] font-medium px-1 py-0.5 rounded flex-shrink-0 ${
          type.toLowerCase() === 'fact' ? 'bg-indigo-50 text-indigo-600' :
          type.toLowerCase() === 'dimension' || type.toLowerCase() === 'dim' ? 'bg-teal-50 text-teal-600' :
          type.toLowerCase() === 'view' ? 'bg-purple-50 text-purple-600' :
          'bg-gray-50 text-gray-500'
        }`}>
          {type}
        </span>
      )}
    </button>
  )
}

function TableList({ tables, details, onTableClick, initialShow = 8 }: {
  tables: string[]
  details?: { name: string; schema?: string; type?: string }[]
  onTableClick?: (name: string) => void
  initialShow?: number
}) {
  const [expanded, setExpanded] = useState(false)
  const visible = expanded ? tables : tables.slice(0, initialShow)
  const hasMore = tables.length > initialShow

  return (
    <div className="space-y-1">
      {visible.map((table, i) => {
        const detail = details?.find(d => d.name === table)
        return (
          <TableNode
            key={i}
            name={table}
            type={detail?.type}
            onClick={() => onTableClick?.(table)}
          />
        )
      })}
      {hasMore && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1 text-[11px] text-genie-600 hover:text-genie-700 font-medium transition-colors mt-1"
        >
          {expanded ? (
            <><ChevronDown size={12} /> Show fewer</>
          ) : (
            <><ChevronRight size={12} /> +{tables.length - initialShow} more</>
          )}
        </button>
      )}
    </div>
  )
}

export default function LineageCard({ data, onTableClick }: Props) {
  if (data.error) {
    return (
      <div className="mt-3 border border-amber-200 rounded-lg px-3 py-2 bg-amber-50 text-xs text-amber-700">
        {data.error}
      </div>
    )
  }

  const hasUpstream = data.upstream && data.upstream.length > 0
  const hasDownstream = data.downstream && data.downstream.length > 0

  if (!hasUpstream && !hasDownstream) return null

  return (
    <div className="mt-3 border border-gray-200 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 bg-gray-50 border-b border-gray-200">
        <GitBranch size={14} className="text-genie-600" />
        <span className="text-xs font-medium text-gray-700">
          Lineage{data.table_name ? `: ${data.table_name}` : ''}
        </span>
        {data.depth != null && (
          <span className="text-[10px] text-gray-400 ml-auto">depth {data.depth}</span>
        )}
      </div>

      {/* Lineage visualization */}
      <div className="px-3 py-3">
        <div className="flex items-start gap-3">
          {/* Upstream */}
          {hasUpstream && (
            <div className="flex-1 min-w-0">
              <div className="text-[10px] font-medium text-gray-400 uppercase tracking-wider mb-2">
                Upstream ({data.upstream!.length})
              </div>
              <TableList
                tables={data.upstream!}
                details={data.upstream_details}
                onTableClick={onTableClick}
              />
            </div>
          )}

          {/* Arrow + Center table */}
          {data.table_name && (
            <div className="flex flex-col items-center gap-1 pt-5 flex-shrink-0">
              {hasUpstream && <ArrowRight size={14} className="text-gray-400" />}
              <div className="px-3 py-1.5 rounded-lg bg-genie-100 border-2 border-genie-300 text-xs font-mono font-bold text-genie-800 whitespace-nowrap">
                {data.table_name}
              </div>
              {hasDownstream && <ArrowRight size={14} className="text-gray-400" />}
            </div>
          )}

          {/* Downstream */}
          {hasDownstream && (
            <div className="flex-1 min-w-0">
              <div className="text-[10px] font-medium text-gray-400 uppercase tracking-wider mb-2">
                Downstream ({data.downstream!.length})
              </div>
              <TableList
                tables={data.downstream!}
                details={data.downstream_details}
                onTableClick={onTableClick}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
