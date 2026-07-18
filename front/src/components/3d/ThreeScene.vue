<template>
  <div ref="containerRef" class="three-scene-container" :style="containerStyle">
    <canvas ref="canvasRef" class="three-canvas" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch, computed } from 'vue';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

interface Props {
  width?: number;
  height?: number;
  background?: string;
  transparent?: boolean;
  enableControls?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  width: 400,
  height: 560,
  background: '#1a1a2e',
  transparent: false,
  enableControls: true,
});

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

const containerStyle = computed(() => ({
  width: `${props.width}px`,
  height: `${props.height}px`,
  background: props.transparent ? 'transparent' : props.background,
}));

const initScene = () => {
  if (!containerRef.value || !canvasRef.value) return;

  scene = new THREE.Scene();
  scene.background = props.transparent ? null : new THREE.Color(props.background);

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

  setupLights();

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

  const ambientLight = new THREE.AmbientLight(0xffffff, 0.75);
  scene.add(ambientLight);

  const keyLight = new THREE.DirectionalLight(0xfff5e6, 1.1);
  keyLight.position.set(2.5, 4, 3);
  scene.add(keyLight);

  const fillLight = new THREE.DirectionalLight(0xd6e8ff, 0.45);
  fillLight.position.set(-3, 2, -1);
  scene.add(fillLight);

  const rimLight = new THREE.DirectionalLight(0xffffff, 0.35);
  rimLight.position.set(0, 2, -3);
  scene.add(rimLight);
};

/**
 * 根据模型包围盒自动调整相机，保证全身（含头发余量）入画
 */
const frameObject = (object: THREE.Object3D, padding = 1.35) => {
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
  const fittedCenter = box.getCenter(new THREE.Vector3());

  // 头顶留一点余量（长发 / 帽子）
  const height = Math.max(fittedSize.y * 1.06, 0.5);
  const width = Math.max(fittedSize.x, fittedSize.z, 0.3) * 1.08;
  const fov = camera.fov * (Math.PI / 180);
  const aspect = camera.aspect;

  const distForHeight = height / 2 / Math.tan(fov / 2);
  const distForWidth = width / 2 / Math.tan(fov / 2) / aspect;
  const distance = Math.max(distForHeight, distForWidth) * padding;

  // 看向身体中心略偏上（胸口），略俯视
  const lookY = fittedCenter.y * 0.92;
  camera.position.set(0, lookY + height * 0.08, distance);
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
};

const startRenderLoop = () => {
  const render = () => {
    if (!scene || !camera || !renderer || !clock) return;

    const delta = clock.getDelta();
    emit('frame', delta);

    if (controls) controls.update();
    renderer.render(scene, camera);
    animationId = requestAnimationFrame(render);
  };

  render();
};

const updateSize = () => {
  if (!camera || !renderer) return;

  camera.aspect = props.width / props.height;
  camera.updateProjectionMatrix();
  renderer.setSize(props.width, props.height);
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

  if (renderer) {
    renderer.dispose();
    renderer = null;
  }

  scene = null;
  camera = null;
  clock = null;
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

.three-canvas {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
