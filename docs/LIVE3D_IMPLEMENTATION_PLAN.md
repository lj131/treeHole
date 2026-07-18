# LIVE3D 虚拟人物实施计划

## 概述

将当前静态头像升级为 LIVE3D 立体人物，支持实时语音同步（lip-sync）和微表情交互。

## 技术选型

### 核心技术栈

| 技术 | 版本 | 用途 | 说明 |
|-----|------|-----|------|
| **Three.js** | latest | 3D 渲染引擎 | 业内最成熟的 Web 3D 库 |
| **Vue3-Three** | ^1.2.0 | Vue3 + Three.js 集成 | [vue-three-bridge](https://github.com/tresjs/tres) 或 [vue3-three](https://github.com/YiguiDing/vue3-live2d) |
| **LipSync-JS** | latest | 音频到嘴型转换 | 基于 RMS/频谱分析的轻量方案，或使用 [Rhubarb Lip Sync](https://github.com/DanielSWolf/rhubarb-lip-sync) |
| **Live2D Cubism** | 4.0+ | 2D 立体人物渲染 | 备选方案：更动漫风格、性能更好 |

### 两种方案对比

| 维度 | Three.js VRM 方案 | Live2D 方案 |
|-----|------------------|-------------|
| **风格** | 3D 写实/卡通 | 2D 动漫（看板娘） |
| **性能** | GPU 负载高 | CPU 友好 |
| **模型来源** | Ready Player Me / VRoid Hub | Live2D Cubism Editor 制作 |
| **Lip Sync** | MorphTargets (Viseme) | Live2D 自带 lip-sync 模块 |
| **复杂度** | 高 | 中 |
| **适用场景** | 写实虚拟助手 | 可爱看板娘风格 |

**推荐方案**: 首选 **Three.js VRM**（更符合"立体人物"描述），备选 **Live2D**（如用户偏好动漫风格）。

---

## 实施阶段

### Phase 1: 基础架构搭建 (1-2 天)

#### 1.1 安装依赖
```bash
cd front
npm install three @types/three vue3-three
# 或者使用 TresJS
npm install @tresjs/core @tresjs/cientos
```

#### 1.2 创建 3D 头像组件
```
front/src/components/3d/
  ├── Avatar3D.vue          # 主组件
  ├── ThreeScene.vue        # Three.js 场景容器
  ├── VRMLoader.vue         # VRM 模型加载器
  └── LipSyncEngine.ts      # 语音同步引擎
```

#### 1.3 数据结构扩展
在角色数据中添加 3D 模型字段：
```typescript
// Character 接口扩展
interface Character {
  // ... 现有字段
  vrmModelUrl?: string;        // VRM 模型文件路径
  live2DModelUrl?: string;     // Live2D 模型文件路径（备选）
  expressionPreset?: {         // 表情预设
    neutral: string;
    happy: string;
    angry: string;
    sad: string;
  };
}
```

---

### Phase 2: 3D 模型集成 (2-3 天)

#### 2.1 VRM 模型加载器
使用 `@pixiv/three-vrm` 或 `@three-vrm/vrm` 加载 VRM 模型：
```typescript
// VRMLoader.vue 核心逻辑
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

const loader = new GLTFLoader();
loader.register((parser) => new VRMLoaderPlugin(parser));

const gltf = await loader.loadAsync(modelUrl);
const vrm = gltf.userData.vrm;
VRMUtils.deepRemoveVertexColors(vrm.scene);
VRMUtils.removeUnnecessaryVertices(vrm.scene);
```

#### 2.2 模型资源管理
- 本地模型存储: `front/public/models/vrm/{characterId}.vrm`
- CDN 备选: 从 Ready Player Me API 或 VRoid Hub 动态加载
- 模型缓存: IndexedDB 缓存已加载模型

#### 2.3 场景初始化
```typescript
// ThreeScene.vue 核心逻辑
- 场景 Scene + 相机 Camera + 渲染器 WebGLRenderer
- 灯光 AmbientLight + DirectionalLight
- OrbitControls (可选：允许用户旋转查看)
- 自适应窗口大小
```

---

### Phase 3: Lip Sync 语音同步 (3-4 天)

#### 3.1 音频分析引擎
两种技术路径：

**路径 A: 基于频谱的轻量方案**（推荐）
```typescript
// LipSyncEngine.ts - 实时分析 Web Audio
class LipSyncEngine {
  private audioContext: AudioContext;
  private analyser: AnalyserNode;

  constructor(audioStream: MediaStream) {
    this.audioContext = new AudioContext();
    this.analyser = this.audioContext.createAnalyser();
    this.analyser.fftSize = 512;
    const source = this.audioContext.createMediaStreamSource(audioStream);
    source.connect(this.analyser);
  }

  getVolume(): number {
    const dataArray = new Uint8Array(this.analyser.frequencyBinCount);
    this.analyser.getByteFrequencyData(dataArray);
    return this.calculateRMS(dataArray);
  }
}
```

**路径 B: Rhubarb Lip Sync**（精确但需额外编译）
- 预处理音频 → 生成 viseme 时间轴
- 运行时播放时查找对应嘴型
- 需要 WASM 版本的 Rhubarb

#### 3.2 Viseme 到 MorphTarget 映射
```typescript
// 常见 viseme 集
const VISEME_TO_MORPH: Record<string, string[]> = {
  'ah': ['aa', 'A'],       // 嘴张大开
  'ee': ['ih', 'E'],       // 嘴向两侧拉
  'oh': ['oh', 'O'],       // 嘴呈圆形
  'rest': ['neutral'],     // 闭合状态
};

// 更新 MorphTarget 权重
function updateMorphTargets(vrm: VRM, viseme: string, intensity: number) {
  const mesh = vrm.scene.getObjectByName('Head');
  if (!mesh) return;

  const targets = VISEME_TO_MORPH[viseme] || ['neutral'];
  targets.forEach(name => {
    const index = mesh.morphTargetDictionary[name];
    if (index !== undefined) {
      mesh.morphTargetInfluences[index] = intensity;
    }
  });
}
```

#### 3.3 与现有语音播放整合
在 `Chat.vue` 中:
```vue
<template>
  <Avatar3D :model="currentCharacter.vrmModelUrl" ref="avatar3D" />
  <audio ref="audioPlayer" @timeupdate="onAudioProgress" />
</template>

<script setup>
const avatar3D = ref<Avatar3DInstance>();

function playAudio(audioUrl: string) {
  audioPlayer.src = audioUrl;
  audioPlayer.play();
  // 启动 lip-sync
  avatar3D.value?.startLipSync(audioPlayer);
}
</script>
```

---

### Phase 4: 表情系统 (2-3 天)

#### 4.1 表情切换
基于好感度和对话内容触发表情：
```typescript
// 基于好感度映射
const EXPRESSION_BY_FAVORABILITY = {
  high: ['happy', 'blink'],      // 亲密
  medium: ['neutral', 'blink'],  // 普通
  low: ['sad', 'angry'],         // 冷淡
};

// 基于文本分析（可选）
function detectExpression(text: string): string {
  if (/[😊😄😃]/.test(text)) return 'happy';
  if (/[😢😭]/.test(text)) return 'sad';
  // 更多规则...
}
```

#### 4.2 混合表情
允许表情叠加（如 happy + blink）：
```typescript
function blendExpressions(base: string, overlay: string, weight: number) {
  // 平滑过渡表情权重
}
```

---

### Phase 5: 优化与移动端适配 (2-3 天)

#### 5.1 性能优化
| 优化项 | 实现 |
|-------|------|
| 模型精简 | `VRMUtils.removeUnnecessaryVertices()` |
| LOD 切换 | 远距离降低面数 |
| 离屏渲染 | 多个角色共享渲染器（仅 Electron 需要） |
| 惰性加载 | 非可见角色不加载 3D 模型 |

#### 5.2 移动端适配
```css
/* 响应式画布 */
.canvas-container {
  width: 100%;
  height: auto;
  max-height: 50vh;  /* 移动端高度限制 */
}

@media (max-width: 900px) {
  .canvas-container {
    /* 使用轻量级渲染设置 */
  }
}
```

#### 5.3 降级策略
```typescript
// 检测 WebGL 支持
if (!isWebGLAvailable()) {
  return <StaticAvatar />;  // 回退到静态头像
}

// 检测性能，低端设备用 Live2D
if (isLowEndDevice()) {
  return <Live2DAvatar />;
}
```

---

### Phase 6: 后端支持 (1-2 天)

#### 6.1 模型上传 API
```python
# backend/api/character.py
@router.post("/character/{id}/model")
async def upload_3d_model(
    id: str,
    file: UploadFile,
    current_user: User = Depends(get_current_user),
):
    # 验证 VRM/Live2D 文件格式
    # 保存到 public/models/
    # 更新 character 元数据
```

#### 6.2 模型 CDN 配置
- 使用阿里云 OSS / 腾讯云 COS 存储大型模型文件
- 配置 CDN 加速

---

### Phase 7: 测试与文档 (1-2 天)

#### 7.1 测试清单
- [ ] 模型加载成功（不同角色）
- [ ] Lip Sync 与语音同步准确
- [ ] 表情切换平滑
- [ ] 移动端流畅运行
- [ ] 降级策略正常触发
- [ ] 多角色切换无内存泄漏

#### 7.2 文档更新
- 更新 `front/CLAUDE.md`: 添加 3D 头像架构说明
- 更新 `CLAUDE.md`: 添加新依赖和技术选型
- 编写用户手册：如何上传自定义模型

---

## 预估工作量

| 阶段 | 工作量 | 备注 |
|-----|--------|------|
| Phase 1 | 1-2 天 | 基础架构 |
| Phase 2 | 2-3 天 | 模型集成 |
| Phase 3 | 3-4 天 | Lip Sync（核心难点） |
| Phase 4 | 2-3 天 | 表情系统 |
| Phase 5 | 2-3 天 | 优化与适配 |
| Phase 6 | 1-2 天 | 后端支持 |
| Phase 7 | 1-2 天 | 测试与文档 |
| **总计** | **12-19 天** | 约 2-3 周 |

---

## 关键技术难点与解决方案

| 难点 | 解决方案 |
|-----|---------|
| **中文语音的 viseme 映射** | 使用基于 RMS 的轻量方案（不依赖精确的音素识别）；或使用中文语音识别 + 注音映射 |
| **多角色同时渲染性能** | 单场景多模型共享渲染器；非可见角色惰性加载 |
| **模型文件体积大** | CDN 加速；IndexedDB 缓存；压缩 VRM 文件 |
| **跨浏览器兼容性** | 使用 [WebGL Detector](https://github.com/mrdoob/three.js/blob/master/examples/jsm/WebGL.js) 检测；提供降级方案 |
| **Electron 桌面挂件集成** | 使用 `BrowserWindow` 的 `webPreferences.webGL` 配置；可能需要透明背景支持 |

---

## 资源参考

- [Ready Player Me Avatar Generator](https://readyplayer.me/)
- [VRoid Hub](https://hub.vroid.com/) - 免费动漫风格 3D 模型
- [Three.js VRM Examples](https://github.com/pixiv/three-vrm/tree/dev/examples)
- [Lip Sync with MorphTargets](https://stackoverflow.com/questions/71951363/smooth-and-efficient-lipsync-with-morph-targets-in-three-js)
- [Live2D Vue3 Integration](https://github.com/YiguiDing/vue3-live2d)
- [LIVE3D VTuber Maker](https://live3d.io/tutorial/vtuber-maker-audio-based-lipsync)

---

## 风险评估

| 风险 | 影响 | 缓解措施 |
|-----|------|---------|
| Lip Sync 精度不够 | 中 | 提供表情调整 UI，允许用户微调 |
| 性能问题（移动端） | 高 | 提供 Live2D 降级选项；自适应 LOD |
| 模型来源限制 | 低 | 集成 Ready Player Me API，允许用户生成自定义模型 |
| 中文语音识别准确率 | 中 | 使用基于音量的方案，不依赖识别 |

---

## 下一步行动

1. **确认技术选型**: Three.js VRM 还是 Live2D？
2. **准备模型资源**: 选取或生成测试用的 VRM/Live2D 模型
3. **搭建 PoC**: 实现最小可用 demo（单个角色 + 简单的 lip-sync）
4. **评审 PoC**: 确认效果和性能后继续完整实施

---

*计划生成时间: 2026-07-18*
*预计完成时间: 2026-08-08*