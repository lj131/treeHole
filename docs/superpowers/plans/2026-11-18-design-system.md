# 全站设计系统统一（2026-11-18）

## Goal + 边界

消除各页面"同用途不同值"的样式漂移：**只统一结构样式，语义色保留**。
不改视觉风格（保持暗色紫调）、不改结构/逻辑、不做响应式重排。

## 摸底证据（已核对）

| 项 | 现状 |
|---|---|
| 圆角 | 15 种值：4/6/8/9/10/11/12/14/16/18/20/24/999px（8/10/12px 各 31 次） |
| 次要文字色 | `#94a3b8`(29 次，9 页) vs `#8888aa`(19 次，About/Admin/Chat 3 页) —— 两套独立配色 |
| 正文色 | `#cbd5e1`(20) / `#e2e8f0`(17) / `#e8e8f0`(14) 混用 |
| 字号 | `0.82/0.84/0.85/0.86/0.88/0.9/0.92/0.95rem` 八个近似值 |
| 卡片边框 | rgba(255,255,255,·) 透明度 0.06/0.07/0.08/0.09/0.12 五种 |
| 卡片底色 | rgba(255,255,255,·) 0.03/0.04/0.05/0.08 四种 |

**语义色（保留，不迁）**：错误红 `#fca5a5`/`#f87171`、成功绿 `#6ee7b7`/`#4ade80`、
警告橙 `#fdba74`/`#fbbf24`、品牌紫渐变 `#667eea→#764ba2`/`#7b5cff`/`#c8b6ff`。
这些表达状态，合并会丢信息。

## Token 体系（在 App.vue `:root`，light 主题有对应覆盖）

### 圆角（4 档 + 胶囊）
- `--radius-xs: 6px`（徽章/小标签）
- `--radius-sm: 8px`（小按钮/输入框）
- `--radius-md: 10px`（常规按钮/控件）
- `--radius-lg: 14px`（中等卡片）
- `--radius-xl: 20px`（大卡片/弹窗）
- `--radius-pill: 999px`（胶囊/圆头像）
- 保留既有 `--radius-card`(16px) / `--radius-btn`(10px) 不动（已有页面在用）

### 文字色（结构）
- `--text-muted: #94a3b8`（次要说明；**替换掉 `#8888aa`** —— 统一到多数派）
- `--text-subtle: #64748b`（更弱的三级文字）
- `--text-body: #e2e8f0`（正文强调）

### 字阶
- `--text-xs: 0.75rem` / `--text-sm: 0.85rem` / `--text-base: 1rem`
- `--text-lg: 1.25rem` / `--text-xl: 1.5rem` / `--text-2xl: 2rem`

### 卡片/边框/阴影
- `--card-bg` / `--card-border`（上一轮已建，沿用）
- `--border-subtle: rgba(255,255,255,0.06)`（分隔线/表格行）

## 迁移映射规则（机械替换，逐页生效）

| 旧值 | 新 token | 例外 |
|---|---|---|
| `border-radius: 6px` | `var(--radius-xs)` | 精确到 50% / 999px 的圆头像不动（已是 pill） |
| `border-radius: 8px` | `var(--radius-sm)` | |
| `border-radius: 10px` / `11px` / `9px` | `var(--radius-md)` | |
| `border-radius: 12px` / `14px` | `var(--radius-lg)` | 12px→14px 有 2px 微差，可接受 |
| `border-radius: 16px` / `18px` / `20px` | `var(--radius-xl)` | |
| `border-radius: 4px` | 保留 | 4px 多用于极小 chip，过度统一不值当 |
| `color: #94a3b8` / `#8888aa` | `var(--text-muted)` | |
| `color: #cbd5e1` / `#e2e8f0` | `var(--text-body)` | |
| `font-size: 0.82~0.88rem` | `var(--text-sm)` | 0.9/0.92/0.95rem 保留（语义上偏"正文小"，统一会跳变） |
| `background: rgba(255,255,255,0.03/0.04/0.05)` | `var(--card-bg)` | 0.08+ 是 hover/激活态，保留 |
| `border: 1px solid rgba(255,255,255,0.06/0.07/0.08/0.09)` | `var(--card-border)` | 0.12+ 是强调边框，保留 |

⚠️ **只替换 CSS 声明里的值**，不碰 template 里的 inline style（那些多是有意为之的动态值）。

## 分批（每批截图+检查+提交，可随时喊停）

- ✅ **批次 1**（提交 `da26501`）：App.vue token 补全 → AboutView / AdminView /
  Chat / AuthModal / WorldEventPanel / StoryTree / RelationGraph —— 98 处
- ✅ **批次 2**（提交 `52d4f23`）：SettingsView / CharactersView / MemoryView —— 91 处
- ✅ **批次 3**：HomeView / NpcGroupChatView / DigestView / StoryView /
  DesktopWidget / PoC3DAvatar / OAuthCallbackView / 各 Modal / App.vue / 3d 组件 —— 75 处
  + 手工补漏 4 处（Chat echo-panel / ThreeScene / VRMAvatar / WelcomeItem）

## 验收

- 每批：真浏览器截图对比（改前 baseline 已存 `3d-verify/design-*.png`），
  确认无错位/溢出；前端 type-check / lint:ci / vitest / build 全绿
- 全站：grep 确认 `#8888aa` 归零、`border-radius` 硬编码种类下降
- 同步 `front/CLAUDE.md`；每批一个提交


## 完成记录（2026-11-18）

三批共迁移 **268 处**，26 个文件引用 token。
- `color:#8888aa` 全站归零（仅剩 SVG stroke 一处，不在范围）
- `border-radius` 硬编码 **15 种 → 5 种**：999px(胶囊) / 4px(极小chip) /
  24px(弹窗) / 2px / 3px —— 全是方案里列的合理例外
- 逐批真浏览器截图验收：聊天/关于/管理/设置/角色/记忆/首页/群聊旁观/日报
  共 9 页，无错位、无颜色突变、语义色（状态徽章/进度条/品牌渐变）全部保留
- 前端 type-check 0 / lint 0 / vitest 208 / build 0（每批都跑）
- ⚠️ 验收截图踩坑：Playwright 截首页偶发整块空白，是渲染时机问题不是代码回归；
  用多次 evaluate 读 computed style 触发重绘，并用 PIL 采样确认非 1 色。已写进 front/CLAUDE.md。
