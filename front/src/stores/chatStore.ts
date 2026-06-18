import { defineStore } from 'pinia'
import {
  sendChat,
  sendChatStream,
  switchCharacter,
  getHistory,
  getCurrentCharacter,
  getCharacterState,
  getRelationship,
  getCharacters,
  getLongMemory,
  getEvents,
  getProactive,
} from '@/api'
import type {
  Character,
  CharacterBrief,
  CharacterState,
  Relationship,
  ChatMessage,
  EventItem,
} from '@/types/api'

export const useChatStore = defineStore('chat', {
  state: () => ({
    messages: [] as ChatMessage[],
    longMemory: [] as string[],
    events: [] as EventItem[],
    favorability: 50,
    relationship: { level: '陌生', last_reason: '' } as Relationship,
    loading: false,
    streaming: false,
    switching: false,
    character: null as Character | null,
    characterState: { mood: '平静', energy: 80, current_event: '' } as CharacterState,
    availableCharacters: [] as CharacterBrief[],
    currentCharacterId: '',
    error: null as string | null,
    lastFailedMessage: null as string | null,
    _msgSeq: 0,
  }),

  getters: {
    characterName: (state) => state.character?.name ?? '林婉',
    mood: (state) => state.characterState.mood ?? '平静',
    energy: (state) => state.characterState.energy ?? 80,
    displayMessages: (state) =>
      state.messages.filter((m) => m.role === 'user' || m.role === 'assistant'),
    favorLevel: (state) => {
      const f = state.favorability
      if (f >= 80) return '挚爱'
      if (f >= 60) return '亲密'
      if (f >= 40) return '朋友'
      if (f >= 20) return '熟悉'
      return '陌生'
    },
  },

  actions: {
    async refreshAll() {
      const [characterRes, stateRes, relRes, historyRes, longMemRes, eventsRes, charsRes] =
        await Promise.all([
          getCurrentCharacter(),
          getCharacterState(),
          getRelationship(),
          getHistory(),
          getLongMemory(),
          getEvents(),
          getCharacters(),
        ])

      this.character = characterRes.character
      this.currentCharacterId = characterRes.character.id
      this.characterState = stateRes.state ?? {}
      this.relationship = relRes.relationship ?? {}
      this.favorability = relRes.favorability ?? 50
      this.messages = historyRes.messages ?? []
      this.longMemory = longMemRes.long_memory ?? []
      this.events = eventsRes.events ?? []
      this.availableCharacters = charsRes.characters ?? []
    },

    async send(message: string) {
      this.loading = true
      this.streaming = false
      this.error = null

      const userMsg: ChatMessage = {
        role: 'user',
        content: message,
        id: ++this._msgSeq,
        failed: false,
      }
      this.messages.push(userMsg)

      // 空占位消息（流式逐 token 填充）
      const assistantMsg: ChatMessage = {
        role: 'assistant',
        content: '',
        id: ++this._msgSeq,
        failed: false,
      }
      this.messages.push(assistantMsg)
      const msgIndex = this.messages.length - 1

      sendChatStream(message, {
        onToken: (token: string) => {
          // 首 token 到来 → 切到 streaming 状态，让 typing 气泡消失（避免和占位气泡叠加）
          if (!this.streaming) this.streaming = true
          // 触发 Vue 响应式：替换数组中的单条消息
          const msgs = [...this.messages]
          msgs[msgIndex] = {
            ...msgs[msgIndex],
            content: msgs[msgIndex].content + token,
          }
          this.messages = msgs
        },
        onDone: (favorability: number) => {
          this.favorability = favorability
          this.lastFailedMessage = null
          this.loading = false
          this.streaming = false

          // 后台刷新状态
          Promise.all([
            getCharacterState(),
            getRelationship(),
            getLongMemory(),
          ])
            .then(([stateRes, relRes, longMemRes]) => {
              this.characterState = stateRes.state ?? this.characterState
              this.relationship = relRes.relationship ?? this.relationship
              this.longMemory = longMemRes.long_memory ?? this.longMemory
            })
            .catch(() => {
              /* 静默忽略 */
            })
        },
        onError: (errorMsg: string) => {
          // 流式失败：移除占位 assistant 消息，标记 user 消息失败
          this.messages = this.messages.filter((m) => m.id !== assistantMsg.id)
          this._markFailed(userMsg.id!, message, errorMsg)
          this.loading = false
          this.streaming = false
        },
      })
    },

    _markFailed(msgId: string | number, message: string, errorMsg: string) {
      const msg = this.messages.find((m) => m.id === msgId)
      if (msg) msg.failed = true
      this.lastFailedMessage = message
      this.error = errorMsg
    },

    async retry() {
      if (!this.lastFailedMessage || this.loading) return
      const msg = this.lastFailedMessage
      // 移除已标记 failed 的消息（避免重发后重复）
      this.messages = this.messages.filter((m) => !m.failed)
      await this.send(msg)
    },

    clearError() {
      this.error = null
    },

    async switchCharacter(characterId: string) {
      if (characterId === this.currentCharacterId) return

      this.switching = true
      try {
        await switchCharacter(characterId)
        await this.refreshAll()
      } finally {
        this.switching = false
      }
    },

    async checkProactive() {
      if (this.loading || this.switching) return

      try {
        const res = await getProactive()
        const message = res.message?.trim()
        if (!message) return

        const last = this.messages[this.messages.length - 1]
        if (last?.role === 'assistant' && last.content === message) return

        this.messages.push({ role: 'assistant', content: message })
      } catch {
        // 轮询失败时静默忽略，避免打断聊天
      }
    },
  },
})
