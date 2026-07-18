export interface Character {
  id: string
  name: string
  description?: string
  personality?: string
  system_prompt?: string
  avatar?: string
  /** VRM 模型路径或 URL（可选；缺省用前端默认演示模型） */
  vrm_model?: string
  created_by?: number
}

export interface User {
  id: number
  username: string
  role: string
  status: string
  created_at?: string
  daily_chat_limit: number
  character_limit: number
  today_chat_count?: number
  character_count?: number
}

export interface UsageByEndpoint {
  count: number
  tokens_in: number
  tokens_out: number
}

export interface UsageSummary {
  user_id: number
  days: number
  by_endpoint: Record<string, UsageByEndpoint>
}

export interface CharacterBrief {
  id: string
  name: string
  description?: string
  avatar?: string
  created_by?: number | null
}

export interface CharacterCreateInput {
  keyword: string
  name?: string
}

export interface CharacterState {
  mood?: string
  energy?: number
  current_event?: string | { title?: string; description?: string; event_date?: string; start_time?: string; impact?: number }
}

export interface Relationship {
  level?: string
  last_reason?: string
}

export interface StoryBranchPoint {
  stage: number
  at?: string
  reason?: string
  favorability?: number
  alt_direction?: string
}

export interface Story {
  // 新格式 (stories 数组中的项)
  id?: string
  title?: string
  description?: string
  type?: 'main' | 'side'
  status?: 'active' | 'paused' | 'completed'
  stage?: number
  max_stage?: number
  stages?: string[]
  branch_points?: StoryBranchPoint[]
  tags?: string[]
  started_at?: string
  last_advance_date?: string
  changed?: boolean
  world_event_id?: string
  // 兼容旧字段
  story_id?: string
  last_update_date?: string
}

export interface StoryHistoryItem {
  id?: string
  title?: string
  type?: 'main' | 'side'
  stages?: string[]
  branch_points?: StoryBranchPoint[]
  total_stages?: number
  completed_at?: string
}

export interface World {
  id: string
  name: string
  description?: string
  background?: string
  world_event?: {
    title?: string
    impact?: number
  }
}

export interface EventItem {
  time?: string
  event: string
}

export interface MemorySearchResult {
  text: string
  collection: string // profile/long_memory/story/events/relationship/chat_summary
  score: number // 越小越相关（向量距离）
  weighted_score?: number
  metadata?: Record<string, unknown>
}

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant'
  content: string
  id?: string | number
  failed?: boolean
}

export interface UserProfile {
  name?: string
  city?: string
  job?: string
  mood?: string
  recent_topics?: string[]
  [key: string]: unknown
}

export interface FullMemory {
  profile?: UserProfile
  favorability?: number
  long_memory?: string[]
  events?: EventItem[]
  chat_summary?: string[]
  relationship?: Relationship
  character_state?: CharacterState
  story?: Story // 兼容字段（取主线 active）
  stories?: Story[]
  story_history?: StoryHistoryItem[]
  last_chat_time?: string
}

export interface NpcRelationship {
  favorability?: number
  trust?: number
  intimacy?: number
}

export interface NpcDialogue {
  speaker?: string
  content?: string
}

export interface NpcInteractionRecord {
  time?: string
  summary?: string
  dialogues?: NpcDialogue[]
  world_impact?: string
  event_id?: string
}

export interface NpcGossip {
  time?: string
  source?: string
  target?: string
  content?: string
}

export interface WorldImpactRecord {
  time?: string
  impact?: string
}

export interface WorldInteractionsSnapshot {
  world_id?: string
  characters?: Record<string, string>
  relationships?: Record<string, Record<string, NpcRelationship>>
  recent_interactions?: NpcInteractionRecord[]
  gossip?: NpcGossip[]
  world_impacts?: WorldImpactRecord[]
  last_interaction_date?: string
}
