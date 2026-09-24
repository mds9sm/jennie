import { useState } from 'react'
import { Check, Copy } from 'lucide-react'

interface CopyButtonProps {
  text: string
  label: string
}

function CopyButton({ text, label }: CopyButtonProps) {
  const [copied, setCopied] = useState(false)

  function handleCopy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }).catch(() => {
      window.prompt('Copy this URL:', text)
    })
  }

  return (
    <button
      onClick={handleCopy}
      className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
    >
      {copied ? <Check size={14} className="text-green-600" /> : <Copy size={14} className="text-gray-500" />}
      {copied ? 'Copied!' : label}
    </button>
  )
}

const KNOWLEDGE_MCP_URL = 'https://dev-apis.example.com/genie/mcp'
const DATA_MCP_URL = 'https://np-apis.example.com/data-mcp/mcp'

const SYSTEM_PROMPT = `You have two MCP connections for your data platform:
- Genie Knowledge (genie-knowledge): business context, lineage, glossary, DOMO metrics, event schemas, rendered pipeline SQL
- NP Data (your-org): direct Redshift query execution + MWAA logs for np and prd (via datashare)

RULES:
1. Start every data question with get_data_platform_context (Genie Knowledge).
   This gives you enriched table descriptions, DOMO metrics, and SQL patterns — write SQL on the first try.

2. Use NP Data execute_query for all Redshift queries (default).
   prd tables are accessible via datashare — use prd_dw.schema.table notation.

3. If Genie Knowledge is unavailable, use NP Data list_tables + list_columns for live schema discovery.

4. get_transform_detail returns the actual rendered SQL a pipeline runs —
   use this to understand data transformations before writing SQL.

5. Always SELECT only. Never request data modifications.`

export default function ClaudeIntegrationTab() {
  const [promptCopied, setPromptCopied] = useState(false)

  function handleCopyPrompt() {
    navigator.clipboard.writeText(SYSTEM_PROMPT).then(() => {
      setPromptCopied(true)
      setTimeout(() => setPromptCopied(false), 2000)
    }).catch(() => {
      window.prompt('Copy this system prompt:', SYSTEM_PROMPT)
    })
  }

  return (
    <div className="max-w-2xl space-y-8">
      <div>
        <h2 className="text-lg font-semibold text-gray-900 mb-1">Connect to claude.ai</h2>
        <p className="text-sm text-gray-500">
          Use claude.ai as your AI interface. Add Genie as an MCP server to give claude.ai
          access to your data catalog, lineage, glossary, and query execution.
        </p>
      </div>

      {/* Step 1 */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <span className="flex items-center justify-center w-6 h-6 rounded-full bg-genie-600 text-white text-xs font-semibold">1</span>
          <h3 className="text-sm font-semibold text-gray-800">Add MCP servers in claude.ai</h3>
        </div>
        <p className="text-sm text-gray-500 ml-8">
          Go to <strong>claude.ai → Settings → Connectors</strong> and add each server below.
          Each will ask you to sign in with Okta once.
        </p>

        <div className="ml-8 space-y-3">
          <div className="border border-gray-200 rounded-lg p-4 bg-gray-50">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider mb-1">Knowledge</p>
                <p className="text-xs text-gray-400 mb-2">Catalog, lineage, glossary, DOMO, event schemas, rendered SQL</p>
                <code className="text-sm text-gray-800 break-all">{KNOWLEDGE_MCP_URL}</code>
              </div>
              <CopyButton text={KNOWLEDGE_MCP_URL} label="Copy" />
            </div>
          </div>

          <div className="border border-gray-200 rounded-lg p-4 bg-gray-50">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider mb-1">NP Data</p>
                <p className="text-xs text-gray-400 mb-2">Direct Redshift queries · np native + prd via datashare · MWAA logs</p>
                <code className="text-sm text-gray-800 break-all">{DATA_MCP_URL}</code>
              </div>
              <CopyButton text={DATA_MCP_URL} label="Copy" />
            </div>
          </div>
        </div>
      </div>

      {/* Step 2 */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <span className="flex items-center justify-center w-6 h-6 rounded-full bg-genie-600 text-white text-xs font-semibold">2</span>
          <h3 className="text-sm font-semibold text-gray-800">Add the system prompt (admin, once)</h3>
        </div>
        <p className="text-sm text-gray-500 ml-8">
          Ask your claude.ai Team admin to paste this into <strong>Team Settings → System Prompt</strong>.
          This tells claude.ai how to use the two MCP servers.
        </p>

        <div className="ml-8">
          <div className="border border-gray-200 rounded-lg overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2 bg-gray-100 border-b border-gray-200">
              <span className="text-xs font-medium text-gray-600">System Prompt</span>
              <button
                onClick={handleCopyPrompt}
                className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-800 transition-colors"
              >
                {promptCopied ? <Check size={12} className="text-green-600" /> : <Copy size={12} />}
                {promptCopied ? 'Copied!' : 'Copy'}
              </button>
            </div>
            <pre className="p-4 text-xs text-gray-700 whitespace-pre-wrap font-mono bg-white leading-relaxed">
              {SYSTEM_PROMPT}
            </pre>
          </div>
        </div>
      </div>

      {/* Tip */}
      <div className="ml-8 rounded-lg border border-blue-100 bg-blue-50 p-4">
        <p className="text-xs text-blue-800">
          <strong>prd data:</strong> The NP Data MCP connects to np Redshift, which has prd tables available
          via datashare. Query prd data using <code className="font-mono">prd_dw.schema.table</code> notation —
          no separate prd connection needed.
        </p>
      </div>
    </div>
  )
}
