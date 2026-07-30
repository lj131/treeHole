/**
 * ParticleField — 漂浮微光粒子系统
 *
 * 在角色周围生成缓慢漂浮的微光粒子，营造温暖的魔法氛围。
 * 使用 THREE.Points + 自定义圆形精灵贴图 + 叠加混合。
 */
import * as THREE from 'three';

/** 粒子配置 */
export interface ParticleFieldConfig {
  /** 粒子数量 */
  count?: number;
  /** 分布半径 */
  radius?: number;
  /** 分布高度 */
  height?: number;
  /** 粒子颜色 */
  color?: number;
  /** 粒子最大尺寸 */
  maxSize?: number;
  /** 上升速度 (单位/秒) */
  riseSpeed?: number;
  /** 粒子透明度范围 */
  opacity?: [number, number];
}

const DEFAULT_CONFIG: Required<ParticleFieldConfig> = {
  count: 80,
  radius: 2.5,
  height: 3.5,
  color: 0xd4bfff,
  maxSize: 0.018,
  riseSpeed: 0.08,
  opacity: [0.08, 0.35],
};

export class ParticleField {
  private points: THREE.Points;
  private positions: Float32Array;
  private velocities: Float32Array;
  private phases: Float32Array;
  private config: Required<ParticleFieldConfig>;

  constructor(config?: ParticleFieldConfig) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    const { count, radius, height, maxSize, color } = this.config;

    // 创建圆形精灵贴图
    const spriteSize = 64;
    const canvas = document.createElement('canvas');
    canvas.width = spriteSize;
    canvas.height = spriteSize;
    const ctx = canvas.getContext('2d')!;
    const gradient = ctx.createRadialGradient(
      spriteSize / 2, spriteSize / 2, 0,
      spriteSize / 2, spriteSize / 2, spriteSize / 2
    );
    gradient.addColorStop(0, 'rgba(255, 255, 255, 1)');
    gradient.addColorStop(0.15, 'rgba(255, 255, 255, 0.85)');
    gradient.addColorStop(0.4, 'rgba(255, 255, 255, 0.3)');
    gradient.addColorStop(0.7, 'rgba(255, 255, 255, 0.05)');
    gradient.addColorStop(1, 'rgba(255, 255, 255, 0)');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, spriteSize, spriteSize);

    const spriteTexture = new THREE.CanvasTexture(canvas);
    spriteTexture.needsUpdate = true;

    // 初始化位置和速度数组
    this.positions = new Float32Array(count * 3);
    this.velocities = new Float32Array(count * 3); // x,y,z 漂移速度
    this.phases = new Float32Array(count); // 透明度/尺寸 相位

    for (let i = 0; i < count; i++) {
      this.resetParticle(i, radius, height, true);
    }

    // 几何体
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(this.positions, 3));
    geometry.setAttribute('size', new THREE.BufferAttribute(new Float32Array(count), 1));

    // 材质 — 叠加混合 + 半透明
    const material = new THREE.PointsMaterial({
      map: spriteTexture,
      color,
      size: maxSize,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      depthTest: true,
      opacity: 0.7,
    });

    this.points = new THREE.Points(geometry, material);
    this.points.frustumCulled = false;
    this.points.renderOrder = 999; // 最后渲染，确保在角色之上
  }

  /** 将粒子 i 重置到随机位置 */
  private resetParticle(i: number, radius: number, height: number, initial: boolean): void {
    const angle = Math.random() * Math.PI * 2;
    const dist = Math.sqrt(Math.random()) * radius; // sqrt 分布，中心更多
    const x = Math.cos(angle) * dist;
    const z = Math.sin(angle) * dist;
    const y = initial
      ? Math.random() * height - height * 0.3
      : -height * 0.4; // 从底部重新开始

    this.positions[i * 3] = x;
    this.positions[i * 3 + 1] = y;
    this.positions[i * 3 + 2] = z;

    // 随机漂移速度（水平面）
    this.velocities[i * 3] = (Math.random() - 0.5) * 0.04;
    this.velocities[i * 3 + 1] = this.config.riseSpeed * (0.5 + Math.random() * 0.5);
    this.velocities[i * 3 + 2] = (Math.random() - 0.5) * 0.04;

    this.phases[i] = Math.random() * Math.PI * 2;
  }

  /** 每帧更新，由外部调用 */
  update(delta: number): void {
    const { count, radius, height } = this.config;
    const cappedDelta = Math.min(delta, 0.1);
    const posArr = this.points.geometry.attributes.position.array as Float32Array;
    const sizeArr = this.points.geometry.attributes.size?.array as Float32Array | undefined;

    for (let i = 0; i < count; i++) {
      const i3 = i * 3;

      // 更新位置
      posArr[i3] += this.velocities[i3] * cappedDelta;
      posArr[i3 + 1] += this.velocities[i3 + 1] * cappedDelta;
      posArr[i3 + 2] += this.velocities[i3 + 2] * cappedDelta;

      // 水平布朗运动微调
      posArr[i3] += Math.sin(this.phases[i] + posArr[i3 + 1] * 3) * 0.001;
      posArr[i3 + 2] += Math.cos(this.phases[i] + posArr[i3 + 1] * 2.5) * 0.001;

      // 重置到顶部/底部的粒子
      if (posArr[i3 + 1] > height * 0.55) {
        this.resetParticle(i, radius, height, false);
      }

      // 可选：更新尺寸（模拟闪烁）
      if (sizeArr) {
        const flicker = 0.7 + 0.3 * Math.sin(this.phases[i] + performance.now() * 0.002);
        sizeArr[i] = this.config.maxSize * flicker;
      }

      this.phases[i] += cappedDelta * 0.5;
    }

    this.points.geometry.attributes.position.needsUpdate = true;
    if (sizeArr) {
      this.points.geometry.attributes.size!.needsUpdate = true;
    }
  }

  /** 将粒子系统添加到场景 */
  addToScene(scene: THREE.Scene): void {
    scene.add(this.points);
  }

  /** 从场景移除 */
  removeFromScene(scene: THREE.Scene): void {
    scene.remove(this.points);
  }

  /** 清理资源 */
  dispose(): void {
    this.points.geometry.dispose();
    if (Array.isArray(this.points.material)) {
      for (const m of this.points.material) m.dispose();
    } else {
      (this.points.material as THREE.Material).dispose();
    }
  }
}
