export interface ActionCard {
  type: 'sql' | 'definition' | 'pipeline' | 'impact' | 'table' | 'lineage' | 'code'
  data: unknown
}

export interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp?: string
  toolCalls?: ToolCall[]
  queryResult?: QueryResult
  actionCards?: ActionCard[]
}

export interface ToolCall {
  tool: string
  input: Record<string, unknown>
  result?: unknown
}

export interface QueryResult {
  columns: string[]
  rows: unknown[][]
  row_count: number
  execution_time_ms: number
  environment: string
  truncated: boolean
  query_id: string
}

export interface Pillar {
  id: string
  name: string
  key_tables: string[]
  key_metrics: string[]
}

export interface Environment {
  id: string
  name: string
  prefix: string
  default: boolean
  description: string
}

export interface GlossaryEntry {
  term: string
  definition: string
  formula?: string
  source_table?: string
  dag?: string
  pillar?: string
  notes?: string
  score?: number
}

export interface CatalogTable {
  name: string
  schema: string
  database?: string
  description: string
  columns: { name: string; type: string; description: string }[]
  distkey?: string
  sortkey?: string
  dag?: string
  row_count_estimate?: number
}

export interface PipelineResult {
  yaml_config: string
  sql_files: Record<string, string>
  explanation: string
}

export interface UsageSummary {
  today: {
    capability: string
    call_count: number
    total_input_tokens: number
    total_output_tokens: number
    total_cost: number
  }[]
  totals: {
    call_count: number
    total_input_tokens: number
    total_output_tokens: number
    total_cost: number
  }
}

export interface ChatSession {
  id: string
  pillar: string | null
  title: string
  created_at: string
  updated_at: string
}

export interface QueryHistoryItem {
  id: number
  query_text: string
  environment: string
  execution_time_ms: number | null
  created_at: string
}

export interface GlossaryFeedbackItem {
  id: number
  term: string
  correction: string
  submitted_by: string
  status: string
  created_at: string
}

export type Capability =
  | 'chat'
  | 'query-runner'
  | 'pipeline-builder'
  | 'sql-optimizer'
  | 'definition-lookup'
  | 'impact-analysis'
