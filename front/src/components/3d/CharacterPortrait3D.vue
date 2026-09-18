<template>
  <div
    ref="portraitRef"
    class="character-portrait-3d"
    :style="boxStyle"
    @mousemove="onMouseMove"
    @mouseleave="onMouseLeave"
  >
    <VRMAvatar
      v-if="use3d"
      ref="avatarRef"
      :model-url="activeModelUrl"
      :width="width"
      :height="height"
      :transparent="false"
      background="#16162a"
      :enable-controls="enableControls"
      :expression="expression"
      :expression-weight="expressionWeight"
      :enable-gaze-control="enableGazeControl"
      :model-scale="render.scale"
      :rotation-y="render.rotationY"
      :camera-padding="render.cameraPadding"
      :auto-rotate="render.autoRotate"
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
  resolveModelRender,
  expressionFromFavorability,
  DEFAULT_VRM_URL,
} from '@/utils/avatar3d'
import type { Model3DConfig } from '@/types/api'
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
  /** @deprecated 旧字段，改用 modelConfig */
  vrmModel?: string
  /** 后端角色配置里的 3D 模型配置（model3d） */
  modelConfig?: Model3DConfig | null
  favorability?: number
  width?: number
  height?: number
  /** 同一时刻只应有一个订阅者 */
  enableCallLipSync?: boolean
  /** 启用智能注视（鼠标跟随 + 输入注视） */
  enableGazeControl?: boolean
  /** 启用鼠标旋转/缩放控制 */
  enableControls?: boolean
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
  modelConfig: null,
  // 不传好感度时，表情跟随模型配置的 default_expression
  favorability: undefined,
  width: 140,
  height: 180,
  enableCallLipSync: false,
  enableGazeControl: false,
  enableControls: true,
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
  resolveModelRender({
    vrm_model: props.vrmModel || undefined,
    model3d: props.modelConfig ?? null,
  }).url,
)

/** 后端配置解析出的渲染参数（缩放 / 旋转 / 取景 / 自动旋转） */
const render = computed(() =>
  resolveModelRender({
    vrm_model: props.vrmModel || undefined,
    model3d: props.modelConfig ?? null,
  }),
)

/** 是否在用内置 demo 模型（角色还没配自己的模型） */
const isFallbackModel = computed(() => render.value.isFallback)

const favExpr = computed(() =>
  typeof props.favorability === 'number'
    ? expressionFromFavorability(props.favorability)
    : null,
)
const expression = computed(
  () => favExpr.value?.expression ?? render.value.defaultExpression ?? 'neutral',
)
const expressionWeight = computed(() => favExpr.value?.weight ?? 0.7)

const staticAvatar = computed(() => getCharacterAvatarUrl(props.avatar))
const gradient = computed(() => getCharacterGradient(props.characterId))
const initial = computed(() => getCharacterInitial(props.characterName || '?'))

const use3d = computed(() => webglOk.value && !useStatic.value)

// 鼠标位置追踪 → 驱动 GazeController
const portraitRef = ref<HTMLDivElement>()

function onMouseMove(e: MouseEvent) {
  if (!props.enableGazeControl || !use3d.value) return
  const el = portraitRef.value
  if (!el) return

  const rect = el.getBoundingClientRect()
  const x = (e.clientX - rect.left) / rect.width
  const y = (e.clientY - rect.top) / rect.height

  avatarRef.value?.updateGazePosition?.(x, y)
}

function onMouseLeave() {
  if (!props.enableGazeControl || !use3d.value) return
  avatarRef.value?.clearGazeMouse?.()
}

// 输入状态传递
watch(() => props.inputState, (state) => {
  if (!props.enableGazeControl || !use3d.value) return
  avatarRef.value?.updateInputState?.(state.focused, state.hasContent)
}, { deep: true })

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
  /** 供 UI / 测试判断是否在用内置 demo 模型 */
  isFallbackModel: () => isFallbackModel.value,
  /** 当前生效的模型 URL */
  activeModelUrl: () => activeModelUrl.value,
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
