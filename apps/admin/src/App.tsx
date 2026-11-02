import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { hasAdminSession } from './api/client'
import AdminLayout from './layouts/AdminLayout'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import UsersPage from './pages/UsersPage'
import AuditPage from './pages/AuditPage'
import ProvidersPage from './pages/ProvidersPage'
import KnowledgePage from './pages/KnowledgePage'
import SettingsPage from './pages/SettingsPage'

function RequireAuth({ children }: { children: ReactNode }) {
  if (!hasAdminSession()) return <Navigate to="/login" replace />
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <AdminLayout />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="users" element={<Navigate to="/users/clients" replace />} />
        <Route path="users/clients" element={<UsersPage mode="clients" />} />
        <Route path="users/admins" element={<UsersPage mode="admins" />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="providers" element={<ProvidersPage />} />
        <Route path="knowledge" element={<KnowledgePage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  )
}
