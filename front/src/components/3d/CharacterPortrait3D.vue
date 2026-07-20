<template>
  <div class="character-portrait-3d" :style="boxStyle">
    <VRMAvatar
      v-if="use3d"
      ref="avatarRef"
      :model-url="activeModelUrl"
      :width="width"
      :height="height"
      :transparent="false"
      background="#16162a"
      :enable-controls="false"
      :expression="expression"
      :expression-weight="expressionWeight"
      :enable-gaze-control="enableGazeControl"
      @load-error="onLoadError"
      @model-loaded="onModelLoaded"
    />

    <div
      v-else
      class="static-portrait"
      :style="{ background: staticAvatar ? 'transparent' : gradient }"
    >
      <img
        v-if="staticAvatar"
        :src="staticAvatar"
        class="static-img"
        alt="角色头像"
      />
      <span v-else class="static-initial">{{ initial }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import VRMAvatar from './VRMAvatar.vue'
import {
  isWebGLAvailable,
  getCharacterVrmUrl,
  expressionFromFavorability,
  DEFAULT_VRM_URL,
} from '@/utils/avatar3d'
import { subscribeTtsLipSync } from '@/services/webrtcService'
import {
  getCharacterAvatarUrl,
  getCharacterGradient,
  getCharacterInitial,
} from '@/utils/character'

interface Props {
  characterId?: string
  characterName?: string
  avatar?: string
  vrmModel?: string
  favorability?: number
  width?: number
  height?: number
  /** 同一时刻只应有一个订阅者 */
  enableCallLipSync?: boolean
  /** 启用智能注视（鼠标跟随 + 输入注视） */
  enableGazeControl?: boolean
  /** 输入框状态 */
  inputState?: {
    focused: boolean
    hasContent: boolean
  }
}

const props = withDefaults(defineProps<Props>(), {
  characterId: 'default',
  characterName: '',
  avatar: '',
  vrmModel: '',
  favorability: 50,
  width: 140,
  height: 180,
  enableCallLipSync: false,
  enableGazeControl: false,
  inputState: () => ({ focused: false, hasContent: false }),
})

const avatarRef = ref<InstanceType<typeof VRMAvatar> | null>(null)
const webglOk = ref(false)
const useStatic = ref(false)
const activeModelUrl = ref(DEFAULT_VRM_URL)

const boxStyle = computed(() => ({
  width: `${props.width}px`,
  height: `${props.height}px`,
}))

const preferredModelUrl = computed(() =>
  getCharacterVrmUrl({
    id: props.characterId,
    vrm_model: props.vrmModel || undefined,
  }),
)

const favExpr = computed(() => expressionFromFavorability(props.favorability))
const expression = computed(() => favExpr.value.expression)
const expressionWeight = computed(() => favExpr.value.weight)

const staticAvatar = computed(() => getCharacterAvatarUrl(props.avatar))
const gradient = computed(() => getCharacterGradient(props.characterId))
const initial = computed(() => getCharacterInitial(props.characterName || '?'))

const use3d = computed(() => webglOk.value && !useStatic.value)

// TODO: 注视控制器功能待实现
// 鼠标位置追踪
// const onMouseMove = (e: MouseEvent) => {
//   if (!props.enableGazeControl || !use3d.value) return;
//   if (!e.currentTarget) return;
//
//   const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
//   const x = e.clientX - rect.left;
//   const y = e.clientY - rect.top;
//
//   avatarRef.value?.updateGazePosition?.(x, y);
// };

// // 输入状态传递
// watch(() => props.inputState, (state) => {
//   if (!props.enableGazeControl || !use3d.value) return;
//   avatarRef.value?.updateInputState?.(state.focused, state.hasContent);
// }, { deep: true });

function resetModelUrl() {
  activeModelUrl.value = preferredModelUrl.value
  useStatic.value = false
}

function onLoadError() {
  if (activeModelUrl.value !== DEFAULT_VRM_URL) {
    activeModelUrl.value = DEFAULT_VRM_URL
    return
  }
  useStatic.value = true
}

function onModelLoaded() {
  useStatic.value = false
}

let unsubLipSync: (() => void) | null = null

function bindLipSync(enabled: boolean) {
  unsubLipSync?.()
  unsubLipSync = null
  if (!enabled) return
  unsubLipSync = subscribeTtsLipSync((intensity) => {
    avatarRef.value?.updateMouthMorph(intensity)
  })
}

watch(preferredModelUrl, () => resetModelUrl(), { immediate: true })

watch(
  () => [props.enableCallLipSync, use3d.value] as const,
  ([lip, ok]) => bindLipSync(!!lip && ok),
  { immediate: true },
)

onMounted(() => {
  webglOk.value = isWebGLAvailable()
})

onBeforeUnmount(() => {
  unsubLipSync?.()
  unsubLipSync = null
})

defineExpose({
  updateMouthMorph: (intensity: number) => {
    avatarRef.value?.updateMouthMorph(intensity)
  },
})
</script>

<style scoped>
.character-portrait-3d {
  position: relative;
  margin: 0 auto;
  border-radius: 24px;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(123, 92, 255, 0.3);
  flex-shrink: 0;
}

.character-portrait-3d :deep(.vrm-avatar-container),
.character-portrait-3d :deep(.three-scene-container) {
  width: 100% !important;
  height: 100% !important;
  border-radius: 0;
}

.character-portrait-3d :deep(.three-canvas) {
  border-radius: 0;
}

.static-portrait {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.static-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.static-initial {
  font-size: 64px;
  font-weight: 800;
  color: rgba(255, 255, 255, 0.9);
  text-shadow: 0 2px 12px rgba(0, 0, 0, 0.3);
}
</style>
