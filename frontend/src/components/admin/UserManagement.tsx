import { useState, useEffect } from 'react'
import { UserPlus, Edit3, XCircle, CheckCircle, Loader2, Clock, X, KeyRound } from 'lucide-react'
import { fetchJSON } from '../../api/client'
import { useUser } from '../../context/UserContext'

interface UserRow {
  id: number
  email: string
  name: string
  role: string
  team: string | null
  is_active: boolean
  last_login_at: string | null
  created_at: string
}

interface RegistrationRow {
  id: number
  email: string
  name: string
  team: string | null
  reason: string | null
  status: string
  created_at: string
}

interface PasswordResetRow {
  id: number
  email: string
  user_name: string | null
  status: string
  reviewed_by: string | null
  created_at: string
}

const ROLES = [
  { id: 'viewer', label: 'Viewer', desc: 'Chat + view glossary/lineage', color: 'bg-gray-100 text-gray-600' },
  { id: 'analyst', label: 'Analyst', desc: '+ query nonprod, submit glossary, browse repo', color: 'bg-blue-100 text-blue-700' },
  { id: 'engineer', label: 'Engineer', desc: '+ query prod, profile tables, review glossary, git commit', color: 'bg-purple-100 text-purple-700' },
  { id: 'admin', label: 'Admin', desc: '+ admin console, user management, analyze, glossary merge', color: 'bg-red-100 text-red-700' },
]

const TEAMS = ['Data Engineering', 'Analytics', 'ML Engineering', 'Product Analytics', 'Marketing Analytics', 'Platform']

export default function UserManagement() {
  const { token } = useUser()
  const [users, setUsers] = useState<UserRow[]>([])
  const [registrations, setRegistrations] = useState<RegistrationRow[]>([])
  const [passwordResets, setPasswordResets] = useState<PasswordResetRow[]>([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)

  const [newEmail, setNewEmail] = useState('')
  const [newName, setNewName] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newRole, setNewRole] = useState('analyst')
  const [newTeam, setNewTeam] = useState('')

  const [editName, setEditName] = useState('')
  const [editRole, setEditRole] = useState('')
  const [editTeam, setEditTeam] = useState('')

  useEffect(() => { loadAll() }, [])

  async function loadAll() {
    setLoading(true)
    try {
      const [usersRes, regsRes, resetsRes] = await Promise.all([
        fetchJSON<UserRow[]>('/users/users', { headers: { 'X-Auth-Token': token } }),
        fetchJSON<RegistrationRow[]>('/users/registrations', { headers: { 'X-Auth-Token': token } }).catch(() => [] as RegistrationRow[]),
        fetchJSON<PasswordResetRow[]>('/users/password-resets', { headers: { 'X-Auth-Token': token } }).catch(() => [] as PasswordResetRow[]),
      ])
      setUsers(usersRes)
      setRegistrations(regsRes)
      setPasswordResets(resetsRes)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  async function handleAdd() {
    await fetchJSON('/users/users', {
      method: 'POST',
      headers: { 'X-Auth-Token': token },
      body: JSON.stringify({ email: newEmail, name: newName, password: newPassword, role: newRole, team: newTeam || null }),
    })
    setShowAdd(false)
    setNewEmail(''); setNewName(''); setNewPassword(''); setNewRole('analyst'); setNewTeam('')
    await loadAll()
  }

  async function handleUpdate(id: number) {
    await fetchJSON(`/users/users/${id}`, {
      method: 'PUT',
      headers: { 'X-Auth-Token': token },
      body: JSON.stringify({ name: editName, role: editRole, team: editTeam || null }),
    })
    setEditId(null)
    await loadAll()
  }

  async function handleDeactivate(id: number) {
    if (!confirm('Deactivate this user?')) return
    await fetchJSON(`/users/users/${id}`, { method: 'DELETE', headers: { 'X-Auth-Token': token } })
    await loadAll()
  }

  async function handleApprove(reqId: number) {
    try {
      const res = await fetchJSON<{ temp_password: string; email: string }>(`/users/registrations/${reqId}/approve`, {
        method: 'POST',
        headers: { 'X-Auth-Token': token },
      })
      alert(`Approved! Temporary password for ${res.email}:\n\n${res.temp_password}\n\nShare this with the user. They can change it after logging in.`)
      await loadAll()
    } catch (err: any) {
      alert('Failed to approve: ' + (err?.message || err?.detail || 'Unknown error'))
    }
  }

  async function handleReject(reqId: number) {
    if (!confirm('Reject this registration request?')) return
    try {
      await fetchJSON(`/users/registrations/${reqId}/reject`, {
        method: 'POST',
        headers: { 'X-Auth-Token': token },
        body: JSON.stringify({}),
      })
      await loadAll()
    } catch (err: any) {
      alert('Failed to reject: ' + (err?.message || err?.detail || 'Unknown error'))
    }
  }

  async function handleApproveReset(reqId: number) {
    try {
      const res = await fetchJSON<{ temp_password: string; email: string }>(`/users/password-resets/${reqId}/approve`, {
        method: 'POST',
        headers: { 'X-Auth-Token': token },
      })
      alert(`Password reset for ${res.email}.\n\nTemporary password:\n\n${res.temp_password}\n\nShare this with the user over Slack. They can change it from Settings after logging in.`)
      await loadAll()
    } catch (err: any) {
      alert('Failed to reset password: ' + (err?.message || err?.detail || 'Unknown error'))
    }
  }

  async function handleRejectReset(reqId: number) {
    if (!confirm('Reject this password reset request?')) return
    try {
      await fetchJSON(`/users/password-resets/${reqId}/reject`, {
        method: 'POST',
        headers: { 'X-Auth-Token': token },
        body: JSON.stringify({}),
      })
      await loadAll()
    } catch (err: any) {
      alert('Failed to reject: ' + (err?.message || err?.detail || 'Unknown error'))
    }
  }

  function startEdit(u: UserRow) {
    setEditId(u.id)
    setEditName(u.name)
    setEditRole(u.role)
    setEditTeam(u.team || '')
  }

  const pendingRegs = registrations.filter(r => r.status === 'pending')
  const pastRegs = registrations.filter(r => r.status !== 'pending')
  const pendingResets = passwordResets.filter(r => r.status === 'pending')
  const pastResets = passwordResets.filter(r => r.status !== 'pending')

  if (loading) return <div className="flex items-center justify-center py-12"><Loader2 className="animate-spin text-gray-400" /></div>

  return (
    <div className="max-w-3xl space-y-4">
      {/* Pending Registrations */}
      {pendingRegs.length > 0 && (
        <div className="border border-amber-200 rounded-lg bg-amber-50 p-4">
          <div className="flex items-center gap-2 mb-3">
            <Clock size={14} className="text-amber-600" />
            <h3 className="text-sm font-medium text-amber-900">
              Pending Registrations ({pendingRegs.length})
            </h3>
          </div>
          <div className="space-y-2">
            {pendingRegs.map(r => (
              <div key={r.id} className="bg-white rounded-lg border border-amber-100 p-3 flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-900">{r.name}</span>
                    <span className="text-xs font-mono text-gray-500">{r.email}</span>
                  </div>
                  {r.team && <div className="text-xs text-gray-500 mt-0.5">Team: {r.team}</div>}
                  {r.reason && <div className="text-xs text-gray-500 mt-0.5 italic">"{r.reason}"</div>}
                  <div className="text-[10px] text-gray-400 mt-1">
                    Submitted {new Date(r.created_at).toLocaleDateString()} at {new Date(r.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </div>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  <button onClick={() => handleApprove(r.id)}
                    className="flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-lg bg-green-100 text-green-700 hover:bg-green-200 font-medium">
                    <CheckCircle size={12} /> Approve
                  </button>
                  <button onClick={() => handleReject(r.id)}
                    className="flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-lg bg-red-100 text-red-600 hover:bg-red-200 font-medium">
                    <X size={12} /> Reject
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Past registrations (collapsed) */}
      {pastRegs.length > 0 && (
        <details className="border border-gray-200 rounded-lg">
          <summary className="px-4 py-2 text-xs text-gray-500 cursor-pointer hover:bg-gray-50">
            Past registration requests ({pastRegs.length})
          </summary>
          <div className="px-4 pb-3 space-y-1">
            {pastRegs.map(r => (
              <div key={r.id} className="flex items-center gap-3 text-xs py-1">
                <span className={`px-1.5 py-0.5 rounded text-[10px] ${
                  r.status === 'approved' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-600'
                }`}>{r.status}</span>
                <span className="font-medium">{r.name}</span>
                <span className="font-mono text-gray-500">{r.email}</span>
                <span className="text-gray-400">{new Date(r.created_at).toLocaleDateString()}</span>
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Pending password resets */}
      {pendingResets.length > 0 && (
        <div className="border border-blue-200 rounded-lg bg-blue-50 p-4">
          <div className="flex items-center gap-2 mb-3">
            <KeyRound size={14} className="text-blue-600" />
            <h3 className="text-sm font-medium text-blue-900">
              Password Reset Requests ({pendingResets.length})
            </h3>
          </div>
          <div className="space-y-2">
            {pendingResets.map(r => (
              <div key={r.id} className="bg-white rounded-lg border border-blue-100 p-3 flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-900">{r.user_name || '—'}</span>
                    <span className="text-xs font-mono text-gray-500">{r.email}</span>
                  </div>
                  <div className="text-[10px] text-gray-400 mt-1">
                    Requested {new Date(r.created_at).toLocaleDateString()} at {new Date(r.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </div>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  <button onClick={() => handleApproveReset(r.id)}
                    className="flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-lg bg-blue-100 text-blue-700 hover:bg-blue-200 font-medium">
                    <KeyRound size={12} /> Reset & share
                  </button>
                  <button onClick={() => handleRejectReset(r.id)}
                    className="flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 font-medium">
                    <X size={12} /> Reject
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Past password resets (collapsed) */}
      {pastResets.length > 0 && (
        <details className="border border-gray-200 rounded-lg">
          <summary className="px-4 py-2 text-xs text-gray-500 cursor-pointer hover:bg-gray-50">
            Past password reset requests ({pastResets.length})
          </summary>
          <div className="px-4 pb-3 space-y-1">
            {pastResets.map(r => (
              <div key={r.id} className="flex items-center gap-3 text-xs py-1">
                <span className={`px-1.5 py-0.5 rounded text-[10px] ${
                  r.status === 'approved' ? 'bg-blue-100 text-blue-700' : 'bg-red-100 text-red-600'
                }`}>{r.status}</span>
                <span className="font-medium">{r.user_name || '—'}</span>
                <span className="font-mono text-gray-500">{r.email}</span>
                <span className="text-gray-400">{new Date(r.created_at).toLocaleDateString()}</span>
                {r.reviewed_by && <span className="text-gray-400">by {r.reviewed_by}</span>}
              </div>
            ))}
          </div>
        </details>
      )}

      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-medium text-gray-900">Users</h3>
          <p className="text-xs text-gray-500">{users.length} users</p>
        </div>
        <button onClick={() => setShowAdd(!showAdd)}
          className="flex items-center gap-1.5 px-3 py-2 text-sm rounded-lg bg-genie-600 text-white hover:bg-genie-700">
          <UserPlus size={14} /> Add User
        </button>
      </div>

      {/* Role descriptions */}
      <div className="grid grid-cols-4 gap-2">
        {ROLES.map(r => (
          <div key={r.id} className={`rounded-lg p-2 ${r.color}`}>
            <div className="text-xs font-medium">{r.label}</div>
            <div className="text-[9px] opacity-75 mt-0.5">{r.desc}</div>
          </div>
        ))}
      </div>

      {/* Add user form */}
      {showAdd && (
        <div className="border border-gray-200 rounded-lg p-4 bg-gray-50">
          <h4 className="text-sm font-medium text-gray-700 mb-2">New User</h4>
          <div className="grid grid-cols-2 gap-2 mb-2">
            <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="Full name"
              className="text-sm border border-gray-300 rounded px-2 py-1.5" />
            <input value={newEmail} onChange={e => setNewEmail(e.target.value)} placeholder="email@example.com"
              className="text-sm border border-gray-300 rounded px-2 py-1.5" />
            <input type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} placeholder="Initial password"
              className="text-sm border border-gray-300 rounded px-2 py-1.5" />
            <select value={newRole} onChange={e => setNewRole(e.target.value)}
              className="text-sm border border-gray-300 rounded px-2 py-1.5">
              {ROLES.map(r => <option key={r.id} value={r.id}>{r.label}</option>)}
            </select>
          </div>
          <select value={newTeam} onChange={e => setNewTeam(e.target.value)}
            className="text-sm border border-gray-300 rounded px-2 py-1.5 mb-2 w-full">
            <option value="">No team</option>
            {TEAMS.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
          <div className="flex gap-2">
            <button onClick={handleAdd} disabled={!newEmail || !newName || !newPassword}
              className="text-xs px-3 py-1.5 rounded bg-genie-600 text-white disabled:opacity-50">Create</button>
            <button onClick={() => setShowAdd(false)} className="text-xs text-gray-500">Cancel</button>
          </div>
        </div>
      )}

      {/* User list */}
      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-gray-50 text-gray-500 uppercase">
            <tr>
              <th className="px-3 py-2 text-left">Name</th>
              <th className="px-3 py-2 text-left">Email</th>
              <th className="px-3 py-2 text-center">Role</th>
              <th className="px-3 py-2 text-left">Team</th>
              <th className="px-3 py-2 text-center">Status</th>
              <th className="px-3 py-2 text-left">Last Login</th>
              <th className="px-3 py-2 text-center">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {users.map(u => {
              const roleInfo = ROLES.find(r => r.id === u.role)
              return (
                <tr key={u.id} className={`hover:bg-gray-50 ${!u.is_active ? 'opacity-40' : ''}`}>
                  <td className="px-3 py-2 font-medium">
                    {editId === u.id ? (
                      <input value={editName} onChange={e => setEditName(e.target.value)}
                        className="text-xs border rounded px-1 py-0.5 w-full" />
                    ) : u.name}
                  </td>
                  <td className="px-3 py-2 font-mono text-gray-600">{u.email}</td>
                  <td className="px-3 py-2 text-center">
                    {editId === u.id ? (
                      <select value={editRole} onChange={e => setEditRole(e.target.value)}
                        className="text-[10px] border rounded px-1 py-0.5">
                        {ROLES.map(r => <option key={r.id} value={r.id}>{r.label}</option>)}
                      </select>
                    ) : (
                      <span className={`text-[10px] px-1.5 py-0.5 rounded ${roleInfo?.color || ''}`}>
                        {roleInfo?.label || u.role}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-gray-600">
                    {editId === u.id ? (
                      <select value={editTeam} onChange={e => setEditTeam(e.target.value)}
                        className="text-[10px] border rounded px-1 py-0.5 w-full">
                        <option value="">---</option>
                        {TEAMS.map(t => <option key={t} value={t}>{t}</option>)}
                      </select>
                    ) : (u.team || '---')}
                  </td>
                  <td className="px-3 py-2 text-center">
                    {u.is_active
                      ? <span className="text-[10px] bg-green-100 text-green-700 px-1.5 py-0.5 rounded">Active</span>
                      : <span className="text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">Inactive</span>
                    }
                  </td>
                  <td className="px-3 py-2 text-gray-400">
                    {u.last_login_at ? new Date(u.last_login_at).toLocaleDateString() : 'Never'}
                  </td>
                  <td className="px-3 py-2 text-center">
                    {editId === u.id ? (
                      <div className="flex gap-1 justify-center">
                        <button onClick={() => handleUpdate(u.id)} className="text-[10px] px-1.5 py-0.5 bg-green-100 text-green-700 rounded">Save</button>
                        <button onClick={() => setEditId(null)} className="text-[10px] text-gray-500">Cancel</button>
                      </div>
                    ) : (
                      <div className="flex gap-1 justify-center">
                        <button onClick={() => startEdit(u)} className="text-gray-400 hover:text-gray-600"><Edit3 size={12} /></button>
                        {u.is_active && <button onClick={() => handleDeactivate(u.id)} className="text-red-400 hover:text-red-600"><XCircle size={12} /></button>}
                      </div>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
