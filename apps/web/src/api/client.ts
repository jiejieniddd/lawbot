import type { Citation } from '../types/citation'

const API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ||
  (import.meta.env.VITE_API_BASE as string | undefined) ||
  ''

const ACCESS_KEY = 'lawbot_token'
const REFRESH_KEY = 'lawbot_refresh_token'
const REFRESH_SKEW_MS = 60_000

export type { Citation }

export type TokenPair = {
  access_token: string
  refresh_token: string
  token_type?: string
  expires_in?: number
}

export function getToken(): string | null {
  return localStorage.getItem(ACCESS_KEY)
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY)
}

export function hasSession(): boolean {
  return Boolean(getRefreshToken() || getToken())
}

export function setTokens(access: string | null, refresh: string | null = null) {
  if (access) localStorage.setItem(ACCESS_KEY, access)
  else localStorage.removeItem(ACCESS_KEY)
  if (refresh) localStorage.setItem(REFRESH_KEY, refresh)
  else if (access === null) localStorage.removeItem(REFRESH_KEY)
}

/** @deprecated prefer setTokens */
export function setToken(token: string | null) {
  setTokens(token, token ? getRefreshToken() : null)
}

function clearSession() {
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

function handleUnauthorized(): never {
  clearSession()
  const redirect = encodeURIComponent(`${window.location.pathname}${window.location.search}`)
  window.location.assign(`/login?redirect=${redirect}`)
  throw new Error('未登录或登录已过期')
}

function isAuthExempt(path: string): boolean {
  return (
    path.includes('/api/v1/auth/login') ||
    path.includes('/api/v1/auth/register') ||
    path.includes('/api/v1/auth/refresh')
  )
}

function accessExpiresSoon(token: string | null, skewMs = REFRESH_SKEW_MS): boolean {
  if (!token) return true
  try {
    const part = token.split('.')[1]
    if (!part) return true
    const json = atob(part.replace(/-/g, '+').replace(/_/g, '/'))
    const payload = JSON.parse(json) as { exp?: number }
    if (!payload.exp) return true
    return payload.exp * 1000 <= Date.now() + skewMs
  } catch {
    return true
  }
}

let refreshPromise: Promise<boolean> | null = null

async function refreshAccessToken(): Promise<boolean> {
  if (refreshPromise) return refreshPromise
  refreshPromise = (async () => {
    const refresh = getRefreshToken()
    if (!refresh) return false
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refresh }),
      })
      if (!res.ok) return false
      const data = (await res.json()) as TokenPair
      setTokens(data.access_token, data.refresh_token)
      return true
    } catch {
      return false
    } finally {
      refreshPromise = null
    }
  })()
  return refreshPromise
}

export async function ensureAccessToken(): Promise<string | null> {
  if (!accessExpiresSoon(getToken())) return getToken()
  const ok = await refreshAccessToken()
  if (!ok) return getToken()
  return getToken()
}

export async function logoutRequest(): Promise<void> {
  const refresh = getRefreshToken()
  if (refresh) {
    try {
      await fetch(`${API_BASE}/api/v1/auth/logout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refresh }),
      })
    } catch {
      /* ignore */
    }
  }
  clearSession()
}

export async function api<T>(path: string, options: RequestInit = {}, retried = false): Promise<T> {
  const headers = new Headers(options.headers || {})
  if (!headers.has('Content-Type') && options.body) {
    headers.set('Content-Type', 'application/json')
  }
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (res.status === 401 && !isAuthExempt(path) && !retried) {
    const ok = await refreshAccessToken()
    if (ok) return api<T>(path, options, true)
    handleUnauthorized()
  }
  if (res.status === 401) {
    handleUnauthorized()
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Request failed')
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export type ChatEvent = {
  type: 'token' | 'citation' | 'done' | 'error'
  data: Record<string, unknown>
  request_id: string
}

export async function streamChat(
  conversationId: string,
  content: string,
  onEvent: (ev: ChatEvent) => void,
): Promise<void> {
  await ensureAccessToken()
  const doFetch = async () => {
    const token = getToken()
    return fetch(`${API_BASE}/api/v1/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ conversation_id: conversationId, content }),
    })
  }

  let res = await doFetch()
  if (res.status === 401) {
    const ok = await refreshAccessToken()
    if (!ok) handleUnauthorized()
    res = await doFetch()
  }
  if (res.status === 401) {
    handleUnauthorized()
  }
  if (!res.ok || !res.body) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Chat failed')
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() || ''
    for (const part of parts) {
      const line = part.trim()
      if (!line.startsWith('data:')) continue
      const json = line.slice(5).trim()
      if (!json) continue
      onEvent(JSON.parse(json) as ChatEvent)
    }
  }
}
