<template>
  <div
    ref="containerRef"
    class="three-scene-container"
    :class="{ 'is-transparent': transparent }"
    :style="containerStyle"
  >
    <canvas ref="canvasRef" class="three-canvas" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch, computed } from 'vue';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RGBELoader } from 'three/examples/jsm/loaders/RGBELoader.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import {
  EffectComposer,
  EffectPass,
  RenderPass,
  BloomEffect,
  VignetteEffect,
} from 'postprocessing';
import { ParticleField } from './ParticleField';
import { computeFraming, type Framing } from '@/utils/avatar3d';
import { createNightBackgroundTexture } from './sceneBackground';

export type { Framing };

interface Props {
  width?: number;
  height?: number;
  background?: string;
  transparent?: boolean;
  enableControls?: boolean;
  /** 是否启用后处理特效 (Bloom + Vignette) */
  enablePostProcessing?: boolean;
  /** 是否启用漂浮粒子 */
  enableParticles?: boolean;
  /** 取景方式 */
  framing?: Framing;
  /** 是否渲染地面接触阴影（透明模式下靠它让角色"站"在卡片上） */
  enableGroundShadow?: boolean;
  /** 接触阴影浓度 0–1 */
  groundShadowOpacity?: number;
}

const props = withDefaults(defineProps<Props>(), {
  width: 400,
  height: 560,
  background: '#1a1a2e',
  transparent: false,
  enableControls: true,
  enablePostProcessing: true,
  enableParticles: true,
  framing: 'full',
  enableGroundShadow: true,
  groundShadowOpacity: 0.22,
});

/**
 * 透明画布下必须关掉后处理：
 * - Vignette 按屏幕坐标压暗，在透明底上会显出一圈方形暗影 —— 正是我们要去掉的「框」；
 * - EffectComposer 还会额外吃一次离屏渲染，小尺寸浮出窗里不值当。
 * 粒子同理，透明底上会变成悬空噪点。
 */
const usePostProcessing = computed(() => props.enablePostProcessing && !props.transparent);
const useParticles = computed(() => props.enableParticles && !props.transparent);

const emit = defineEmits<{
  sceneReady: [scene: THREE.Scene];
  resize: [width: number, height: number];
  /** 每帧回调，供 VRM 更新用 */
  frame: [delta: number];
}>();

const containerRef = ref<HTMLDivElement>();
const canvasRef = ref<HTMLCanvasElement>();

let scene: THREE.Scene | null = null;
let camera: THREE.PerspectiveCamera | null = null;
let renderer: THREE.WebGLRenderer | null = null;
let controls: OrbitControls | null = null;
let animationId: number | null = null;
let clock: THREE.Clock | null = null;
let composer: EffectComposer | null = null;
let particleField: ParticleField | null = null;
let keyLightRef: THREE.DirectionalLight | null = null;
let groundShadow: THREE.Mesh | null = null;
/** 当前生效的环境贴图（RoomEnvironment 或 HDRI），换新的时要 dispose 旧的 */
let envTextureRef: THREE.Texture | null = null;
/** 程序化夜色背景贴图（非透明模式） */
let backgroundTexture: THREE.Texture | null = null;

const containerStyle = computed(() => ({
  width: `${props.width}px`,
  height: `${props.height}px`,
  background: props.transparent ? 'transparent' : props.background,
}));

const initScene = () => {
  if (!containerRef.value || !canvasRef.value) return;

  scene = new THREE.Scene();
  // 背景分两种：透明模式交给页面（浮出用），否则用程序化夜色贴图。
  // 注意这里**不是** `new THREE.Color(background)` —— 纯色太"塑料"，
  // 而外链 HDRI 天空照又太写实（人物像站在大白天里）。见 sceneBackground.ts。
  if (props.transparent) {
    scene.background = null;
  } else {
    backgroundTexture = createNightBackgroundTexture(props.background);
    scene.background = backgroundTexture;
  }

  // 略宽 FOV，全身入画更稳，少裁脚/头顶
  camera = new THREE.PerspectiveCamera(35, props.width / props.height, 0.1, 100);
  camera.position.set(0, 1.35, 3.8);
  camera.lookAt(0, 0.95, 0);

  renderer = new THREE.WebGLRenderer({
    canvas: canvasRef.value,
    alpha: props.transparent,
    antialias: true,
    powerPreference: 'high-performance',
  });
  renderer.setSize(props.width, props.height);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;

  // 启用阴影增强立体感
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.shadowMap.autoUpdate = true;

  // 后处理：Bloom + Vignette（透明浮出模式下自动跳过）
  if (usePostProcessing.value) {
    composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene, camera));

    const bloom = new BloomEffect({
      intensity: 0.15,
      luminanceThreshold: 0.7,
      luminanceSmoothing: 0.3,
      mipmapBlur: true,
    });

    const vignette = new VignetteEffect({
      darkness: 0.3,
      offset: 0.5,
    });

    composer.addPass(new EffectPass(camera, bloom, vignette));
  }

  setupLights();

  // 添加接收阴影的地面（增强立体感和空间定位）
  if (props.enableGroundShadow) {
    const groundGeometry = new THREE.PlaneGeometry(10, 10);
    const groundMaterial = new THREE.ShadowMaterial({
      opacity: props.groundShadowOpacity,
      color: 0x000000,
    });
    const ground = new THREE.Mesh(groundGeometry, groundMaterial);
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = 0;
    ground.receiveShadow = true;
    ground.name = '__ground_shadow__';
    scene.add(ground);
    groundShadow = ground;
  }

  // 粒子环境（透明浮出模式下会变成悬空噪点，自动跳过）
  if (useParticles.value) {
    particleField = new ParticleField({
      count: 80,
      radius: 2.5,
      height: 3.5,
      color: 0xd4bfff,
      maxSize: 0.018,
      riseSpeed: 0.08,
    });
    particleField.addToScene(scene);
  }

  if (props.enableControls) {
    controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0.95, 0);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 1.0;
    controls.maxDistance = 10;
    controls.maxPolarAngle = Math.PI * 0.92;
    controls.minPolarAngle = Math.PI * 0.08;
    controls.update();
  }

  clock = new THREE.Clock();
  emit('sceneReady', scene);
  startRenderLoop();
};

const setupLights = () => {
  if (!scene) return;

  const currentScene = scene; // Capture non-null reference

  // 基础环境光（降低强度，让 HDRI 主导）
  const ambientLight = new THREE.AmbientLight(0xffffff, 0.38);
  currentScene.add(ambientLight);

  // 三点布光增强立体感
  const keyLight = new THREE.DirectionalLight(0xfff5e6, 1.35);
  keyLight.position.set(2.5, 4, 3);
  keyLight.castShadow = true;
  // 2048 + 贴紧包围盒的阴影相机 = 脚下那圈接触阴影够实、又不至于糊成一片灰
  keyLight.shadow.mapSize.width = 2048;
  keyLight.shadow.mapSize.height = 2048;
  keyLight.shadow.camera.near = 0.1;
  keyLight.shadow.camera.far = 12;
  keyLight.shadow.bias = -0.0012;
  keyLight.shadow.normalBias = 0.02;
  keyLight.shadow.radius = 2;
  currentScene.add(keyLight);
  keyLightRef = keyLight;

  const fillLight = new THREE.DirectionalLight(0xd6e8ff, 0.45);
  fillLight.position.set(-3, 1.6, 2.2);
  currentScene.add(fillLight);

  // 轮廓光：从后上方打，给头发/肩线勾一圈亮边，人物才"立"得起来
  const rimLight = new THREE.DirectionalLight(0xffe9d6, 0.9);
  rimLight.position.set(-1.6, 3.2, -3.4);
  currentScene.add(rimLight);

  // 地面反弹光：从下往上补一点，避免下巴/脖子死黑
  const bounceLight = new THREE.DirectionalLight(0xc9b8ff, 0.18);
  bounceLight.position.set(0.4, -2, 1.2);
  currentScene.add(bounceLight);

  // 环境贴图第一步：本地程序化生成（RoomEnvironment），立刻可用。
  // 之前只挂外链 HDRI —— CDN 一慢或一被墙，scene.environment 就是 null，
  // 所有 PBR 材质退化成"只有直射光"，人物发灰发平，而且首帧要等好几秒。
  const roomEnv = new RoomEnvironment();
  const pmrem = new THREE.PMREMGenerator(renderer as THREE.WebGLRenderer);
  const roomEnvTexture = pmrem.fromScene(roomEnv, 0.04).texture;
  roomEnv.dispose();
  pmrem.dispose();
  currentScene.environment = roomEnvTexture;
  currentScene.environmentIntensity = 0.8;
  envTextureRef = roomEnvTexture;

  // 环境贴图第二步：外链 HDRI 加载成功后升级成更真实的天空环境；
  // 失败就保持 RoomEnvironment，画面依然成立（不会白也不会黑）。
  // **只用于 scene.environment，绝不再当 scene.background** —— 写实天空照当背景
  // 会让人物像站在大白天里，且高饱和的蓝跟暗色 UI 打架。
  const rgbeLoader = new RGBELoader();
  rgbeLoader.load(
    'https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/1k/puresky_1k.hdr',
    (texture) => {
      texture.mapping = THREE.EquirectangularReflectionMapping;
      currentScene.environment = texture;
      currentScene.environmentIntensity = 0.8;

      // 换掉旧的环境贴图，避免显存泄漏
      envTextureRef?.dispose();
      envTextureRef = texture;
    },
    undefined,
    (error) => {
      console.warn('[ThreeScene] HDRI 加载失败，继续用程序化环境贴图:', error);
    }
  );
};

/**
 * 把主光的阴影相机贴合模型包围盒。
 * 不这么做的话默认阴影相机覆盖范围过大，接触阴影会糊成一片灰。
 */
const fitShadowCamera = (box: THREE.Box3) => {
  const light = keyLightRef;
  if (!light) return;

  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const radius = Math.max(size.x, size.y, size.z) * 0.75 + 0.35;

  const cam = light.shadow.camera as THREE.OrthographicCamera;
  cam.left = -radius;
  cam.right = radius;
  cam.top = radius;
  cam.bottom = -radius;
  cam.near = 0.1;
  cam.far = radius * 8;
  cam.updateProjectionMatrix();

  // 让主光始终从模型斜上方指向模型中心。
  // 高度分量刻意压得比水平分量大得多 —— 光越接近头顶，投影越收在脚下，
  // 才是"接触阴影"；光一低，投影就拖成一条长影子，人物看着像站在地板上。
  const dir = new THREE.Vector3(0.28, 1, 0.34).normalize();
  light.position.copy(center).addScaledVector(dir, radius * 3.2);

  // DirectionalLight.target 必须挂在场景里，矩阵才会被更新
  if (!light.target.parent && scene) scene.add(light.target);
  light.target.position.copy(center);
  light.target.updateMatrixWorld();
  light.shadow.needsUpdate = true;
};

/**
 * 根据模型包围盒自动调整相机。
 *
 * - `full`：全身入画（默认），含头发/帽子的余量；
 * - `bust`：半身特写，只取从胸口到头顶这一段，小尺寸卡片里人物更有存在感。
 *
 * 取景数学在 `utils/avatar3d.computeFraming()` 里（纯函数，有单测兜底）。
 * 注意：`padding` 只影响远近，不影响构图中心；改缩放语义请走调用方的 effectivePadding()。
 */
const frameObject = (
  object: THREE.Object3D,
  padding = 1.35,
  framing: Framing = props.framing
) => {
  if (!camera) return;

  // SkinnedMesh / VRM 必须先更新世界矩阵，否则包围盒会偏小导致裁切
  object.updateMatrixWorld(true);

  const box = new THREE.Box3().setFromObject(object);
  if (box.isEmpty()) return;

  const center = box.getCenter(new THREE.Vector3());

  // 脚底贴地、水平居中（相对当前包围盒）
  object.position.x += -center.x;
  object.position.z += -center.z;
  object.position.y += -box.min.y;
  object.updateMatrixWorld(true);

  box.setFromObject(object);
  const fittedSize = box.getSize(new THREE.Vector3());

  const { distance, lookY, visibleHeight } = computeFraming({
    size: { x: fittedSize.x, y: fittedSize.y, z: fittedSize.z },
    minY: box.min.y,
    framing,
    padding,
    fovDeg: camera.fov,
    aspect: camera.aspect,
  });

  camera.position.set(0, lookY + visibleHeight * 0.08, distance);
  camera.near = Math.max(0.05, distance / 100);
  camera.far = Math.max(50, distance * 20);
  camera.updateProjectionMatrix();
  camera.lookAt(0, lookY, 0);

  if (controls) {
    controls.target.set(0, lookY, 0);
    controls.minDistance = distance * 0.4;
    controls.maxDistance = distance * 3;
    controls.update();
  }

  // 阴影相机跟着模型走，接触阴影才够实
  fitShadowCamera(box);

  // 地面阴影平面贴着脚底，避免浮空
  if (groundShadow) {
    groundShadow.position.y = box.min.y + 0.001;
  }
};

const startRenderLoop = () => {
  const render = () => {
    if (!scene || !camera || !renderer || !clock) return;

    const delta = clock.getDelta();
    emit('frame', delta);

    if (controls) controls.update();
    if (particleField) particleField.update(delta);

    if (composer) {
      composer.render(delta);
    } else {
      renderer.render(scene, camera);
    }

    animationId = requestAnimationFrame(render);
  };

  render();
};

const updateSize = () => {
  if (!camera || !renderer) return;

  camera.aspect = props.width / props.height;
  camera.updateProjectionMatrix();
  renderer.setSize(props.width, props.height);
  composer?.setSize(props.width, props.height);
  emit('resize', props.width, props.height);
};

const dispose = () => {
  if (animationId !== null) {
    cancelAnimationFrame(animationId);
    animationId = null;
  }

  if (controls) {
    controls.dispose();
    controls = null;
  }

  if (composer) {
    composer.dispose();
    composer = null;
  }

  if (particleField) {
    if (scene) particleField.removeFromScene(scene);
    particleField.dispose();
    particleField = null;
  }

  if (renderer) {
    renderer.dispose();
    renderer = null;
  }

  scene = null;
  camera = null;
  clock = null;
  keyLightRef = null;
  groundShadow = null;
  envTextureRef?.dispose();
  envTextureRef = null;
  backgroundTexture?.dispose();
  backgroundTexture = null;
};

defineExpose({
  scene: () => scene,
  camera: () => camera,
  renderer: () => renderer,
  controls: () => controls,
  frameObject,
  updateSize,
  dispose,
});

watch([() => props.width, () => props.height], () => {
  updateSize();
});

onMounted(() => {
  initScene();
});

onBeforeUnmount(() => {
  dispose();
});
</script>

<style scoped>
.three-scene-container {
  position: relative;
  overflow: hidden;
  border-radius: 12px;
}

/* 无框浮出：不要圆角裁切、不要底色，让角色直接落在父容器上 */
.three-scene-container.is-transparent {
  border-radius: 0;
  background: transparent;
}

.three-canvas {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
