import type { ResumeRecord } from '../stores/resume'

export const RESUME_MAX_BYTES = 8 * 1024 * 1024

export const RESUME_ACCEPT =
  '.pdf,.docx,.png,application/pdf,image/png,application/vnd.openxmlformats-officedocument.wordprocessingml.document'

const RESUME_MIME_TYPES = [
  'application/pdf',
  'image/png',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
] as const

/** Returns an error message, or null if the file is valid. */
export function validateResumeFile(file: File): string | null {
  const name = (file.name || '').toLowerCase()
  const okExt = name.endsWith('.pdf') || name.endsWith('.docx') || name.endsWith('.png')
  const okType = (RESUME_MIME_TYPES as readonly string[]).includes(file.type)
  if (!okExt && !okType) {
    return '仅支持 PDF / DOCX / PNG'
  }
  if (file.size > RESUME_MAX_BYTES) {
    return '简历不能超过 8MB'
  }
  return null
}

export type ResumeUploadToast = {
  type: 'success' | 'warning'
  message: string
}

export function formatResumeUploadMessage(row: ResumeRecord): ResumeUploadToast {
  if (row.parse_status === 'ready') {
    return { type: 'success', message: '简历已上传并解析' }
  }
  if (row.parse_status.startsWith('failed')) {
    return { type: 'warning', message: `上传成功，但解析失败：${row.parse_status}` }
  }
  return { type: 'success', message: `已上传，状态：${row.parse_status}` }
}
