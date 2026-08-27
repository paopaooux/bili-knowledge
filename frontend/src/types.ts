export type StageName = 'parse' | 'acquire' | 'transcribe' | 'generate' | 'organize' | 'publish'
export type Status = 'pending' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'skipped'

export interface VideoPart {
  id: string
  index: number
  title: string
  duration?: number
  subtitles: Array<{ language: string; kind: string }>
}

export interface Inspection {
  id: string
  bvid: string
  title: string
  uploader?: string
  cover_url?: string
  duration?: number
  parts: VideoPart[]
}

export interface Stage {
  stage: StageName
  status: Status
  error?: string
  retries: number
}

export interface Artifact { id: string; kind: string; path: string }

export interface JobPart {
  id: string
  part_index: number
  title: string
  status: Status
  stages: Stage[]
  artifacts: Artifact[]
}

export interface Job {
  id: string
  video_title: string
  bvid: string
  video_url?: string
  status: Status
  error?: string
  created_at: string
  updated_at?: string
  profile_id?: string
  profile_name?: string
  draft_policy?: 'reuse' | 'regenerate'
  draft_model?: string
  parts: JobPart[]
  artifacts: Artifact[]
}

export type DraftPolicy = 'reuse' | 'regenerate'

export type KnowledgeProfileMode = 'open' | 'guided' | 'strict'

export interface KnowledgeProfileTopic {
  name: string
  path: string
  description: string
}

export interface KnowledgeProfile {
  id: string
  name: string
  mode: KnowledgeProfileMode
  scope: string
  preferred_topics: KnowledgeProfileTopic[]
  rules: { ignore_out_of_scope: boolean; merge_similar: boolean }
  is_active: boolean
  version: number
  created_at: string
  updated_at: string
}

export interface TopicSuggestion {
  action: 'use_existing' | 'create'
  path: string
  reason: string
}

export interface KnowledgeFile {
  name: string
  path: string
  type: 'directory' | 'file'
  size: number | null
  modified_at: string
  previewable: boolean
  children?: KnowledgeFile[]
}
