import { api } from './client'

export type FinanceSkillKey = 'general' | 'accounting' | 'tax' | 'review'

export interface FinanceAIStatus {
  configured: boolean
  model: string | null
  skills: Array<{ key: FinanceSkillKey; name: string }>
}

export interface FinanceChatMessage {
  role: 'user' | 'assistant'
  content: string
}


export const financeAIApi = {
  status: () => api.get<FinanceAIStatus>('/finance-ai/status'),
  chat: (payload: { skill: FinanceSkillKey; messages: FinanceChatMessage[]; period_context?: string }) =>
    api.post<{ content: string; model: string; usage?: Record<string, number> }>(
      '/finance-ai/chat',
      payload,
      { timeout: 90000 },
    ),
}

