import { useState } from 'react'
import { FileCode, ChevronDown, ChevronRight, Copy, Check } from 'lucide-react'

interface FileMatch {
  file?: string
  path?: string
  lines?: { line_number?: number; content?: string; match?: boolean }[]
  matches?: string[]
  snippet?: string
}

interface CodeResultData {
  results?: FileMatch[]
  query?: string
  error?: string
  // flat result from grep-style search
  file?: string
  path?: string
  lines?: { line_number?: number; content?: string; match?: boolean }[]
  matches?: string[]
  snippet?: string
}

interface Props {
  data: CodeResultData
}

function FileSection({ file }: { file: FileMatch }) {
  const [expanded, setExpanded] = useState(true)
  const [copied, setCopied] = useState(false)
  const filePath = file.file || file.path || 'Unknown file'
  const fileName = filePath.split('/').pop() || filePath

  const lines = file.lines || []
  const hasLines = lines.length > 0
  const flatMatches = file.matches || []
  const snippet = file.snippet || ''

  function getContent(): string {
    if (hasLines) {
      return lines.map(l => `${l.line_number != null ? `${l.line_number}: ` : ''}${l.content || ''}`).join('\n')
    }
    if (flatMatches.length > 0) return flatMatches.join('\n')
    return snippet
  }

  function handleCopy() {
    navigator.clipboard.writeText(getContent())
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="border-b border-gray-100 last:border-b-0">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-gray-50 transition-colors"
      >
        {expanded ? <ChevronDown size={12} className="text-gray-400" /> : <ChevronRight size={12} className="text-gray-400" />}
        <FileCode size={12} className="text-purple-500 flex-shrink-0" />
        <span className="text-xs font-medium text-gray-700 truncate" title={filePath}>
          {fileName}
        </span>
        <span className="text-[10px] text-gray-400 truncate ml-1 hidden sm:inline" title={filePath}>
          {filePath !== fileName ? filePath : ''}
        </span>
        {hasLines && (
          <span className="ml-auto text-[10px] text-gray-400 flex-shrink-0">
            {lines.length} line{lines.length !== 1 ? 's' : ''}
          </span>
        )}
      </button>
      {expanded && (
        <div className="relative">
          <pre className="bg-gray-900 text-gray-100 text-xs font-mono px-3 py-2 overflow-x-auto max-h-64">
            {hasLines ? (
              lines.map((line, i) => (
                <div
                  key={i}
                  className={`flex ${line.match ? 'bg-yellow-900/30' : ''}`}
                >
                  {line.line_number != null && (
                    <span className="text-gray-500 select-none w-10 text-right pr-3 flex-shrink-0">
                      {line.line_number}
                    </span>
                  )}
                  <span className="whitespace-pre-wrap break-all">{line.content}</span>
                </div>
              ))
            ) : flatMatches.length > 0 ? (
              flatMatches.map((m, i) => (
                <div key={i} className="whitespace-pre-wrap">{m}</div>
              ))
            ) : (
              <span className="whitespace-pre-wrap">{snippet}</span>
            )}
          </pre>
          <button
            onClick={handleCopy}
            className="absolute top-1.5 right-1.5 inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] bg-gray-700 text-gray-300 rounded hover:bg-gray-600 transition-colors"
          >
            {copied ? <Check size={10} /> : <Copy size={10} />}
          </button>
        </div>
      )}
    </div>
  )
}

export default function CodeResultCard({ data }: Props) {
  if (data.error) {
    return (
      <div className="mt-3 border border-amber-200 rounded-lg px-3 py-2 bg-amber-50 text-xs text-amber-700">
        {data.error}
      </div>
    )
  }

  // Normalize: could be a list of results or a single result
  let files: FileMatch[] = []
  if (data.results && Array.isArray(data.results)) {
    files = data.results
  } else if (data.file || data.path || data.lines || data.matches || data.snippet) {
    files = [data as FileMatch]
  }

  if (files.length === 0) {
    return (
      <div className="mt-3 border border-gray-200 rounded-lg px-3 py-2.5 bg-gray-50 text-xs text-gray-500">
        No code results found.
      </div>
    )
  }

  return (
    <div className="mt-3 border border-gray-200 rounded-lg overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 bg-gray-50 border-b border-gray-200">
        <FileCode size={14} className="text-purple-600" />
        <span className="text-xs font-medium text-gray-700">
          {files.length} file{files.length !== 1 ? 's' : ''}
          {data.query ? ` matching "${data.query}"` : ''}
        </span>
      </div>
      <div>
        {files.map((file, i) => (
          <FileSection key={i} file={file} />
        ))}
      </div>
    </div>
  )
}
