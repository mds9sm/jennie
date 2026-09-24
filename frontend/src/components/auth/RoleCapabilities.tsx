import { useState, useEffect } from 'react'
import { fetchJSON } from '../../api/client'
import { Check, X, Loader2, ChevronRight } from 'lucide-react'
import { useUser } from '../../context/UserContext'

interface Capability {
  permission: string
  label: string
  granted: boolean
}

interface Role {
  role: string
  description: string
  capabilities: Capability[]
}

interface Props {
  /** If true, show "Request Role Change" button */
  allowRequest?: boolean
  /** Highlight this role as "your current role" */
  currentRole?: string
  /** If true, render compact (for onboarding embed) */
  compact?: boolean
}

export default function RoleCapabilities({ allowRequest = false, currentRole, compact = false }: Props) {
  const { user } = useUser()
  const [roles, setRoles] = useState<Role[]>([])
  const [loading, setLoading] = useState(true)
  const [requestModal, setRequestModal] = useState(false)
  const [selectedRole, setSelectedRole] = useState('')
  const [reason, setReason] = useState('')
  const [requestLoading, setRequestLoading] = useState(false)
  const [requestResult, setRequestResult] = useState<{ ok: boolean; message: string } | null>(null)

  const activeRole = currentRole || user?.role || ''

  useEffect(() => {
    fetchJSON<Role[]>('/okta/roles')
      .then(setRoles)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  async function handleRequestRole() {
    if (!selectedRole) return
    setRequestLoading(true)
    setRequestResult(null)
    try {
      const res = await fetchJSON<{ message: string }>('/okta/request-role-change', {
        method: 'POST',
        body: JSON.stringify({ requested_role: selectedRole, reason }),
      })
      setRequestResult({ ok: true, message: res.message || 'Request submitted' })
    } catch (err: any) {
      setRequestResult({ ok: false, message: err?.message || 'Request failed' })
    } finally {
      setRequestLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8 text-gray-400">
        <Loader2 size={20} className="animate-spin mr-2" />
        Loading roles...
      </div>
    )
  }

  if (!roles.length) return null

  // Get all unique capability labels (use first role as template)
  const allCapabilities = roles[0]?.capabilities || []

  return (
    <div className={compact ? '' : 'space-y-4'}>
      {!compact && (
        <h3 className="text-sm font-semibold text-gray-700">Role Capabilities</h3>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="border-b border-gray-200">
              <th className="text-left py-2 pr-3 text-gray-500 font-medium w-48">Capability</th>
              {roles.map(r => (
                <th key={r.role} className={`text-center py-2 px-2 font-semibold capitalize ${
                  r.role === activeRole
                    ? 'text-genie-700 bg-genie-50 rounded-t-lg'
                    : 'text-gray-600'
                }`}>
                  {r.role}
                  {r.role === activeRole && (
                    <span className="block text-[10px] font-normal text-genie-500 mt-0.5">current</span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {allCapabilities.map((cap, i) => (
              <tr key={cap.permission} className={i % 2 === 0 ? 'bg-gray-50/50' : ''}>
                <td className="py-1.5 pr-3 text-gray-600">{cap.label}</td>
                {roles.map(r => {
                  const roleCap = r.capabilities.find(c => c.permission === cap.permission)
                  const granted = roleCap?.granted ?? false
                  return (
                    <td key={r.role} className={`text-center py-1.5 px-2 ${
                      r.role === activeRole ? 'bg-genie-50/50' : ''
                    }`}>
                      {granted ? (
                        <Check size={14} className="inline text-green-500" />
                      ) : (
                        <X size={14} className="inline text-gray-300" />
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Role descriptions */}
      {!compact && (
        <div className="grid grid-cols-4 gap-2 mt-3">
          {roles.map(r => (
            <div key={r.role} className={`text-[10px] text-center px-2 py-1.5 rounded-lg ${
              r.role === activeRole
                ? 'bg-genie-50 text-genie-700 border border-genie-200'
                : 'text-gray-400'
            }`}>
              {r.description}
            </div>
          ))}
        </div>
      )}

      {/* Request role change */}
      {allowRequest && activeRole !== 'admin' && (
        <div className="mt-4">
          {!requestModal ? (
            <button onClick={() => setRequestModal(true)}
              className="text-xs text-genie-600 hover:text-genie-700 font-medium flex items-center gap-1">
              Request a different role <ChevronRight size={12} />
            </button>
          ) : (
            <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
              <h4 className="text-sm font-medium text-gray-800">Request Role Change</h4>

              <div>
                <label className="text-xs text-gray-600 block mb-1">Select role</label>
                <select value={selectedRole} onChange={e => setSelectedRole(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm">
                  <option value="">Choose a role...</option>
                  {roles.filter(r => r.role !== activeRole).map(r => (
                    <option key={r.role} value={r.role}>{r.role} — {r.description}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-xs text-gray-600 block mb-1">Why do you need this role?</label>
                <textarea value={reason} onChange={e => setReason(e.target.value)}
                  placeholder="Brief explanation..."
                  rows={2}
                  className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm resize-none" />
              </div>

              {requestResult && (
                <div className={`text-xs p-2 rounded-lg ${
                  requestResult.ok ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-600'
                }`}>
                  {requestResult.message}
                </div>
              )}

              <div className="flex gap-2">
                <button onClick={handleRequestRole}
                  disabled={!selectedRole || requestLoading}
                  className="bg-genie-600 text-white rounded-lg px-3 py-1.5 text-xs font-medium hover:bg-genie-700 disabled:opacity-50 flex items-center gap-1">
                  {requestLoading && <Loader2 size={12} className="animate-spin" />}
                  Submit Request
                </button>
                <button onClick={() => { setRequestModal(false); setRequestResult(null) }}
                  className="text-gray-500 hover:text-gray-700 text-xs">
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
