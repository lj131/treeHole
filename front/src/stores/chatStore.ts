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
import { sendNotification } from '@/utils/notification'

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
    _abortFn: null as (() => void) | null,
    _editingIndex: -1,       // 正在编辑的消息 index（-1 = 未编辑）
    _editingText: '',        // 编辑中的文本
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
    /** 最后一条 AI 消息的 index（用于重新生成按钮） */
    lastAssistantIndex: (state) => {
      for (let i = state.messages.length - 1; i >= 0; i--) {
        const m = state.messages[i]
        if (m && m.role === 'assistant' && m.content) return i
      }
      return -1
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

    /** 发送消息（核心） */
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

      const assistantMsg: ChatMessage = {
        role: 'assistant',
        content: '',
        id: ++this._msgSeq,
        failed: false,
      }
      this.messages.push(assistantMsg)
      const msgIndex = this.messages.length - 1

      const { abort } = sendChatStream(message, {
        onToken: (token: string) => {
          if (!this.streaming) this.streaming = true
          const msgs = [...this.messages]
          msgs[msgIndex] = { ...msgs[msgIndex], content: msgs[msgIndex].content + token }
          const current = msgs[msgIndex]
          if (!current) return
          msgs[msgIndex] = {
            ...current,
            content: current.content + token,
          }
          this.messages = msgs
        },
        onDone: (favorability: number) => {
          this._finishStream(favorability, assistantMsg)
        },
        onError: (errorMsg: string) => {
          this.messages = this.messages.filter((m) => m.id !== assistantMsg.id)
          this._markFailed(userMsg.id!, message, errorMsg)
          this.loading = false
          this.streaming = false
          this._abortFn = null
        },
      })
      this._abortFn = abort
    },

    /** 内部：流式完成后处理 */
    _finishStream(favorability: number, assistantMsg: ChatMessage) {
      this.favorability = favorability
      this.lastFailedMessage = null
      this.loading = false
      this.streaming = false
      this._abortFn = null

      const lastAiMsg = [...this.messages].reverse().find(m => m.role === 'assistant')
      if (lastAiMsg?.content) {
        sendNotification(this.characterName, lastAiMsg.content)
      }

      Promise.all([getCharacterState(), getRelationship(), getLongMemory()])
        .then(([stateRes, relRes, longMemRes]) => {
          this.characterState = stateRes.state ?? this.characterState
          this.relationship = relRes.relationship ?? this.relationship
          this.longMemory = longMemRes.long_memory ?? this.longMemory
        })
        .catch(() => {})
    },

    /** 中止流式输出 */
    abortStream() {
      if (this._abortFn) {
        this._abortFn()
        this._abortFn = null
      }
    },

    /** 重新生成最后一条 AI 回复 */
    async regenerate() {
      if (this.loading) return
      // 找到最后一条 user 消息和 assistant 消息
      const msgs = [...this.messages]
      let lastUserIdx = -1
      let lastAssistantIdx = -1
      for (let i = msgs.length - 1; i >= 0; i--) {
        const m = msgs[i]
        if (!m) continue
        if (lastAssistantIdx === -1 && m.role === 'assistant' && m.content) {
          lastAssistantIdx = i
        }
        if (lastUserIdx === -1 && m.role === 'user') {
          lastUserIdx = i
        }
        if (lastUserIdx !== -1 && lastAssistantIdx !== -1) break
      }
      if (lastUserIdx === -1) return
      const userMsg = msgs[lastUserIdx]
      if (!userMsg) return
      // 删除最后的 assistant 消息（如果有的话）
      if (lastAssistantIdx !== -1) {
        this.messages = msgs.filter((_, i) => i !== lastAssistantIdx)
      }
      await this.send(userMsg.content)
    },

    /** 编辑用户消息并重新发送 */
    startEdit(msgIndex: number) {
      const msg = this.displayMessages[msgIndex]
      if (!msg || msg.role !== 'user') return
      // 找到在 this.messages 中的真实 index
      const realIdx = this._realIndex(msgIndex)
      this._editingIndex = realIdx
      this._editingText = msg.content
    },

    cancelEdit() {
      this._editingIndex = -1
      this._editingText = ''
    },

    async confirmEdit(newText: string) {
      if (this._editingIndex < 0 || !newText.trim()) return
      const editIdx = this._editingIndex
      // 删除该 user 消息之后的所有消息（包括对应的 assistant 回复）
      this.messages = this.messages.slice(0, editIdx)
      this._editingIndex = -1
      this._editingText = ''
      await this.send(newText.trim())
    },

    /** displayMessages index → real messages index 转换 */
    _realIndex(displayIdx: number): number {
      let count = -1
      for (let i = 0; i < this.messages.length; i++) {
        const m = this.messages[i]
        if (m && (m.role === 'user' || m.role === 'assistant')) {
          count++
          if (count === displayIdx) return i
        }
      }
      return -1
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
      } catch {}
    },
  },
})
