import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import ConnectionTab from '../settings/ConnectionTab'
import KnowledgeBaseTab from '../settings/KnowledgeBaseTab'
import TableOpsTab from '../settings/TableOpsTab'
import UserManagement from './UserManagement'
import AgentPrompts from './AgentPrompts'

const TABS = [
  { id: 'connection', label: 'Connection' },
  { id: 'knowledge-base', label: 'Knowledge Base' },
  { id: 'table-ops', label: 'Table Ops' },
  { id: 'agents', label: 'Agent Prompts' },
  { id: 'users', label: 'Users' },
]

export default function AdminConsole() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [activeTab, setActiveTab] = useState(searchParams.get('tab') || 'connection')

  function changeTab(tab: string) {
    setActiveTab(tab)
    setSearchParams({ tab })
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="border-b border-gray-200 px-6 pt-5 pb-0">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Admin Console</h2>

        {/* Tabs */}
        <div className="flex gap-1">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => changeTab(tab.id)}
              className={`px-4 py-2 text-sm rounded-t-lg transition-colors ${
                activeTab === tab.id
                  ? 'bg-white text-gray-900 font-medium border border-gray-200 border-b-white -mb-px'
                  : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-auto p-6">
        {activeTab === 'connection' && <ConnectionTab settings={{} as any} onUpdate={() => {}} />}
        {activeTab === 'knowledge-base' && <KnowledgeBaseTab />}
        {activeTab === 'table-ops' && <TableOpsTab />}
        {activeTab === 'agents' && <AgentPrompts />}
        {activeTab === 'users' && <UserManagement />}
      </div>
    </div>
  )
}
