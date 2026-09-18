<template>
  <div
    ref="portraitRef"
    class="character-portrait-3d"
    :class="{ 'is-popout': popOut && use3d }"
    :style="boxStyle"
    @mousemove="onMouseMove"
    @mouseleave="onMouseLeave"
  >
    <template v-if="use3d">
      <!-- 脚下柔光：把角色"焊"在卡片上，不然无框之后会有漂浮感 -->
      <div v-if="popOut" class="portrait-halo" aria-hidden="true" />

      <div class="portrait-stage" :class="{ 'is-popout': popOut }" :style="stageStyle">
        <VRMAvatar
          ref="avatarRef"
          :model-url="activeModelUrl"
          :width="canvasWidth"
          :height="canvasHeight"
          :transparent="popOut"
          :background="popOut ? 'transparent' : '#16162a'"
          :enable-controls="enableControls"
          :expression="expression"
          :expression-weight="expressionWeight"
          :enable-gaze-control="enableGazeControl"
          :enable-body-follow="enableBodyFollow"
          :framing="framing"
          :model-scale="render.scale"
          :rotation-y="render.rotationY"
          :camera-padding="cameraPadding"
          :auto-rotate="render.autoRotate"
          @load-error="onLoadError"
          @model-loaded="onModelLoaded"
          @avatar-click="emit('avatarClick')"
        />
      </div>
    </template>

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
  resolveExpression,
  computePopOutStage,
  DEFAULT_VRM_URL,
  type Framing,
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
  /** 角色当前心情（character_state.mood，如「开心」「生气」）；优先于好感度驱动表情 */
  mood?: string
  width?: number
  height?: number
  /** 同一时刻只应有一个订阅者 */
  enableCallLipSync?: boolean
  /** 启用智能注视（鼠标跟随 + 输入注视） */
  enableGazeControl?: boolean
  /** 启用鼠标旋转/缩放控制 */
  enableControls?: boolean
  /** 鼠标在角色区域内时上半身轻微跟随 */
  enableBodyFollow?: boolean
  /** 输入框状态 */
  inputState?: {
    focused: boolean
    hasContent: boolean
  }
  /**
   * 无框浮出：去掉深色底 / 圆角 / 裁切，把画布放大并底部锚定，
   * 让人物溢出卡片边界，看起来是"站在卡片上"而不是"被框住"。
   * 只在 3D 真正渲染时生效；降级成静态头像时仍然是有边框的头像块。
   */
  popOut?: boolean
  /** 取景方式：full = 全身；bust = 半身特写 */
  framing?: Framing
}

const props = withDefaults(defineProps<Props>(), {
  characterId: 'default',
  characterName: '',
  avatar: '',
  vrmModel: '',
  modelConfig: null,
  // 不传好感度时，表情跟随模型配置的 default_expression
  favorability: undefined,
  mood: '',
  width: 140,
  height: 180,
  enableCallLipSync: false,
  enableGazeControl: false,
  enableControls: true,
  enableBodyFollow: true,
  inputState: () => ({ focused: false, hasContent: false }),
  popOut: true,
  framing: 'full',
})

const emit = defineEmits<{
  /** 角色被点击 */
  avatarClick: []
}>()

const avatarRef = ref<InstanceType<typeof VRMAvatar> | null>(null)
const webglOk = ref(false)
const useStatic = ref(false)
const activeModelUrl = ref(DEFAULT_VRM_URL)

const boxStyle = computed(() => ({
  width: `${props.width}px`,
  height: `${props.height}px`,
}))

/** 浮出画布的尺寸 / 溢出量（纯函数，见 utils/avatar3d.computePopOutStage） */
const stage = computed(() =>
  computePopOutStage({ width: props.width, height: props.height, popOut: props.popOut }),
)

const canvasWidth = computed(() => stage.value.canvasWidth)
const canvasHeight = computed(() => stage.value.canvasHeight)

/** 浮出时取景留白要乘一个系数，让角色在放大后的画布里填得更满 */
const cameraPadding = computed(() => render.value.cameraPadding * stage.value.framingScale)

/** 浮出时把画布从文档流里拿出来，底部锚定 + 水平居中，才能溢出槽位 */
const stageStyle = computed(() => {
  if (!stage.value.popOut) return undefined
  return {
    width: `${stage.value.canvasWidth}px`,
    height: `${stage.value.canvasHeight}px`,
    bottom: `${-stage.value.bottomOffset}px`,
  }
})

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

/** 表情解析：心情优先 → 好感度 → 模型配置的默认表情 */
const resolvedExpression = computed(() =>
  resolveExpression({
    mood: props.mood,
    favorability: typeof props.favorability === 'number' ? props.favorability : null,
    defaultExpression: render.value.defaultExpression,
  }),
)
const expression = computed(() => resolvedExpression.value.expression)
const expressionWeight = computed(() => resolvedExpression.value.weight)

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
  /** 当前表情与来源（供 UI / 测试断言） */
  currentExpression: () => resolvedExpression.value,
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

/*
 * 无框浮出：槽位本身不再画任何东西（无底色 / 无圆角裁切 / 无外阴影），
 * 只保留尺寸用于占位，真正的角色由 .portrait-stage 溢出渲染。
 * overflow 必须放开，否则父级一裁切，"浮出"立刻退回"框里"。
 */
.character-portrait-3d.is-popout {
  border-radius: 0;
  overflow: visible;
  box-shadow: none;
  background: transparent;
  z-index: 2;
}

.portrait-stage {
  width: 100%;
  height: 100%;
}

.portrait-stage.is-popout {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  z-index: 2;
}

/* 脚下柔光：无框之后角色容易显得飘，用一层暖紫光晕把重心压回卡片 */
.portrait-halo {
  position: absolute;
  left: 50%;
  bottom: -10px;
  width: 150%;
  height: 55%;
  transform: translateX(-50%);
  background: radial-gradient(
    ellipse at 50% 62%,
    rgba(123, 92, 255, 0.28) 0%,
    rgba(123, 92, 255, 0.1) 45%,
    transparent 74%
  );
  filter: blur(4px);
  pointer-events: none;
  z-index: 1;
}

.character-portrait-3d :deep(.vrm-avatar-container) {
  width: 100% !important;
  height: 100% !important;
}

/* 非浮出模式仍然要把内层画布的圆角压平，避免双层圆角 */
.character-portrait-3d:not(.is-popout) :deep(.three-scene-container),
.character-portrait-3d:not(.is-popout) :deep(.three-canvas) {
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
