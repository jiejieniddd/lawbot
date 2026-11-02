import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  api,
  getRefreshToken,
  getToken,
  logoutRequest,
  setTokens,
  type TokenPair,
} from '../api/client'

export type User = {
  id: string
  email: string
  display_name: string | null
  role: string
  disabled: boolean
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const token = ref<string | null>(getToken())

  function applyTokens(pair: TokenPair) {
    setTokens(pair.access_token, pair.refresh_token)
    token.value = pair.access_token
  }

  async function register(email: string, password: string, displayName?: string) {
    const res = await api<TokenPair>('/api/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password, display_name: displayName }),
    })
    applyTokens(res)
    await fetchMe()
  }

  async function login(email: string, password: string) {
    const res = await api<TokenPair>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
    applyTokens(res)
    await fetchMe()
  }

  async function fetchMe() {
    if (!getToken() && !getRefreshToken()) {
      user.value = null
      return
    }
    user.value = await api<User>('/api/v1/auth/me')
  }

  async function logout() {
    await logoutRequest()
    token.value = null
    user.value = null
  }

  return { user, token, register, login, fetchMe, logout }
})
