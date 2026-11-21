import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '../api/client'

export type ResumeRecord = {
  id: string
  filename: string
  mime: string
  size_bytes: number
  parse_status: string
  error?: string | null
  is_active: boolean
  skills: string[]
  intent: string
  structured?: Record<string, unknown>
  created_at?: string | null
  updated_at?: string | null
}

export const useResumeStore = defineStore('resume', () => {
  const active = ref<ResumeRecord | null>(null)
  const loading = ref(false)
  const uploading = ref(false)

  const badgeLabel = computed(() => {
    if (!active.value) return ''
    const status = active.value.parse_status
    if (status === 'ready') {
      const n = active.value.skills?.length || 0
      return n ? `当前简历 · ${n} 项技能` : '当前简历 · 已解析'
    }
    if (status === 'parsing' || status === 'pending') return '简历解析中…'
    if (status.startsWith('failed')) return `简历解析失败（${status}）`
    return `简历 · ${status}`
  })

  async function fetchActive() {
    loading.value = true
    try {
      const data = await api<{ resume: ResumeRecord | null }>('/api/v1/me/resumes/active')
      active.value = data.resume
    } finally {
      loading.value = false
    }
  }

  async function upload(file: File) {
    uploading.value = true
    try {
      const form = new FormData()
      form.append('file', file)
      active.value = await api<ResumeRecord>('/api/v1/me/resumes', {
        method: 'POST',
        body: form,
      })
      return active.value
    } finally {
      uploading.value = false
    }
  }

  async function remove(id: string) {
    await api<void>(`/api/v1/me/resumes/${id}`, { method: 'DELETE' })
    if (active.value?.id === id) active.value = null
  }

  return { active, loading, uploading, badgeLabel, fetchActive, upload, remove }
})
