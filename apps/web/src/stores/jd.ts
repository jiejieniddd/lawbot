import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '../api/client'

export type JdRecord = {
  id: string
  filename: string
  mime: string
  size_bytes: number
  parse_status: string
  error?: string | null
  is_active: boolean
  skills: string[]
  raw_text?: string
  text?: string
  structured?: Record<string, unknown>
}

export const useJdStore = defineStore('jd', () => {
  const active = ref<JdRecord | null>(null)
  const loading = ref(false)
  const uploading = ref(false)

  const badgeLabel = computed(() => {
    if (!active.value) return ''
    const status = active.value.parse_status
    if (status === 'ready') {
      const title =
        (active.value.structured?.title as string | undefined) ||
        active.value.filename ||
        'JD'
      return `当前 JD · ${String(title).slice(0, 16)}`
    }
    if (status.startsWith('failed')) return `JD 解析失败（${status}）`
    return `JD · ${status}`
  })

  async function fetchActive() {
    loading.value = true
    try {
      const data = await api<{ jd: JdRecord | null }>('/api/v1/me/jds/active')
      active.value = data.jd
    } finally {
      loading.value = false
    }
  }

  async function upload(file: File) {
    uploading.value = true
    try {
      const form = new FormData()
      form.append('file', file)
      active.value = await api<JdRecord>('/api/v1/me/jds', { method: 'POST', body: form })
      return active.value
    } finally {
      uploading.value = false
    }
  }

  async function paste(text: string) {
    uploading.value = true
    try {
      active.value = await api<JdRecord>('/api/v1/me/jds/paste', {
        method: 'POST',
        body: JSON.stringify({ text }),
      })
      return active.value
    } finally {
      uploading.value = false
    }
  }

  async function remove(id: string) {
    await api<void>(`/api/v1/me/jds/${id}`, { method: 'DELETE' })
    if (active.value?.id === id) active.value = null
  }

  return { active, loading, uploading, badgeLabel, fetchActive, upload, paste, remove }
})
