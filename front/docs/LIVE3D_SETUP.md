# LIVE3D PoC 安装与测试指南

## 1. 安装依赖

在 `front/` 目录下运行：

```bash
npm install three @pixiv/three-vrm
```

### 依赖说明

| 包 | 版本 | 用途 |
|---|------|-----|
| `three` | latest | 3D 渲染核心库 |
| `@pixiv/three-vrm` | latest | VRM 模型加载与渲染 |

---

## 2. 准备测试资源

### 2.1 获取测试模型

#### 选项 A: Ready Player Me（推荐，快速）
1. 访问 https://readyplayer.me/
2. 选择性别和风格 → 点击 "Next"
3. 完成头像定制 → 点击右上角 "Download"
4. 选择 ".vrm" 格式 → 下载文件
5. 将文件重命名为 `rpm_demo.vrm`
6. 放置到 `front/public/models/` 目录

#### 选项 B: VRoid Hub（免费动漫风格）
1. 访问 https://hub.vroid.com/
2. 搜索 "free" 或 "free to use"
3. 选择喜欢的模型 → 下载 VRM 文件
4. 将文件重命名为 `vroid_demo.vrm`
5. 放置到 `front/public/models/` 目录

#### 选项 C: 使用在线 URL（无需下载）
- 打开 PoC 页面 → 在"自定义模型 URL"输入框中粘贴 VRM 公开链接
- 示例: `https://models.readyplayer.me/64f0e2a3b6c8d12f1a3b45c6.vrm`

### 2.2 生成测试音频

#### 方法 1: 使用在线 TTS（推荐）
1. 访问 https://ttsmaker.com/zh-CN
2. 输入测试文本（中文或英文）
3. 选择语音 → 点击"转换为语音"
4. 下载生成的 MP3/WAV 文件
5. 转换为 WAV 格式（如需要）：使用在线转换工具如 https://convertio.co/zh/
6. 将文件重命名为 `test-audio.wav`
7. 放置到 `front/public/models/` 目录

#### 方法 2: 使用生成脚本
1. 打开 `front/scripts/generate-test-audio.html`（浏览器打开即可）
2. 输入测试文本
3. 点击"合成并播放"预览
4. 使用系统录音工具或在线 TTS 生成最终音频

#### 测试文本建议
```
中文：
你好！这是一个测试语音，用于验证唇形同步功能。
嘴巴张开的时候，应该能看到角色的嘴唇同步动作。

English：
Hello! This is a test audio for lip sync verification.
Watch the mouth movement sync with the audio.
```

---

## 3. 启动开发服务器

```bash
cd front
npm run dev
```

服务器将在 `http://127.0.0.1:5173` 启动。

---

## 4. 访问 PoC 页面

### 方式 1: 首页入口
1. 打开 http://127.0.0.1:5173
2. 点击首页的 **"🎭 LIVE3D 测试"** 按钮

### 方式 2: 直接访问
1. 打开 http://127.0.0.1:5173/#/poc-3d

---

## 5. 测试流程

### 5.1 验证模型加载
1. 页面加载后，点击 "Ready Player Me" 或 "VRoid Hub" 按钮
2. 观察加载动画 → 3D 模型出现
3. 检查状态面板是否显示"加载成功"

### 5.2 验证 Lip Sync
1. 确保 `test-audio.wav` 文件存在于 `front/public/models/` 目录
2. 点击 "▶ 播放测试音频" 按钮
3. 观察角色嘴唇是否随音频播放同步运动
4. 音频播放完成后，嘴唇应自动复位

### 5.3 自定义模型测试
1. 在"自定义模型 URL"输入框中粘贴 VRM 文件链接
2. 点击"加载"按钮
3. 验证模型显示是否正常

---

## 6. 故障排查

| 问题 | 可能原因 | 解决方案 |
|-----|---------|---------|
| 模型加载失败 | VRM 文件格式错误 | 使用 VRM Viewer 验证模型 |
| 模型加载慢 | 文件过大 (>50MB) | 压缩模型或使用精简版 |
| Lip Sync 不工作 | 模型缺少 Mouth MorphTarget | 确保模型包含嘴形变形目标 |
| 控制台报错 | Three.js 版本冲突 | 删除 `node_modules` 重新安装 |
| 音频不播放 | 浏览器阻止自动播放 | 检查浏览器媒体设置 |

---

## 7. 性能优化建议

### 模型精简
- 使用 VRM Studio 或 Blender 优化模型
- 目标面数: < 50k
- 纹理大小: 1024x1024 或更低

### 浏览器设置
- 启用硬件加速（默认开启）
- 使用 Chrome/Edge（最佳 WebGL 支持）
- 关闭不必要的浏览器扩展

---

## 8. 下一步

PoC 验证通过后，可继续推进：

1. **集成到 Chat.vue** - 将 3D 头像替换当前静态头像
2. **表情系统** - 根据好感度/对话内容切换表情
3. **移动端适配** - 优化低性能设备的渲染质量
4. **多角色支持** - 支持同时渲染多个角色

详见完整计划: `docs/LIVE3D_IMPLEMENTATION_PLAN.md`

---

## 技术支持

- Three.js 文档: https://threejs.org/docs/
- @pixiv/three-vrm: https://github.com/pixiv/three-vrm
- VRM 规范: https://vrm.dev/en/

*更新时间: 2026-07-18*