/**
 * MentionInput — textarea with @mention autocomplete.
 * Shows team member dropdown when user types @.
 * Used in: tasks, glossary comments, chat flag descriptions.
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { fetchJSON } from '../../api/client'

interface TeamMember {
  id: number
  name: string
  email: string
  role: string
  team: string
}

interface Props {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  rows?: number
  className?: string
}

export default function MentionInput({ value, onChange, placeholder, rows = 3, className = '' }: Props) {
  const [team, setTeam] = useState<TeamMember[]>([])
  const [showDropdown, setShowDropdown] = useState(false)
  const [filter, setFilter] = useState('')
  const [cursorPos, setCursorPos] = useState(0)
  const [dropdownIdx, setDropdownIdx] = useState(0)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    fetchJSON<TeamMember[]>('/users/team').then(setTeam).catch(() => {})
  }, [])

  const filtered = filter
    ? team.filter(m =>
        m.name.toLowerCase().includes(filter.toLowerCase()) ||
        m.email.toLowerCase().includes(filter.toLowerCase())
      )
    : team

  const handleInput = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const text = e.target.value
    const pos = e.target.selectionStart || 0
    onChange(text)
    setCursorPos(pos)

    // Check if we're in an @mention context
    const beforeCursor = text.slice(0, pos)
    const lastAt = beforeCursor.lastIndexOf('@')
    if (lastAt >= 0) {
      const afterAt = beforeCursor.slice(lastAt + 1)
      // Only show dropdown if @ is at start or after whitespace, and no space in the query
      if ((lastAt === 0 || /\s/.test(beforeCursor[lastAt - 1])) && !/\s/.test(afterAt)) {
        setFilter(afterAt)
        setShowDropdown(true)
        setDropdownIdx(0)
        return
      }
    }
    setShowDropdown(false)
  }, [onChange])

  function insertMention(member: TeamMember) {
    const beforeCursor = value.slice(0, cursorPos)
    const lastAt = beforeCursor.lastIndexOf('@')
    const afterCursor = value.slice(cursorPos)
    const newValue = beforeCursor.slice(0, lastAt) + '@' + member.name + ' ' + afterCursor
    onChange(newValue)
    setShowDropdown(false)

    // Focus back and set cursor after mention
    setTimeout(() => {
      if (textareaRef.current) {
        const newPos = lastAt + member.name.length + 2
        textareaRef.current.focus()
        textareaRef.current.setSelectionRange(newPos, newPos)
      }
    }, 0)
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (!showDropdown || filtered.length === 0) return

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setDropdownIdx(prev => Math.min(prev + 1, filtered.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setDropdownIdx(prev => Math.max(prev - 1, 0))
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      if (showDropdown && filtered.length > 0) {
        e.preventDefault()
        insertMention(filtered[dropdownIdx])
      }
    } else if (e.key === 'Escape') {
      setShowDropdown(false)
    }
  }

  const roleColors: Record<string, string> = {
    admin: 'text-purple-600',
    engineer: 'text-blue-600',
    analyst: 'text-green-600',
    viewer: 'text-gray-500',
  }

  return (
    <div className="relative">
      <textarea
        ref={textareaRef}
        value={value}
        onChange={handleInput}
        onKeyDown={handleKeyDown}
        onBlur={() => setTimeout(() => setShowDropdown(false), 200)}
        placeholder={placeholder || 'Type @ to mention a team member...'}
        rows={rows}
        className={`w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-genie-500 resize-y ${className}`}
      />
      {showDropdown && filtered.length > 0 && (
        <div className="absolute z-20 left-0 mt-1 w-72 bg-white border border-gray-200 rounded-lg shadow-lg max-h-48 overflow-auto">
          {filtered.slice(0, 8).map((member, i) => (
            <button
              key={member.id}
              onClick={() => insertMention(member)}
              className={`w-full flex items-center gap-2 px-3 py-2 text-left text-sm hover:bg-genie-50 ${
                i === dropdownIdx ? 'bg-genie-50' : ''
              }`}
            >
              <div className="w-6 h-6 rounded-full bg-gray-200 flex items-center justify-center text-[10px] font-bold text-gray-600">
                {member.name?.charAt(0)?.toUpperCase() || '?'}
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-medium text-gray-900 truncate">{member.name}</div>
                <div className="text-[10px] text-gray-400 truncate">{member.email}</div>
              </div>
              <span className={`text-[9px] font-medium ${roleColors[member.role] || 'text-gray-400'}`}>
                {member.role}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
