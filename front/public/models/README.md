# LIVE3D PoC 模型目录

此目录用于存放 VRM 3D 模型文件。

## 模型格式

- **VRM (Virtual Reality Model)**: 基于 glTF 2.0 的开放格式，专为虚拟角色设计
- 推荐分辨率: 模型面数 < 50k（保证性能）
- 必须包含: Head 骨骼 + Mouth MorphTargets / Expression（用于 lip-sync）

## 测试模型

### Ready Player Me Demo
- 文件: `rpm_demo.vrm`
- 来源: https://readyplayer.me/
- 特点: 写实风格，支持表情

### VRoid Hub Demo
- 文件: `vroid_demo.vrm`（可选）
- 来源: https://hub.vroid.com/
- 特点: 动漫风格，表情丰富

## 如何获取测试模型

### 方法 1: Ready Player Me
1. 访问 https://readyplayer.me/
2. 自定义头像 → Download → 选择 `.vrm`
3. 重命名为 `rpm_demo.vrm` 并放置于此目录

### 方法 2: VRoid Hub
1. 访问 https://hub.vroid.com/ → 搜索 free → 下载 `.vrm`
2. 重命名为 `vroid_demo.vrm`

### 方法 3: 在线 URL
在 PoC 页面「自定义模型 URL」粘贴公开 VRM 链接即可。

## 测试音频

### 文件: `test-audio.wav`
- 用途: 真实 Web Audio 频谱 Lip Sync
- 格式: WAV PCM 16-bit mono 44.1kHz
- 时长: ~6 秒（合成语音包络）
- 可用 TTS 人声替换以获得更自然的嘴型

## 注意事项

- 模型文件建议 < 50MB
- Lip Sync 依赖 Mouth Expression / MorphTargets
- 表情切换依赖模型是否含 happy/sad 等 VRM Expression
