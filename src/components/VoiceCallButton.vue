<template>
  <!-- 语音通话按钮 + 弹窗 -->
  <div class="voice-call-wrap">
    <button
      class="voice-btn"
      :class="{ 'voice-btn--active': voiceCallStore.isCalling }"
      :disabled="store.loading"
      :title="voiceCallStore.isCalling ? '挂断' : '语音通话'"
      @click="toggleVoiceCall"
    >
      <svg
        class="voice-btn__icon"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
      >
        <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
        <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
        <line x1="12" y1="19" x2="12" y2="23" />
        <line x1="8" y1="23" x2="16" y2="23" />
      </svg>

      <!-- 通话中指示灯 -->
      <span v-if="voiceCallStore.isCalling" class="voice-btn__pulse-dot"></span>
    </button>

    <!-- 模态框 -->
    <VoiceCallModal
      v-if="modalOpen"
      :character="store.character"
      @close="modalOpen = false"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useChatStore } from '@/stores/chatStore'
import { useVoiceCallStore } from '@/stores/voiceCallStore'
import VoiceCallModal from './VoiceCallModal.vue'

const store = useChatStore()
const voiceCallStore = useVoiceCallStore()
const modalOpen = ref(false)

async function toggleVoiceCall() {
  if (voiceCallStore.isCalling) {
    await voiceCallStore.endCall()
    modalOpen.value = false
    return
  }

  // 发起通话 — 先弹窗，再建立连接
  modalOpen.value = true
  const charId = store.currentCharacterId
  if (charId) {
    await voiceCallStore.startCall(charId)
  }
}
</script>

<style scoped>
.voice-call-wrap {
  display: flex;
  align-items: center;
}

.voice-btn {
  position: relative;
  width: 40px;
  height: 40px;
  border: none;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.08);
  color: #e8e8f0;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.25s ease;
}

.voice-btn:hover {
  background: rgba(123, 92, 255, 0.25);
  transform: scale(1.06);
}

.voice-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  transform: none;
}

.voice-btn--active {
  background: linear-gradient(135deg, #ff6b9d, #ff8e8e);
  box-shadow: 0 0 12px rgba(255, 107, 157, 0.5);
}

.voice-btn__icon {
  width: 22px;
  height: 22px;
  transition: transform 0.25s ease;
}

.voice-btn__pulse-dot {
  position: absolute;
  top: -2px;
  right: -2px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #4ade80;
  box-shadow: 0 0 6px #4ade80;
  animation: pulse-dot 1.2s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.6); }
}
</style>
