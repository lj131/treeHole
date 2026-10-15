# D3 桌面挂件增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给桌面挂件补上"挂件感"——**系统托盘**和**开机自启**。

**Architecture:** Electron 宿主已存在且很干净（`front/electron/main.ts` 126 行），
已经实现：置顶 / 拖动 / 收起展开 / 显隐。
本轮只新增两块能力，走**已有的** `ipcMain.handle` → `preload` → `window.widgetApi` → store 链路，
不引入新机制。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `front/electron/main.ts` | 修改 | Tray + autoLaunch + 两个 IPC |
| `front/electron/preload.ts` | 修改 | 透传两个新方法 |
| `front/src/types/electron.d.ts` | 修改 | 补类型 |
| `front/src/stores/widgetStore.ts` | 修改 | 加 `autoLaunch` 状态 + action |
| `front/src/views/DesktopWidget.vue` | 修改 | footer 加两个开关 |
| `front/src/stores/__tests__/widgetStore.spec.ts` | **新增/追加** | 新 action 的测试 |

---

## Task 0: 摸清现状（**先做**）

- [x] 挂件 = Electron BrowserWindow（`transparent` + `frame: false` + `alwaysOnTop`）
- [x] **已有**：置顶切换、拖动、compact/expanded 尺寸、hide/show
- [x] **缺**：`Tray`（系统托盘）、`autoLaunch`（开机自启）、浏览器扩展
- [x] 链路：`ipcMain.handle` → `preload` `contextBridge` → `window.widgetApi` → `widgetStore`

## Task 1: 系统托盘（核心）

- [ ] **Step 1**: `main.ts` 建 `Tray`：
      - 图标用 `electron/default-icon.png`（打包态）/ dev 用同一路径 fallback；
        **不存在时不能崩**（develop 环境常有这问题）→ 空 `nativeImage` 兜底
      - `toolTip` = 'treeHole 桌面挂件'
      - 菜单：`显示 / 隐藏`、`置顶开关`（勾选态）、`退出`
- [ ] **Step 2**: 左键点击 tray = 切换显隐（`show`/`hide`）
- [ ] **Step 3**: **关窗口不退出**：`widgetWindow.on('close')` 拦截 → `hide()`，
      真正退出走 tray 的"退出"（`app.quit()`）。
      ⚠️ 这是挂件的基本语义，否则托盘没意义
- [ ] **Step 4**: IPC `widget:toggle-visibility` 给前端用

## Task 2: 开机自启

- [ ] **Step 1**: `app.setLoginItemSettings({ openAtLogin })`（macOS/Windows 通用，
      比 `auto-launch` 这个 npm 包少一个依赖）
- [ ] **Step 2**: IPC `widget:set-auto-launch` 返回新值；`widget:get-auto-launch` 读当前值
- [ ] **Step 3**: 前端 store 持久化（localStorage，key `widget_auto_launch`），
      **启动时用 `get-auto-launch` 校准** —— 用户在系统设置里改过要以系统为准

## Task 3: 前端接线

- [ ] **Step 1**: `preload.ts` / `electron.d.ts` 补 4 个方法
- [ ] **Step 2**: `widgetStore` 加 `autoLaunch` + `toggleAutoLaunch()` + `initAutoLaunch()`
- [ ] **Step 3**: `DesktopWidget.vue` footer 加两个开关按钮：
      「开机自启：开/关」。托盘显隐已经有 hide/show 入口（header 收起按钮旁）
- [ ] **Step 4**: `onMounted` 里 `initAutoLaunch()`（以系统设置为准）

## Task 4: 测试

- [ ] `widgetStore.toggleAutoLaunch()` 成功 → 状态更新 + 写 localStorage
- [ ] `widgetStore.toggleAutoLaunch()` 被宿主拒绝/抛错 → 状态**回滚** + 不吞错
- [ ] `initAutoLaunch()` 在无 `widgetApi`（浏览器环境）时**不抛**
- [ ] `initAutoLaunch()` 以系统值为准（系统 false → 状态 false，与 localStorage 冲突时系统赢）
- [ ] footer 两个按钮渲染 + 点击调用 store

## 最终验收

- [ ] 前端 type-check / lint / vitest 全绿
- [ ] `npx tsc --noEmit electron/main.ts` 或等效方式确认宿主类型没错
- [ ] 文档 + E2E：**打包态无法在本机跑**（需 electron-builder），
      至少确认 dev 态 `npm run electron:dev` 能起窗口不报错（若链路通）

## Self-Review

**1. Spec coverage**：D3 三个子项里做了托盘 + 开机自启（各 1-2 天，匹配"小步快跑"）；
   浏览器扩展**不做** —— 它是另一套工程（manifest / content script / 发布渠道），
   塞进这个 Issue 只会做出半成品。✅
**2. 最大风险 = 关窗就退不回来**（托盘白做）：Step 3 显式拦截 close。✅
**3. 失败隔离**：Tray 图标不存在、`widgetApi` 不存在（纯浏览器跑）都不能崩。✅
**4. 状态冲突**：localStorage vs 系统设置 → **系统赢**（用户在系统里改了要尊重）。✅
**5. 不过度设计**：没做托盘气泡动画、右键完整菜单、多显示器记忆位置。✅

## Known Issues

- **浏览器扩展不做**：理由如上，且它是独立发布渠道
- **无打包验证**：`electron-builder` 出安装包需要较长时间和签名，
  本轮只确认代码正确 + dev 态可起
- `setLoginItemSettings` 在 Linux 某些桌面需要额外 `.desktop` 文件（不在本机验证范围）
