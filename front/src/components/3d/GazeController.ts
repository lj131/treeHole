/**
 * GazeController — 智能注视系统
 *
 * 模拟真人眼球运动：多种注视模式切换 + 扫视 + 微抖动 + 平滑过渡。
 * 通过操控一个 dummy Object3D 作为 VRM lookAt.target 来实现。
 */
import * as THREE from 'three'
import type { VRM } from '@pixiv/three-vrm'

/** 注视模式 */
export enum GazeMode {
  /** 注视相机（默认），带微小偏移避免"盯穿灵魂" */
  Camera = 'camera',
  /** 自动扫视 —— 随机选点，模拟无意识扫视 */
  Saccade = 'saccade',
  /** 看向输入框方向（打字时） */
  Input = 'input',
  /** 跟随鼠标 */
  Mouse = 'mouse',
}

export class GazeController {
  private vrm: VRM | null = null
  private camera: THREE.Camera | null = null

  /** VRM lookAt 追踪的虚拟目标点 */
  private lookTarget: THREE.Object3D | null = null

  // ── 状态 ──
  private currentMode: GazeMode = GazeMode.Camera
  private modeTimer = 0
  private saccadeHoldTimer = 0
  private saccadeHoldDuration = 1.5
  private peekTimer = 0
  private peekCooldown = 0

  /** 当前注视位置（平滑后） */
  private currentLookPos = new THREE.Vector3(0, 1.4, -2)
  /** 目标注视位置 */
  private targetLookPos = new THREE.Vector3(0, 1.4, -2)

  // ── 微扫视 (micro-saccade) ──
  private microSaccadeTimer = 0
  private microSaccadeInterval = 0.4
  private microSaccadeOffset = new THREE.Vector3()
  private microSaccadeTarget = new THREE.Vector3()

  // ── 生理性微颤 ──
  private tremorPhaseX = Math.random() * Math.PI * 2
  private tremorPhaseY = Math.random() * Math.PI * 2

  // ── 可配置参数 ──
  /** 注视点过渡速度（越大越快） */
  lerpSpeed = 3.5
  /** 微扫视过渡速度 */
  microSaccadeSpeed = 12.0
  /** 扫视间隔范围 (秒) */
  saccadeIntervalMin = 2.0
  saccadeIntervalMax = 5.0
  /** 扫视持续时间范围 (秒) */
  saccadeHoldMin = 0.8
  saccadeHoldMax = 2.5
  /** 扫视锥角 (弧度) */
  saccadeConeAngle = 0.45
  /** 微颤幅度 (世界单位) */
  tremorAmplitude = 0.012
  /** 输入模式注视下移量 (世界单位) */
  inputLookDownOffset = 0.5

  // ── 外部状态输入 ──
  private mouseNormX = 0.5
  private mouseNormY = 0.5
  private hasMouseInput = false
  private inputFocused = false
  private isThinking = false

  // 相机前方基准点缓存
  private cameraForwardBase = new THREE.Vector3()

  /** 初始化：绑定 VRM 和相机 */
  init(vrm: VRM, camera: THREE.Camera): void {
    this.vrm = vrm
    this.camera = camera

    // 创建虚拟注视目标，放在角色面部前方
    this.lookTarget = new THREE.Object3D()
    this.lookTarget.position.copy(this.currentLookPos)

    // 让 VRM lookAt 追踪我们的虚拟目标
    if (vrm.lookAt) {
      vrm.lookAt.target = this.lookTarget
      vrm.lookAt.autoUpdate = true
    }

    // 随机初始化计时器，避免所有角色同步
    this.modeTimer = 1.0 + Math.random() * 2.0
    this.microSaccadeTimer = Math.random() * this.microSaccadeInterval
    this.peekCooldown = 6.0 + Math.random() * 8.0
  }

  /** 更新鼠标位置 (归一化 0-1) */
  updateMousePosition(x: number, y: number): void {
    this.mouseNormX = Math.max(0, Math.min(1, x))
    this.mouseNormY = Math.max(0, Math.min(1, y))
    this.hasMouseInput = true
  }

  /** 清除鼠标输入（鼠标离开角色区域） */
  clearMouseInput(): void {
    this.hasMouseInput = false
  }

  /** 更新输入框状态 */
  updateInputState(focused: boolean, _hasContent: boolean): void {
    this.inputFocused = focused
  }

  /** 设置思考状态 */
  setThinking(thinking: boolean): void {
    this.isThinking = thinking
  }

  /** 设置渲染区域尺寸 */
  setRendererSize(_width: number, _height: number): void {
    // 保留接口，当前不需要
  }

  /** 获取当前注视模式 */
  getCurrentMode(): GazeMode {
    return this.currentMode
  }

  // ─────────────────────────────────────
  // 每帧更新
  // ─────────────────────────────────────
  update(delta: number): void {
    if (!this.vrm?.lookAt || !this.lookTarget || !this.camera) return

    const cappedDelta = Math.min(delta, 0.1) // 防止大帧跳跃

    this.determineMode(cappedDelta)
    this.calculateTargetPosition()
    this.updateMicroSaccade(cappedDelta)
    this.smoothLookPosition(cappedDelta)
    this.applyTremor(cappedDelta)

    // 将最终位置写入 dummy target
    const final = this.currentLookPos.clone().add(this.microSaccadeOffset)
    this.lookTarget.position.copy(final)
  }

  // ─────────────────────────────────────
  // 模式决策
  // ─────────────────────────────────────
  private determineMode(delta: number): void {
    this.modeTimer -= delta
    this.peekCooldown -= delta

    // 优先级: Input > Mouse > (Saccade/Camera 交替)
    if (this.inputFocused) {
      this.transitionTo(GazeMode.Input)
      return
    }

    if (this.hasMouseInput) {
      this.transitionTo(GazeMode.Mouse)
      return
    }

    // 无交互时：Camera 和 Saccade 交替
    if (this.currentMode === GazeMode.Saccade) {
      this.saccadeHoldTimer -= delta
      if (this.saccadeHoldTimer <= 0) {
        this.transitionTo(GazeMode.Camera)
        this.modeTimer = this.saccadeIntervalMin + Math.random() * (this.saccadeIntervalMax - this.saccadeIntervalMin)
      }
      return
    }

    // Camera 模式：计时到了且有冷却 → 扫视或偷看
    if (this.modeTimer <= 0 && this.currentMode === GazeMode.Camera) {
      // 偶尔"偷看"用户：快速看向相机再移开
      if (this.peekCooldown <= 0) {
        this.triggerPeek()
        return
      }

      // 正常扫视
      this.transitionTo(GazeMode.Saccade)
      this.saccadeHoldTimer = this.saccadeHoldMin + Math.random() * (this.saccadeHoldMax - this.saccadeHoldMin)
    }
  }

  private transitionTo(mode: GazeMode): void {
    if (this.currentMode === mode) return
    this.currentMode = mode
  }

  /** "偷看"用户：快速看向相机方向 */
  private triggerPeek(): void {
    // 暂存一个很短的 saccade 到相机位置
    this.transitionTo(GazeMode.Camera)
    this.lerpSpeed = 6.0 // 快速移回
    this.peekCooldown = 6.0 + Math.random() * 10.0
    this.modeTimer = 0.4 + Math.random() * 0.3 // 停留 0.4-0.7s

    // 停留后恢复正常速度
    setTimeout(() => {
      this.lerpSpeed = 3.5
      this.modeTimer = this.saccadeIntervalMin + Math.random() * (this.saccadeIntervalMax - this.saccadeIntervalMin)
    }, 500)
  }

  // ─────────────────────────────────────
  // 目标位置计算
  // ─────────────────────────────────────
  private calculateTargetPosition(): void {
    if (!this.camera) return

    const camPos = this.camera.position
    const camDir = new THREE.Vector3()
    this.camera.getWorldDirection(camDir)

    // 相机前方 1.5m 作为基准面
    this.cameraForwardBase.copy(camPos).addScaledVector(camDir, 1.5)

    switch (this.currentMode) {
      case GazeMode.Camera:
        this.calcCameraTarget()
        break
      case GazeMode.Saccade:
        this.calcSaccadeTarget()
        break
      case GazeMode.Input:
        this.calcInputTarget()
        break
      case GazeMode.Mouse:
        this.calcMouseTarget(camPos, camDir)
        break
    }
  }

  /** Camera 模式：注视相机上方（模拟看脸），加微小随机偏移 */
  private calcCameraTarget(): void {
    const base = this.cameraForwardBase.clone()
    // 微微偏上，模拟看眼睛而非看镜头
    base.y += 0.08
    // 微小偏移避免完美静止
    base.x += Math.sin(this.modeTimer * 0.7) * 0.03
    base.y += Math.cos(this.modeTimer * 0.5) * 0.02
    this.targetLookPos.copy(base)
  }

  /** Saccade 模式：在锥形视野范围内随机选点 */
  private calcSaccadeTarget(): void {
    // 每次进入扫视模式时计算新的随机目标
    if (this.saccadeHoldTimer > this.saccadeHoldMax - 0.05) {
      return // 刚切换，保持现状让过渡自然
    }

    const base = this.cameraForwardBase.clone()
    const angle = this.saccadeConeAngle * (0.3 + Math.random() * 0.7)
    const azimuth = Math.random() * Math.PI * 2

    // 在相机前方锥形区域内随机偏移
    const right = new THREE.Vector3()
    const up = new THREE.Vector3()
    if (this.camera) {
      const camDir = new THREE.Vector3()
      this.camera.getWorldDirection(camDir)
      right.crossVectors(camDir, new THREE.Vector3(0, 1, 0)).normalize()
      up.crossVectors(right, camDir).normalize()
    }

    const offset = new THREE.Vector3()
    offset.addScaledVector(right, Math.cos(azimuth) * angle)
    offset.addScaledVector(up, Math.sin(azimuth) * angle)

    this.targetLookPos.copy(base).add(offset)
  }

  /** Input 模式：视线向下偏移 */
  private calcInputTarget(): void {
    const base = this.cameraForwardBase.clone()
    base.y -= this.inputLookDownOffset
    // 轻微左右偏移增加自然感
    base.x += Math.sin(this.modeTimer * 1.2) * 0.04
    this.targetLookPos.copy(base)
  }

  /** Mouse 模式：鼠标位置映射到视野偏移 */
  private calcMouseTarget(camPos: THREE.Vector3, camDir: THREE.Vector3): void {
    // 将归一化鼠标位置 (0-1) 映射到视野偏移 (-1 ~ 1)
    const offsetX = (this.mouseNormX - 0.5) * 0.5
    const offsetY = (this.mouseNormY - 0.5) * 0.35

    const right = new THREE.Vector3()
    const up = new THREE.Vector3()
    right.crossVectors(camDir, new THREE.Vector3(0, 1, 0)).normalize()
    up.crossVectors(right, camDir).normalize()

    const base = this.cameraForwardBase.clone()
    base.addScaledVector(right, offsetX)
    base.addScaledVector(up, offsetY)
    this.targetLookPos.copy(base)
  }

  // ─────────────────────────────────────
  // 微扫视（micro-saccade）
  // ─────────────────────────────────────
  private updateMicroSaccade(delta: number): void {
    this.microSaccadeTimer -= delta
    if (this.microSaccadeTimer <= 0) {
      // 触发微扫视：随机小偏移
      this.microSaccadeTarget.set(
        (Math.random() - 0.5) * 0.04,
        (Math.random() - 0.5) * 0.03,
        (Math.random() - 0.5) * 0.02,
      )
      this.microSaccadeTimer = 0.3 + Math.random() * 0.8
    }

    // 快速 lerp 到微扫视目标
    const factor = 1 - Math.exp(-this.microSaccadeSpeed * delta)
    this.microSaccadeOffset.lerp(this.microSaccadeTarget, factor)
  }

  // ─────────────────────────────────────
  // 平滑注视位置
  // ─────────────────────────────────────
  private smoothLookPosition(delta: number): void {
    const factor = 1 - Math.exp(-this.lerpSpeed * delta)
    this.currentLookPos.lerp(this.targetLookPos, factor)
  }

  // ─────────────────────────────────────
  // 生理性微颤
  // ─────────────────────────────────────
  private applyTremor(delta: number): void {
    // 高频复合正弦波模拟眼球微颤
    this.tremorPhaseX += delta * 35.0
    this.tremorPhaseY += delta * 42.0

    const tx = Math.sin(this.tremorPhaseX) * this.tremorAmplitude
      + Math.sin(this.tremorPhaseX * 1.7 + 1.2) * this.tremorAmplitude * 0.6
    const ty = Math.sin(this.tremorPhaseY) * this.tremorAmplitude
      + Math.sin(this.tremorPhaseY * 1.3 + 0.8) * this.tremorAmplitude * 0.5

    this.currentLookPos.x += tx
    this.currentLookPos.y += ty
  }

  // ─────────────────────────────────────
  // 清理
  // ─────────────────────────────────────
  dispose(): void {
    if (this.vrm?.lookAt && this.lookTarget) {
      this.vrm.lookAt.target = undefined as unknown as THREE.Object3D
    }
    this.vrm = null
    this.camera = null
    this.lookTarget = null
  }
}

/** 全局单例，匹配 LipSyncEngine 模式 */
export const gazeController = new GazeController()
