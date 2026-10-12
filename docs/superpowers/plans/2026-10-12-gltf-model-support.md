# 3D 收尾：纯 glTF 模型加载与骨骼动画播放 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让**非 VRM 的 glTF/glb 模型**能被加载并播放骨骼动画，而不是直接报错。

**Architecture:** 实测发现的问题比方案里写的更严重 —— 后端 `model3d.EXTENSION_FORMAT_MAP`
**允许上传 `.glb` / `.gltf`**，但前端 `VRMAvatar.vue` 只有 VRM 一条路径：

```ts
const loadedVrm = gltf.userData.vrm as VRM | undefined;
if (!loadedVrm) {
  throw new Error('VRM 数据未找到，可能不是有效的 VRM 文件');   // ← 上传 glb 就走到这
}
```

也就是说**后端接受的文件类型，前端会让角色直接坏掉**。而且全项目**没有任何**
`AnimationMixer` / `AnimationClip` 用法，glTF 的骨骼动画从来没被播放过。

**做法**：把加载流程分成「VRM」和「纯 glTF」两条分支，共用"取景 / 阴影 / 自转 / 帧循环"这些
与模型类型无关的部分。

```
loadModel(url)
  ├─ VRM        → vrm = gltf.userData.vrm
  │               → 表情 / SpringBone / 注视 / 程序化 idle 动画（现状）
  └─ 纯 glTF    → currentRoot = gltf.scene，vrm = null
                  → gltf.animations 有内容就建 AnimationMixer 播放第一个 clip（循环）
                  → VRM 专属特性全部跳过（它们本身都 guard 了 vrm）
```

**关键约束**：VRM 路径**不许有任何行为变化**（现在每天在用，改了要出人命）。
所有改动都走"新增分支 + 把 `vrm.scene` 换成 `currentRoot`"的方式。

**Tech Stack:** Vue 3 / three.js（`AnimationMixer` 在核心包里）/ vitest / Playwright。

---

## 前置基线

```bash
cd front && npm run lint:ci && npm run type-check && npx vitest run   # 全绿（138）
```

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `front/src/components/3d/VRMAvatar.vue` | 修改 | 纯 glTF 分支 + AnimationMixer + `currentRoot` |
| `front/src/utils/__tests__/avatar3d.spec.ts` 或新建 | 修改/新增 | 取景/旋转等纯函数回归 |

> 说明：`VRMAvatar.vue` 是 1263 行的大型组件，**核心逻辑（取景、帧循环）不便单测**。
> 可测的纯函数尽量下沉到 `utils/avatar3d.ts`；WebGL 相关的验收用 Playwright + 截图。

---

## Task 1: 加载分支

- [x] **Step 1: 加模块状态**

```ts
/**
 * 纯 glTF/glb 模型的播放状态。
 * VRM 走 `vrm` 那一套；非 VRM 时 `vrm === null`，由这里驱动动画。
 */
let currentRoot: THREE.Object3D | null = null;   // 模型根节点（VRM 或 glTF 通用）
let gltfMixer: THREE.AnimationMixer | null = null;
let gltfClips: THREE.AnimationClip[] = [];
```

- [x] **Step 2: `loadModel` 拆成两条分支**

保留 VRM 分支原样；`if (!loadedVrm)` 从 throw 改为走新分支：

```ts
if (loadedVrm) {
  // ── VRM：原逻辑一字不改 ──
  VRMUtils.removeUnnecessaryVertices(gltf.scene);
  VRMUtils.combineSkeletons(gltf.scene);
  ...遍历开阴影 / rotateVRM0 / baseSceneRotationY / vrm = loadedVrm / tuneSpringBones / gaze...
} else {
  // ── 纯 glTF/glb：后端允许上传，前端此前直接报错 ──
  vrm = null;
  currentRoot = gltf.scene;
  gltfClips = Array.isArray(gltf.animations) ? gltf.animations : [];
  gltfMixer?.stopAllAction();
  gltfMixer = gltfClips.length ? new THREE.AnimationMixer(gltf.scene) : null;

  gltf.scene.traverse((obj) => {
    obj.frustumCulled = false;
    if (obj instanceof THREE.Mesh) { obj.castShadow = true; obj.receiveShadow = true; }
  });

  baseSceneRotationY = 0;
  spinAngle = 0;
  applySceneRotation();
  scene.add(gltf.scene);
}
```

- [x] **Step 3: 清理旧状态**

`loadModel` 开头（现在只在 `if (vrm)` 里清理）要把 glTF 的也清掉：

```ts
if (vrm) { scene.remove(vrm.scene); VRMUtils.deepDispose(vrm.scene); vrm = null; }
if (currentRoot && currentRoot !== vrm?.scene) { scene.remove(currentRoot); }
gltfMixer?.stopAllAction(); gltfMixer = null;
disposeGltfScene(currentRoot);      // 见 Step 5
currentRoot = null;
```

- [x] **Step 4: 播放 clip**

有动画就播**第一个**并循环；没有就只显示静态模型（比报错好）。

```ts
if (gltfMixer && gltfClips.length > 0) {
  const action = gltfMixer.clipAction(gltfClips[0]);
  action.setLoop(THREE.LoopRepeat, Infinity);
  action.reset().play();
}
```

> 之后可以加 `model3d.animation_clip` 让用户选第几个 —— **本次不做**，先保证能播。

- [x] **Step 5: 释放**

`VRMUtils.deepDispose` 是 VRM 专用的；纯 glTF 用 three 自己的遍历释放
（**不释放会显存泄漏**，切换几次模型就把 WebGL 上下文吃光）：

```ts
function disposeGltfScene(root: THREE.Object3D | null): void {
  if (!root) return;
  root.traverse((obj) => {
    const mesh = obj as THREE.Mesh;
    if (mesh.geometry) mesh.geometry.dispose();
    const mat = (mesh as unknown as { material?: THREE.Material | THREE.Material[] }).material;
    if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
    else if (mat) mat.dispose();
  });
}
```

## Task 2: 帧循环与共享逻辑改用 `currentRoot`

- [x] **Step 1: `applySceneRotation` / `reframe` 改用 `currentRoot`**

```ts
function applySceneRotation(): void {
  if (!currentRoot) return;
  const deg = Number.isFinite(props.rotationY) ? props.rotationY : 0;
  currentRoot.rotation.y = baseSceneRotationY + (deg * Math.PI) / 180 + spinAngle;
}
```
`reframe` 同理（把里面的 `vrm.scene` 换成 `currentRoot`）。

- [x] **Step 2: `onFrame` 里让 mixer 转起来**

```ts
const onFrame = (delta: number) => {
  if (!vrm && !currentRoot) return;

  clockElapsed += delta;
  updatePose(delta);                    // 与 vrm 无关，纯数值，可无条件跑
  updateIdleAnimation(delta);           // 内部已 guard vrm
  if (vrm) vrm.update(delta);
  if (gltfMixer) gltfMixer.update(delta);   // ← 新增：驱动骨骼动画

  if (props.autoRotate) { spinAngle += delta * 0.35; applySceneRotation(); }  // 现在对 glTF 也生效
  if (gazeInitialized && props.enableGazeControl) gazeController.update(delta);
};
```

- [x] **Step 3: 加载完成后的取景也走 `currentRoot`**

`loadModel` 尾部那段双 `requestAnimationFrame` + `frameObject(...)` 现在用 `loadedVrm.scene`，
要改成 `currentRoot`（否则 glTF 模型不会自适应取景，会跑出画面）。

- [x] **Step 4: `emit('modelLoaded', ...)` 改成发根节点**

`modelLoaded` **没有任何父组件在监听**（实测只有 `load-error` 被用），所以可以安全改：
`emit('modelLoaded', currentRoot)`。并在注释里说明。

## Task 3: 验收

- [x] **Step 1: 静态检查 + 单测 + 构建**

```bash
cd front && npm run lint:ci && npm run type-check && npx vitest run && npm run build
```

- [x] **Step 2: 用真实 glb 端到端验证（Playwright）**

找一个带动画的 glb（three 官方示例库里有，或本地造一个）。断言：
1. 页面**不出现** `.error-overlay`（此前上传 glb 必报错）
2. 模型真的在动 —— 连续两帧截图像素有差异（不能只证明"没报错"）
3. `gltf.animations` 有内容时 mixer 真的创建了

> **没有现成 glb 时的兜底**：用 three 在页面里程序化造一个带动画的 `SkinnedMesh` glTF
> 成本太高；改为用一个已知带动画的公开示例 glb（离线则跳过该步并说明）。

- [x] **Step 3: VRM 回归（不许有行为变化）**

用现有 `rpm_demo.vrm` 走一遍，确认：
- 不报错、正常显示、idle/眨眼/lip-sync 仍工作（lip-sync 峰值 > 0）
- 截图与改动前无明显差异

## 最终验收

- [ ] `lint:ci` / `type-check` / `vitest` / `build` 全绿
- [ ] glb（带动画）能加载、能播放、无 error overlay
- [ ] VRM 功能无回归
- [ ] 连续切换模型不泄漏（跑 5 次加载，控制台无 WebGL 警告）

## Known Issues

- **播哪个 clip 暂不开放配置**：固定播第一个。要支持选择得加后端字段 + 界面，本次不做。
- **纯 glTF 没有 VRM 的表情系统**，所以眨眼、微表情、lip-sync 嘴型对非 VRM 模型无效 ——
  这是模型格式本身的限制（glTF 没有标准表情轨道），不是缺陷。
- **CDN 化（2.4 的第二项）本次不做**：那是运维/部署决策（要选供应商、改上传目标、
  处理回源），不是代码能单方面完成的。已有 `model3d.url` 字段支持外链，
  真要 CDN 化是在部署流程里配置，不是改前端。

## Self-Review

**1. Spec coverage：** glb 加载 + 动画播放（Task 1-2）+ VRM 零回归（Task 3）✅。
CDN 化已说明为何不在本次范围。✅
**2. Placeholder scan：** Task 3 Step 2 的 glb 来源是**开放问题**（需要找一个带动画的样本），
已显式标注兜底方案。⚠️
**3. 一致性：** `currentRoot` / `gltfMixer` / `disposeGltfScene` 命名一致。✅
**4. 最大风险 = 改坏 VRM**：方案反复强调"原逻辑一字不改"、"只加分支"，
并把 VRM 回归单列为验收项。✅
**5. 显存泄漏**：glTF 换模型要释放 geometry/material，否则 WebGL 上下文会被吃光（Task 1 Step 5）。✅

---

## 执行结果（2026-10-12）

4 个 Task 全部完成。

### 实测发现比方案里写的更严重

方案写"带骨骼动画的 glTF 模型动不起来" —— 实际是：后端 `model3d.EXTENSION_FORMAT_MAP`
**允许上传 `.glb` / `.gltf`**，但前端 `VRMAvatar.vue` 只有 VRM 一条路径，
`if (!loadedVrm) throw new Error('VRM 数据未找到')`。
**也就是后端接受的文件类型，会让角色直接坏掉**，不只是"动画播不出来"。

另外全项目**没有任何** `AnimationMixer` / `AnimationClip` 用法，glTF 骨骼动画从未被播放过。

### 改动

| 文件 | 内容 |
|---|---|
| `front/src/components/3d/VRMAvatar.vue` | 纯 glTF 分支 + `AnimationMixer` + `currentRoot` + `disposeGltfScene` |

具体：
- `loadModel` 拆成 VRM / 纯 glTF 两条分支。**VRM 分支原逻辑一字未改**（只缩进）。
- 纯 glTF：`gltf.animations` 有内容就建 mixer 播第一个 clip（循环）；没有就静止显示（比报错好）。
- `applySceneRotation` / `reframe` / `frameObject` 从 `vrm.scene` 改用 `currentRoot` ——
  取景与自转现在对 glTF 也生效。
- `onFrame` 里加 `gltfMixer.update(delta)`；VRM 专属特性（表情/注视/SpringBone）按原样 guard。
- 新增 `disposeGltfScene()` 释放 geometry/material —— **不释放会显存泄漏**，
  切几次模型就把 WebGL 上下文吃光。
- `emit('modelLoaded')` 从发 `VRM` 改成发根节点。实测**没有父组件监听它**（只有 `load-error` 被用到）。

### 验证（Playwright + 真实画面像素比对）

**glb 路径** —— 用 three 的 `GLTFExporter` 在 Node 里自造了一个 15KB 带动画 glb
（本机连不上 glTF 官方示例库），然后用**路由拦截**把它顶替掉原本的 VRM 请求，
这样不改任何数据就能走到纯 glTF 分支：
- `errorOverlay: 0` ✅（改动前必报「VRM 数据未找到」）
- `canvasCount: 1` ✅
- **`pixelsChanged: 1264 / changeRatio: 0.0278`** ✅ —— 两帧截图 700ms 内有 2.78% 像素变化，
  **画面真的在动**（不是只证明"没报错"）
- 两帧截图里手臂位置肉眼可见不同 ✅

**VRM 回归**（不许有行为变化）—— 不拦截，加载真实 17MB `rpm_demo.vrm`：
- `errorOverlay: 0`、`canvasCount: 1` ✅
- **`changeRatio: 0.0347`** ✅ —— idle 动画仍在动
- 截图与改动前一致 ✅

**其它**：后端 pytest 307 passed；前端 lint:ci 0 / type-check 0 / vitest 138 / build 通过。

### 踩的坑

- `GLTFExporter` 在 Node 里需要 shim `FileReader`，**而且它用的是 `onloadend` 不是 `onload`** ——
  只 shim `onload` 的话 `parse` 的**回调永远不触发**，表现为"脚本静默退出 0"。
- 脚本用 `.mjs` 就别写 TS 的 `!` 非空断言（会 SyntaxError）。
- 为测试装 `pngjs` 会污染依赖 —— 改成在页面里 `createImageBitmap + canvas` 解码比较像素。

### 遗留

- **播哪个 clip 不开放配置**：固定播第一个。要支持选择得加后端字段 + 界面。
- 纯 glTF **没有 VRM 表情系统**，所以眨眼/微表情/lip-sync 嘴型对非 VRM 无效 ——
  这是 glTF 格式本身的限制（没有标准表情轨道），不是缺陷。
- **CDN 化（2.4 第二项）未做**：那是运维/部署决策（选供应商、改上传目标、回源），
  不是代码能单方面完成的。`model3d.url` 已支持外链，真要 CDN 化是在部署流程里配。
