# 前端 lint 清债 + 接入 CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 清掉前端全部 lint 问题，并把 lint 接进 CI 作为阻断门。

**Architecture:** `package.json` 的 `lint` 脚本跑 **两个** linter（`lint:oxlint` + `lint:eslint`），但 `.github/workflows/ci.yml` 里**一个都没跑**。实测当前：

| linter | 数量 | 构成 |
|---|---|---|
| oxlint | **29 errors** | 21 × `vitest/require-mock-type-parameters`（测试文件里 `vi.fn()` 缺类型参数）、`no-unused-vars`、`no-misleading-character-class` |
| eslint | **67 errors** + 15 warnings | `no-explicit-any` 32、`no-unused-vars` 21、`ban-ts-comment` 6、`prefer-const` 4、`no-require-imports` 3、`vue/multi-word-component-names` 1 |

**两处需要先纠正的旧结论**（都在本次实测中被推翻）：

1. 我在 2026-09-18 的备忘里写「`VRMAvatar.vue` 12 处已过时、两个 `.vue` 早已干净」——
   那是**只看 oxlint** 得出的。**eslint 给出的正好是 12 处**，旧说法是准的。本次一并更正。
2. 我在推进方案里写「`LipSyncEngine.test.ts` 与 `LipSyncEngine.spec.ts` 内容重复，该合并」——
   **不准确**。两者测的是不同侧面（前者测 MediaElementSource 创建/复用，后者测 RMS 计算），
   只有部分重叠。本次**不合并**（合并是无谓的 churn），只修 lint。

**注意：`dist-electron/` 是构建产物**，被 eslint 扫到 3 个 `no-require-imports` —— 那是误报，
应加进 `globalIgnores`（oxlint 已正确忽略）。

**Tech Stack:** oxlint / eslint(flat config) / vue-tsc / GitHub Actions。

---

## 前置基线

```bash
cd front
npx oxlint .            # 29 errors
npx eslint .            # 67 errors, 15 warnings
npx vue-tsc --noEmit -p tsconfig.app.json   # exit 0
npx vitest run          # 138 passed
npm run build           # 通过
```

**每个 Task 结束后必须复跑 `vitest run`** —— lint 修复会删死代码，删错了只有测试能发现。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `front/eslint.config.ts` | 修改 | `globalIgnores` 加 `dist-electron`（构建产物误报） |
| `front/.oxlintrc.json` | 修改 | 确认 ignore 覆盖构建产物 |
| `front/src/utils/readAloud.ts` | 修改 | 修 `no-misleading-character-class`（本次新增的债） |
| 17 个 src 文件 | 修改 | 清 `no-explicit-any` / `no-unused-vars` / `prefer-const` / `ban-ts-comment` / `vue/multi-word-component-names` |
| `.github/workflows/ci.yml` | 修改 | 加 lint 阻断门 |

---

## Task 1: 修配置（构建产物误报）+ 清掉本次新增的债

- [ ] **Step 1: `eslint.config.ts` 忽略构建产物**

```ts
globalIgnores(['**/dist/**', '**/dist-ssr/**', '**/dist-electron/**', '**/coverage/**']),
```

- [ ] **Step 2: 修 `src/utils/readAloud.ts` 的 emoji 正则**

`no-misleading-character-class`：`\u{FE0F}` 是变体选择符（combining class），
放进字符类里会被误判为"可能想匹配组合序列"。改用 `u` 标志下的显式转义或拆开写：

```ts
/** 表情符号。变体选择符 U+FE0F 单独处理 —— 它放在字符类里会触发
 *  no-misleading-character-class（会被当成想匹配组合序列）。 */
const EMOJI_RE = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2190}-\u{21FF}\u{2B00}-\u{2BFF}]/gu
const VARIATION_SELECTOR_RE = /\uFE0F/gu
```
清洗时两次替换即可（顺序无关）。

- [ ] **Step 3: 验证**

```bash
cd front && npx oxlint src/utils/readAloud.ts && npx eslint src/utils/readAloud.ts && npx vitest run src/utils/__tests__/readAloud.spec.ts
```
Expected: 两个 linter 都 0 问题；16 passed（emoji 用例仍要过）。

---

## Task 2: 清 oxlint 的 29 个

- [ ] **Step 1: 测试文件的 `vi.fn()` 补类型参数（21 个）**

涉及 `LipSyncEngine.test.ts`(12)、`__tests__/LipSyncEngine.spec.ts`(9)、
`StoryView.spec.ts`(2)、`character-model.spec.ts`(2)、`story.spec.ts`(1)。

规则要求 mock 函数带类型参数。按被 mock 的签名写，例如：

```ts
// 之前
const onToken = vi.fn()
// 之后
const onToken = vi.fn<(t: string) => void>()
```

**不要图省事写 `vi.fn<any>()`** —— eslint 会再报 `no-explicit-any`，等于把债从左边搬到右边。

- [ ] **Step 2: `chatStore.ts` 未使用参数**

L144 `assistantMsg` 未使用 → 按规则要求加下划线前缀：`_assistantMsg`。

- [ ] **Step 3: 验证**

```bash
cd front && npx oxlint .        # 期望 0
npx vitest run                  # 期望 138 passed（改了测试文件，必须复跑）
```

---

## Task 3: 清 eslint 的 67 个

按文件推进，**每修完一个文件就跑一次 `vitest run` + `vue-tsc`**。

- [ ] **Step 1: `no-unused-vars`（21 个）—— 删死代码**

多数是真死代码，直接删：
- `VRMAvatar.vue`：未使用的 import（`LipSyncEngine`、`GazeMode`）、
  赋值后从不使用的 `targetExpressionWeights` / `visemeSmoothFactor`、
  未使用的 `applyBaseExpressionDeprecated`、回调里未使用的 `delta` 参数（→ `_delta`）
- `VoiceCallModal.vue`(8)、`MemoryView.vue`(2)、`SettingsView.vue`(1)、
  `AuthModal.vue`(1)、`Chat.vue`(1) 同理

**注意**：`delta` 这类**回调参数**不能直接删（位置参数会错位），要改成 `_delta`。

- [ ] **Step 2: `prefer-const`（4 个，全在 VRMAvatar.vue）**

`let` 改 `const`。注意有些变量同时命中 `no-unused-vars`（如 `targetExpressionWeights`）——
**那种情况直接删，不是改 const**。

- [ ] **Step 3: `no-explicit-any`（32 个）**

按文件：`webrtcService.spec.ts`(9)、`VoiceCallModal.vue`(7)、`webrtcService.ts`(3)、
`LipSyncEngine.test.ts`(2)、`LipSyncEngine.spec.ts`(2)、`authStore.ts`(2)、`AdminView.vue`(2)、
`SettingsView.vue`(2)、`AboutView.vue`(1)、`CharactersView.vue`(1)、`DesktopWidget.vue`(1)。

修法优先级：
1. **能写出真实类型就写**（最好）；
2. 收窄成 `unknown` 再在调用处断言；
3. 实在无法表达（如 mock 的复杂泛型）用 `// eslint-disable-next-line @typescript-eslint/no-explicit-any` + **一句说明为什么**。

**不要无脑全局禁用这条规则** —— 它抓到的是真问题。

- [ ] **Step 4: `ban-ts-comment`（6 个）**

`LipSyncEngine.test.ts`(3) + `LipSyncEngine.spec.ts`(3)。规则要求 `@ts-expect-error` 必须带说明：

```ts
// @ts-expect-error 故意传错类型，验证运行时的防御性检查
engine.foo('bad')
```

- [ ] **Step 5: `vue/multi-word-component-names`（1 个，Chat.vue）**

单字组件名。路由组件不需要多词名 → 在该文件顶部加：
```vue
<!-- eslint-disable-next-line vue/multi-word-component-names -->
```
**或**更干净：在 `eslint.config.ts` 里给 `src/views/**` 关掉这条规则（视图就是路由组件，天然单名）。
**采用后者**，并在配置里写明理由。

- [ ] **Step 6: 验证**

```bash
cd front && npx eslint .        # 期望 0 errors, 0 warnings
npx oxlint .                    # 期望 0
npx vue-tsc --noEmit -p tsconfig.app.json
npx vitest run                  # 期望 138 passed
npm run build
```

---

## Task 4: 接进 CI

- [ ] **Step 1: 在 `type-check` 之后加 lint 步**

```yaml
      - name: Lint (oxlint + eslint)
        run: npm run lint
```

**放在 `type-check` 之后、`vitest` 之前** —— 静态检查失败最快、最便宜，先跑。

**注意**：`lint` 脚本带 `--fix`（`oxlint . --fix` / `eslint . --fix --cache`）。
CI 里跑 `--fix` 不会失败（它把问题就地改了然后退出 0），等于**门是空的**。
所以要么给 CI 用不带 `--fix` 的变体，要么改脚本。**采用**：`package.json` 加两个不带 fix 的脚本，
CI 用它们：

```json
"lint:ci": "run-s lint:ci:*",
"lint:ci:oxlint": "oxlint .",
"lint:ci:eslint": "eslint . --max-warnings 0",
```

`--max-warnings 0` 让 warnings 也阻断 —— 否则 15 个 warning 会一直躺着。

- [ ] **Step 2: 验证 CI 门真的会拦**

故意在任一 src 文件里插一行 `const _x: any = 1`，跑 `npm run lint:ci`，确认**非 0 退出**；
然后删掉探针。

---

## 最终验收

```bash
cd front
npx oxlint .                                   # 0
npx eslint . --max-warnings 0                  # 0
npm run lint:ci; echo "LINT_EXIT:$?"           # LINT_EXIT:0
npx vue-tsc --noEmit -p tsconfig.app.json      # exit 0
npx vitest run                                 # 138 passed
npm run build                                  # 通过
```

- [ ] 故意注入一个 lint 错误 → `lint:ci` 退出非 0（证明门有效）

## Known Issues

- 本次只清前端 lint。**后端没有配 linter**（无 ruff/flake8），不在范围内。
- `vue/multi-word-component-names` 用配置关掉而非改名 —— 视图组件是路由组件，
  改名会牵动 router 与测试；关规则是更小的改动。已在配置里注明理由。
- 清 `no-explicit-any` 时若有站点确实无法表达类型，会用带说明的 `eslint-disable`，
  **这类豁免会在提交信息里逐条列出**，避免变成新的隐性债。

## Self-Review

**1. Spec coverage：** 清债（Task 1-3）+ 进 CI（Task 4）✅。两处旧结论纠正已写入开头。
**2. Placeholder scan：** Task 3 按文件列举而非逐行给代码（67 处，逐行列举会让文档长到没人看），
但每类给了明确的修法与优先级。⚠️ 已标注。
**3. 一致性：** `lint:ci*` 脚本命名在 Task 4 与验收中一致。
**4. 提交粒度：** Task 1（配置）/ Task 2（oxlint）/ Task 3（eslint）/ Task 4（CI）各自独立 commit。
**5. 风险控制：** 每个 Task 后复跑 vitest —— lint 修复会删死代码，只有测试能发现删错。
