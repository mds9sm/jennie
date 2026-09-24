import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { Search, ZoomIn, ZoomOut, Maximize2, Loader2, Layers, ChevronLeft, ChevronRight, Minus, Plus } from 'lucide-react'
import { fetchJSON } from '../../api/client'

interface LineageData {
  [table: string]: { upstream: string[]; downstream: string[] }
}

interface GraphNode {
  id: string
  label: string
  schema: string
  x: number
  y: number
  col: number
  type: 'upstream' | 'root' | 'downstream'
  depth: number
}

interface GraphEdge {
  from: string
  to: string
}

const NODE_W = 200
const NODE_H = 36
const COL_GAP = 260
const ROW_GAP = 48

const COLORS = {
  upstream: { fill: '#0e7490', text: '#fff' },
  root: { fill: '#7c3aed', text: '#fff' },
  downstream: { fill: '#047857', text: '#fff' },
}

function shortName(fq: string): string {
  return fq.split('.').pop() || fq
}
function schemaPrefix(fq: string): string {
  const parts = fq.split('.')
  return parts.length > 1 ? parts.slice(0, -1).join('.') : ''
}

export default function LineageGraph() {
  const [lineage, setLineage] = useState<LineageData>({})
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [selectedTable, setSelectedTable] = useState<string | null>(null)
  const [upDepth, setUpDepth] = useState(1)
  const [downDepth, setDownDepth] = useState(1)
  const [viewMode, setViewMode] = useState<'tables' | 'dags'>('tables')
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 40, y: 40 })
  const [dragging, setDragging] = useState(false)
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 })
  const searchRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    fetchJSON<LineageData>('/catalog/lineage')
      .then(setLineage)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  // Separate tables from DAG names
  const { tableKeys, dagKeys } = useMemo(() => {
    const tables: string[] = []
    const dags: string[] = []
    for (const key of Object.keys(lineage)) {
      if (key.includes('.') && !/^[A-Z]/.test(key) && !key.startsWith('TRANSFORM') && !key.startsWith('DOMO')) {
        tables.push(key)
      } else {
        dags.push(key)
      }
    }
    return { tableKeys: tables.sort(), dagKeys: dags.sort() }
  }, [lineage])

  const activeKeys = viewMode === 'tables' ? tableKeys : dagKeys

  // Autocomplete suggestions — match both directions:
  // key contains query (user types partial) OR query contains key (user types fully-qualified name but key is short-form)
  useEffect(() => {
    if (!search.trim()) { setSuggestions([]); return }
    const q = search.toLowerCase()
    // Strip common database prefixes so "prd_dw.fact.x" also matches "fact.x"
    const qVariants = [q]
    const dbPrefixMatch = q.match(/^(prd_\w+|np_\w+)\.(.*)/);
    if (dbPrefixMatch) qVariants.push(dbPrefixMatch[2])
    const matches = activeKeys.filter(k => {
      const kl = k.toLowerCase()
      return qVariants.some(qv => kl.includes(qv) || qv.includes(kl))
    }).slice(0, 12)
    setSuggestions(matches)
  }, [search, activeKeys])

  function selectTable(t: string) {
    setSelectedTable(t)
    setSearch('')
    setSuggestions([])
    setShowSuggestions(false)
    setPan({ x: 40, y: 40 })
    setZoom(1)
  }

  // Build graph with configurable depth
  const { nodes, edges, svgW, svgH } = useMemo(() => {
    if (!selectedTable || !lineage[selectedTable]) return { nodes: [], edges: [], svgW: 800, svgH: 400 }

    const nodeMap = new Map<string, GraphNode>()
    const edgeList: GraphEdge[] = []
    const visited = new Set<string>()

    function traverse(table: string, direction: 'up' | 'down', depth: number, maxDepth: number) {
      const key = `${direction}:${table}`
      if (visited.has(key) || depth >= maxDepth) return
      visited.add(key)

      const deps = lineage[table]
      if (!deps) return

      const neighbors = direction === 'up' ? (deps.upstream || []) : (deps.downstream || [])
      for (const n of neighbors) {
        if (!nodeMap.has(n)) {
          nodeMap.set(n, {
            id: n, label: shortName(n), schema: schemaPrefix(n),
            x: 0, y: 0,
            col: direction === 'up' ? -(depth + 1) : (depth + 1),
            type: direction === 'up' ? 'upstream' : 'downstream',
            depth: depth + 1,
          })
        }
        if (direction === 'up') {
          edgeList.push({ from: n, to: table })
        } else {
          edgeList.push({ from: table, to: n })
        }
        traverse(n, direction, depth + 1, maxDepth)
      }
    }

    // Root
    nodeMap.set(selectedTable, {
      id: selectedTable, label: shortName(selectedTable), schema: schemaPrefix(selectedTable),
      x: 0, y: 0, col: 0, type: 'root', depth: 0,
    })

    traverse(selectedTable, 'up', 0, upDepth)
    traverse(selectedTable, 'down', 0, downDepth)

    // Layout
    const columns = new Map<number, GraphNode[]>()
    for (const node of nodeMap.values()) {
      if (!columns.has(node.col)) columns.set(node.col, [])
      columns.get(node.col)!.push(node)
    }

    const sortedCols = [...columns.keys()].sort((a, b) => a - b)
    const minCol = sortedCols[0] || 0
    let maxRowCount = 0

    for (const col of sortedCols) {
      const nodesInCol = columns.get(col)!
      maxRowCount = Math.max(maxRowCount, nodesInCol.length)
      nodesInCol.forEach((node, i) => {
        node.x = (col - minCol) * COL_GAP + 20
        node.y = i * ROW_GAP + 20
      })
    }

    // Center root
    const root = nodeMap.get(selectedTable)!
    root.y = Math.max(0, (maxRowCount - 1) * ROW_GAP / 2)

    const w = sortedCols.length * COL_GAP + 60
    const h = maxRowCount * ROW_GAP + 80

    return { nodes: [...nodeMap.values()], edges: edgeList, svgW: Math.max(800, w), svgH: Math.max(300, h) }
  }, [selectedTable, lineage, upDepth, downDepth])

  // Count neighbors for info display
  const neighborInfo = useMemo(() => {
    if (!selectedTable || !lineage[selectedTable]) return null
    const deps = lineage[selectedTable]
    return {
      upstream: deps.upstream?.length || 0,
      downstream: deps.downstream?.length || 0,
    }
  }, [selectedTable, lineage])

  function handleMouseDown(e: React.MouseEvent) {
    if (e.button !== 0) return
    setDragging(true)
    setDragStart({ x: e.clientX - pan.x, y: e.clientY - pan.y })
  }
  function handleMouseMove(e: React.MouseEvent) {
    if (!dragging) return
    setPan({ x: e.clientX - dragStart.x, y: e.clientY - dragStart.y })
  }
  function handleMouseUp() { setDragging(false) }
  function handleWheel(e: React.WheelEvent) {
    e.preventDefault()
    setZoom(z => Math.max(0.3, Math.min(2.5, z - e.deltaY * 0.001)))
  }

  if (loading) {
    return <div className="flex items-center justify-center h-full"><Loader2 className="animate-spin text-gray-400" /></div>
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="border-b border-gray-200 px-6 pt-5 pb-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Data Lineage</h2>
            <p className="text-sm text-gray-500">
              {tableKeys.length} tables, {dagKeys.length} DAGs with lineage
            </p>
          </div>
          <div className="flex gap-1">
            <button onClick={() => setZoom(z => Math.min(z + 0.15, 2.5))} className="p-2 border border-gray-300 rounded hover:bg-gray-50"><ZoomIn size={14} /></button>
            <button onClick={() => setZoom(z => Math.max(z - 0.15, 0.3))} className="p-2 border border-gray-300 rounded hover:bg-gray-50"><ZoomOut size={14} /></button>
            <button onClick={() => { setZoom(1); setPan({ x: 40, y: 40 }) }} className="p-2 border border-gray-300 rounded hover:bg-gray-50"><Maximize2 size={14} /></button>
          </div>
        </div>

        {/* Controls row */}
        <div className="flex items-center gap-3 flex-wrap">
          {/* View toggle */}
          <div className="flex border border-gray-300 rounded-lg overflow-hidden">
            {(['tables', 'dags'] as const).map(mode => (
              <button key={mode} onClick={() => { setViewMode(mode); setSelectedTable(null) }}
                className={`px-3 py-1.5 text-xs ${viewMode === mode ? 'bg-genie-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>
                {mode === 'tables' ? `Tables (${tableKeys.length})` : `DAGs (${dagKeys.length})`}
              </button>
            ))}
          </div>

          {/* Search with autocomplete */}
          <div className="relative flex-1 max-w-md">
            <Search size={14} className="absolute left-2.5 top-2.5 text-gray-400" />
            <input ref={searchRef} value={search} onChange={e => { setSearch(e.target.value); setShowSuggestions(true) }}
              placeholder={`Search ${viewMode}...`}
              className="w-full pl-8 pr-3 py-2 text-sm border border-gray-300 rounded-lg"
              onFocus={() => setShowSuggestions(true)}
              onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
              onKeyDown={e => {
                if (e.key === 'Enter') {
                  if (suggestions.length > 0) {
                    selectTable(suggestions[0])
                  } else {
                    const q = search.trim().toLowerCase()
                    const exact = activeKeys.find(k => k.toLowerCase() === q)
                    if (exact) selectTable(exact)
                  }
                }
              }}
            />
            {showSuggestions && suggestions.length > 0 && (
              <div className="absolute top-full left-0 right-0 bg-white border border-gray-200 rounded-lg shadow-lg mt-1 z-20 max-h-64 overflow-auto">
                {suggestions.map(s => {
                  const deps = lineage[s]
                  const up = deps?.upstream?.length || 0
                  const down = deps?.downstream?.length || 0
                  return (
                    <button key={s} onClick={() => selectTable(s)}
                      className="w-full text-left px-3 py-2 text-xs hover:bg-genie-50 border-b border-gray-50 flex justify-between">
                      <span className="font-mono truncate">{s}</span>
                      <span className="text-gray-400 ml-2 whitespace-nowrap">{up}↑ {down}↓</span>
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          {/* Depth controls */}
          <div className="flex items-center gap-2 border border-gray-300 rounded-lg px-2 py-1">
            <span className="text-[10px] text-gray-500">Upstream</span>
            <button onClick={() => setUpDepth(d => Math.max(0, d - 1))} className="p-0.5 hover:bg-gray-100 rounded"><Minus size={12} /></button>
            <span className="text-xs font-mono w-4 text-center">{upDepth}</span>
            <button onClick={() => setUpDepth(d => Math.min(5, d + 1))} className="p-0.5 hover:bg-gray-100 rounded"><Plus size={12} /></button>
          </div>
          <div className="flex items-center gap-2 border border-gray-300 rounded-lg px-2 py-1">
            <span className="text-[10px] text-gray-500">Downstream</span>
            <button onClick={() => setDownDepth(d => Math.max(0, d - 1))} className="p-0.5 hover:bg-gray-100 rounded"><Minus size={12} /></button>
            <span className="text-xs font-mono w-4 text-center">{downDepth}</span>
            <button onClick={() => setDownDepth(d => Math.min(5, d + 1))} className="p-0.5 hover:bg-gray-100 rounded"><Plus size={12} /></button>
          </div>
        </div>

        {/* Selected info */}
        {selectedTable && neighborInfo && (
          <div className="mt-2 flex items-center gap-3 text-xs">
            <span className="font-mono font-medium text-gray-800">{selectedTable}</span>
            <span className="text-teal-600">{neighborInfo.upstream} upstream</span>
            <span className="text-green-600">{neighborInfo.downstream} downstream</span>
            <span className="text-gray-400">showing {upDepth}↑ {downDepth}↓</span>
          </div>
        )}
      </div>

      {/* Graph canvas */}
      <div className="flex-1 bg-gray-50 overflow-hidden"
        style={{ cursor: dragging ? 'grabbing' : 'grab' }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onWheel={handleWheel}>
        {selectedTable && nodes.length > 0 ? (
          <svg width="100%" height="100%">
            <g transform={`translate(${pan.x},${pan.y}) scale(${zoom})`}>
              <defs>
                <marker id="arrow" viewBox="0 0 10 7" refX="10" refY="3.5"
                  markerWidth="7" markerHeight="5" orient="auto">
                  <polygon points="0 0, 10 3.5, 0 7" fill="#94a3b8" />
                </marker>
              </defs>

              {/* Depth column labels */}
              {Array.from(new Set(nodes.map(n => n.col))).sort((a, b) => a - b).map(col => {
                const x = nodes.find(n => n.col === col)?.x || 0
                const label = col < 0 ? `↑ Level ${-col}` : col > 0 ? `↓ Level ${col}` : 'Selected'
                return (
                  <text key={col} x={x + NODE_W / 2} y={8} textAnchor="middle"
                    fill="#9ca3af" fontSize={9} fontWeight={500}>
                    {label}
                  </text>
                )
              })}

              {/* Edges */}
              {edges.map((e, i) => {
                const from = nodes.find(n => n.id === e.from)
                const to = nodes.find(n => n.id === e.to)
                if (!from || !to) return null
                const x1 = from.x + NODE_W
                const y1 = from.y + NODE_H / 2
                const x2 = to.x
                const y2 = to.y + NODE_H / 2
                const cx = (x1 + x2) / 2
                return (
                  <path key={i}
                    d={`M${x1},${y1} C${cx},${y1} ${cx},${y2} ${x2},${y2}`}
                    stroke="#d1d5db" strokeWidth={1.5} fill="none"
                    markerEnd="url(#arrow)" />
                )
              })}

              {/* Nodes */}
              {nodes.map(node => {
                const color = COLORS[node.type]
                const isRoot = node.type === 'root'
                const hasLineage = !!lineage[node.id]
                return (
                  <g key={node.id} className={hasLineage && !isRoot ? 'cursor-pointer' : ''}
                    onClick={() => { if (hasLineage && !isRoot) selectTable(node.id) }}>
                    <rect x={node.x} y={node.y} width={NODE_W} height={NODE_H}
                      rx={4} fill={color.fill}
                      stroke={isRoot ? '#fff' : 'transparent'} strokeWidth={isRoot ? 2 : 0}
                      opacity={isRoot ? 1 : 0.9} />
                    <text x={node.x + 8} y={node.y + 14}
                      fill={color.text} fontSize={10} fontWeight={600}
                      fontFamily="ui-monospace, monospace">
                      {node.label.length > 24 ? node.label.slice(0, 22) + '..' : node.label}
                    </text>
                    <text x={node.x + 8} y={node.y + 26}
                      fill="rgba(255,255,255,0.55)" fontSize={8}
                      fontFamily="ui-monospace, monospace">
                      {node.schema}
                    </text>
                    {/* Navigable indicator */}
                    {hasLineage && !isRoot && (
                      <circle cx={node.x + NODE_W - 10} cy={node.y + NODE_H / 2} r={3}
                        fill="rgba(255,255,255,0.4)" />
                    )}
                  </g>
                )
              })}
            </g>

            {/* Legend */}
            <g transform="translate(16, 16)">
              <rect x={0} y={0} width={280} height={24} rx={4} fill="rgba(255,255,255,0.9)" />
              {[
                { color: COLORS.upstream.fill, label: 'Upstream (sources)' },
                { color: COLORS.root.fill, label: 'Selected' },
                { color: COLORS.downstream.fill, label: 'Downstream (consumers)' },
              ].map((item, i) => (
                <g key={i} transform={`translate(${8 + i * 92}, 7)`}>
                  <rect x={0} y={0} width={8} height={8} rx={2} fill={item.color} />
                  <text x={12} y={8} fontSize={8} fill="#6b7280">{item.label}</text>
                </g>
              ))}
            </g>
          </svg>
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-gray-400">
            <Layers size={32} className="mb-2" />
            <p className="text-sm">Search for a table to view its lineage</p>
            <p className="text-xs mt-1">Use +/- to adjust upstream and downstream depth</p>
          </div>
        )}
      </div>
    </div>
  )
}
