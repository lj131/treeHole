<template>
  <div class="vrm-avatar-container">
    <ThreeScene
      ref="sceneRef"
      :width="width"
      :height="height"
      :transparent="transparent"
      :background="background"
      :enable-controls="enableControls"
      @scene-ready="onSceneReady"
      @frame="onFrame"
    />

    <div v-if="loading" class="loading-overlay">
      <div class="loading-spinner" />
      <span class="loading-text">加载模型中...</span>
    </div>

    <div v-if="error" class="error-overlay">
      <span class="error-text">{{ error }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onBeforeUnmount, watch } from 'vue';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRM, VRMUtils } from '@pixiv/three-vrm';
import ThreeScene from './ThreeScene.vue';
import { LipSyncEngine, lipSyncEngine } from './LipSyncEngine';
// TODO: 实现 GazeController.ts 暂时注释掉
// import { gazeController, GazeMode } from './GazeController';

/** 预设表情名（VRM Expression 标准子集） */
export type AvatarExpression =
  | 'neutral'
  | 'happy'
  | 'angry'
  | 'sad'
  | 'surprised'
  | 'relaxed';

interface Props {
  modelUrl: string;
  width?: number;
  height?: number;
  transparent?: boolean;
  background?: string;
  enableControls?: boolean;
  lipSyncAudio?: HTMLAudioElement | null;
  /** 当前基础表情（与眨眼 / 嘴型叠加） */
  expression?: AvatarExpression;
  /** 基础表情强度 0–1 */
  expressionWeight?: number;
  /** 是否启用智能注视 */
  enableGazeControl?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  width: 400,
  height: 560,
  transparent: false,
  background: '#1a1a2e',
  enableControls: true,
  lipSyncAudio: null,
  expression: 'neutral',
  expressionWeight: 0.7,
  enableGazeControl: false,
});

const emit = defineEmits<{
  modelLoaded: [vrm: VRM];
  loadError: [error: string];
}>();

const sceneRef = ref<InstanceType<typeof ThreeScene>>();
const loading = ref(false);
const error = ref<string | null>(null);

let vrm: VRM | null = null;
let currentModelUrl = '';
let scene: THREE.Scene | null = null;
let clockElapsed = 0;
let nextBlinkAt = 2.5;
let blinkProgress = -1; // -1 = idle, 0..1 = blinking
let mouthIntensity = 0;
let activeExpression: AvatarExpression = 'neutral';
let activeExpressionWeight = 0.7;

// 表情平滑过渡
let targetExpressionWeights: Record<string, number> = {};
let currentExpressionWeights: Record<string, number> = {};
const expressionSmoothFactor = 0.08;

// 呼吸动画优化
let breathPhase = 0;
let breathAmplitude = 0.028;

// 注视控制
let gazeInitialized = false;

// 嘴型 viseme
let currentViseme = 'neutral';
let visemeSmoothFactor = 0.15; // 嘴型平滑因子

/** 互斥基础表情列表（切换时清零） */
const BASE_EXPRESSIONS: AvatarExpression[] = [
  'happy',
  'angry',
  'sad',
  'surprised',
  'relaxed',
];

const onSceneReady = (readyScene: THREE.Scene) => {
  scene = readyScene;
  if (props.modelUrl) {
    loadModel(props.modelUrl);
  }
};

/**
 * 每帧：VRM 物理/表情更新 + idle 动画
 */
const onFrame = (delta: number) => {
  if (!vrm) return;

  clockElapsed += delta;
  updateIdleAnimation(delta);
  vrm.update(delta);
};

const loadModel = async (url: string) => {
  if (!url || !scene) return;
  if (url === currentModelUrl && vrm) return;

  loading.value = true;
  error.value = null;

  if (vrm) {
    scene.remove(vrm.scene);
    VRMUtils.deepDispose(vrm.scene);
    vrm = null;
  }

  try {
    const loader = new GLTFLoader();
    // GLTFParser 类型由 three 提供；此处用 any 避免与 VRMLoaderPlugin 签名漂移
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    loader.register((parser: any) => new VRMLoaderPlugin(parser));

    const gltf = await loader.loadAsync(url);
    const loadedVrm = gltf.userData.vrm as VRM | undefined;

    if (!loadedVrm) {
      throw new Error('VRM 数据未找到，可能不是有效的 VRM 文件');
    }

    // 优化几何 / 骨骼
    VRMUtils.removeUnnecessaryVertices(gltf.scene);
    VRMUtils.combineSkeletons(gltf.scene);

    loadedVrm.scene.traverse((obj: THREE.Object3D) => {
      obj.frustumCulled = false;
      if (obj instanceof THREE.Mesh) {
        obj.castShadow = true;
        obj.receiveShadow = true;
      }
    });

    // 仅 VRM0 需要转 180°；VRM1 已面向 -Z
    VRMUtils.rotateVRM0(loadedVrm);

    scene.add(loadedVrm.scene);
    vrm = loadedVrm;
    currentModelUrl = url;

    // 注视相机，增加眼神生动感（autoUpdate 在 vrm.update 里驱动）
    if (loadedVrm.lookAt) {
      loadedVrm.lookAt.autoUpdate = true;
      const cam = sceneRef.value?.camera?.();
      if (cam) {
        loadedVrm.lookAt.target = cam;
      }
    }

    // 重置 idle 状态
    clockElapsed = 0;
    nextBlinkAt = 1.2 + Math.random() * 2;
    blinkProgress = -1;
    mouthIntensity = 0;

    // 更新姿态后再构图（双 rAF 确保骨骼矩阵就绪）
    loadedVrm.scene.updateMatrixWorld(true);
    requestAnimationFrame(() => {
      loadedVrm.scene.updateMatrixWorld(true);
      requestAnimationFrame(() => {
        sceneRef.value?.frameObject?.(loadedVrm.scene, 1.4);
      });
    });

    emit('modelLoaded', vrm);
  } catch (err) {
    console.error('[VRMAvatar] 加载失败:', err);
    error.value = err instanceof Error ? err.message : '模型加载失败';
    emit('loadError', error.value);
  } finally {
    loading.value = false;
  }
};

/**
 * Idle：呼吸 + 重心转移 + 肩臂微摆 + 头部微动 + 眨眼
 * 优化版本：更自然的节奏，减少机械感
 */
const updateIdleAnimation = (delta: number) => {
  if (!vrm) return;

  const humanoid = vrm.humanoid;
  if (!humanoid) return;

  // 更新呼吸相位（使用连续的时间累加）
  breathPhase += delta * 0.95;

  // 呼吸：胸 / 脊柱起伏（使用平滑的呼吸曲线）
  const chest =
    humanoid.getNormalizedBoneNode('chest') ??
    humanoid.getNormalizedBoneNode('spine');
  if (chest) {
    // 使用正弦波的平方根使呼吸更柔和
    const breathRaw = Math.sin(breathPhase);
    const breath = breathRaw >= 0 ? Math.sqrt(breathRaw) : -Math.sqrt(-breathRaw);
    const breathValue = breath * breathAmplitude;
    chest.rotation.x = breathValue;
    chest.position.y = breathValue * 0.5;
  }

  const spine = humanoid.getNormalizedBoneNode('spine');
  if (spine && spine !== chest) {
    const breathValue = Math.sin(breathPhase * 0.9) * breathAmplitude * 0.35;
    spine.rotation.x = breathValue;
  }

  // 重心：髋部左右微摆 + 轻微前后（使用不同频率组合）
  const hips = humanoid.getNormalizedBoneNode('hips');
  if (hips) {
    const t = clockElapsed;
    hips.rotation.y = Math.sin(t * 0.35) * 0.04 + Math.sin(t * 0.12) * 0.015;
    hips.rotation.z = Math.sin(t * 0.42) * 0.025 + Math.cos(t * 0.18) * 0.008;
    hips.rotation.x = Math.sin(t * 0.38) * 0.01;
  }

  // 肩部开合（稍微夸张以显示呼吸感）
  const leftShoulder = humanoid.getNormalizedBoneNode('leftShoulder');
  const rightShoulder = humanoid.getNormalizedBoneNode('rightShoulder');
  if (leftShoulder) {
    const breathInfluence = Math.sin(breathPhase) * 0.02;
    leftShoulder.rotation.z = Math.sin(clockElapsed * 0.52) * 0.035 - 0.015 + breathInfluence;
    leftShoulder.rotation.y = Math.sin(clockElapsed * 0.38 + 0.6) * 0.02;
  }
  if (rightShoulder) {
    const breathInfluence = Math.sin(breathPhase) * 0.02;
    rightShoulder.rotation.z = -Math.sin(clockElapsed * 0.52 + 0.3) * 0.035 + 0.015 + breathInfluence;
    rightShoulder.rotation.y = Math.sin(clockElapsed * 0.38) * 0.02;
  }

  // 上臂轻微摆动（更放松的姿态）
  const leftUpperArm = humanoid.getNormalizedBoneNode('leftUpperArm');
  const rightUpperArm = humanoid.getNormalizedBoneNode('rightUpperArm');
  if (leftUpperArm) {
    leftUpperArm.rotation.z = Math.sin(clockElapsed * 0.45) * 0.05 - 0.06;
    leftUpperArm.rotation.x = Math.sin(clockElapsed * 0.35 + 1.2) * 0.03;
  }
  if (rightUpperArm) {
    rightUpperArm.rotation.z = -Math.sin(clockElapsed * 0.45 + 0.4) * 0.05 + 0.06;
    rightUpperArm.rotation.x = Math.sin(clockElapsed * 0.35 + 0.8) * 0.03;
  }

  // 头部自然微动（更多细微变化）
  const head = humanoid.getNormalizedBoneNode('head');
  if (head) {
    const t = clockElapsed;
    // 复合正弦波，避免重复模式
    head.rotation.y = Math.sin(t * 0.28) * 0.045 + Math.sin(t * 0.09) * 0.015;
    head.rotation.x = Math.sin(t * 0.38 + 0.5) * 0.025;
    head.rotation.z = Math.sin(t * 0.22 + 0.3) * 0.012;
  }

  // 颈部轻微跟随（更自然的链条运动）
  const neck = humanoid.getNormalizedBoneNode('neck');
  if (neck) {
    const t = clockElapsed;
    neck.rotation.y = Math.sin(t * 0.25) * 0.018;
    neck.rotation.x = Math.sin(t * 0.35 + 0.5) * 0.012;
  }

  updateBlink(delta);
  smoothExpressions();
  applyCurrentExpressions();
  updateVisemeBasedMouth(delta);

  // TODO: 注视控制器功能待实现 (GazeController.ts)
  // if (props.enableGazeControl) {
  //   // 初始化注视控制器
  //   if (vrm.lookAt && !gazeInitialized) {
  //     const cam = sceneRef.value?.camera?.();
  //     if (cam) {
  //       gazeController.init(vrm, cam);
  //       gazeController.setRendererSize(props.width, props.height);
  //       gazeInitialized = true;
  //     }
  //   }
  //   gazeController.update(delta);
  // }
};

const updateBlink = (delta: number) => {
  if (!vrm?.expressionManager) return;

  if (blinkProgress < 0) {
    if (clockElapsed >= nextBlinkAt) {
      blinkProgress = 0;
    }
    return;
  }

  // 一次眨眼约 150ms：0→1→0，使用缓动函数使眨眼更自然
  blinkProgress += delta / 0.15;
  let value = 0;

  // 使用 smoothstep 使眨眼更自然
  if (blinkProgress < 0.5) {
    const t = blinkProgress * 2;
    value = t * t * (3 - 2 * t); // smoothstep
  } else if (blinkProgress < 1) {
    const t = (1 - blinkProgress) * 2;
    value = t * t * (3 - 2 * t); // smoothstep
  } else {
    value = 0;
    blinkProgress = -1;
    // 下次眨眼时间更随机，避免可预测的模式
    nextBlinkAt = clockElapsed + 2.0 + Math.random() * 4.0;
  }

  setExpression('blink', value);
  // 部分模型用左右分眼
  setExpression('blinkLeft', value);
  setExpression('blinkRight', value);
};

const setExpression = (name: string, value: number) => {
  if (!vrm?.expressionManager) return;
  try {
    vrm.expressionManager.setValue(name, value);
  } catch {
    // 该模型没有此表情时忽略
  }
};

/**
 * 平滑过渡表情权重
 */
const smoothExpressions = () => {
  // 初始化目标权重
  for (const name of BASE_EXPRESSIONS) {
    const targetWeight =
      name === activeExpression && activeExpression !== 'neutral'
        ? activeExpressionWeight
        : 0;

    // 当前权重如果不存在则初始化
    if (currentExpressionWeights[name] === undefined) {
      currentExpressionWeights[name] = 0;
    }

    // 使用 Lerp 平滑过渡
    currentExpressionWeights[name] += (targetWeight - currentExpressionWeights[name]) * expressionSmoothFactor;
  }
};

/**
 * 应用当前平滑后的表情权重
 */
const applyCurrentExpressions = () => {
  if (!vrm?.expressionManager) return;

  for (const name of BASE_EXPRESSIONS) {
    const weight = currentExpressionWeights[name] ?? 0;
    setExpression(name, weight);
  }
};

/**
 * 应用基础表情（happy/sad/...），与 blink / mouth 共存
 * @deprecated 使用 smoothExpressions + applyCurrentExpressions
 */
const applyBaseExpressionDeprecated = () => {
  if (!vrm?.expressionManager) return;

  for (const name of BASE_EXPRESSIONS) {
    const weight =
      name === activeExpression && activeExpression !== 'neutral'
        ? activeExpressionWeight
        : 0;
    setExpression(name, weight);
  }
};

/**
 * 设置基础表情（可由 prop 或 expose API 调用）
 * 新机制：仅更新状态，smoothExpressions + applyCurrentExpressions 每帧自动处理
 */
const setAvatarExpression = (
  expression: AvatarExpression,
  weight = props.expressionWeight
) => {
  activeExpression = expression;
  activeExpressionWeight = Math.max(0, Math.min(1, weight));
};

/**
 * 基于 viseme 更新嘴型（增强版）
 */
const updateVisemeBasedMouth = (delta: number) => {
  if (mouthIntensity <= 0) {
    setExpression('aa', 0);
    setExpression('oh', 0);
    setExpression('ee', 0);
    currentViseme = 'neutral';
    return;
  }

  // 平滑过渡 viseme
  const targetViseme = currentViseme;

  // 根据 viseme 应用嘴型
  if (vrm?.expressionManager) {
    switch (targetViseme) {
      case 'aa':
        setExpression('aa', mouthIntensity * 0.9);
        setExpression('oh', mouthIntensity * 0.2);
        setExpression('ee', 0);
        break;
      case 'oh':
        setExpression('aa', mouthIntensity * 0.3);
        setExpression('oh', mouthIntensity * 0.85);
        setExpression('ee', 0);
        break;
      case 'neutral':
        // 微张嘴
        setExpression('aa', mouthIntensity * 0.4);
        setExpression('oh', mouthIntensity * 0.3);
        setExpression('ee', 0);
        break;
      default:
        setExpression('aa', mouthIntensity * 0.5);
        setExpression('oh', mouthIntensity * 0.3);
        setExpression('ee', 0);
    }
  } else {
    // 回退：使用 MorphTarget
    const morphNames: Record<string, string[]> = {
      aa: ['aa', 'A', 'mouthOpen', 'jawOpen', 'MouthOpen', 'JawOpen'],
      oh: ['oh', 'O', 'mouthOh', 'vrc.v_oh'],
      ee: ['ee', 'E', 'mouthEe', 'vrc.v_e'],
    };

    const targetMorphs = morphNames[targetViseme] ?? morphNames.aa ?? morphNames.aa!;
    const otherMorphs = Object.values(morphNames).flat().filter(
      name => !targetMorphs.includes(name)
    );

    vrm?.scene.traverse((node: THREE.Object3D) => {
      if (!(node instanceof THREE.Mesh) || !node.morphTargetDictionary || !node.morphTargetInfluences) {
        return;
      }
      const dict = node.morphTargetDictionary;
      const influences = node.morphTargetInfluences;

      // 设置目标 morph
      if (targetMorphs) {
        for (const name of targetMorphs) {
          const index = dict[name];
          if (index !== undefined) {
            influences[index] = mouthIntensity;
          }
        }
      }

      // 清理其他 morph
      if (otherMorphs) {
        for (const name of otherMorphs) {
          const index = dict[name];
          if (index !== undefined) {
            influences[index] = 0;
          }
        }
      }
    });
  }
};

/**
 * Lip Sync：优先走 VRM Expression（aa），再回退 MorphTarget
 * @deprecated 使用 updateVisemeBasedMouth
 */
const updateMouthMorph = (intensity: number) => {
  mouthIntensity = Math.max(0, Math.min(1, intensity));

  if (!vrm) return;

  if (vrm.expressionManager) {
    setExpression('aa', mouthIntensity);
    setExpression('oh', mouthIntensity * 0.35);
    return;
  }

  // 回退：遍历所有带 morph 的 mesh
  vrm.scene.traverse((node: THREE.Object3D) => {
    if (!(node instanceof THREE.Mesh) || !node.morphTargetDictionary || !node.morphTargetInfluences) {
      return;
    }
    const dict = node.morphTargetDictionary;
    const names = ['aa', 'A', 'mouthOpen', 'jawOpen', 'MouthOpen', 'JawOpen', 'vrc.v_aa'];
    for (const name of names) {
      const index = dict[name];
      if (index !== undefined) {
        node.morphTargetInfluences[index] = mouthIntensity;
        break;
      }
    }
  });
};

watch(
  () => props.modelUrl,
  (url) => {
    if (url && scene) {
      // 允许强制重载不同 URL
      if (url !== currentModelUrl) {
        loadModel(url);
      }
    }
  }
);

watch(
  () => props.lipSyncAudio,
  (audio) => {
    if (audio) {
      lipSyncEngine.startElementAnalysis(
        audio,
        (intensity: number) => {
          mouthIntensity = Math.max(0, Math.min(1, intensity));
          updateVisemeBasedMouth(0.016); // 约 60fps
        }
      );
    } else {
      lipSyncEngine.stop();
      updateVisemeBasedMouth(0);
    }
  },
  { immediate: true }
);

watch(
  () => [props.expression, props.expressionWeight] as const,
  ([expression, weight]) => {
    setAvatarExpression(expression, weight);
  },
  { immediate: true }
);

defineExpose({
  vrm: () => vrm,
  updateMouthMorph,
  updateMorph: (intensity: number) => {
    updateMouthMorph(intensity);
  },
  setExpression: setAvatarExpression,
  getExpression: () => activeExpression,
  // TODO: 注视控制器功能待实现
  // updateGazePosition: (x: number, y: number) => {
  //   gazeController.updateMousePosition(x, y);
  // },
  // updateInputState: (focused: boolean, hasContent: boolean) => {
  //   gazeController.updateInputState(focused, hasContent);
  // },
  // getGazeMode: () => gazeController.getCurrentMode(),
  dispose: () => {
    lipSyncEngine.dispose();
    // gazeController.dispose();
    if (vrm && scene) {
      scene.remove(vrm.scene);
      VRMUtils.deepDispose(vrm.scene);
      vrm = null;
    }
  },
});

onBeforeUnmount(() => {
  lipSyncEngine.dispose();
  if (vrm && scene) {
    scene.remove(vrm.scene);
    VRMUtils.deepDispose(vrm.scene);
    vrm = null;
  }
  scene = null;
});
</script>

<style scoped>
.vrm-avatar-container {
  position: relative;
  width: 100%;
  height: 100%;
}

.loading-overlay,
.error-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.7);
  color: white;
  font-size: 14px;
  border-radius: 12px;
  z-index: 2;
}

.loading-spinner {
  width: 40px;
  height: 40px;
  border: 4px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin-bottom: 8px;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.loading-text,
.error-text {
  font-weight: 500;
}

.error-text {
  color: #ff6b6b;
}
</style>
