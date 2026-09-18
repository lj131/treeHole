export interface Character {
  id: string
  name: string
  description?: string
  personality?: string
  system_prompt?: string
  avatar?: string
  /** @deprecated 旧字段，仅作兼容；新代码读 model3d */
  vrm_model?: string
  /** 3D 模型配置（VRM / glTF），未配置时为 null */
  model3d?: Model3DConfig | null
  created_by?: number
}

/** 3D 模型配置（后端角色 JSON 的 model3d 字段） */
export interface Model3DConfig {
  url: string
  format: 'vrm' | 'glb' | 'gltf' | string
  enabled?: boolean
  /** 模型缩放，0.1–5 */
  scale?: number
  /** 绕 Y 轴初始旋转（度），-180–180 */
  rotation_y?: number
  position?: { x: number; y: number; z: number }
  /** 相机距离，0.3–5（越大越远） */
  camera_distance?: number
  /** 相机高度，0–3 */
  camera_height?: number
  /** 视场角，10–90 */
  camera_fov?: number
  /** 默认表情：neutral/happy/angry/sad/relaxed/surprised */
  default_expression?: string
  auto_rotate?: boolean
  background?: string
  updated_at?: string
}

/** 角色列表里的 3D 模型摘要 */
export interface Model3DSummary {
  url: string
  format: string
  enabled: boolean
}

/** GET /character/model 响应 */
export interface CharacterModelResponse {
  character_id: string
  model3d: Model3DConfig | null
  supported_expressions: string[]
  max_size_mb: number
}

/** POST /character/model/config 请求体（局部更新） */
export interface Model3DConfigPatch {
  url?: string
  format?: string
  enabled?: boolean
  scale?: number
  rotation_y?: number
  position?: { x: number; y: number; z: number }
  camera_distance?: number
  camera_height?: number
  camera_fov?: number
  default_expression?: string
  auto_rotate?: boolean
  background?: string
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
  /** 3D 模型摘要（未配置为 null） */
  model3d?: Model3DSummary | null
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

// ============================================================
// 语音包（Voice Pack）—— 全局库，管理员维护
// ============================================================

/** TTS 引擎：edge = 云端固定音色（立即可用）；clone = 本地音色克隆（需部署引擎） */
export type VoiceEngine = 'edge' | 'clone'

/** 一个语音包：同时装「音色参数」和「参考音频」 */
export interface VoicePack {
  id: string
  name: string
  description: string
  engine: VoiceEngine | string
  voice_name: string
  speaking_rate: number
  pitch: number
  volume: number
  style: string
  /** 是否已上传参考音频（音色克隆用） */
  has_reference_audio: boolean
  reference_audio: string | null
  reference_text: string
  /** 该包所用引擎当前是否真的能合成（UI 据此打「引擎未部署」标记） */
  engine_available?: boolean
  created_at?: string | null
  updated_at?: string | null
}

/** 可选音色 */
export interface VoiceOption {
  short_name: string
  label: string
  gender: string
  locale: string
}

export interface VoiceEngineInfo {
  engine: string
  available: boolean
  label: string
}

export interface VoiceOptionsResponse {
  voices: VoiceOption[]
  engines: VoiceEngineInfo[]
  default_voice: string
  max_packs: number
  max_ref_size_mb: number
  allowed_audio_exts: string[]
}

/** 某角色当前生效的音色（含来源，方便 UI 说清「这个声音是哪来的」） */
export interface CharacterVoiceBinding {
  character_id: string
  character_name: string
  avatar: string
  pack_id: string | null
  effective_source: 'pack' | 'legacy' | 'default' | string
  effective_voice: string
  effective_pack_name: string | null
}

export interface VoicePacksResponse {
  packs: VoicePack[]
  bindings: CharacterVoiceBinding[]
  max_packs: number
}

/** 新建/更新语音包（PATCH 语义：只传要改的字段） */
export interface VoicePackInput {
  name?: string
  description?: string
  engine?: string
  voice_name?: string
  speaking_rate?: number
  pitch?: number
  volume?: number
  style?: string
  reference_text?: string
}

/** 试听：传 pack_id，或传即时参数（新建时试听还没保存的配置） */
export interface VoicePreviewInput {
  pack_id?: string
  text?: string
  engine?: string
  voice_name?: string
  speaking_rate?: number
  pitch?: number
  volume?: number
}
