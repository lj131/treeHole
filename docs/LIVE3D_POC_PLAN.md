# LIVE3D 立体人物 PoC 实施计划

## 目标

最小可行 demo：**单个角色 + 3D 头像 + 基础 lip-sync 语音同步**

## 技术选择（已确认）

- ✅ **Three.js VRM** - 立体 3D 渲染
- ✅ **双模型源支持** - Ready Player Me + VRoid Hub
- ✅ **先 PoC 再全量** - 验证效果后再完整实施

---

## PoC 范围

| 功能 | 包含 | 说明 |
|-----|------|------|
| 3D 模型加载 | ✅ | 支持单个 VRM 文件加载 |
| 模型切换 | ✅ | Ready Player Me ↔ VRoid Hub |
| 语音播放 | ✅ | 使用现有 Web Audio 播放 |
| Lip Sync | ✅ | 基于音量/RMS 的轻量方案 |
| 表情 | ⏸️ | PoC 阶段暂不实现 |
| 多角色 | ⏸️ | 先做单个角色验证 |
| 移动端适配 | ⏸️ | 先桌面端验证 |

---

## PoC 实施步骤

### Step 1: 安装依赖 (5 分钟)
```bash
cd front
npm install three @pixiv/three-vrm @tresjs/core @tresjs/cientos
```

### Step 2: 创建 PoC 页面组件 (30 分钟)
```
front/src/views/PoC3DAvatar.vue  # PoC 测试页面
front/src/components/3d/
  ├── ThreeScene.vue              # Three.js 场景容器
  ├── VRMAvatar.vue               # VRM 角色组件
  └── LipSyncEngine.ts            # 语音同步引擎
```

### Step 3: 实现核心功能 (2-3 小时)

#### 3.1 ThreeScene.vue
- 初始化 Scene、Camera、Renderer
- 添加灯光
- VRM 加载逻辑
- 响应式画布

#### 3.2 VRMAvatar.vue
- 从 GLTF 加载 VRM
- 解析 MorphTarget (viseme)
- 模型切换逻辑

#### 3.3 LipSyncEngine.ts
- AudioContext 频谱分析
- RMS 音量计算
- 映射到 MorphTarget 权重

#### 3.4 PoC3DAvatar.vue
- 两个模型切换按钮
- 测试音频播放
- 调用 LipSync 同步

### Step 4: 测试模型资源 (准备测试数据)

#### 模型 A: Ready Player Me
- 生成链接: https://readyplayer.me/
- 预览模型: `/public/models/rpm_demo.vrm`
- 或使用 CDN: `https://models.readyplayer.me/xxx.vrm`

#### 模型 B: VRoid Hub
- 免费模型示例
- 本地存储: `/public/models/vroid_demo.vrm`

### Step 5: 集成测试 (1 小时)

测试场景：
1. 页面加载 → 模型 A 自动加载
2. 切换模型按钮 → 模型 B 加载
3. 播放测试音频 → 嘴巴同步动
4. 播放停止 → 嘴巴复位

---

## 成功标准

- ✅ 页面加载后 3D 模型正确显示
- ✅ 模型切换流畅（无内存泄漏）
- ✅ 语音播放时嘴唇随音量同步
- ✅ 播放停止后嘴唇复位
- ✅ 无明显性能问题（FPS > 30）

---

## 文件清单

```
front/src/views/PoC3DAvatar.vue          # PoC 测试入口
front/src/components/3d/
  ├── ThreeScene.vue                      # 场景容器
  ├── VRMAvatar.vue                       # VRM 加载组件
  └── LipSyncEngine.ts                    # Lip sync 引擎
front/public/models/
  ├── rpm_demo.vrm                        # Ready Player Me 模型
  └── vroid_demo.vrm                      # VRoid 模型
front/src/router/index.ts                 # 添加 /poc-3d 路由
```

---

## 下一步

1. **创建文件结构** - 开始编写组件
2. **准备测试模型** - 下载或生成 VRM 模型
3. **运行测试** - 验证效果

---

*计划生成时间: 2026-07-18*
*预计完成时间: 2026-07-18（当天验证）*