import { createContext, useContext, useMemo, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { hasAdminSession } from '../api/client'

export type RoleBrief = { id: string; code: string; name: string }

export type AdminMe = {
  id: string
  email: string
  display_name: string | null
  role: string
  disabled: boolean
  roles: RoleBrief[]
  permissions: string[]
}

type AuthContextValue = {
  me: AdminMe | undefined
  loading: boolean
  permissions: Set<string>
  hasPermission: (code: string) => boolean
  isSuperAdmin: boolean
  refetch: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const enabled = hasAdminSession()
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ['admin-me'],
    enabled,
    retry: 1,
    queryFn: async () => (await api.get<AdminMe>('/api/admin/auth/me')).data,
  })

  const value = useMemo<AuthContextValue>(() => {
    const permissions = new Set(data?.permissions || [])
    const isSuperAdmin = data?.role === 'super_admin'
    return {
      me: data,
      // Stop spinning once request settles (success or error)
      loading: enabled && isPending,
      permissions,
      hasPermission: (code: string) => isSuperAdmin || permissions.has(code),
      isSuperAdmin,
      refetch: () => {
        void refetch()
      },
    }
  }, [data, enabled, isPending, refetch])

  if (enabled && isError) {
    const detail =
      (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
      (error as Error)?.message ||
      '加载当前用户失败'
    return (
      <div style={{ padding: 48 }}>
        <p>无法加载账号权限：{String(detail)}</p>
        <button type="button" onClick={() => void refetch()}>
          重试
        </button>
      </div>
    )
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

export function usePermission(code: string) {
  const { hasPermission, loading } = useAuth()
  return { allowed: hasPermission(code), loading }
}
