/**
 * CreatableCombobox — autocomplete dropdown that allows free-text creation.
 *
 * Type to filter; if the typed text doesn't exactly match any option, a
 * "+ Create '<text>'" row appears at the bottom and pressing Enter (or clicking it)
 * fires onChange with the new value. Click outside to commit, Esc to revert.
 */

import { useState, useRef, useEffect, useMemo } from 'react'
import { ChevronDown, Plus, X } from 'lucide-react'

export interface ComboOption {
  label: string
  value: string
  hint?: string
}

interface Props {
  value: string | null | undefined
  options: ComboOption[]
  onChange: (newValue: string | null) => void
  placeholder?: string
  allowCreate?: boolean
  disabled?: boolean
  saving?: boolean
  saved?: boolean
  className?: string
}

export default function CreatableCombobox({
  value,
  options,
  onChange,
  placeholder = 'Select…',
  allowCreate = true,
  disabled = false,
  saving = false,
  saved = false,
  className = '',
}: Props) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [highlightIdx, setHighlightIdx] = useState(0)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const trimmed = query.trim()
  const filtered = useMemo(() => {
    if (!trimmed) return options
    const q = trimmed.toLowerCase()
    return options.filter(o => o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q))
  }, [options, trimmed])

  const exactMatch = useMemo(
    () => options.some(o => o.value.toLowerCase() === trimmed.toLowerCase()),
    [options, trimmed],
  )
  const showCreate = allowCreate && trimmed.length > 0 && !exactMatch

  useEffect(() => {
    if (!open) return
    function handleClick(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false)
        setQuery('')
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  useEffect(() => {
    if (open && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [open])

  useEffect(() => {
    setHighlightIdx(0)
  }, [query, open])

  function commitSelection(newVal: string | null) {
    onChange(newVal)
    setOpen(false)
    setQuery('')
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      setOpen(false)
      setQuery('')
      return
    }
    const totalRows = filtered.length + (showCreate ? 1 : 0)
    if (totalRows === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlightIdx(prev => Math.min(prev + 1, totalRows - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlightIdx(prev => Math.max(prev - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (highlightIdx < filtered.length) {
        commitSelection(filtered[highlightIdx].value)
      } else if (showCreate) {
        commitSelection(trimmed)
      }
    }
  }

  const displayValue = value || ''
  const hasValue = !!displayValue

  return (
    <div ref={wrapperRef} className={`relative ${className}`}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => !disabled && setOpen(o => !o)}
        className={`w-full flex items-center justify-between gap-1 px-2 py-1 text-xs border rounded transition-colors text-left ${
          disabled
            ? 'border-gray-200 bg-gray-50 text-gray-400 cursor-not-allowed'
            : open
              ? 'border-genie-500 bg-white'
              : 'border-gray-200 bg-white hover:border-gray-300'
        }`}
        title={displayValue || placeholder}
      >
        <span className={`truncate ${hasValue ? 'text-gray-800' : 'text-gray-400'}`}>
          {displayValue || placeholder}
        </span>
        <span className="flex items-center gap-1 shrink-0">
          {saving && <span className="text-[9px] text-gray-400">saving…</span>}
          {!saving && saved && <span className="text-[9px] text-green-600">✓</span>}
          {hasValue && !disabled && !saving && (
            <X
              size={11}
              className="text-gray-300 hover:text-gray-600"
              onClick={e => {
                e.stopPropagation()
                commitSelection(null)
              }}
            />
          )}
          <ChevronDown size={12} className="text-gray-400" />
        </span>
      </button>

      {open && (
        <div className="absolute z-30 left-0 right-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-64 overflow-auto min-w-[200px]">
          <div className="sticky top-0 bg-white border-b border-gray-100 p-1">
            <input
              ref={inputRef}
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type to filter or add…"
              className="w-full px-2 py-1 text-xs border-0 focus:outline-none"
            />
          </div>

          {filtered.length === 0 && !showCreate && (
            <div className="px-3 py-2 text-xs text-gray-400">No matches</div>
          )}

          {filtered.map((opt, i) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => commitSelection(opt.value)}
              className={`w-full flex items-center justify-between gap-2 px-3 py-1.5 text-left text-xs ${
                i === highlightIdx ? 'bg-genie-50' : 'hover:bg-gray-50'
              } ${opt.value === displayValue ? 'font-medium text-genie-700' : 'text-gray-700'}`}
            >
              <span className="truncate">{opt.label}</span>
              {opt.hint && <span className="text-[9px] text-gray-400 truncate">{opt.hint}</span>}
            </button>
          ))}

          {showCreate && (
            <button
              type="button"
              onClick={() => commitSelection(trimmed)}
              className={`w-full flex items-center gap-2 px-3 py-1.5 text-left text-xs border-t border-gray-100 ${
                highlightIdx === filtered.length ? 'bg-genie-50' : 'hover:bg-gray-50'
              } text-genie-700`}
            >
              <Plus size={11} />
              <span className="truncate">Create "{trimmed}"</span>
            </button>
          )}
        </div>
      )}
    </div>
  )
}
