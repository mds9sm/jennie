import React, { useState, useEffect, useCallback } from 'react'
import {
  GitBranch, GitCommit, GitPullRequest, ChevronRight, ChevronDown,
  FileCode, Folder, FolderPlus, RefreshCw, Save, Upload, Plus, Check, X, Diff, Loader2
} from 'lucide-react'
import { fetchJSON } from '../../api/client'

interface FileEntry {
  name: string
  path: string
  type: 'dir' | 'file'
  ext?: string
  size?: number
  children_count?: number
}

interface BranchInfo {
  name: string
  commit: string
  current: boolean
}

interface GitStatus {
  branch: string
  is_main: boolean
  changed_files: { state: string; path: string }[]
  ahead: number
  behind: number
}

// ---------------------------------------------------------------------------
// Repo File Browser
// ---------------------------------------------------------------------------

export function RepoFileBrowser({ onOpenFile, onCreateFile }: {
  onOpenFile: (path: string, content: string) => void
  onCreateFile?: (path: string, content: string) => void
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [children, setChildren] = useState<Record<string, FileEntry[]>>({})
  const [rootEntries, setRootEntries] = useState<FileEntry[]>([])
  const [loading, setLoading] = useState<Set<string>>(new Set())

  // Context menu
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; entry: FileEntry | null } | null>(null)
  // Inline input for new/rename
  const [inlineAction, setInlineAction] = useState<{
    type: 'new-file' | 'new-dir' | 'rename'
    parentPath: string   // directory context
    entry?: FileEntry    // for rename
  } | null>(null)
  const [inlineValue, setInlineValue] = useState('')

  useEffect(() => {
    loadDir('')
  }, [])

  // Close context menu on any click
  useEffect(() => {
    const close = () => setCtxMenu(null)
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [])

  async function loadDir(path: string) {
    setLoading(prev => new Set(prev).add(path))
    try {
      const res = await fetchJSON<{ entries: FileEntry[] }>(`/git/files?path=${encodeURIComponent(path)}`)
      if (path === '') {
        setRootEntries(res.entries)
      } else {
        setChildren(prev => ({ ...prev, [path]: res.entries }))
      }
    } catch { /* ignore */ }
    finally {
      setLoading(prev => { const n = new Set(prev); n.delete(path); return n })
    }
  }

  async function handleClick(entry: FileEntry) {
    if (entry.type === 'dir') {
      if (expanded.has(entry.path)) {
        setExpanded(prev => { const n = new Set(prev); n.delete(entry.path); return n })
      } else {
        if (!children[entry.path]) await loadDir(entry.path)
        setExpanded(prev => new Set(prev).add(entry.path))
      }
    } else {
      try {
        const res = await fetchJSON<{ content: string }>(`/git/file?path=${encodeURIComponent(entry.path)}`)
        onOpenFile(entry.path, res.content)
      } catch { /* ignore */ }
    }
  }

  function handleContextMenu(e: React.MouseEvent, entry: FileEntry) {
    e.preventDefault()
    e.stopPropagation()
    setCtxMenu({ x: e.clientX, y: e.clientY, entry })
  }

  function handleRootContextMenu(e: React.MouseEvent) {
    e.preventDefault()
    setCtxMenu({ x: e.clientX, y: e.clientY, entry: null })
  }

  function startInlineAction(type: 'new-file' | 'new-dir' | 'rename', parentPath: string, entry?: FileEntry) {
    setCtxMenu(null)
    if (type === 'rename' && entry) {
      setInlineValue(entry.name)
    } else {
      setInlineValue('')
    }
    setInlineAction({ type, parentPath, entry })
    // Ensure parent dir is expanded
    if (parentPath) {
      if (!children[parentPath]) loadDir(parentPath)
      setExpanded(prev => new Set(prev).add(parentPath))
    }
  }

  async function commitInlineAction() {
    if (!inlineAction || !inlineValue.trim()) { setInlineAction(null); return }
    const { type, parentPath, entry } = inlineAction
    const prefix = parentPath ? (parentPath.endsWith('/') ? parentPath : parentPath + '/') : ''

    try {
      if (type === 'new-file') {
        const fullPath = prefix + inlineValue.trim()
        if (onCreateFile) {
          onCreateFile(fullPath, '')
        }
      } else if (type === 'new-dir') {
        const dirPath = prefix + inlineValue.trim()
        await fetchJSON('/git/create-directory', {
          method: 'POST',
          body: JSON.stringify({ path: dirPath }),
        })
        if (parentPath) await loadDir(parentPath)
        else await loadDir('')
      } else if (type === 'rename' && entry) {
        const oldPath = entry.path
        const parentPrefix = oldPath.includes('/') ? oldPath.substring(0, oldPath.lastIndexOf('/') + 1) : ''
        const newPath = parentPrefix + inlineValue.trim()
        await fetchJSON('/git/rename', {
          method: 'POST',
          body: JSON.stringify({ old_path: oldPath, new_path: newPath }),
        })
        // Refresh parent
        const refreshPath = parentPrefix ? parentPrefix.replace(/\/$/, '') : ''
        if (refreshPath) await loadDir(refreshPath)
        else await loadDir('')
      }
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Operation failed')
    }
    setInlineAction(null)
  }

  async function handleDelete(entry: FileEntry) {
    setCtxMenu(null)
    const label = entry.type === 'dir' ? 'directory' : 'file'
    if (!window.confirm(`Delete ${label} "${entry.name}"? This uses git rm.`)) return
    try {
      await fetchJSON('/git/delete', {
        method: 'POST',
        body: JSON.stringify({ path: entry.path }),
      })
      const parentPath = entry.path.includes('/') ? entry.path.substring(0, entry.path.lastIndexOf('/')) : ''
      if (parentPath) await loadDir(parentPath)
      else await loadDir('')
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Delete failed')
    }
  }

  function renderInlineInput() {
    if (!inlineAction) return null
    return (
      <div className="flex items-center gap-1 px-2 py-1 bg-blue-50 border-b border-blue-200">
        <input
          value={inlineValue}
          onChange={e => setInlineValue(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') commitInlineAction()
            if (e.key === 'Escape') setInlineAction(null)
          }}
          placeholder={inlineAction.type === 'new-dir' ? 'folder_name' : 'filename.sql'}
          className="flex-1 text-xs border border-blue-300 rounded px-2 py-1 font-mono bg-white"
          autoFocus
        />
        <button onClick={commitInlineAction} className="text-green-600 hover:text-green-700"><Check size={14} /></button>
        <button onClick={() => setInlineAction(null)} className="text-gray-400 hover:text-gray-600"><X size={14} /></button>
      </div>
    )
  }

  function renderEntries(entries: FileEntry[], depth: number) {
    return entries.map(entry => (
      <div key={entry.path}>
        <div
          className="flex items-center gap-1 px-2 py-1 cursor-pointer hover:bg-gray-100 text-xs"
          style={{ paddingLeft: `${depth * 14 + 8}px` }}
          onClick={() => handleClick(entry)}
          onContextMenu={e => handleContextMenu(e, entry)}
        >
          {entry.type === 'dir' ? (
            expanded.has(entry.path) ? <ChevronDown size={10} className="text-gray-400" /> : <ChevronRight size={10} className="text-gray-400" />
          ) : <span className="w-2.5" />}
          {entry.type === 'dir'
            ? <Folder size={11} className="text-amber-500" />
            : <FileCode size={11} className={entry.ext === '.sql' ? 'text-blue-500' : entry.ext === '.yaml' || entry.ext === '.yml' ? 'text-green-500' : 'text-gray-400'} />
          }
          <span className="truncate font-mono">{entry.name}</span>
          {entry.children_count != null && <span className="text-[9px] text-gray-400 ml-auto">{entry.children_count}</span>}
          {loading.has(entry.path) && <Loader2 size={10} className="animate-spin text-gray-400 ml-auto" />}
        </div>
        {/* Inline input renders inside the expanded dir where the action targets */}
        {entry.type === 'dir' && expanded.has(entry.path) && inlineAction && inlineAction.parentPath === entry.path && inlineAction.type !== 'rename' && (
          <div style={{ paddingLeft: `${(depth + 1) * 14 + 8}px` }}>
            {renderInlineInput()}
          </div>
        )}
        {entry.type === 'dir' && expanded.has(entry.path) && children[entry.path] && (
          renderEntries(children[entry.path], depth + 1)
        )}
      </div>
    ))
  }

  return (
    <div className="flex-1 overflow-auto relative" onContextMenu={handleRootContextMenu}>
      {/* Inline input at root level */}
      {inlineAction && !inlineAction.parentPath && inlineAction.type !== 'rename' && (
        <div className="px-2">{renderInlineInput()}</div>
      )}
      {/* Inline input for rename (shown at top) */}
      {inlineAction && inlineAction.type === 'rename' && (
        <div className="px-2">{renderInlineInput()}</div>
      )}
      {rootEntries.length > 0 ? renderEntries(rootEntries, 0) : (
        <div className="text-center py-4 text-[10px] text-gray-400">
          {loading.has('') ? 'Loading...' : 'No repo files. Clone repo in Settings.'}
        </div>
      )}

      {/* Context Menu */}
      {ctxMenu && (
        <div
          className="fixed z-50 bg-white rounded-lg shadow-lg border border-gray-200 py-1 min-w-[140px]"
          style={{ left: ctxMenu.x, top: ctxMenu.y }}
          onClick={e => e.stopPropagation()}
        >
          {ctxMenu.entry?.type === 'dir' ? (
            <>
              <button className="w-full text-left px-3 py-1.5 text-xs hover:bg-gray-100 flex items-center gap-2"
                onClick={() => startInlineAction('new-file', ctxMenu.entry!.path)}>
                <Plus size={12} /> New File
              </button>
              <button className="w-full text-left px-3 py-1.5 text-xs hover:bg-gray-100 flex items-center gap-2"
                onClick={() => startInlineAction('new-dir', ctxMenu.entry!.path)}>
                <FolderPlus size={12} /> New Folder
              </button>
              <div className="border-t border-gray-100 my-1" />
              <button className="w-full text-left px-3 py-1.5 text-xs hover:bg-gray-100 flex items-center gap-2"
                onClick={() => startInlineAction('rename', '', ctxMenu.entry!)}>
                <FileCode size={12} /> Rename
              </button>
              <button className="w-full text-left px-3 py-1.5 text-xs hover:bg-red-50 text-red-600 flex items-center gap-2"
                onClick={() => handleDelete(ctxMenu.entry!)}>
                <X size={12} /> Delete
              </button>
            </>
          ) : ctxMenu.entry ? (
            <>
              <button className="w-full text-left px-3 py-1.5 text-xs hover:bg-gray-100 flex items-center gap-2"
                onClick={() => startInlineAction('rename', '', ctxMenu.entry!)}>
                <FileCode size={12} /> Rename
              </button>
              <button className="w-full text-left px-3 py-1.5 text-xs hover:bg-red-50 text-red-600 flex items-center gap-2"
                onClick={() => handleDelete(ctxMenu.entry!)}>
                <X size={12} /> Delete
              </button>
            </>
          ) : (
            <>
              <button className="w-full text-left px-3 py-1.5 text-xs hover:bg-gray-100 flex items-center gap-2"
                onClick={() => startInlineAction('new-file', '')}>
                <Plus size={12} /> New File
              </button>
              <button className="w-full text-left px-3 py-1.5 text-xs hover:bg-gray-100 flex items-center gap-2"
                onClick={() => startInlineAction('new-dir', '')}>
                <FolderPlus size={12} /> New Folder
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}


// ---------------------------------------------------------------------------
// Git Control Panel (branch, status, commit, push, PR)
// ---------------------------------------------------------------------------

export function GitControlPanel({ refreshKey = 0 }: { refreshKey?: number }) {
  const [status, setStatus] = useState<GitStatus | null>(null)
  const [branches, setBranches] = useState<BranchInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [showNewBranch, setShowNewBranch] = useState(false)
  const [newBranchName, setNewBranchName] = useState('')
  const [commitMsg, setCommitMsg] = useState('')
  const [commitFiles, setCommitFiles] = useState<Set<string>>(new Set())
  const [showDiff, setShowDiff] = useState<string | null>(null)
  const [diffContent, setDiffContent] = useState('')
  const [prTitle, setPrTitle] = useState('')
  const [prBody, setPrBody] = useState('')
  const [prBase, setPrBase] = useState('main')
  const [showPR, setShowPR] = useState(false)
  const [actionResult, setActionResult] = useState<{ type: 'success' | 'error'; msg: string } | null>(null)

  useEffect(() => { refresh() }, [refreshKey])

  async function refresh() {
    setLoading(true)
    try {
      const [s, b] = await Promise.all([
        fetchJSON<GitStatus>('/git/status'),
        fetchJSON<{ branches: BranchInfo[] }>('/git/branches'),
      ])
      setStatus(s)
      setBranches(b.branches)
      setCommitFiles(new Set(s.changed_files.map(f => f.path)))
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  async function createBranch() {
    if (!newBranchName) return
    try {
      await fetchJSON('/git/branches', { method: 'POST', body: JSON.stringify({ name: newBranchName }) })
      setShowNewBranch(false)
      setNewBranchName('')
      await refresh()
      setActionResult({ type: 'success', msg: `Branch '${newBranchName}' created` })
    } catch (e) {
      setActionResult({ type: 'error', msg: e instanceof Error ? e.message : 'Failed' })
    }
  }

  async function switchBranch(branch: string) {
    await fetchJSON('/git/branches/switch', { method: 'POST', body: JSON.stringify({ branch }) })
    await refresh()
  }

  async function handleCommit() {
    if (!commitMsg) return
    try {
      const res = await fetchJSON<{ commit: string }>('/git/commit', {
        method: 'POST',
        body: JSON.stringify({ message: commitMsg, files: [...commitFiles] }),
      })
      setCommitMsg('')
      await refresh()
      setActionResult({ type: 'success', msg: `Committed: ${res.commit}` })
    } catch (e) {
      setActionResult({ type: 'error', msg: e instanceof Error ? e.message : 'Failed' })
    }
  }

  async function handlePush() {
    try {
      await fetchJSON('/git/push', { method: 'POST' })
      await refresh()
      setActionResult({ type: 'success', msg: 'Pushed to origin' })
    } catch (e) {
      setActionResult({ type: 'error', msg: e instanceof Error ? e.message : 'Failed' })
    }
  }

  async function handleCreatePR() {
    if (!prTitle) return
    try {
      const res = await fetchJSON<{ url?: string; error?: string }>('/git/pull-request', {
        method: 'POST',
        body: JSON.stringify({ title: prTitle, body: prBody, base: prBase }),
      })
      if (res.url) {
        setActionResult({ type: 'success', msg: `PR created: ${res.url}` })
        setShowPR(false)
        setPrTitle('')
        setPrBody('')
      } else {
        setActionResult({ type: 'error', msg: res.error || 'Failed' })
      }
    } catch (e) {
      setActionResult({ type: 'error', msg: e instanceof Error ? e.message : 'Failed' })
    }
  }

  async function viewDiff(path: string) {
    const res = await fetchJSON<{ diff: string }>(`/git/diff?path=${encodeURIComponent(path)}`)
    setDiffContent(res.diff)
    setShowDiff(path)
  }

  if (!status) return <div className="p-2 text-xs text-gray-400">Loading...</div>

  return (
    <div className="h-full flex flex-col overflow-auto text-xs">
      {/* Branch info */}
      <div className="px-3 py-2 border-b border-gray-100 bg-gray-50">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <GitBranch size={12} className="text-genie-600" />
            <span className="font-medium">{status.branch}</span>
            {status.is_main && <span className="text-[9px] bg-red-100 text-red-600 px-1 rounded">main</span>}
          </div>
          <button onClick={refresh} className="text-gray-400 hover:text-gray-600"><RefreshCw size={10} /></button>
        </div>
        {(status.ahead > 0 || status.behind > 0) && (
          <div className="text-[10px] text-gray-400 mt-0.5 flex items-center gap-1">
            {status.ahead > 0 && <span className="text-green-600">↑{status.ahead} ahead</span>}
            {status.ahead > 0 && status.behind > 0 && ' · '}
            {status.behind > 0 && (
              <>
                <span className="text-amber-600">↓{status.behind} behind</span>
                <button
                  onClick={async () => {
                    try {
                      await fetchJSON('/git/pull', { method: 'POST' })
                      await refresh()
                    } catch (err) {
                      alert('Pull failed: ' + (err instanceof Error ? err.message : 'Unknown error'))
                    }
                  }}
                  className="text-[10px] text-blue-500 hover:text-blue-700 underline ml-1"
                >
                  Pull
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {/* Branch switcher */}
      <div className="px-3 py-1.5 border-b border-gray-100">
        <select value={status.branch} onChange={e => switchBranch(e.target.value)}
          className="w-full text-[10px] border border-gray-200 rounded px-1 py-0.5">
          {branches.map(b => <option key={b.name} value={b.name}>{b.name}</option>)}
        </select>
        <button onClick={() => setShowNewBranch(!showNewBranch)}
          className="text-[10px] text-genie-600 hover:text-genie-800 mt-1 flex items-center gap-0.5">
          <Plus size={9} /> New Branch
        </button>
        {showNewBranch && (
          <div className="flex gap-1 mt-1">
            <input value={newBranchName} onChange={e => setNewBranchName(e.target.value)}
              placeholder="feature/my-change"
              className="flex-1 text-[10px] border border-gray-300 rounded px-1 py-0.5" />
            <button onClick={createBranch} className="text-[10px] px-1.5 py-0.5 bg-genie-600 text-white rounded">Create</button>
          </div>
        )}
      </div>

      {/* Changed files */}
      {status.changed_files.length > 0 && (
        <div className="px-3 py-2 border-b border-gray-100">
          <div className="text-[10px] font-medium text-gray-500 uppercase mb-1">
            Changes ({status.changed_files.length})
          </div>
          {status.changed_files.map(f => (
            <div key={f.path} className="flex items-center gap-1 py-0.5">
              <input type="checkbox" checked={commitFiles.has(f.path)}
                onChange={() => setCommitFiles(prev => {
                  const n = new Set(prev); n.has(f.path) ? n.delete(f.path) : n.add(f.path); return n
                })}
                className="rounded text-genie-600" style={{ width: 10, height: 10 }} />
              <span className={`text-[9px] font-mono w-3 ${
                f.state === 'M' ? 'text-amber-600' : f.state === 'A' ? 'text-green-600' : f.state === 'D' ? 'text-red-600' : 'text-gray-500'
              }`}>{f.state}</span>
              <span className="font-mono truncate text-gray-700 flex-1">{f.path.split('/').pop()}</span>
              <button onClick={() => viewDiff(f.path)} className="text-gray-400 hover:text-gray-600"><Diff size={10} /></button>
            </div>
          ))}

          {/* Commit */}
          {!status.is_main && (
            <div className="mt-2">
              <input value={commitMsg} onChange={e => setCommitMsg(e.target.value)}
                placeholder="Commit message..."
                onKeyDown={e => e.key === 'Enter' && handleCommit()}
                className="w-full text-[10px] border border-gray-300 rounded px-1.5 py-1 mb-1" />
              <div className="flex gap-1">
                <button onClick={handleCommit} disabled={!commitMsg || commitFiles.size === 0}
                  className="text-[10px] px-2 py-0.5 bg-genie-600 text-white rounded disabled:opacity-50 flex items-center gap-0.5">
                  <GitCommit size={9} /> Commit ({commitFiles.size})
                </button>
                <button onClick={handlePush}
                  className="text-[10px] px-2 py-0.5 border border-gray-300 rounded hover:bg-gray-50 flex items-center gap-0.5">
                  <Upload size={9} /> Push
                </button>
                <button onClick={() => setShowPR(!showPR)}
                  className="text-[10px] px-2 py-0.5 border border-gray-300 rounded hover:bg-gray-50 flex items-center gap-0.5">
                  <GitPullRequest size={9} /> PR
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {status.is_main && status.changed_files.length === 0 && (
        <div className="px-3 py-4 text-center text-[10px] text-gray-400">
          On main branch. Create a feature branch to make changes.
        </div>
      )}

      {/* PR form */}
      {showPR && (
        <div className="px-3 py-2 border-b border-gray-100 bg-blue-50">
          <div className="text-[10px] font-medium text-blue-700 mb-1">Create Pull Request</div>
          <div className="flex gap-1 mb-1">
            <input value={prTitle} onChange={e => setPrTitle(e.target.value)} placeholder="PR title"
              className="flex-1 text-[10px] border border-gray-300 rounded px-1.5 py-1" />
            <select value={prBase} onChange={e => setPrBase(e.target.value)}
              className="text-[10px] border border-gray-300 rounded px-1 py-1">
              <option value="main">→ main</option>
              <option value="stage">→ stage</option>
              <option value="develop">→ develop</option>
            </select>
          </div>
          <textarea value={prBody} onChange={e => setPrBody(e.target.value)} placeholder="Description (optional)"
            rows={3} className="w-full text-[10px] border border-gray-300 rounded px-1.5 py-1 mb-1" />
          <button onClick={handleCreatePR} disabled={!prTitle}
            className="text-[10px] px-2 py-0.5 bg-blue-600 text-white rounded disabled:opacity-50">
            Create PR → {prBase}
          </button>
        </div>
      )}

      {/* Diff viewer */}
      {showDiff && (
        <div className="px-3 py-2 border-b border-gray-100">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] font-medium text-gray-700">{showDiff}</span>
            <button onClick={() => setShowDiff(null)} className="text-gray-400"><X size={10} /></button>
          </div>
          <pre className="text-[9px] font-mono bg-gray-50 p-2 rounded overflow-auto max-h-48 whitespace-pre-wrap">
            {diffContent || '(no diff)'}
          </pre>
        </div>
      )}

      {/* Action result */}
      {actionResult && (
        <div className={`px-3 py-1.5 text-[10px] ${actionResult.type === 'success' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-600'}`}>
          {actionResult.msg}
          <button onClick={() => setActionResult(null)} className="ml-2 underline">dismiss</button>
        </div>
      )}
    </div>
  )
}
