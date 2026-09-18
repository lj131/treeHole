<template>
  <div class="settings-page">
    <h1 class="page-title">个人设置</h1>

    <div class="settings-grid">
      <!-- 个人信息 -->
      <section class="card">
        <h2 class="card-title">👤 个人信息</h2>
        <div class="profile-row">
          <div class="avatar-wrap" @click="triggerAvatarUpload">
            <img v-if="avatarUrl" :src="avatarUrl" class="avatar-img" alt="头像" />
            <div v-else class="avatar-fallback">{{ avatarInitial }}</div>
            <div class="avatar-overlay">📷</div>
            <input ref="avatarInput" type="file" accept="image/*" hidden @change="onAvatarChange" />
          </div>
          <div class="profile-fields">
            <label class="field-label">昵称</label>
            <div class="input-row">
              <input v-model="nickname" class="input" placeholder="设置昵称" maxlength="50" />
              <button class="btn btn-sm" :disabled="savingProfile" @click="saveProfile">
                {{ savingProfile ? '保存中...' : '保存' }}
              </button>
            </div>
            <p class="field-hint">用户名：{{ auth.user?.username }}</p>
          </div>
        </div>
        <p v-if="profileMsg" class="msg" :class="profileOk ? 'msg-ok' : 'msg-err'">{{ profileMsg }}</p>
      </section>

      <!-- 修改密码 -->
      <section class="card">
        <h2 class="card-title">🔒 修改密码</h2>
        <div class="form-col">
          <input v-model="pwForm.old" type="password" class="input" placeholder="当前密码" />
          <input v-model="pwForm.new1" type="password" class="input" placeholder="新密码（至少4位）" />
          <input v-model="pwForm.new2" type="password" class="input" placeholder="确认新密码" />
          <button class="btn" :disabled="changingPw" @click="doChangePassword">
            {{ changingPw ? '修改中...' : '修改密码' }}
          </button>
        </div>
        <p v-if="pwMsg" class="msg" :class="pwOk ? 'msg-ok' : 'msg-err'">{{ pwMsg }}</p>
      </section>

      <!-- 消息通知 -->
      <section class="card">
        <h2 class="card-title">🔔 消息通知</h2>
        <div class="notif-row">
          <div>
            <p class="notif-desc">页面后台时收到 AI 回复，推送浏览器通知</p>
            <p class="notif-status">
              权限状态：<strong>{{ permText }}</strong>
            </p>
          </div>
          <div class="notif-actions">
            <button v-if="notifPerm === 'default'" class="btn btn-sm" @click="askNotifPerm">
              允许通知
            </button>
            <label class="toggle-label" v-if="notifPerm === 'granted'">
              <input type="checkbox" v-model="notifEnabled" @change="saveNotifSetting" />
              <span class="toggle-track"><span class="toggle-thumb" /></span>
              {{ notifEnabled ? '已开启' : '已关闭' }}
            </label>
          </div>
        </div>
      </section>

      <!-- 语音包（仅管理员） -->
      <section v-if="auth.isAdmin" class="card card-wide">
        <h2 class="card-title">
          🔊 语音包
          <span class="vp-badge">仅管理员</span>
        </h2>
        <p class="field-hint vp-intro">
          给每个角色配一个自己的声音。语音包是全局资源，改动会影响所有用户和所有角色。
        </p>

        <div v-if="voiceLoading" class="field-hint">加载中...</div>
        <p v-else-if="voiceLoadError" class="msg msg-err">{{ voiceLoadError }}</p>

        <div v-else class="vp-layout">
          <!-- 左：语音包库 -->
          <div class="vp-col">
            <div class="vp-col-head">
              <span class="vp-col-title">语音包库 {{ voicePacks.length }}/{{ voiceMaxPacks }}</span>
              <button class="btn btn-sm" :disabled="showPackForm && !editingPackId" @click="openCreateForm">
                + 新建
              </button>
            </div>

            <div v-if="showPackForm" class="vp-form">
              <div class="vp-form-head">
                <b>{{ editingPackId ? '编辑语音包' : '新建语音包' }}</b>
                <button class="vp-link-btn" @click="closePackForm">取消</button>
              </div>
              <div>
                <label class="field-label">名称</label>
                <input v-model="packForm.name" class="input" maxlength="40" placeholder="例如：温柔学姐" />
              </div>
              <div>
                <label class="field-label">描述（可选）</label>
                <input v-model="packForm.description" class="input" maxlength="200" placeholder="低语速、略低音" />
              </div>
              <div>
                <label class="field-label">引擎</label>
                <select v-model="packForm.engine" class="input">
                  <option v-for="e in voiceEngines" :key="e.engine" :value="e.engine">
                    {{ e.label }}{{ e.available ? '' : '（未部署）' }}
                  </option>
                </select>
                <p v-if="packForm.engine === 'clone'" class="field-hint">
                  克隆引擎需要额外部署，保存后暂时无法试听/合成；参考音频会先存下来，引擎就位即可生效。
                </p>
              </div>
              <div v-if="packForm.engine === 'edge'">
                <label class="field-label">音色</label>
                <select v-model="packForm.voice_name" class="input">
                  <option v-for="v in voiceOptions" :key="v.short_name" :value="v.short_name">
                    {{ v.label }}
                  </option>
                </select>
              </div>
              <div class="vp-slider">
                <label class="field-label">语速 <b>{{ packForm.speaking_rate.toFixed(2) }}</b></label>
                <input v-model.number="packForm.speaking_rate" type="range" min="0.5" max="2" step="0.05" />
              </div>
              <div class="vp-slider">
                <label class="field-label">
                  音调 <b>{{ packForm.pitch > 0 ? '+' : '' }}{{ packForm.pitch.toFixed(0) }}Hz</b>
                </label>
                <input v-model.number="packForm.pitch" type="range" min="-50" max="50" step="1" />
                <p class="field-hint">
                  实测 edge 的部分中文音色会忽略音调（调了听不出差别），且非零音调更容易合成失败。
                  听不出变化属正常，优先用「语速」调语气。
                </p>
              </div>
              <div class="vp-slider">
                <label class="field-label">音量 <b>{{ packForm.volume.toFixed(2) }}</b></label>
                <input v-model.number="packForm.volume" type="range" min="0" max="2" step="0.05" />
              </div>
              <div>
                <label class="field-label">参考音频对应的文本（可选）</label>
                <input
                  v-model="packForm.reference_text"
                  class="input"
                  maxlength="500"
                  placeholder="音频里念的那句话，克隆引擎会用到"
                />
                <p class="field-hint">
                  音色克隆引擎需要知道参考音频说了什么才能对齐音色。现在填上，接引擎时直接生效。
                </p>
              </div>
              <div class="vp-form-actions">
                <button class="btn btn-sm vp-btn-ghost" :disabled="voicePreviewing" @click="previewDraft">
                  {{ voicePreviewing ? '合成中…' : '▶ 试听' }}
                </button>
                <button
                  class="btn btn-sm"
                  :disabled="voiceSaving || !packForm.name.trim()"
                  @click="savePackForm"
                >
                  {{ voiceSaving ? '保存中…' : editingPackId ? '保存修改' : '保存' }}
                </button>
              </div>
            </div>

            <p v-if="!voicePacks.length" class="field-hint">还没有语音包，点「新建」创建第一个。</p>
            <ul class="vp-list">
              <li v-for="p in voicePacks" :key="p.id" class="vp-item vp-item--pack">
                <div class="vp-item-main">
                  <div class="vp-item-title">
                    <b>{{ p.name }}</b>
                    <span class="vp-tag">{{ p.voice_name }}</span>
                    <span v-if="p.engine !== 'edge'" class="vp-tag">{{ p.engine }}</span>
                    <span v-if="p.has_reference_audio" class="vp-tag vp-tag-ok">参考音频</span>
                    <span v-if="p.engine_available === false" class="vp-tag vp-tag-warn">引擎未部署</span>
                  </div>
                  <div class="vp-item-sub">
                    {{ p.description || '无描述' }} · 语速 {{ p.speaking_rate }} · 音调
                    {{ p.pitch > 0 ? '+' : '' }}{{ p.pitch }}Hz · 音量 {{ p.volume }}
                  </div>
                </div>
                <div class="vp-item-actions">
                  <button class="btn btn-sm vp-btn-ghost" :disabled="voicePreviewing" @click="previewPack(p)">
                    ▶ 试听
                  </button>
                  <button
                    class="btn btn-sm vp-btn-ghost"
                    :class="{ 'vp-btn-active': editingPackId === p.id }"
                    @click="openEditForm(p)"
                  >
                    编辑
                  </button>
                  <button class="btn btn-sm vp-btn-ghost" @click="pickReference(p)">上传音频</button>
                  <button v-if="p.has_reference_audio" class="btn btn-sm vp-btn-ghost" @click="removeReference(p)">
                    删音频
                  </button>
                  <button class="btn btn-sm vp-btn-danger" @click="removePack(p)">删除</button>
                </div>
              </li>
            </ul>
            <input
              ref="refInput"
              type="file"
              :accept="voiceRefAccept"
              hidden
              @change="onReferenceChange"
            />
          </div>

          <!-- 右：角色绑定 -->
          <div class="vp-col">
            <div class="vp-col-head">
              <span class="vp-col-title">角色音色</span>
            </div>
            <p v-if="!voiceBindings.length" class="field-hint">没有可用角色。</p>
            <ul class="vp-list">
              <li v-for="b in voiceBindings" :key="b.character_id" class="vp-item">
                <div class="vp-item-main">
                  <div class="vp-item-title"><b>{{ b.character_name }}</b></div>
                  <div class="vp-item-sub">{{ effectiveText(b) }}</div>
                </div>
                <select
                  class="input vp-bind-select"
                  :value="b.pack_id || ''"
                  @change="onBindChange(b.character_id, ($event.target as HTMLSelectElement).value)"
                >
                  <option value="">内置默认音色</option>
                  <option v-for="p in voicePacks" :key="p.id" :value="p.id">{{ p.name }}</option>
                </select>
              </li>
            </ul>
          </div>
        </div>

        <p v-if="voiceMsg" class="msg" :class="voiceOk ? 'msg-ok' : 'msg-err'">{{ voiceMsg }}</p>
      </section>

      <!-- 用量统计 -->
      <section class="card card-wide">
        <h2 class="card-title">📊 用量统计（最近 30 天）</h2>
        <div v-if="usageLoading" class="loading-text">加载中...</div>
        <div v-else-if="usage" class="usage-grid">
          <div class="stat-box">
            <span class="stat-num">{{ totalRequests }}</span>
            <span class="stat-label">总调用次数</span>
          </div>
          <div class="stat-box">
            <span class="stat-num">{{ totalTokensIn }}</span>
            <span class="stat-label">输入 Token</span>
          </div>
          <div class="stat-box">
            <span class="stat-num">{{ totalTokensOut }}</span>
            <span class="stat-label">输出 Token</span>
          </div>
        </div>
        <div v-if="endpointList.length" class="endpoint-list">
          <div v-for="ep in endpointList" :key="ep.name" class="endpoint-row">
            <span class="ep-name">{{ ep.name }}</span>
            <span class="ep-count">{{ ep.count }} 次</span>
            <div class="ep-bar">
              <div class="ep-bar-fill" :style="{ width: epPercent(ep.count) + '%' }"></div>
            </div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useAuthStore } from '@/stores/authStore'
import { updateProfile, changePassword, uploadAvatar, getMyUsage } from '@/api/auth'
import {
  getVoiceOptions,
  getVoicePacks,
  createVoicePack,
  updateVoicePack,
  deleteVoicePack,
  uploadVoiceReference,
  deleteVoiceReference,
  previewVoice,
  bindVoicePack,
} from '@/api/voice'
import type { CharacterVoiceBinding, VoiceEngineInfo, VoiceOption, VoicePack } from '@/types/api'
import {
  isNotificationSupported,
  getNotificationPermission,
  requestNotificationPermission,
  isNotificationEnabled,
  setNotificationEnabled,
} from '@/utils/notification'

const auth = useAuthStore()

// ---- 个人信息 ----
const nickname = ref(auth.user?.nickname || '')
const avatarUrl = ref<string | null>(auth.user?.avatar ? `${import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'}${auth.user.avatar}` : null)
const avatarInput = ref<HTMLInputElement | null>(null)
const avatarInitial = computed(() => (auth.user?.nickname || auth.user?.username || '?')[0]?.toUpperCase())
const savingProfile = ref(false)
const profileMsg = ref('')
const profileOk = ref(false)

async function saveProfile() {
  savingProfile.value = true
  profileMsg.value = ''
  try {
    const res = await updateProfile({ nickname: nickname.value })
    auth.user = res.user
    profileMsg.value = '保存成功'
    profileOk.value = true
  } catch (e: any) {
    profileMsg.value = e.message || '保存失败'
    profileOk.value = false
  } finally {
    savingProfile.value = false
  }
}

function triggerAvatarUpload() {
  avatarInput.value?.click()
}

async function onAvatarChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  try {
    const res = await uploadAvatar(file)
    if (auth.user) auth.user.avatar = res.avatar
    const base = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
    avatarUrl.value = `${base}${res.avatar}`
    profileMsg.value = '头像上传成功'
    profileOk.value = true
  } catch {
    profileMsg.value = '头像上传失败'
    profileOk.value = false
  }
}

// ---- 修改密码 ----
const pwForm = ref({ old: '', new1: '', new2: '' })
const changingPw = ref(false)
const pwMsg = ref('')
const pwOk = ref(false)

async function doChangePassword() {
  pwMsg.value = ''
  if (pwForm.value.new1 !== pwForm.value.new2) {
    pwMsg.value = '两次输入的新密码不一致'
    pwOk.value = false
    return
  }
  changingPw.value = true
  try {
    await changePassword({ old_password: pwForm.value.old, new_password: pwForm.value.new1 })
    pwMsg.value = '密码修改成功'
    pwOk.value = true
    pwForm.value = { old: '', new1: '', new2: '' }
  } catch (e: any) {
    pwMsg.value = e.message || '修改失败'
    pwOk.value = false
  } finally {
    changingPw.value = false
  }
}

// ---- 通知 ----
const notifPerm = ref<NotificationPermission | 'unsupported'>(getNotificationPermission())
const notifEnabled = ref(isNotificationEnabled())

const permText = computed(() => {
  if (notifPerm.value === 'unsupported') return '浏览器不支持'
  if (notifPerm.value === 'granted') return '已允许'
  if (notifPerm.value === 'denied') return '已拒绝（需在浏览器设置中允许）'
  return '未授权'
})

async function askNotifPerm() {
  const p = await requestNotificationPermission()
  notifPerm.value = p
}

function saveNotifSetting() {
  setNotificationEnabled(notifEnabled.value)
}

// ============================================================
// 语音包（仅管理员）
//
// 后端所有 /voice/* 接口都要管理员权限，这里额外用 v-if 藏掉整个区块，
// 免得普通用户看到一堆点了就 403 的按钮。
// ============================================================

const voiceLoading = ref(false)
const voiceLoadError = ref('')
const voiceMsg = ref('')
const voiceOk = ref(false)
const voiceSaving = ref(false)
const voicePreviewing = ref(false)

const voicePacks = ref<VoicePack[]>([])
const voiceBindings = ref<CharacterVoiceBinding[]>([])
const voiceOptions = ref<VoiceOption[]>([])
const voiceEngines = ref<VoiceEngineInfo[]>([])
const voiceMaxPacks = ref(30)
const voiceRefAccept = ref('.wav,.mp3,.m4a,.ogg,.flac')
/** 后端给的默认音色（中文）——新建表单的初始值，不能用列表第一项（那是 en-AU） */
const voiceDefault = ref('')

const showPackForm = ref(false)
/** 正在编辑的语音包 ID；null = 新建模式 */
const editingPackId = ref<string | null>(null)
const packForm = ref({
  name: '',
  description: '',
  engine: 'edge',
  voice_name: '',
  speaking_rate: 1.0,
  pitch: 0,
  volume: 1.0,
  reference_text: '',
})

function emptyPackForm() {
  return {
    name: '',
    description: '',
    engine: 'edge',
    // 用后端给的默认中文音色，而不是列表首项
    voice_name: voiceDefault.value || voiceOptions.value[0]?.short_name || '',
    speaking_rate: 1.0,
    pitch: 0,
    volume: 1.0,
    reference_text: '',
  }
}

/** 待上传参考音频的目标语音包 */
const pendingRefPackId = ref('')
const refInput = ref<HTMLInputElement | null>(null)

/** 正在播放的试听音频（切换/卸载时要停掉并释放 blob URL） */
let previewAudio: HTMLAudioElement | null = null
let previewUrl = ''

function stopPreview() {
  if (previewAudio) {
    previewAudio.pause()
    previewAudio = null
  }
  if (previewUrl) {
    URL.revokeObjectURL(previewUrl)
    previewUrl = ''
  }
}

function setVoiceMsg(text: string, ok = true) {
  voiceMsg.value = text
  voiceOk.value = ok
}

async function loadVoiceData() {
  if (!auth.isAdmin) return
  voiceLoading.value = true
  voiceLoadError.value = ''
  try {
    const [options, packs] = await Promise.all([getVoiceOptions(), getVoicePacks()])
    // 中文音色排前面：后端按 locale 字母序返回，en-AU 会排在第一个，
    // 直接取列表首项当默认值会让中文角色默认用英文音色。
    voiceOptions.value = [...(options.voices || [])].sort((a, b) => {
      const zh = (v: VoiceOption) => (v.short_name.startsWith('zh') ? 0 : 1)
      return zh(a) - zh(b) || a.short_name.localeCompare(b.short_name)
    })
    voiceEngines.value = options.engines || []
    voiceMaxPacks.value = options.max_packs || 30
    voiceRefAccept.value = (options.allowed_audio_exts || []).join(',') || '.wav,.mp3'
    voiceDefault.value = options.default_voice || voiceOptions.value[0]?.short_name || ''
    voicePacks.value = packs.packs || []
    voiceBindings.value = packs.bindings || []
    if (!packForm.value.voice_name) {
      packForm.value.voice_name = voiceDefault.value
    }
  } catch (e: unknown) {
    voiceLoadError.value = e instanceof Error ? e.message : '语音包加载失败'
  } finally {
    voiceLoading.value = false
  }
}

async function refreshPacks() {
  const packs = await getVoicePacks()
  voicePacks.value = packs.packs || []
  voiceBindings.value = packs.bindings || []
}

function openCreateForm() {
  editingPackId.value = null
  packForm.value = emptyPackForm()
  showPackForm.value = true
}

/**
 * 编辑已有语音包。
 *
 * 之前只能删了重建 —— 而删包会连参考音频一起清掉，等于改个名字就丢样本。
 */
function openEditForm(pack: VoicePack) {
  editingPackId.value = pack.id
  packForm.value = {
    name: pack.name,
    description: pack.description || '',
    engine: pack.engine || 'edge',
    voice_name: pack.voice_name,
    speaking_rate: pack.speaking_rate ?? 1.0,
    pitch: pack.pitch ?? 0,
    volume: pack.volume ?? 1.0,
    reference_text: pack.reference_text || '',
  }
  showPackForm.value = true
}

function closePackForm() {
  showPackForm.value = false
  editingPackId.value = null
  packForm.value = emptyPackForm()
}

/** 播放一段试听音频。同一时刻只留一个，避免叠着响。 */
async function playPreview(input: Parameters<typeof previewVoice>[0], label: string) {
  stopPreview()
  voicePreviewing.value = true
  try {
    const blob = await previewVoice(input)
    previewUrl = URL.createObjectURL(blob)
    previewAudio = new Audio(previewUrl)
    previewAudio.onended = stopPreview
    await previewAudio.play()
    setVoiceMsg(`正在试听：${label}`)
  } catch (e: unknown) {
    setVoiceMsg(e instanceof Error ? e.message : '试听失败', false)
  } finally {
    voicePreviewing.value = false
  }
}

function previewDraft() {
  return playPreview(
    {
      voice_name: packForm.value.voice_name,
      speaking_rate: packForm.value.speaking_rate,
      pitch: packForm.value.pitch,
      volume: packForm.value.volume,
    },
    packForm.value.name || '未保存的配置',
  )
}

function previewPack(pack: VoicePack) {
  return playPreview({ pack_id: pack.id }, pack.name)
}

/** 保存表单：按当前模式走新建或局部更新 */
async function savePackForm() {
  if (!packForm.value.name.trim()) {
    setVoiceMsg('请先填名称', false)
    return
  }
  voiceSaving.value = true
  const payload = {
    name: packForm.value.name.trim(),
    description: packForm.value.description.trim(),
    engine: packForm.value.engine,
    voice_name: packForm.value.voice_name,
    speaking_rate: packForm.value.speaking_rate,
    pitch: packForm.value.pitch,
    volume: packForm.value.volume,
    reference_text: packForm.value.reference_text.trim(),
  }
  try {
    if (editingPackId.value) {
      const res = await updateVoicePack(editingPackId.value, payload)
      await refreshPacks()
      closePackForm()
      setVoiceMsg(`已更新「${res.pack.name}」`)
    } else {
      const res = await createVoicePack(payload)
      await refreshPacks()
      closePackForm()
      setVoiceMsg(`已创建「${res.pack.name}」`)
    }
  } catch (e: unknown) {
    // 失败时**不关表单**，否则用户刚填的内容白填了
    setVoiceMsg(e instanceof Error ? e.message : '保存失败', false)
  } finally {
    voiceSaving.value = false
  }
}

async function removePack(pack: VoicePack) {
  if (!window.confirm(`删除语音包「${pack.name}」？已绑定它的角色会回退到内置默认音色，参考音频也会一起删掉。`)) return
  try {
    const res = await deleteVoicePack(pack.id)
    // 正在编辑的就是这个包 → 表单得关掉，否则保存会打到已删除的 ID 上
    if (editingPackId.value === pack.id) closePackForm()
    await refreshPacks()
    setVoiceMsg(res.warning || `已删除「${pack.name}」`, !res.warning)
  } catch (e: unknown) {
    setVoiceMsg(e instanceof Error ? e.message : '删除失败', false)
  }
}

function pickReference(pack: VoicePack) {
  pendingRefPackId.value = pack.id
  refInput.value?.click()
}

async function onReferenceChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  // 选完就把 input 清空，否则同一个文件选第二次不会触发 change
  input.value = ''
  if (!file || !pendingRefPackId.value) return

  try {
    const res = await uploadVoiceReference(pendingRefPackId.value, file)
    await refreshPacks()
    setVoiceMsg(`参考音频已上传（${res.size_kb} KB）`)
  } catch (e: unknown) {
    setVoiceMsg(e instanceof Error ? e.message : '上传失败', false)
  } finally {
    pendingRefPackId.value = ''
  }
}

async function removeReference(pack: VoicePack) {
  try {
    const res = await deleteVoiceReference(pack.id)
    await refreshPacks()
    setVoiceMsg(res.warning || `已删除「${pack.name}」的参考音频`, !res.warning)
  } catch (e: unknown) {
    setVoiceMsg(e instanceof Error ? e.message : '删除失败', false)
  }
}

async function onBindChange(characterId: string, packId: string) {
  try {
    await bindVoicePack(characterId, packId || null)
    await refreshPacks()
    setVoiceMsg(packId ? '已切换该角色的音色' : '已解绑，回退到内置默认音色')
  } catch (e: unknown) {
    setVoiceMsg(e instanceof Error ? e.message : '绑定失败', false)
    // 失败要把下拉框拉回真实状态，别让 UI 停在用户选的那个值上
    await refreshPacks()
  }
}

/** 说清楚「这个角色现在的声音是哪来的」 */
function effectiveText(b: CharacterVoiceBinding): string {
  if (b.effective_source === 'pack') {
    return `当前：${b.effective_pack_name || b.pack_id}（${b.effective_voice}）`
  }
  if (b.effective_source === 'legacy') {
    return `当前：内置默认（${b.effective_voice}）`
  }
  return `当前：全局兜底（${b.effective_voice}）`
}

// ---- 用量统计 ----
interface UsageEndpoint {
  count: number
  tokens_in: number
  tokens_out: number
}
interface UsageData {
  user_id: number
  days: number
  by_endpoint: Record<string, UsageEndpoint>
}

const usage = ref<UsageData | null>(null)
const usageLoading = ref(true)

const endpointList = computed(() => {
  if (!usage.value?.by_endpoint) return []
  return Object.entries(usage.value.by_endpoint).map(([name, data]) => ({
    name,
    count: data.count,
    tokens_in: data.tokens_in,
    tokens_out: data.tokens_out,
  }))
})

const totalRequests = computed(() => endpointList.value.reduce((s, e) => s + e.count, 0))
const totalTokensIn = computed(() => endpointList.value.reduce((s, e) => s + e.tokens_in, 0))
const totalTokensOut = computed(() => endpointList.value.reduce((s, e) => s + e.tokens_out, 0))

function epPercent(count: number): number {
  if (!totalRequests.value) return 0
  return Math.round((count / totalRequests.value) * 100)
}

onMounted(async () => {
  try {
    usage.value = await getMyUsage(30)
  } catch {
    /* ignore */
  } finally {
    usageLoading.value = false
  }
  // 语音包只有管理员能看/能调，普通用户连请求都不用发（后端会 403）
  loadVoiceData()
})

onBeforeUnmount(stopPreview)
</script>

<style scoped>
.settings-page {
  max-width: 900px;
  margin: 0 auto;
  padding: 24px 16px;
}

.page-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--color-text);
  margin-bottom: 24px;
}

.settings-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.card {
  background: var(--bg-secondary, #1a1a2e);
  border-radius: 14px;
  padding: 20px;
  border: 1px solid rgba(255,255,255,0.06);
}

.card-wide {
  grid-column: 1 / -1;
}

.card-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text);
  margin-bottom: 16px;
}

/* 个人信息 */
.profile-row {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.avatar-wrap {
  position: relative;
  width: 64px;
  height: 64px;
  border-radius: 16px;
  overflow: hidden;
  cursor: pointer;
  flex-shrink: 0;
}

.avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.avatar-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, var(--accent-primary, #667eea), var(--accent-secondary, #764ba2));
}

.avatar-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0,0,0,0.5);
  opacity: 0;
  transition: opacity 0.2s;
  font-size: 20px;
}

.avatar-wrap:hover .avatar-overlay {
  opacity: 1;
}

.profile-fields {
  flex: 1;
}

.field-label {
  display: block;
  font-size: 13px;
  color: var(--color-text);
  opacity: 0.7;
  margin-bottom: 6px;
}

.input-row {
  display: flex;
  gap: 8px;
}

.input {
  flex: 1;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid rgba(255,255,255,0.12);
  background: rgba(0,0,0,0.2);
  color: var(--color-text);
  font-size: 14px;
  outline: none;
}

.input:focus {
  border-color: var(--accent-primary, #667eea);
}

.field-hint {
  font-size: 12px;
  color: var(--color-text);
  opacity: 0.5;
  margin-top: 6px;
}

/* 表单 */
.form-col {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.btn {
  padding: 8px 16px;
  border-radius: 8px;
  border: none;
  background: linear-gradient(135deg, var(--accent-primary, #667eea), var(--accent-secondary, #764ba2));
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
}

.btn:hover { opacity: 0.9; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-sm { padding: 6px 12px; font-size: 13px; }

/* 消息 */
.msg {
  margin-top: 10px;
  font-size: 13px;
  padding: 6px 10px;
  border-radius: 6px;
}

.msg-ok { color: #4ade80; background: rgba(74,222,128,0.1); }
.msg-err { color: #f87171; background: rgba(248,113,113,0.1); }

/* 通知 */
.notif-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.notif-desc {
  font-size: 14px;
  color: var(--color-text);
  opacity: 0.8;
}

.notif-status {
  font-size: 12px;
  color: var(--color-text);
  opacity: 0.6;
  margin-top: 4px;
}

.toggle-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: var(--color-text);
  cursor: pointer;
}

.toggle-label input { display: none; }

.toggle-track {
  width: 40px;
  height: 22px;
  border-radius: 11px;
  background: rgba(255,255,255,0.15);
  position: relative;
  transition: background 0.2s;
}

.toggle-label input:checked + .toggle-track {
  background: var(--accent-primary, #667eea);
}

.toggle-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #fff;
  transition: transform 0.2s;
}

.toggle-label input:checked + .toggle-track .toggle-thumb {
  transform: translateX(18px);
}

/* 用量统计 */
.usage-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.stat-box {
  text-align: center;
  padding: 14px;
  border-radius: 10px;
  background: rgba(0,0,0,0.2);
}

.stat-num {
  display: block;
  font-size: 24px;
  font-weight: 700;
  color: var(--accent-primary, #667eea);
}

.stat-label {
  display: block;
  font-size: 12px;
  color: var(--color-text);
  opacity: 0.6;
  margin-top: 4px;
}

.endpoint-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.endpoint-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.ep-name {
  width: 120px;
  font-size: 13px;
  color: var(--color-text);
}

.ep-count {
  width: 60px;
  font-size: 13px;
  color: var(--color-text);
  opacity: 0.7;
  text-align: right;
}

.ep-bar {
  flex: 1;
  height: 8px;
  border-radius: 4px;
  background: rgba(255,255,255,0.08);
  overflow: hidden;
}

.ep-bar-fill {
  height: 100%;
  border-radius: 4px;
  background: linear-gradient(90deg, var(--accent-primary, #667eea), var(--accent-secondary, #764ba2));
  transition: width 0.3s;
}

.loading-text {
  color: var(--color-text);
  opacity: 0.5;
  font-size: 14px;
  text-align: center;
  padding: 20px;
}

@media (max-width: 768px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
  .usage-grid {
    grid-template-columns: 1fr;
  }
}

/* ============ 语音包 ============ */

/*
 * 用 App.vue 的 --text-primary（主题感知、满对比度），而不是硬编码白色：
 * 硬编码会在 [data-theme="light"] 下把浅底上的字也写成白的。
 */
.vp-layout,
.vp-form,
.vp-badge,
.vp-col-title,
.vp-tag,
.vp-item-title,
.vp-item-sub,
.vp-link-btn {
  color: var(--text-primary);
}

.vp-layout .input,
.vp-form .input,
.vp-bind-select {
  color: var(--text-primary);
}

.vp-badge {
  display: inline-block;
  margin-left: 8px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  color: #fbbf24;
  background: rgba(251, 191, 36, 0.15);
  border: 1px solid rgba(251, 191, 36, 0.3);
  vertical-align: middle;
}

.vp-intro {
  margin-top: -8px;
  margin-bottom: 14px;
}

.vp-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr);
  gap: 18px;
}

.vp-col {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.vp-col-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.vp-col-title {
  font-size: 13px;
  font-weight: 600;
  opacity: 0.75;
}

.vp-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  border-radius: 10px;
  background: rgba(0, 0, 0, 0.22);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.vp-form .input {
  width: 100%;
}

.vp-form-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
}

.vp-link-btn {
  border: none;
  background: none;
  padding: 0;
  color: var(--color-text);
  opacity: 0.55;
  font-size: 12px;
  cursor: pointer;
  text-decoration: underline;
}

.vp-link-btn:hover {
  opacity: 0.9;
}

.vp-slider input[type='range'] {
  width: 100%;
  accent-color: var(--accent-primary, #667eea);
}

.vp-slider b {
  color: var(--accent-primary, #667eea);
  font-variant-numeric: tabular-nums;
}

.vp-form-actions {
  display: flex;
  gap: 8px;
  margin-top: 2px;
}

.vp-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.vp-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.07);
}

/* 语音包条目操作多（试听/编辑/上传/删音频/删除），横排会把左边文字压扁 → 上下两行 */
.vp-item--pack {
  flex-direction: column;
  align-items: stretch;
}

.vp-item--pack .vp-item-actions {
  justify-content: flex-start;
}

.vp-item-main {
  min-width: 0;
  flex: 1;
}

.vp-item-title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 14px;
}

.vp-item-sub {
  margin-top: 3px;
  font-size: 12px;
  opacity: 0.55;
  word-break: break-word;
}

.vp-tag {
  padding: 1px 7px;
  border-radius: 6px;
  font-size: 11px;
  background: rgba(255, 255, 255, 0.08);
  opacity: 0.85;
}

.vp-tag-ok {
  color: #4ade80;
  background: rgba(74, 222, 128, 0.14);
}

.vp-tag-warn {
  color: #fbbf24;
  background: rgba(251, 191, 36, 0.14);
}

.vp-item-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
  flex-shrink: 0;
}

.vp-btn-ghost {
  background: rgba(255, 255, 255, 0.12);
  color: var(--text-primary);
}

/* 正在编辑的那个包，按钮高亮一下，避免"点了编辑但看不出来" */
.vp-btn-active {
  background: rgba(102, 126, 234, 0.35);
  color: #fff;
}

.vp-btn-danger {
  background: rgba(248, 113, 113, 0.18);
  color: #f87171;
}

.vp-bind-select {
  flex: 0 0 auto;
  width: 150px;
}

@media (max-width: 900px) {
  .vp-layout {
    grid-template-columns: 1fr;
  }
  .vp-item {
    flex-direction: column;
    align-items: stretch;
  }
  .vp-bind-select {
    width: 100%;
  }
}
</style>
