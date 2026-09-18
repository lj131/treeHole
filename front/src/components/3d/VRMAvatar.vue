<template>
  <div
    class="vrm-avatar-container"
    :class="{ 'is-clickable': enableClickReaction }"
    @pointerdown="onPointerDown"
  >
    <ThreeScene
      ref="sceneRef"
      :width="width"
      :height="height"
      :transparent="transparent"
      :background="background"
      :enable-controls="enableControls"
      :framing="framing"
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
import type { Framing } from '@/utils/avatar3d';
import { LipSyncEngine, lipSyncEngine } from './LipSyncEngine';
import { gazeController, GazeMode } from './GazeController';

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
  /** 模型缩放（后端 model3d.scale）：1 = 自适应取景；>1 更近更大，<1 更远更小 */
  modelScale?: number;
  /** 绕 Y 轴初始旋转（度，后端 model3d.rotation_y） */
  rotationY?: number;
  /** 取景留白（后端 model3d.camera_distance 换算） */
  cameraPadding?: number;
  /** 缓慢自转（后端 model3d.auto_rotate） */
  autoRotate?: boolean;
  /** 取景方式：full = 全身入画；bust = 半身特写 */
  framing?: Framing;
  /** 鼠标在角色区域内时，上半身跟着轻微转向（配合视线，避免"只有眼珠子在动"） */
  enableBodyFollow?: boolean;
  /** 点击角色的反应（惊讶表情 + 身体轻颤） */
  enableClickReaction?: boolean;
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
  modelScale: 1,
  rotationY: 0,
  cameraPadding: 1.35,
  autoRotate: false,
  framing: 'full',
  enableBodyFollow: true,
  enableClickReaction: true,
});

const emit = defineEmits<{
  modelLoaded: [vrm: VRM];
  loadError: [error: string];
  /** 角色被点击（父级可以拿来做对话/互动） */
  avatarClick: [];
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
/** 呼吸深度调制相位：让呼吸有"深一口浅一口"的变化，而不是节拍器 */
let breathDepthPhase = 0;

// 手臂静止姿态：把 T-pose 压成自然下垂的 A-pose（弧度）
// 左臂绕 Z 轴负向转 = 向下；右臂对称取正
const ARM_REST_Z = 1.18;
const ELBOW_REST_Z = 0.16;

// 注视控制
let gazeInitialized = false;

// ─────────────────────────────────────────
// 站姿系统
//
// 问题：真人站着不会一动不动。之前的 idle 只给各骨骼叠了正弦波，
// 结果是「每个关节都在抖，但整体重心从没挪过」——看起来像机械人。
//
// 做法：把站姿拆成若干「姿势预设」，每隔几秒挑一个，所有参数向它缓慢
// 缓动（约 1.5s 完成），于是重心会真的从一条腿挪到另一条腿；正弦波只
// 负责在预设之上做微抖动。
// ─────────────────────────────────────────

/** 姿势参数，全部是相对基准姿势的偏移量 */
interface IdlePose {
  /** 重心：-1 完全压左腿，+1 完全压右腿 */
  weight: number;
  /** 躯干左右转（弧度） */
  bodyYaw: number;
  /** 躯干侧倾（弧度） */
  bodyRoll: number;
  /** 头部额外朝向（弧度，正值 = 转向角色自己的左侧） */
  headYaw: number;
  /** 头部额外俯仰（弧度，正值 = 低头） */
  headPitch: number;
  /** 手臂张开度：正值让上臂离身体远一点（弧度） */
  armOpen: number;
  /** 手肘弯曲：正值让双手往前收到身前（弧度） */
  armBend: number;
  /** 单侧手臂前摆（弧度，正 = 右手往前） */
  armSwing: number;
}

const NEUTRAL_POSE: IdlePose = {
  weight: 0,
  bodyYaw: 0,
  bodyRoll: 0,
  headYaw: 0,
  headPitch: 0,
  armOpen: 0,
  armBend: 0,
  armSwing: 0,
};

/** 候选姿势 + 相对权重（neutral 权重最高，避免角色一直在动） */
const POSE_POOL: Array<{ pose: IdlePose; weight: number }> = [
  { pose: NEUTRAL_POSE, weight: 3 },
  {
    pose: { ...NEUTRAL_POSE, weight: -0.9, bodyYaw: 0.05, bodyRoll: -0.03, headYaw: 0.05, armOpen: 0.03 },
    weight: 2,
  },
  {
    pose: { ...NEUTRAL_POSE, weight: 0.9, bodyYaw: -0.05, bodyRoll: 0.03, headYaw: -0.05, armOpen: 0.03 },
    weight: 2,
  },
  {
    // 双手收到身前（像在摆弄衣角 / 抱着手臂）
    pose: { ...NEUTRAL_POSE, weight: 0.15, bodyYaw: 0.02, headPitch: 0.04, armOpen: 0.10, armBend: 0.30, armSwing: 0.06 },
    weight: 1.4,
  },
  {
    // 转头看别处（比眼球扫视更明显的一次「走神」）
    pose: { ...NEUTRAL_POSE, weight: -0.4, bodyYaw: -0.07, headYaw: 0.24, headPitch: 0.02, armOpen: 0.02 },
    weight: 1.2,
  },
  {
    // 单手叉腰
    pose: { ...NEUTRAL_POSE, weight: 0.7, bodyYaw: 0.04, bodyRoll: 0.04, headYaw: -0.08, armOpen: 0.16, armBend: 0.5, armSwing: -0.08 },
    weight: 0.8,
  },
];

const poseTarget: IdlePose = { ...NEUTRAL_POSE };
const poseCurrent: IdlePose = { ...NEUTRAL_POSE };
/** 距离下次换姿势的秒数 */
let poseTimer = 2.5 + Math.random() * 3;

/** 点击反应：一个会衰减的脉冲，叠加在姿势上 */
let reactionImpulse = 0;
/** 反应触发的表情（短暂覆盖基础表情） */
let reactionExpression: { name: AvatarExpression; weight: number } | null = null;
let reactionTimer = 0;

/** 鼠标驱动上半身跟随：目标值（归一化 -1..1） */
let bodyFollowTargetX = 0;
let bodyFollowTargetY = 0;
let bodyFollowCurrentX = 0;
let bodyFollowCurrentY = 0;
let hasBodyFollowInput = false;

function pickPose(): IdlePose {
  const total = POSE_POOL.reduce((sum, item) => sum + item.weight, 0);
  let roll = Math.random() * total;
  for (const item of POSE_POOL) {
    roll -= item.weight;
    if (roll <= 0) return item.pose;
  }
  return NEUTRAL_POSE;
}

/** 缓动逼近目标姿势；factor 越小越慢 */
function updatePose(delta: number): void {
  poseTimer -= delta;
  if (poseTimer <= 0) {
    Object.assign(poseTarget, pickPose());
    // 3.5–9s 换一次，偶尔长时间保持同一姿势（真人也是这样的）
    poseTimer = 3.5 + Math.random() * 5.5;
  }

  const factor = 1 - Math.exp(-1.4 * delta);
  for (const key of Object.keys(NEUTRAL_POSE) as Array<keyof IdlePose>) {
    poseCurrent[key] += (poseTarget[key] - poseCurrent[key]) * factor;
  }

  // 鼠标跟随（独立于姿势，响应更快）
  const followFactor = 1 - Math.exp(-3.2 * delta);
  const targetX = hasBodyFollowInput ? bodyFollowTargetX : 0;
  const targetY = hasBodyFollowInput ? bodyFollowTargetY : 0;
  bodyFollowCurrentX += (targetX - bodyFollowCurrentX) * followFactor;
  bodyFollowCurrentY += (targetY - bodyFollowCurrentY) * followFactor;

  // 点击脉冲指数衰减
  if (reactionImpulse > 0) {
    reactionImpulse *= Math.exp(-4.5 * delta);
    if (reactionImpulse < 0.002) reactionImpulse = 0;
  }

  // 反应表情计时
  if (reactionTimer > 0) {
    reactionTimer -= delta;
    if (reactionTimer <= 0) reactionExpression = null;
  }
}

function resetPoseState(): void {
  Object.assign(poseTarget, NEUTRAL_POSE);
  Object.assign(poseCurrent, NEUTRAL_POSE);
  poseTimer = 2 + Math.random() * 2.5;
  reactionImpulse = 0;
  reactionExpression = null;
  reactionTimer = 0;
  bodyFollowTargetX = 0;
  bodyFollowTargetY = 0;
  bodyFollowCurrentX = 0;
  bodyFollowCurrentY = 0;
  hasBodyFollowInput = false;
  breathPhase = 0;
  breathDepthPhase = 0;
}

// 模型姿态（后端 model3d 配置驱动）
let baseSceneRotationY = 0; // rotateVRM0 之后的基准朝向，配置旋转叠加在它之上
let spinAngle = 0; // auto_rotate 累加角度

/** 生效取景留白：cameraPadding / scale —— 缩放语义为「取景远近」，
 *  与 frameObject 的自适应取景配合（直接改 mesh.scale 会被自动取景抵消）。 */
function effectivePadding(): number {
  const scale = Number.isFinite(props.modelScale) && props.modelScale > 0 ? props.modelScale : 1;
  return props.cameraPadding / scale;
}

/** 把 rotationY + auto_rotate 叠加到模型根节点朝向 */
function applySceneRotation(): void {
  if (!vrm) return;
  const deg = Number.isFinite(props.rotationY) ? props.rotationY : 0;
  vrm.scene.rotation.y = baseSceneRotationY + (deg * Math.PI) / 180 + spinAngle;
}

/** 重新取景（缩放 / 相机距离 / 取景方式变化时） */
function reframe(): void {
  if (!vrm) return;
  sceneRef.value?.frameObject?.(vrm.scene, effectivePadding(), props.framing);
}

/** 点击角色：惊讶一下 + 身体轻颤，像被戳到 */
function onPointerDown(): void {
  if (!props.enableClickReaction || !vrm) return;

  reactionImpulse = 1;
  reactionExpression = { name: 'surprised', weight: 0.75 };
  reactionTimer = 0.65;
  // 被戳到会下意识眨一下眼
  blinkProgress = 0;
  emit('avatarClick');
}

// 微表情系统
const microTimers = new Map<string, number>([
  ['browUp', 3 + Math.random() * 5],
  ['browDown', 5 + Math.random() * 6],
  ['mouthPout', 7 + Math.random() * 8],
  ['microSmile', 6 + Math.random() * 7],
  ['lipPart', 5 + Math.random() * 10],
]);
const microWeights = new Map<string, number>([
  ['browUp', 0],
  ['browDown', 0],
  ['mouthPout', 0],
  ['microSmile', 0],
  ['lipPart', 0],
]);
// 微表情衰减速度 (指数衰减因子, 越大越快)
const microDecay = 0.92;

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
  updatePose(delta);
  updateIdleAnimation(delta);
  vrm.update(delta);

  // 缓慢自转（后端 model3d.auto_rotate）
  if (props.autoRotate) {
    spinAngle += delta * 0.35;
    applySceneRotation();
  }

  // 更新智能注视控制器
  if (gazeInitialized && props.enableGazeControl) {
    gazeController.update(delta);
  }
};

/**
 * 调优 VRM SpringBone 物理参数，让头发/裙摆摆动更自然
 */
function tuneSpringBones(vrmInstance: VRM): void {
  const sbm = vrmInstance.springBoneManager;
  if (!sbm) return;

  try {
    // @pixiv/three-vrm 3.x: springBones 是 VRMSpringBone 数组
    const springBones = (sbm as unknown as Record<string, unknown>).springBones as Array<Record<string, unknown>> | undefined;
    if (!springBones || !Array.isArray(springBones)) return;

    for (const group of springBones) {
      // 遍历每个弹簧骨组的关节/骨骼
      const joints = group.settings as Array<Record<string, unknown>> | undefined;
      const bones = group.bones as Array<Record<string, unknown>> | undefined;
      // 尝试 settings.joints 或直接在 group 上
      const targets = joints ?? bones ?? [];

      if (Array.isArray(targets)) {
        for (const joint of targets) {
          // 降低硬度 → 摆动幅度更大
          if (typeof joint.stiffness === 'number') {
            joint.stiffness *= 0.45;
          }
          // 降低阻力 → 摆动更持久
          if (typeof joint.dragForce === 'number') {
            joint.dragForce *= 0.55;
          }
          // 轻微增加重力 → 更自然的垂感
          if (typeof joint.gravityPower === 'number') {
            joint.gravityPower = Math.min(joint.gravityPower * 1.15, 2.0);
          }
        }
      }
    }
  } catch (err) {
    // SpringBone 调优失败不影响模型显示
    console.debug('[VRMAvatar] SpringBone tuning skipped:', err);
  }
}

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

    // 记录基准朝向，叠加后端配置的旋转
    baseSceneRotationY = loadedVrm.scene.rotation.y;
    spinAngle = 0;
    vrm = loadedVrm;
    applySceneRotation();

    scene.add(loadedVrm.scene);
    currentModelUrl = url;

    // 调优 SpringBone 物理参数，让头发/裙摆更自然
    tuneSpringBones(loadedVrm);

    // 注视系统：启用 GazeController 或回退简单相机注视
    if (loadedVrm.lookAt) {
      loadedVrm.lookAt.autoUpdate = true;
      const cam = sceneRef.value?.camera?.();
      if (cam) {
        if (props.enableGazeControl) {
          gazeController.init(loadedVrm, cam);
          gazeInitialized = true;
        } else {
          loadedVrm.lookAt.target = cam;
        }
      }
    }

    // 重置 idle 状态
    clockElapsed = 0;
    nextBlinkAt = 1.2 + Math.random() * 2;
    blinkProgress = -1;
    mouthIntensity = 0;
    resetPoseState();

    // 重置微表情
    for (const key of microWeights.keys()) microWeights.set(key, 0);
    for (const key of microTimers.keys()) microTimers.set(key, randomMicroInterval(key));

    // 重置手指骨骼缓存（新模型骨骼结构不同）
    fingerBoneCache.clear();

    // 更新姿态后再构图（双 rAF 确保骨骼矩阵就绪）
    loadedVrm.scene.updateMatrixWorld(true);
    requestAnimationFrame(() => {
      loadedVrm.scene.updateMatrixWorld(true);
      requestAnimationFrame(() => {
        sceneRef.value?.frameObject?.(loadedVrm.scene, effectivePadding(), props.framing);
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
 *
 * 骨骼轴向备忘（实测确认，别凭直觉改）：
 * - 归一化 humanoid 里左臂静止方向是 -X、右臂是 +X；
 * - Euler 默认 XYZ 序 = R = Rx · Ry · Rz，所以 Z 最先作用、X 最后作用；
 * - 上臂 `rotation.z` 控制抬/垂（左正右负 = 下垂），`rotation.x` 控制前后摆；
 * - 小臂 `rotation.z` 是往身体内侧收；**`rotation.y` 才是往前屈肘**，
 *   `rotation.x` 只是绕骨骼自身轴扭转（会把手掌拧成"刀片"）。左右手符号相反。
 */
const updateIdleAnimation = (delta: number) => {
  if (!vrm) return;

  const humanoid = vrm.humanoid;
  if (!humanoid) return;

  const t = clockElapsed;
  const pose = poseCurrent;

  // 呼吸：除了相位，再叠一层慢速「深度调制」，于是会偶尔来一口深呼吸，
  // 而不是永远同一个振幅的节拍器。
  breathDepthPhase += delta * 0.11;
  breathPhase += delta * 0.95;
  const depthMod = 0.78 + 0.3 * Math.sin(breathDepthPhase) + 0.12 * Math.sin(breathDepthPhase * 2.7);
  const breathAmp = breathAmplitude * Math.max(0.35, depthMod);
  const breathRaw = Math.sin(breathPhase);
  const breath = breathRaw >= 0 ? Math.sqrt(breathRaw) : -Math.sqrt(-breathRaw);
  const breathValue = breath * breathAmp;

  // 鼠标跟随 / 点击脉冲（未启用时保持 0）
  const followX = props.enableBodyFollow ? bodyFollowCurrentX : 0;
  const followY = props.enableBodyFollow ? bodyFollowCurrentY : 0;
  const jolt = reactionImpulse;

  // ── 髋部：姿势重心 + 呼吸微浮 + 反应轻颤 ──
  const hips = humanoid.getNormalizedBoneNode('hips');
  if (hips) {
    hips.rotation.y = pose.bodyYaw * 0.6 + followX * 0.05 + Math.sin(t * 0.31) * 0.018;
    hips.rotation.z = pose.weight * 0.045 + pose.bodyRoll + Math.sin(t * 0.42) * 0.012;
    hips.rotation.x = Math.sin(t * 0.38) * 0.008 + jolt * 0.025;
    hips.position.x = pose.weight * 0.012;
    hips.position.y = breathValue * 0.25 - jolt * 0.005;
  }

  // ── 腿：反向补偿髋部偏移，脚底尽量不挪窝 ──
  const leftUpperLeg = humanoid.getNormalizedBoneNode('leftUpperLeg');
  const rightUpperLeg = humanoid.getNormalizedBoneNode('rightUpperLeg');
  if (leftUpperLeg) {
    leftUpperLeg.rotation.z = -pose.weight * 0.028 + Math.sin(t * 0.24) * 0.005;
    leftUpperLeg.rotation.y = -pose.bodyYaw * 0.4;
  }
  if (rightUpperLeg) {
    rightUpperLeg.rotation.z = -pose.weight * 0.028 - Math.sin(t * 0.24 + 0.7) * 0.005;
    rightUpperLeg.rotation.y = -pose.bodyYaw * 0.4;
  }

  // ── 胸 / 脊柱：呼吸起伏 + 躯干朝向 ──
  const chest =
    humanoid.getNormalizedBoneNode('chest') ??
    humanoid.getNormalizedBoneNode('spine');
  if (chest) {
    chest.rotation.x = breathValue;
    chest.rotation.y = pose.bodyYaw * 0.5 + followX * 0.04;
    chest.rotation.z = pose.bodyRoll * 0.6;
    chest.position.y = breathValue * 0.5;
  }

  const spine = humanoid.getNormalizedBoneNode('spine');
  if (spine && spine !== chest) {
    spine.rotation.x = Math.sin(breathPhase * 0.9) * breathAmp * 0.35;
    spine.rotation.y = pose.bodyYaw * 0.3;
  }

  // ── 肩部：呼吸开合 + 重心侧的肩下沉 ──
  const leftShoulder = humanoid.getNormalizedBoneNode('leftShoulder');
  const rightShoulder = humanoid.getNormalizedBoneNode('rightShoulder');
  const breathInfluence = breath * 0.018;
  if (leftShoulder) {
    leftShoulder.rotation.z = Math.sin(t * 0.52) * 0.03 - 0.012 + breathInfluence + pose.weight * 0.02;
    leftShoulder.rotation.y = Math.sin(t * 0.38 + 0.6) * 0.018;
  }
  if (rightShoulder) {
    rightShoulder.rotation.z = -Math.sin(t * 0.52 + 0.3) * 0.03 + 0.012 + breathInfluence - pose.weight * 0.02;
    rightShoulder.rotation.y = Math.sin(t * 0.38) * 0.018;
  }

  // ── 上臂：A-pose 基准 + 姿势张开度 + 前后摆 + 呼吸摆动 ──
  // VRM rest pose 是 T-pose，不压基准的话角色会一直平举双臂。
  const armOpen = pose.armOpen;
  const leftUpperArm = humanoid.getNormalizedBoneNode('leftUpperArm');
  const rightUpperArm = humanoid.getNormalizedBoneNode('rightUpperArm');
  const armIdleSway = Math.sin(t * 0.45) * 0.04;
  if (leftUpperArm) {
    leftUpperArm.rotation.z = ARM_REST_Z - armOpen + armIdleSway + breath * 0.01;
    leftUpperArm.rotation.x = pose.armSwing + Math.sin(t * 0.33 + 1.2) * 0.025;
    leftUpperArm.rotation.y = Math.sin(t * 0.27 + 0.4) * 0.03;
  }
  if (rightUpperArm) {
    rightUpperArm.rotation.z = -(ARM_REST_Z - armOpen) - armIdleSway - breath * 0.01;
    rightUpperArm.rotation.x = pose.armSwing + Math.sin(t * 0.33 + 0.8) * 0.025;
    rightUpperArm.rotation.y = Math.sin(t * 0.27) * 0.03;
  }

  // ── 小臂：内收基准 + 屈肘（往前弯） ──
  // 轴向推导（实测 + 叉积验证，别再凭直觉改）：
  // 上臂绕 Z 转 1.18 之后，小臂的局部 X 轴在世界上是 Rz(1.18)·X ≈ (0.38, 0.93, 0)，
  // 而小臂骨骼方向 ≈ (-0.38, -0.93, 0) —— 两者**反平行**，所以 `rotation.x` 是
  // 绕骨骼自身轴的扭转（会把扁平的手掌拧成一片"刀片"），不是屈肘。
  // 局部 Y 轴 ≈ (-0.93, 0.38, 0) 与骨骼方向垂直，绕它转才是真正的前后屈肘。
  // 左右手符号相反：左臂 +y 往前，右臂 -y 往前。
  const armBend = pose.armBend;
  const leftLowerArm = humanoid.getNormalizedBoneNode('leftLowerArm');
  const rightLowerArm = humanoid.getNormalizedBoneNode('rightLowerArm');
  if (leftLowerArm) {
    leftLowerArm.rotation.z = ELBOW_REST_Z + Math.sin(t * 0.3 + 0.7) * 0.018;
    leftLowerArm.rotation.y = armBend + Math.sin(t * 0.26 + 1.5) * 0.02;
  }
  if (rightLowerArm) {
    rightLowerArm.rotation.z = -ELBOW_REST_Z - Math.sin(t * 0.3 + 1.1) * 0.018;
    rightLowerArm.rotation.y = -armBend - Math.sin(t * 0.26 + 2.1) * 0.02;
  }

  // ── 头部：姿势朝向 + 鼠标跟随 + 微动 ──
  const head = humanoid.getNormalizedBoneNode('head');
  if (head) {
    head.rotation.y = pose.headYaw + followX * 0.16 + Math.sin(t * 0.28) * 0.035 + Math.sin(t * 0.09) * 0.012;
    head.rotation.x = pose.headPitch + followY * 0.08 + Math.sin(t * 0.38 + 0.5) * 0.022 - jolt * 0.06;
    head.rotation.z = Math.sin(t * 0.22 + 0.3) * 0.012;
  }

  // ── 颈部：跟随头部但幅度更小，形成自然的链条运动 ──
  const neck = humanoid.getNormalizedBoneNode('neck');
  if (neck) {
    neck.rotation.y = pose.headYaw * 0.35 + followX * 0.06 + Math.sin(t * 0.25) * 0.014;
    neck.rotation.x = pose.headPitch * 0.3 + followY * 0.03 + Math.sin(t * 0.35 + 0.5) * 0.01;
  }

  updateHandGestures(delta);
  updateAudioBodyAnimation(delta);
  updateBlink(delta);
  updateMicroExpressions(delta);
  smoothExpressions();
  applyCurrentExpressions();
  updateVisemeBasedMouth(delta);
};

/**
 * 微表情调度器：周期性触发 + 指数衰减
 * 叠加在基础表情之上，强度 0~0.2
 */
const updateMicroExpressions = (delta: number) => {
  for (const [name, timer] of microTimers) {
    const remaining = timer - delta;
    if (remaining <= 0) {
      // 触发微表情
      triggerMicroExpression(name);
      microTimers.set(name, randomMicroInterval(name));
    } else {
      microTimers.set(name, remaining);
    }
  }

  // 衰减所有微表情权重
  for (const [name, weight] of microWeights) {
    const decayed = weight * microDecay;
    // 低于阈值视为0
    microWeights.set(name, decayed < 0.003 ? 0 : decayed);
  }

  // 将微表情叠加到 targetExpressionWeights
  applyMicroExpressions();
};

function triggerMicroExpression(name: string): void {
  switch (name) {
    case 'browUp':
      microWeights.set('browUp', 0.1 + Math.random() * 0.1);
      microWeights.set('browDown', 0);
      break;
    case 'browDown':
      microWeights.set('browDown', 0.08 + Math.random() * 0.1);
      microWeights.set('browUp', 0);
      break;
    case 'mouthPout':
      microWeights.set('mouthPout', 0.06 + Math.random() * 0.08);
      break;
    case 'microSmile':
      microWeights.set('microSmile', 0.08 + Math.random() * 0.1);
      break;
    case 'lipPart':
      microWeights.set('lipPart', 0.05 + Math.random() * 0.04);
      break;
  }
}

function randomMicroInterval(name: string): number {
  switch (name) {
    case 'browUp':
    case 'browDown':
      return 3 + Math.random() * 6;
    case 'mouthPout':
      return 5 + Math.random() * 8;
    case 'microSmile':
      return 5 + Math.random() * 10;
    case 'lipPart':
      return 6 + Math.random() * 12;
    default:
      return 5 + Math.random() * 8;
  }
}

/** 将微表情权重叠加到 target 层 */
function applyMicroExpressions(): void {
  // 眉毛互斥
  const browUp = microWeights.get('browUp') ?? 0;
  const browDown = microWeights.get('browDown') ?? 0;
  if (browUp > 0) {
    setExpression('browUp', Math.min(browUp, 0.2));
  }
  if (browDown > 0) {
    setExpression('browDown', Math.min(browDown, 0.2));
  }

  // 张口嘴型
  const lipPart = microWeights.get('lipPart') ?? 0;
  if (lipPart > 0 && mouthIntensity < 0.1) {
    // 只在不说话时微张嘴
    setExpression('aa', lipPart * 0.5);
  }

  // 微笑和撇嘴叠加到基础表情
  const microSmile = microWeights.get('microSmile') ?? 0;
  const mouthPout = microWeights.get('mouthPout') ?? 0;
  if (microSmile > 0 && activeExpression !== 'happy') {
    const currentHappy = currentExpressionWeights['happy'] ?? 0;
    setExpression('happy', Math.min(currentHappy + microSmile, 1.0));
  }
  if (mouthPout > 0) {
    const currentSad = currentExpressionWeights['sad'] ?? 0;
    setExpression('sad', Math.min(currentSad + mouthPout, 0.25));
  }
}

// ─────────────────────────────────────────
// P4: 手势系统 — 手指微动 idle + 说话手势增强
// ─────────────────────────────────────────

/** 手指骨骼名映射（VRM Humanoid 标准） */
const FINGER_NAMES: Record<string, string[]> = {
  leftThumb: ['leftThumbProximal', 'leftThumbIntermediate', 'leftThumbDistal'],
  leftIndex: ['leftIndexProximal', 'leftIndexIntermediate', 'leftIndexDistal'],
  leftMiddle: ['leftMiddleProximal', 'leftMiddleIntermediate', 'leftMiddleDistal'],
  leftRing: ['leftRingProximal', 'leftRingIntermediate', 'leftRingDistal'],
  leftLittle: ['leftLittleProximal', 'leftLittleIntermediate', 'leftLittleDistal'],
  rightThumb: ['rightThumbProximal', 'rightThumbIntermediate', 'rightThumbDistal'],
  rightIndex: ['rightIndexProximal', 'rightIndexIntermediate', 'rightIndexDistal'],
  rightMiddle: ['rightMiddleProximal', 'rightMiddleIntermediate', 'rightMiddleDistal'],
  rightRing: ['rightRingProximal', 'rightRingIntermediate', 'rightRingDistal'],
  rightLittle: ['rightLittleProximal', 'rightLittleIntermediate', 'rightLittleDistal'],
};

/** 缓存已查找到的手指骨骼引用 */
const fingerBoneCache = new Map<string, THREE.Object3D | null>();

function getFingerBone(humanoid: NonNullable<VRM['humanoid']>, name: string): THREE.Object3D | null {
  const cacheKey = name;
  if (fingerBoneCache.has(cacheKey)) return fingerBoneCache.get(cacheKey) ?? null;

  try {
    const bone = humanoid.getNormalizedBoneNode(name as Parameters<typeof humanoid.getNormalizedBoneNode>[0]);
    fingerBoneCache.set(cacheKey, bone ?? null);
    return bone ?? null;
  } catch {
    fingerBoneCache.set(cacheKey, null);
    return null;
  }
}

const updateHandGestures = (delta: number) => {
  if (!vrm?.humanoid) return;

  const humanoid = vrm.humanoid;
  const t = clockElapsed;

  // 每根手指独立相位 + 振幅（减少幅度，更自然）
  const fingerPhases: Record<string, number> = {
    leftThumb: 0.0, leftIndex: 0.3, leftMiddle: 0.6, leftRing: 0.9, leftLittle: 1.2,
    rightThumb: 0.5, rightIndex: 0.8, rightMiddle: 1.1, rightRing: 1.4, rightLittle: 1.7,
  };
  const fingerAmps: Record<string, number> = {
    leftThumb: 0.03, leftIndex: 0.025, leftMiddle: 0.03, leftRing: 0.025, leftLittle: 0.02,
    rightThumb: 0.03, rightIndex: 0.025, rightMiddle: 0.03, rightRing: 0.025, rightLittle: 0.02,
  };

  // 说话时手势幅度增强
  const speechBoost = mouthIntensity > 0.2 ? 1 + mouthIntensity * 2.5 : 1.0;

  for (const [fingerGroup, boneNames] of Object.entries(FINGER_NAMES)) {
    const phase = fingerPhases[fingerGroup] ?? 0;
    const baseAmp = (fingerAmps[fingerGroup] ?? 0.025) * speechBoost;
    const fingerCurl = Math.sin(t * 0.25 + phase) * baseAmp;

    for (const boneName of boneNames) {
      const bone = getFingerBone(humanoid, boneName);
      if (bone) {
        // 手指弯曲绕 z 轴（T-pose 默认），用 = 避免帧间累积
        bone.rotation.z = fingerCurl;
      }
    }
  }

  // 手腕微转
  const leftHand = humanoid.getNormalizedBoneNode('leftHand');
  const rightHand = humanoid.getNormalizedBoneNode('rightHand');
  const wristAmplitude = 0.02 * speechBoost;
  if (leftHand) {
    leftHand.rotation.y = Math.sin(t * 0.3 + 0.2) * wristAmplitude;
    leftHand.rotation.z = Math.sin(t * 0.22 + 0.8) * wristAmplitude * 0.7;
  }
  if (rightHand) {
    rightHand.rotation.y = -Math.sin(t * 0.3 + 0.2) * wristAmplitude;
    rightHand.rotation.z = -Math.sin(t * 0.22 + 0.8) * wristAmplitude * 0.7;
  }
};

// ─────────────────────────────────────────
// P7: 音频驱动体态 — 说话时头部/身体微动
// ─────────────────────────────────────────
const updateAudioBodyAnimation = (delta: number) => {
  if (!vrm?.humanoid || mouthIntensity <= 0.15) return;

  const humanoid = vrm.humanoid;
  const intensity = mouthIntensity;

  // 头部微微前倾 + 点头（随语音强度）
  const head = humanoid.getNormalizedBoneNode('head');
  if (head) {
    // 叠加到已有 head.rotation.x 上（由 idle 动画设定了基础值）
    head.rotation.x += Math.sin(clockElapsed * 9.0) * intensity * 0.012;
  }

  // 脊柱微前倾（叠加在 idle 基础上）
  const spine = humanoid.getNormalizedBoneNode('spine');
  if (spine) {
    spine.rotation.x += intensity * 0.006;
  }

  // 眉毛随语音微扬（说话时眉毛会动）
  if (vrm.expressionManager) {
    setExpression('browUp', intensity * 0.08);
  }

  // 肩膀微耸（叠加在 idle 基础上）
  const leftShoulder = humanoid.getNormalizedBoneNode('leftShoulder');
  const rightShoulder = humanoid.getNormalizedBoneNode('rightShoulder');
  if (leftShoulder) {
    leftShoulder.rotation.z += Math.sin(clockElapsed * 8.0) * intensity * 0.02;
  }
  if (rightShoulder) {
    rightShoulder.rotation.z -= Math.sin(clockElapsed * 8.0 + 0.3) * intensity * 0.02;
  }
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
    // 约 18% 概率连眨第二下 —— 真人眨眼经常是成对的
    if (Math.random() < 0.18) {
      nextBlinkAt = clockElapsed + 0.16 + Math.random() * 0.12;
    } else {
      // 下次眨眼时间更随机，避免可预测的模式
      nextBlinkAt = clockElapsed + 2.0 + Math.random() * 4.0;
    }
  }

  setExpression('blink', value);
  // 部分模型用左右分眼；给一点左右差异，避免「两只眼一模一样」的塑料感
  setExpression('blinkLeft', Math.min(1, value * 1.04));
  setExpression('blinkRight', Math.min(1, value * 0.96));
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
 * 点击反应（reactionExpression）优先级最高，短暂覆盖基础表情
 */
const applyCurrentExpressions = () => {
  if (!vrm?.expressionManager) return;

  const overridden = reactionExpression?.name;

  for (const name of BASE_EXPRESSIONS) {
    if (name === overridden) {
      setExpression(name, reactionExpression?.weight ?? 0);
      continue;
    }
    // 反应期间把其它基础表情压下去，避免两张脸叠在一起
    const weight = currentExpressionWeights[name] ?? 0;
    setExpression(name, reactionExpression ? weight * 0.15 : weight);
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

// 后端 3D 配置变化 → 重新取景 / 更新朝向（无需重载模型）
watch(
  () => [props.modelScale, props.cameraPadding] as const,
  () => reframe()
);

// 取景方式变化（全身 ↔ 半身）→ 重新构图
watch(
  () => props.framing,
  () => reframe()
);

watch(
  () => props.rotationY,
  () => applySceneRotation()
);

watch(
  () => props.autoRotate,
  (on) => {
    if (!on) {
      spinAngle = 0;
      applySceneRotation();
    }
  }
);

defineExpose({
  vrm: () => vrm,
  updateMouthMorph,
  updateMorph: (intensity: number) => {
    updateMouthMorph(intensity);
  },
  setExpression: setAvatarExpression,
  getExpression: () => activeExpression,
  updateGazePosition: (x: number, y: number) => {
    gazeController.updateMousePosition(x, y);
    // 同一份鼠标位置顺带驱动上半身跟随（眼珠子动、身体不动会很怪）
    hasBodyFollowInput = true;
    bodyFollowTargetX = Math.max(-1, Math.min(1, (x - 0.5) * 2));
    bodyFollowTargetY = Math.max(-1, Math.min(1, (0.5 - y) * 2));
  },
  clearGazeMouse: () => {
    gazeController.clearMouseInput();
    hasBodyFollowInput = false;
  },
  updateInputState: (focused: boolean, hasContent: boolean) => {
    gazeController.updateInputState(focused, hasContent);
  },
  getGazeMode: () => gazeController.getCurrentMode(),
  dispose: () => {
    lipSyncEngine.dispose();
    gazeController.dispose();
    gazeInitialized = false;
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

.vrm-avatar-container.is-clickable {
  cursor: pointer;
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
