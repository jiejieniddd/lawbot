import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, apiBlob } from '../api/client'

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

export type ResumePreviewKind = 'pdf' | 'png' | 'docx' | 'unknown'

function detectPreviewKind(record: ResumeRecord): ResumePreviewKind {
  const mime = (record.mime || '').toLowerCase()
  const name = (record.filename || '').toLowerCase()
  if (mime.includes('pdf') || name.endsWith('.pdf')) return 'pdf'
  if (mime.includes('png') || name.endsWith('.png')) return 'png'
  if (
    mime.includes('wordprocessingml') ||
    mime.includes('msword') ||
    name.endsWith('.docx') ||
    name.endsWith('.doc')
  ) {
    return 'docx'
  }
  return 'unknown'
}

export const useResumeStore = defineStore('resume', () => {
  const active = ref<ResumeRecord | null>(null)
  const loading = ref(false)
  const uploading = ref(false)

  const previewOpen = ref(false)
  const previewLoading = ref(false)
  const previewError = ref('')
  const previewKind = ref<ResumePreviewKind>('unknown')
  const previewUrl = ref('')
  const previewRecord = ref<ResumeRecord | null>(null)

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

  function revokePreviewUrl() {
    if (previewUrl.value) {
      URL.revokeObjectURL(previewUrl.value)
      previewUrl.value = ''
    }
  }

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
    if (previewRecord.value?.id === id) closePreview()
  }

  async function fetchFileBlob(id: string, opts?: { inline?: boolean }) {
    const q = opts?.inline ? '?inline=1' : ''
    return apiBlob(`/api/v1/me/resumes/${id}/file${q}`)
  }

  async function openPreview(record?: ResumeRecord | null) {
    const target = record || active.value
    if (!target?.id) {
      previewError.value = '暂无简历可查看'
      previewOpen.value = true
      previewKind.value = 'unknown'
      previewRecord.value = null
      return
    }

    revokePreviewUrl()
    previewOpen.value = true
    previewLoading.value = true
    previewError.value = ''
    previewRecord.value = target
    previewKind.value = detectPreviewKind(target)

    try {
      if (previewKind.value === 'pdf' || previewKind.value === 'png') {
        const blob = await fetchFileBlob(target.id, { inline: true })
        previewUrl.value = URL.createObjectURL(blob)
      } else if (previewKind.value === 'unknown') {
        // Try inline blob anyway for odd mime; fall back to summary-only on failure.
        try {
          const blob = await fetchFileBlob(target.id, { inline: true })
          previewUrl.value = URL.createObjectURL(blob)
        } catch {
          /* keep summary / download path */
        }
      }
      // docx: no object URL — summary + download only
    } catch (e) {
      previewError.value = (e as Error).message || '简历加载失败'
    } finally {
      previewLoading.value = false
    }
  }

  function closePreview() {
    revokePreviewUrl()
    previewOpen.value = false
    previewLoading.value = false
    previewError.value = ''
    previewKind.value = 'unknown'
    previewRecord.value = null
  }

  async function downloadActiveFile(record?: ResumeRecord | null) {
    const target = record || previewRecord.value || active.value
    if (!target?.id) throw new Error('暂无简历可下载')
    const blob = await fetchFileBlob(target.id, { inline: false })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = target.filename || 'resume'
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  return {
    active,
    loading,
    uploading,
    badgeLabel,
    previewOpen,
    previewLoading,
    previewError,
    previewKind,
    previewUrl,
    previewRecord,
    fetchActive,
    upload,
    remove,
    fetchFileBlob,
    openPreview,
    closePreview,
    downloadActiveFile,
  }
})
