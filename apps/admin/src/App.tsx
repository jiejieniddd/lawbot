import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { hasAdminSession } from './api/client'
import { AuthProvider, useAuth } from './auth/AuthContext'
import AdminLayout from './layouts/AdminLayout'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import UsersPage from './pages/UsersPage'
import AuditPage from './pages/AuditPage'
import ProvidersPage from './pages/ProvidersPage'
import KnowledgePage from './pages/KnowledgePage'
import SettingsPage from './pages/SettingsPage'
import RolesPage from './pages/RolesPage'
import { Result, Spin } from 'antd'

function RequireAuth({ children }: { children: ReactNode }) {
  if (!hasAdminSession()) return <Navigate to="/login" replace />
  return <AuthProvider>{children}</AuthProvider>
}

function RequirePermission({
  permission,
  children,
}: {
  permission: string
  children: ReactNode
}) {
  const { hasPermission, loading } = useAuth()
  if (loading) return <Spin style={{ margin: 48 }} />
  if (!hasPermission(permission)) {
    return <Result status="403" title="403" subTitle="当前账号无此权限" />
  }
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
        <Route
          index
          element={
            <RequirePermission permission="stats:read">
              <DashboardPage />
            </RequirePermission>
          }
        />
        <Route path="users" element={<Navigate to="/users/clients" replace />} />
        <Route
          path="users/clients"
          element={
            <RequirePermission permission="user:list">
              <UsersPage mode="clients" />
            </RequirePermission>
          }
        />
        <Route
          path="users/admins"
          element={
            <RequirePermission permission="admin:manage">
              <UsersPage mode="admins" />
            </RequirePermission>
          }
        />
        <Route
          path="roles"
          element={
            <RequirePermission permission="role:manage">
              <RolesPage />
            </RequirePermission>
          }
        />
        <Route
          path="audit"
          element={
            <RequirePermission permission="audit:read">
              <AuditPage />
            </RequirePermission>
          }
        />
        <Route
          path="providers"
          element={
            <RequirePermission permission="provider:manage">
              <ProvidersPage />
            </RequirePermission>
          }
        />
        <Route
          path="knowledge"
          element={
            <RequirePermission permission="knowledge:read">
              <KnowledgePage />
            </RequirePermission>
          }
        />
        <Route
          path="settings"
          element={
            <RequirePermission permission="settings:read">
              <SettingsPage />
            </RequirePermission>
          }
        />
      </Route>
    </Routes>
  )
}
