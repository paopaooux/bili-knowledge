import type { Inspection, Job, KnowledgeProfile, StageName, TopicSuggestion } from './types'

export interface TranscriptSegment {
  start: number
  end: number
  text: string
  source: string
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options?.headers },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new Error(payload.detail || `请求失败 (${response.status})`)
  }
  const contentType = response.headers.get('content-type') || ''
  return (contentType.includes('application/json') ? response.json() : response.text()) as Promise<T>
}

export const api = {
  inspect: (url: string) => request<Inspection>('/api/videos/inspect', { method: 'POST', body: JSON.stringify({ url }) }),
  createJob: (videoId: string, partIds: string[]) => request<Job>('/api/jobs', {
    method: 'POST', body: JSON.stringify({ video_id: videoId, part_ids: partIds }),
  }),
  jobs: () => request<Job[]>('/api/jobs'),
  retry: (jobId: string, partId: string, stage: StageName) => request<Job>(`/api/jobs/${jobId}/retry`, {
    method: 'POST', body: JSON.stringify({ part_id: partId, stage }),
  }),
  cancel: (jobId: string) => request(`/api/jobs/${jobId}/cancel`, { method: 'POST' }),
  document: (id: string) => request<string>(`/api/documents/${id}`),
  transcript: (id: string) => request<TranscriptSegment[]>(`/api/transcripts/${id}`),
  settings: () => request<Record<string, string | boolean | null>>('/api/settings'),
  test: (service: 'stt' | 'llm') => request<{ message: string }>('/api/settings/test', {
    method: 'POST', body: JSON.stringify({ service }),
  }),
  openOutput: () => request('/api/settings/open-output', { method: 'POST' }),
  profiles: () => request<KnowledgeProfile[]>('/api/knowledge/profiles'),
  createProfile: (profile: KnowledgeProfile) => request<KnowledgeProfile>('/api/knowledge/profiles', {
    method: 'POST', body: JSON.stringify(profile),
  }),
  updateProfile: (profile: KnowledgeProfile) => request<KnowledgeProfile>(`/api/knowledge/profiles/${profile.id}`, {
    method: 'PUT', body: JSON.stringify(profile),
  }),
  activateProfile: (id: string) => request<KnowledgeProfile>(`/api/knowledge/profiles/${id}/activate`, { method: 'POST' }),
  deleteProfile: (id: string) => request<void>(`/api/knowledge/profiles/${id}`, { method: 'DELETE' }),
  suggestTopic: (profileId: string, name: string, description: string) => request<TopicSuggestion>('/api/knowledge/topic-suggestion', {
    method: 'POST', body: JSON.stringify({ profile_id: profileId, name, description }),
  }),
}
