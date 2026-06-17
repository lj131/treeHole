<template>
  <div class="characters-page">
    <!-- 头部 -->
    <header class="characters-header glass-card">
      <div class="header-text">
        <h1 class="page-title">
          <span class="title-icon">🎭</span> 角色管理
        </h1>
        <p class="page-subtitle">选择一个角色开始对话，或创建一个全新的 AI 伴侣</p>
      </div>
      <button class="create-btn" @click="openCreate">
        <span class="plus">＋</span> 创建角色
      </button>
    </header>

    <!-- 卡片墙 -->
    <div v-if="loading && characters.length === 0" class="empty-state">加载中...</div>
    <div v-else-if="characters.length === 0" class="empty-state">还没有角色，点击上方按钮创建一个吧</div>
    <div v-else class="characters-grid">
      <div
        v-for="char in characters"
        :key="char.id"
        class="character-card glass-card"
        :class="{ active: char.id === currentCharacterId }"
        @click="handleSelect(char.id)"
      >
        <span v-if="char.id === currentCharacterId" class="current-badge">当前</span>
        <div
          class="card-avatar"
          :style="{ background: char.avatar ? 'transparent' : getCharacterGradient(char.id) }"
        >
          <img v-if="char.avatar" :src="getCharacterAvatarUrl(char.avatar)" class="avatar-img" alt="" />
          <span v-else class="avatar-initial">{{ getCharacterInitial(char.name) }}</span>
        </div>
        <h3 class="card-name">{{ char.name }}</h3>
        <p class="card-desc">{{ char.description || '等待与你相遇...' }}</p>
        <span v-if="switchingId === char.id" class="switching-hint">切换中...</span>
      </div>
    </div>

    <!-- 创建角色 Modal -->
    <div v-if="showCreate" class="modal-mask" @click.self="closeCreate">
      <div class="modal glass-card">
        <h2 class="modal-title">
          <span>✨</span> 创建新角色
        </h2>
        <p class="modal-tip">用几句话描述你想要的角色，AI 会自动生成完整人设</p>

        <div class="form-group">
          <label>角色关键词 <span class="required">*</span></label>
          <textarea
            v-model="keyword"
            class="form-input form-textarea"
            placeholder="如：傲娇学姐，理工科，喜欢猫，说话带点毒舌但心软"
            rows="3"
            :disabled="creating"
          ></textarea>
        </div>

        <div class="form-group">
          <label>名字 <span class="optional">（选填，留空则由 AI 生成）</span></label>
          <input
            v-model="customName"
            class="form-input"
            placeholder="给角色起个名字"
            :disabled="creating"
          />
        </div>

        <div class="form-group">
          <label>头像 <span class="optional">（选填）</span></label>
          <div class="avatar-upload">
            <div
              class="avatar-preview"
              :style="{ background: avatarPreview ? 'transparent' : 'rgba(255,255,255,0.05)' }"
            >
              <img v-if="avatarPreview" :src="avatarPreview" class="avatar-img" alt="" />
              <span v-else class="upload-placeholder">点击上传</span>
            </div>
            <input
              type="file"
              accept="image/png,image/jpeg,image/gif,image/webp"
              class="file-input"
              @change="handleFileChange"
              :disabled="creating"
            />
            <button v-if="avatarFile" class="clear-avatar-btn" @click="clearAvatar" :disabled="creating">
              移除
            </button>
          </div>
        </div>

        <p v-if="createError" class="error-msg">{{ createError }}</p>

        <div class="modal-actions">
          <button class="btn-secondary" @click="closeCreate" :disabled="creating">取消</button>
          <button class="btn-primary" @click="submitCreate" :disabled="creating || !keyword.trim()">
            <span v-if="creating" class="spinner"></span>
            {{ creating ? '生成中...' : '生成角色' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useChatStore } from '@/stores/chatStore'
import {
  getCharacters,
  createCharacter,
  uploadCharacterAvatar,
} from '@/api'
import {
  getCharacterGradient,
  getCharacterInitial,
  getCharacterAvatarUrl,
} from '@/utils/character'
import type { CharacterBrief } from '@/types/api'

const router = useRouter()
const store = useChatStore()

const characters = ref<CharacterBrief[]>([])
const loading = ref(true)
const currentCharacterId = ref('')
const switchingId = ref('')

// 创建 Modal 状态
const showCreate = ref(false)
const keyword = ref('')
const customName = ref('')
const avatarFile = ref<File | null>(null)
const avatarPreview = ref('')
const creating = ref(false)
const createError = ref('')

async function loadCharacters() {
  loading.value = true
  try {
    const res = await getCharacters()
    characters.value = res.characters ?? []
    currentCharacterId.value = store.currentCharacterId
  } catch (e) {
    console.error('加载角色列表失败', e)
  } finally {
    loading.value = false
  }
}

async function handleSelect(id: string) {
  if (id === currentCharacterId.value) {
    router.push('/chat')
    return
  }
  switchingId.value = id
  try {
    await store.switchCharacter(id)
    currentCharacterId.value = id
    router.push('/chat')
  } catch (e) {
    console.error('切换角色失败', e)
  } finally {
    switchingId.value = ''
  }
}

function openCreate() {
  showCreate.value = true
  createError.value = ''
}

function closeCreate() {
  if (creating.value) return
  showCreate.value = false
  keyword.value = ''
  customName.value = ''
  avatarFile.value = null
  avatarPreview.value = ''
  createError.value = ''
}

function handleFileChange(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  avatarFile.value = file
  avatarPreview.value = URL.createObjectURL(file)
}

function clearAvatar() {
  avatarFile.value = null
  avatarPreview.value = ''
}

async function submitCreate() {
  if (!keyword.value.trim()) return
  creating.value = true
  createError.value = ''
  try {
    // 1. AI 生成角色
    const res = await createCharacter({
      keyword: keyword.value.trim(),
      name: customName.value.trim() || undefined,
    })
    if ('error' in res) {
      createError.value = res.error || '生成失败，请重试'
      return
    }
    const newChar = res.character

    // 2. 切换为当前角色（上传头像的前置条件）
    await store.switchCharacter(newChar.id)
    currentCharacterId.value = newChar.id

    // 3. 若选了头像，现在上传（此时 current 已是新角色）
    if (avatarFile.value) {
      try {
        await uploadCharacterAvatar(avatarFile.value)
      } catch (e) {
        // 头像失败不阻塞流程，仅提示
        console.warn('头像上传失败', e)
      }
    }

    // 4. 刷新列表 + 关闭 + 跳转聊天
    await loadCharacters()
    closeCreate()
    router.push('/chat')
  } catch (e) {
    createError.value = e instanceof Error ? e.message : '生成失败，请重试'
  } finally {
    creating.value = false
  }
}

onMounted(loadCharacters)
</script>

<style scoped>
.characters-page {
  min-height: calc(100vh - 64px);
  padding: 32px 24px;
  max-width: 1200px;
  margin: 0 auto;
  color: #e2e8f0;
}

/* 玻璃态卡片基类 */
.glass-card {
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 20px;
}

/* 头部 */
.characters-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 24px 28px;
  margin-bottom: 32px;
  flex-wrap: wrap;
}

.page-title {
  font-size: 1.75rem;
  font-weight: 700;
  margin: 0 0 6px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.title-icon {
  font-size: 1.5rem;
}

.page-subtitle {
  margin: 0;
  color: #94a3b8;
  font-size: 0.95rem;
}

.create-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 12px 24px;
  border-radius: 12px;
  border: none;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  font-weight: 600;
  font-size: 0.95rem;
  cursor: pointer;
  transition: all 0.25s ease;
  box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
}

.create-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(102, 126, 234, 0.6);
}

.plus {
  font-size: 1.2rem;
  line-height: 1;
}

/* 卡片墙 */
.characters-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 24px;
}

.character-card {
  position: relative;
  padding: 28px 20px;
  text-align: center;
  cursor: pointer;
  transition: all 0.3s ease;
}

.character-card:hover {
  background: rgba(255, 255, 255, 0.08);
  transform: translateY(-6px);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
}

.character-card.active {
  border-color: rgba(123, 92, 255, 0.5);
  background: rgba(123, 92, 255, 0.12);
}

.current-badge {
  position: absolute;
  top: 12px;
  right: 12px;
  padding: 3px 10px;
  border-radius: 10px;
  background: rgba(123, 92, 255, 0.3);
  color: #c4b5fd;
  font-size: 0.7rem;
  font-weight: 600;
}

.card-avatar {
  width: 84px;
  height: 84px;
  border-radius: 50%;
  margin: 0 auto 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.avatar-initial {
  font-size: 2rem;
  font-weight: 700;
  color: white;
}

.card-name {
  font-size: 1.2rem;
  font-weight: 600;
  margin: 0 0 8px;
  color: #f1f5f9;
}

.card-desc {
  font-size: 0.85rem;
  color: #94a3b8;
  line-height: 1.5;
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.switching-hint {
  display: inline-block;
  margin-top: 8px;
  font-size: 0.75rem;
  color: #a78bfa;
}

.empty-state {
  text-align: center;
  padding: 80px 20px;
  color: #94a3b8;
}

/* Modal */
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
}

.modal {
  width: 100%;
  max-width: 480px;
  padding: 32px;
  max-height: 90vh;
  overflow-y: auto;
}

.modal-title {
  font-size: 1.4rem;
  font-weight: 700;
  margin: 0 0 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.modal-tip {
  margin: 0 0 24px;
  color: #94a3b8;
  font-size: 0.88rem;
}

.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  margin-bottom: 8px;
  font-size: 0.9rem;
  font-weight: 600;
  color: #cbd5e1;
}

.required {
  color: #f87171;
}

.optional {
  color: #64748b;
  font-weight: 400;
  font-size: 0.8rem;
}

.form-input {
  width: 100%;
  padding: 10px 14px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.04);
  color: #e2e8f0;
  font-size: 0.92rem;
  font-family: inherit;
  box-sizing: border-box;
  transition: border-color 0.2s ease;
}

.form-input:focus {
  outline: none;
  border-color: rgba(123, 92, 255, 0.6);
}

.form-input::placeholder {
  color: #64748b;
}

.form-textarea {
  resize: vertical;
  min-height: 72px;
}

.avatar-upload {
  display: flex;
  align-items: center;
  gap: 14px;
}

.avatar-preview {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(255, 255, 255, 0.12);
  cursor: pointer;
}

.upload-placeholder {
  font-size: 0.75rem;
  color: #64748b;
}

.file-input {
  font-size: 0.85rem;
  color: #94a3b8;
}

.clear-avatar-btn {
  padding: 6px 12px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: transparent;
  color: #f87171;
  cursor: pointer;
  font-size: 0.8rem;
}

.error-msg {
  margin: 0 0 16px;
  padding: 10px 14px;
  border-radius: 10px;
  background: rgba(248, 113, 113, 0.12);
  border: 1px solid rgba(248, 113, 113, 0.3);
  color: #fca5a5;
  font-size: 0.85rem;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 8px;
}

.btn-secondary,
.btn-primary {
  padding: 10px 22px;
  border-radius: 10px;
  font-weight: 600;
  font-size: 0.9rem;
  cursor: pointer;
  transition: all 0.2s ease;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.btn-secondary {
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: transparent;
  color: #cbd5e1;
}

.btn-secondary:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.06);
}

.btn-primary {
  border: none;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(102, 126, 234, 0.5);
}

.btn-primary:disabled,
.btn-secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 600px) {
  .characters-page {
    padding: 20px 16px;
  }
  .characters-header {
    flex-direction: column;
    align-items: stretch;
  }
  .create-btn {
    justify-content: center;
  }
}
</style>
