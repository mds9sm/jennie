import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom'
import { PillarProvider } from './context/PillarContext'
import { EnvironmentProvider } from './context/EnvironmentContext'
import { AuthProvider } from './context/AuthContext'
import { UserProvider } from './context/UserContext'
import MainLayout from './components/layout/MainLayout'
import ChatView from './components/chat/ChatView'
import QueryRunner from './components/sql/QueryRunner'
import CatalogBrowser from './components/catalog/CatalogBrowser'
import GlossaryReview from './components/glossary/GlossaryReview'
import LineageGraph from './components/lineage/LineageGraph'
import EventsDQPage from './components/events_dq/EventsDQPage'
import DocsPage from './components/docs/DocsPage'
import ReportsPage from './components/settings/ReportsTab'
import TaskBoard from './components/tasks/TaskBoard'
import TaskDigestPage from './components/tasks/TaskDigestPage'
import SettingsPage from './components/settings/SettingsPage'
import LoginPage from './components/auth/LoginPage'
import OktaCallback from './components/auth/OktaCallback'
import { useUser } from './context/UserContext'

function RequireAuth() {
  const { isAuthenticated, loading } = useUser()
  if (loading) {
    return <div className="h-screen flex items-center justify-center text-gray-400">Loading...</div>
  }
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }
  return <Outlet />
}

function RedirectIfLoggedIn() {
  const { isAuthenticated } = useUser()
  if (isAuthenticated) {
    return <Navigate to="/" replace />
  }
  return <LoginPage />
}

export default function App() {
  return (
    <BrowserRouter>
      <PillarProvider>
        <EnvironmentProvider>
          <AuthProvider>
          <UserProvider>
            <Routes>
              <Route path="/login" element={<RedirectIfLoggedIn />} />
              <Route path="/auth/callback" element={<OktaCallback />} />
              <Route element={<RequireAuth />}>
              <Route element={<MainLayout />}>
                <Route path="/" element={<ChatView />} />
                <Route path="/query" element={<QueryRunner />} />
                <Route path="/catalog" element={<CatalogBrowser />} />
                <Route path="/glossary" element={<GlossaryReview />} />
                <Route path="/lineage" element={<LineageGraph />} />
                <Route path="/events-dq" element={<EventsDQPage />} />
                <Route path="/docs" element={<DocsPage />} />
                <Route path="/tasks" element={<TaskBoard />} />
                <Route path="/task-digest" element={<TaskDigestPage />} />
                <Route path="/reports" element={<ReportsPage />} />
                <Route path="/settings" element={<SettingsPage />} />
              </Route>
              </Route>
            </Routes>
          </UserProvider>
          </AuthProvider>
        </EnvironmentProvider>
      </PillarProvider>
    </BrowserRouter>
  )
}
