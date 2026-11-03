import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'

const API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ||
  (import.meta.env.VITE_API_BASE as string | undefined) ||
  ''

const ACCESS_KEY = 'lawbot_admin_token'
const REFRESH_KEY = 'lawbot_admin_refresh_token'

export const api = axios.create({
  baseURL: API_BASE,
})

type RetryConfig = InternalAxiosRequestConfig & { _retry?: boolean }

let refreshPromise: Promise<boolean> | null = null

async function refreshAdminToken(): Promise<boolean> {
  if (refreshPromise) return refreshPromise
  refreshPromise = (async () => {
    const refresh = getAdminRefreshToken()
    if (!refresh) return false
    try {
      const { data } = await axios.post(
        `${API_BASE}/api/admin/auth/refresh`,
        { refresh_token: refresh },
        { headers: { 'Content-Type': 'application/json' } },
      )
      setAdminTokens(data.access_token, data.refresh_token)
      return true
    } catch {
      return false
    } finally {
      refreshPromise = null
    }
  })()
  return refreshPromise
}

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(ACCESS_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const status = error?.response?.status
    const config = error.config as RetryConfig | undefined
    const url = String(config?.url || '')
    const onAuth =
      url.includes('/api/admin/auth/login') || url.includes('/api/admin/auth/refresh')

    if (status === 401 && config && !config._retry && !onAuth) {
      config._retry = true
      const ok = await refreshAdminToken()
      if (ok) {
        const token = getAdminToken()
        if (token) config.headers.Authorization = `Bearer ${token}`
        return api.request(config)
      }
      clearAdminSession()
      if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
        window.location.assign('/login')
      }
      return Promise.reject(error)
    }

    // Only hard-logout on unauthenticated; 403 is permission denied for RBAC UI
    if (status === 401 && !onAuth) {
      clearAdminSession()
      if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
        window.location.assign('/login')
      }
    }
    return Promise.reject(error)
  },
)

function clearAdminSession() {
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

export function setAdminTokens(access: string | null, refresh: string | null = null) {
  if (access) localStorage.setItem(ACCESS_KEY, access)
  else localStorage.removeItem(ACCESS_KEY)
  if (refresh) localStorage.setItem(REFRESH_KEY, refresh)
  else if (access === null) localStorage.removeItem(REFRESH_KEY)
}

/** @deprecated prefer setAdminTokens */
export function setAdminToken(token: string | null) {
  setAdminTokens(token, token ? getAdminRefreshToken() : null)
}

export function getAdminToken() {
  return localStorage.getItem(ACCESS_KEY)
}

export function getAdminRefreshToken() {
  return localStorage.getItem(REFRESH_KEY)
}

export function hasAdminSession() {
  return Boolean(getAdminRefreshToken() || getAdminToken())
}

export async function adminLogout() {
  const refresh = getAdminRefreshToken()
  if (refresh) {
    try {
      await axios.post(
        `${API_BASE}/api/admin/auth/logout`,
        { refresh_token: refresh },
        { headers: { 'Content-Type': 'application/json' } },
      )
    } catch {
      /* ignore */
    }
  }
  clearAdminSession()
}
