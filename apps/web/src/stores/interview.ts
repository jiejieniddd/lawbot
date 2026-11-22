import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '../api/client'

export type InterviewTurn = {
  id: string
  seq: number
  question: string
  answered?: boolean
  answer?: string
  score?: number
  feedback?: string
  dimensions?: Record<string, number>
}

export type InterviewSession = {
  id: string
  status: string
  question_count: number
  target_role: string
  answered_count: number
  current_seq: number | null
  current_question: InterviewTurn | null
  turns: InterviewTurn[]
  report?: InterviewReport | null
}

export type GapItem = { skill: string; suggestion: string }

export type InterviewReport = {
  total_score: number
  dimension_averages: Record<string, number>
  turns: { seq: number; question: string; score: number; feedback: string }[]
  gaps: GapItem[]
  advice: string
  disclaimer: string
  target_role: string
  has_resume?: boolean
  resume_note?: string
}

export const useInterviewStore = defineStore('interview', () => {
  const session = ref<InterviewSession | null>(null)
  const report = ref<InterviewReport | null>(null)
  const loading = ref(false)
  const submitting = ref(false)
  const error = ref('')

  const phase = computed<'prep' | 'live' | 'debrief'>(() => {
    if (!session.value) return 'prep'
    if (session.value.status === 'completed' || report.value) return 'debrief'
    return 'live'
  })

  async function createSession(payload: {
    question_count: 5 | 8
    target_role: string
    jd_text?: string
  }) {
    loading.value = true
    error.value = ''
    report.value = null
    try {
      session.value = await api<InterviewSession>('/api/v1/interview/sessions', {
        method: 'POST',
        body: JSON.stringify({
          question_count: payload.question_count,
          target_role: payload.target_role,
          jd_text: payload.jd_text || '',
        }),
      })
      return session.value
    } catch (e) {
      error.value = (e as Error).message || '创建面试失败'
      throw e
    } finally {
      loading.value = false
    }
  }

  async function loadSession(id: string) {
    loading.value = true
    error.value = ''
    try {
      session.value = await api<InterviewSession>(`/api/v1/interview/sessions/${id}`)
      if (session.value.status === 'completed') {
        if (session.value.report) {
          report.value = session.value.report
        } else {
          const data = await api<{ report: InterviewReport }>(
            `/api/v1/interview/sessions/${id}/report`,
          )
          report.value = data.report
        }
      }
      return session.value
    } catch (e) {
      error.value = (e as Error).message || '加载面试失败'
      throw e
    } finally {
      loading.value = false
    }
  }

  async function submitAnswer(answer: string) {
    if (!session.value) throw new Error('无进行中的面试')
    submitting.value = true
    error.value = ''
    try {
      const data = await api<{
        done: boolean
        session: InterviewSession
        report?: InterviewReport
      }>(`/api/v1/interview/sessions/${session.value.id}/answer`, {
        method: 'POST',
        body: JSON.stringify({ answer }),
      })
      session.value = data.session
      if (data.done && data.report) {
        report.value = data.report
      }
      return data
    } catch (e) {
      error.value = (e as Error).message || '提交失败'
      throw e
    } finally {
      submitting.value = false
    }
  }

  function reset() {
    session.value = null
    report.value = null
    error.value = ''
  }

  return {
    session,
    report,
    loading,
    submitting,
    error,
    phase,
    createSession,
    loadSession,
    submitAnswer,
    reset,
  }
})
