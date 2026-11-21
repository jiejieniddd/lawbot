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
  created_at?: string | null
  avatar_url?: string | null
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const token = ref<string | null>(getToken())

  function applyTokens(pair: TokenPair) {
    setTokens(pair.access_token, pair.refresh_token)
    token.value = pair.access_token
  }

  async function sendRegisterCode(email: string) {
    return api<{ detail: string; retry_after_seconds: number }>('/api/v1/auth/register/send', {
      method: 'POST',
      body: JSON.stringify({ email }),
    })
  }

  async function sendLoginCode(email: string) {
    return api<{ detail: string; retry_after_seconds: number }>('/api/v1/auth/login/send', {
      method: 'POST',
      body: JSON.stringify({ email }),
    })
  }

  async function register(account: string, password: string, code: string, displayName?: string) {
    const res = await api<TokenPair>('/api/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email: account, password, code, display_name: displayName }),
    })
    applyTokens(res)
    await fetchMe()
  }

  async function loginPassword(account: string, password: string) {
    const res = await api<TokenPair>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ mode: 'password', email: account, password }),
    })
    applyTokens(res)
    await fetchMe()
  }

  async function loginWithCode(account: string, code: string) {
    const res = await api<TokenPair>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ mode: 'email_code', email: account, code }),
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

  async function updateProfile(displayName: string) {
    user.value = await api<User>('/api/v1/auth/me', {
      method: 'PATCH',
      body: JSON.stringify({ display_name: displayName }),
    })
  }

  async function sendChangePasswordCode(oldPassword: string) {
    return api<{ detail: string; retry_after_seconds: number }>('/api/v1/auth/me/password/send', {
      method: 'POST',
      body: JSON.stringify({ old_password: oldPassword }),
    })
  }

  async function changePassword(oldPassword: string, newPassword: string, code: string) {
    await api<void>('/api/v1/auth/me/password', {
      method: 'POST',
      body: JSON.stringify({
        old_password: oldPassword,
        new_password: newPassword,
        code,
      }),
    })
    await logoutRequest()
    token.value = null
    user.value = null
  }

  async function uploadAvatar(file: File) {
    const form = new FormData()
    form.append('file', file)
    user.value = await api<User>('/api/v1/auth/me/avatar', {
      method: 'POST',
      body: form,
    })
  }

  async function removeAvatar() {
    user.value = await api<User>('/api/v1/auth/me/avatar', {
      method: 'DELETE',
    })
  }

  async function logout() {
    await logoutRequest()
    token.value = null
    user.value = null
  }

  return {
    user,
    token,
    sendRegisterCode,
    sendLoginCode,
    register,
    loginPassword,
    loginWithCode,
    fetchMe,
    updateProfile,
    sendChangePasswordCode,
    changePassword,
    uploadAvatar,
    removeAvatar,
    logout,
  }
})
