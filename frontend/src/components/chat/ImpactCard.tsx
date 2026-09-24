import { useState } from 'react'
import { ChevronDown, ChevronRight, AlertTriangle } from 'lucide-react'

interface ImpactSection {
  title: string
  items: string[]
  severity: 'high' | 'medium' | 'low'
}

interface ImpactData {
  report?: string
  affected_sql_files?: string[]
  affected_dags?: string[]
  downstream_tables?: string[]
  affected_pillars?: string[]
  recommended_actions?: string[]
  sections?: ImpactSection[]
}

interface Props {
  data: ImpactData
}

function parseSections(data: ImpactData): ImpactSection[] {
  if (data.sections) return data.sections

  const sections: ImpactSection[] = []

  if (data.affected_sql_files?.length) {
    sections.push({ title: 'Affected SQL Files', items: data.affected_sql_files, severity: 'high' })
  }
  if (data.affected_dags?.length) {
    sections.push({ title: 'Affected DAGs', items: data.affected_dags, severity: 'high' })
  }
  if (data.downstream_tables?.length) {
    sections.push({ title: 'Downstream Tables', items: data.downstream_tables, severity: 'medium' })
  }
  if (data.affected_pillars?.length) {
    sections.push({ title: 'Affected Pillars', items: data.affected_pillars, severity: 'medium' })
  }
  if (data.recommended_actions?.length) {
    sections.push({ title: 'Recommended Actions', items: data.recommended_actions, severity: 'low' })
  }

  // If we only have a report string, try to parse it into sections
  if (sections.length === 0 && data.report) {
    sections.push({ title: 'Impact Report', items: [data.report], severity: 'medium' })
  }

  return sections
}

function CollapsibleSection({ section }: { section: ImpactSection }) {
  const [expanded, setExpanded] = useState(true)

  const severityColors = {
    high: 'bg-red-50 border-red-200 text-red-700',
    medium: 'bg-amber-50 border-amber-200 text-amber-700',
    low: 'bg-blue-50 border-blue-200 text-blue-700',
  }

  const badgeColors = {
    high: 'bg-red-100 text-red-700',
    medium: 'bg-amber-100 text-amber-700',
    low: 'bg-blue-100 text-blue-700',
  }

  return (
    <div className={`border rounded-md ${severityColors[section.severity]}`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium"
      >
        <div className="flex items-center gap-2">
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          {section.title}
        </div>
        <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${badgeColors[section.severity]}`}>
          {section.items.length}
        </span>
      </button>
      {expanded && (
        <div className="px-3 pb-2 space-y-1">
          {section.items.map((item, i) => (
            <div key={i} className="text-xs pl-5 whitespace-pre-wrap">
              {item}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function ImpactCard({ data }: Props) {
  const sections = parseSections(data)

  if (sections.length === 0) return null

  return (
    <div className="mt-3 border border-gray-200 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 bg-gray-50 border-b border-gray-200">
        <AlertTriangle size={14} className="text-amber-500" />
        <span className="text-xs font-medium text-gray-700">Impact Analysis</span>
      </div>

      {/* Sections */}
      <div className="p-3 space-y-2">
        {sections.map((section, i) => (
          <CollapsibleSection key={i} section={section} />
        ))}
      </div>
    </div>
  )
}
