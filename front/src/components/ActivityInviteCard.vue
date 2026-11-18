<template>
  <div v-if="props.invitation" class="invite-overlay-layer">
    <div class="invite-card" :class="{ answered: props.invitation!.status !== 'pending' }">
      <div class="invite-head">
        <span class="invite-badge">📅 活动邀请</span>
        <span v-if="props.invitation!.status === 'pending'" class="invite-live">她正在等你回复</span>
        <span v-else class="invite-live done">
          {{ props.invitation!.status === 'accepted' ? '你答应了' : '你拒绝了' }}
        </span>
      </div>

      <div class="invite-activity">{{ props.invitation!.activity }}</div>
      <blockquote class="invite-message">“{{ props.invitation!.message }}”</blockquote>

      <div v-if="props.invitation!.status === 'pending'" class="invite-actions">
        <button class="invite-btn decline" :disabled="busy" @click="answer('declined')">
          改天吧
        </button>
        <button class="invite-btn accept" :disabled="busy" @click="answer('accepted')">
          一起去
        </button>
      </div>
      <p v-else class="invite-note">
        {{
          props.invitation!.status === 'accepted'
            ? '她记得这个约定，聊天时会提起。'
            : '她短期内不会再约你了。'
        }}
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { answerActivityInvitation, type ActivityInvitation } from '@/api/activity'

const props = defineProps<{ invitation: ActivityInvitation | null }>()
const emit = defineEmits<{ (e: 'answered', action: 'accepted' | 'declined'): void }>()

const busy = ref(false)
async function answer(action: 'accepted' | 'declined') {
  if (busy.value) return
  busy.value = true
  try {
    await answerActivityInvitation(action)
    emit('answered', action)
  } catch {
    /* 失败时保持 pending，用户可以再点一次（后端幂等） */
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.invite-overlay-layer {
  display: flow-root;
}

.invite-card {
  margin: 10px 0 14px;
  padding: 14px 16px;
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.14), rgba(168, 85, 247, 0.1));
  border: 1px solid rgba(129, 140, 248, 0.34);
}

.invite-card.answered {
  opacity: 0.72;
}

.invite-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.invite-badge {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.invite-live {
  font-size: 11px;
  color: #a5b4fc;
}

.invite-live.done {
  color: var(--text-secondary);
}

.invite-activity {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.invite-message {
  margin: 6px 0 0;
  padding-left: 10px;
  border-left: 2px solid rgba(129, 140, 248, 0.5);
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-primary);
}

.invite-actions {
  display: flex;
  gap: 10px;
  margin-top: 12px;
}

.invite-btn {
  flex: 1;
  padding: 9px 0;
  border: none;
  border-radius: var(--radius-md);
  font-size: 13px;
  color: #fff;
  cursor: pointer;
  transition: transform 0.12s ease, opacity 0.12s ease;
}

.invite-btn:active { transform: scale(0.97); }
.invite-btn:disabled { opacity: 0.55; cursor: default; }
.invite-btn.decline { background: rgba(148, 163, 184, 0.55); }
.invite-btn.accept { background: linear-gradient(135deg, #6366f1, #8b5cf6); }

.invite-note {
  margin: 10px 0 0;
  font-size: 11px;
  color: var(--text-secondary);
}
</style>
