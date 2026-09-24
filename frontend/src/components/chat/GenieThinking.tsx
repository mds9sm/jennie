/**
 * Genie Thinking — Goose-style investigation trail.
 * Shows an accumulated step log so users see what Genie is doing at each stage.
 */

import { Search, Database, GitBranch, BookOpen, Cloud, Code, MessageSquare, CheckCircle2, Loader2, BarChart3, FileText } from 'lucide-react'

export interface ThinkingStep {
  id: string
  label: string
  detail?: string  // e.g. "cut_session" or SQL snippet
  tool?: string
  status: 'running' | 'done'
  timestamp: number
}

const TOOL_ICONS: Record<string, React.ElementType> = {
  search_tables: Search,
  search_transforms: Search,
  get_table_detail: Database,
  get_transform_detail: GitBranch,
  get_table_lineage: GitBranch,
  get_view_detail: BarChart3,
  glossary_lookup: BookOpen,
  execute_query: Database,
  aws_lookup: Cloud,
  github_file: FileText,
  repo_search: Code,
  ask_data_expert: MessageSquare,
  ask_redshift_expert: MessageSquare,
  ask_knowledge_expert: MessageSquare,
}

function getIcon(tool?: string) {
  if (!tool) return Search
  return TOOL_ICONS[tool] || Search
}

export default function GenieThinking({ steps }: { steps: ThinkingStep[] }) {
  if (steps.length === 0) return null

  return (
    <div className="flex justify-start max-w-4xl mx-auto">
      <div className="w-full max-w-[80%] px-4 py-3">
        {/* Header with animated lamp */}
        <div className="flex items-center gap-2 mb-2">
          <div className="relative flex-shrink-0">
            <div className="absolute inset-0 rounded-full animate-genie-glow" />
            <img
              src="/logo.png"
              alt="Genie"
              className="h-7 w-7 rounded-full relative z-10 animate-genie-float"
            />
          </div>
          <span className="text-xs font-medium text-gray-500">Investigating</span>
          <span className="flex gap-0.5">
            <span className="w-1 h-1 bg-genie-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
            <span className="w-1 h-1 bg-genie-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
            <span className="w-1 h-1 bg-genie-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
          </span>
        </div>

        {/* Step log */}
        <div className="ml-3 border-l-2 border-gray-200 pl-3 space-y-1.5">
          {steps.map((step) => {
            const Icon = getIcon(step.tool)
            const isRunning = step.status === 'running'
            return (
              <div key={step.id} className="flex items-start gap-2 animate-fade-in">
                <div className={`mt-0.5 flex-shrink-0 ${isRunning ? 'text-genie-600' : 'text-green-500'}`}>
                  {isRunning ? (
                    <Loader2 size={13} className="animate-spin" />
                  ) : (
                    <CheckCircle2 size={13} />
                  )}
                </div>
                <div className="flex items-center gap-1.5 min-w-0">
                  <Icon size={12} className="text-gray-400 flex-shrink-0" />
                  <span className={`text-xs ${isRunning ? 'text-gray-700 font-medium' : 'text-gray-500'}`}>
                    {step.label}
                  </span>
                  {step.detail && (
                    <span className="text-[10px] text-gray-400 truncate max-w-[200px] font-mono">
                      {step.detail}
                    </span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
