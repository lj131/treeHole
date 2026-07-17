# 清偿 P0 技术债 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 清除项目两处 P0 技术债 —— 删除严重过时的 `backend/api接口文档.md`，并把前端 type-check 在 CI 中恢复为阻断门（同步清掉声称"类型债"的过期文档）。

**Architecture:** 本计划不含新功能代码，纯技术债清理 + 文档/CI 配置同步。关键前提（已验证）：前端 type-check 在当前干净代码上**已通过**（exit 0），所谓"类型债"在代码层早已还清，残留的只是 (a) `ci.yml` 仍带 `continue-on-error: true` 让 type-check 变成非阻断，(b) `front/CLAUDE.md` 仍写着类型债已存在的过期描述。后端 `api接口文档.md` 文档了 6 个已不存在的端点（`/memory`、`/clear-memory`、`/messages`、`/character/name` GET/POST）以及完全错误的"关键词匹配好感度"算法（实际是 `unified_state_agent` 一次 LLM 调用），而 `backend/CLAUDE.md` 已有完整准确的端点清单 —— 按 DRY 原则直接删除该过期文档，不留第二份真相源。

**Tech Stack:** GitHub Actions (`.github/workflows/ci.yml`)、vue-tsc (`front`)、pytest (`backend`)、Markdown 文档。

---

## 前置基线（已验证为 GREEN，执行前无需重跑，但 Task 内会复验）

- 后端 `pytest -q`：70 passed，exit 0
- 前端 `vue-tsc --build --force`：exit 0（无类型错误）
- 前端 `vitest run`：4 passed，exit 0
- type-check 门被证明有效：故意注入类型错误 -> `vue-tsc --build` exit 2 + `error TS2322`

## File Structure

本计划触及的文件（每文件单一职责）：

| 文件 | 动作 | 职责 |
|---|---|---|
| `.github/workflows/ci.yml` | 修改 (73-77 行) | 去掉 type-check 步的 `continue-on-error` 与过期注释，恢复为阻断门 |
| `front/CLAUDE.md` | 修改 (209-221 行) | 删除已过期的"类型债"小节 |
| `backend/api接口文档.md` | **删除** | 文档 6 个已删端点 + 错误算法，是误导源 |
| `CLAUDE.md`（根） | 修改 (150 行) | 删除指向已删文档的 Known Issues 条目 |
| `PROJECT_ANALYSIS.md` | 修改 (P0 表 + 文档一致性节) | 标注 P0 已清偿，保持分析文档与现状一致 |

无新增源码文件。无新增测试文件（type-check 与现有 pytest/vitest 即是验证手段）。

---

## Task 1: 恢复前端 type-check 为 CI 阻断门（TDD：先看它失败）

**Files:**
- Modify: `.github/workflows/ci.yml:73-77`

**为什么用 TDD：** 我们要改的是 CI 行为（type-check 失败必须阻断 job）。先用一个故意注入的类型错误证明"type-check 确实能抓到错误"，再看它 fail —— 这才是真正的门，而不是 no-op。改完 `continue-on-error` 后，同一个 fail 就会真正阻断 CI。

- [ ] **Step 1: 注入故意类型错误，跑 type-check，确认它 FAIL（RED）**

在 `front/src/` 下建一个一次性探针文件：

```bash
cd front
printf 'const _probe: number = "not-a-number"\n' > src/__tdd_probe.ts
node_modules/.bin/vue-tsc --build --force 2>&1 | head -15
echo "EXIT:${PIPESTATUS[0]}"
```

Expected: 输出包含 `src/__tdd_probe.ts(1,7): error TS2322: Type 'string' is not assignable to type 'number'.`，`EXIT:2`。

> 这一步证明：type-check 在有类型错误时**会**退出非零。这就是我们要恢复的阻断门的"测试"。

- [ ] **Step 2: 删除探针，确认 type-check 回到 GREEN**

```bash
rm -f src/__tdd_probe.ts
node_modules/.bin/vue-tsc --build --force 2>&1 | head -15
echo "EXIT:${PIPESTATUS[0]}"
```

Expected: 无错误输出，`EXIT:0`。确认探针已清除、代码回到干净状态。

- [ ] **Step 3: 去掉 ci.yml 的 `continue-on-error` 与过期注释**

把 `.github/workflows/ci.yml` 中的这段：

```yaml
      - name: Type check (vue-tsc)
        # 代码库存在预存类型债（VoiceCallModal 引用已删 store 字段、chatStore 类型不匹配），
        # 非本 CI 引入。先设为非阻断，把问题暴露在日志里但不卡绿基线；清债后改回阻断。
        continue-on-error: true
        run: npm run type-check
```

改为：

```yaml
      - name: Type check (vue-tsc)
        run: npm run type-check
```

- [ ] **Step 4: 复跑前端 type-check + 单测，确认仍 GREEN**

```bash
cd front
node_modules/.bin/vue-tsc --build --force; echo "TYPECHECK_EXIT:$?"
npx vitest run 2>&1 | tail -5
```

Expected: `TYPECHECK_EXIT:0`；vitest `Test Files 2 passed (2)` / `Tests 4 passed (4)`。

- [ ] **Step 5: Commit**

```bash
cd ..
git add .github/workflows/ci.yml
git commit -m "ci: 恢复前端 type-check 为阻断门（移除 continue-on-error）

类型债在代码层已还清（vue-tsc --build 干净通过），CI 不再需要 continue-on-error
兜底。同步删除过期的类型债注释。
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: 清掉 front/CLAUDE.md 过期的"类型债"描述

**Files:**
- Modify: `front/CLAUDE.md:209-221`

> 依据 Working Agreement「改完代码就改 CLAUDE.md」：Task 1 让 type-check 重新阻断，`front/CLAUDE.md` 里"类型债"小节的三条都已不成立，必须同步删掉，否则后续 Claude 会照着错的描述去找不存在的问题。

- [ ] **Step 1: 把 Known Issues 节的"类型债"小节整段删除**

把 `front/CLAUDE.md` 末尾这段：

```markdown
## Known Issues

### 类型债

- `VoiceCallModal` 引用已删除的 store 字段（需修复）
- `chatStore` 类型不匹配（`lastFailedMessage` 可能为 null）
- type-check 在 CI 中设为 `continue-on-error`（清债后改回阻断）

### 其他限制

- E2E 测试仅覆盖 Chromium
- 移动端适配：Chat.vue 在窄屏时隐藏侧栏，改用底部 Tab 栏
- 桌面挂件：首次构建 Electron 可能需要手动下载依赖（electron-builder）
```

替换为（删掉"类型债"小节与"### 其他限制"标题，三条真实限制直接作为 Known Issues 列表）：

```markdown
## Known Issues

- E2E 测试仅覆盖 Chromium
- 移动端适配：Chat.vue 在窄屏时隐藏侧栏，改用底部 Tab 栏
- 桌面挂件：首次构建 Electron 可能需要手动下载依赖（electron-builder）
```

- [ ] **Step 2: 校验三个被声明为"已删 store 字段"的字段确实存在（避免误删真问题）**

```bash
cd front
echo "--- store 导出字段 ---"
grep -nE '^\s+(isCalling|isConnected|ttsProvider|isAiThinking|callPhase|isAiSpeaking|networkQualityClass|clearError|endCall|toggleMute)' src/stores/voiceCallStore.ts
echo "--- VoiceCallModal 引用 ---"
grep -oE 'voiceCallStore\.\w+' src/components/VoiceCallModal.vue | sort -u
```

Expected: VoiceCallModal 引用的每个字段都出现在 store 导出列表里。若全部命中，确认"引用已删 store 字段"确为过期描述，删除无误。

- [ ] **Step 3: Commit**

```bash
cd ..
git add front/CLAUDE.md
git commit -m "docs(front): 删除过期的类型债描述

VoiceCallModal 引用的 store 字段均已存在、chatStore 的 lastFailedMessage 已正确
nullable、type-check 已恢复阻断。类型债小节三条均已不成立，删掉避免误导。
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: 删除严重过时的 `backend/api接口文档.md` 并清理引用

**Files:**
- Delete: `backend/api接口文档.md`
- Modify: `CLAUDE.md`（根）`:150`

> 该文档日期 2026/05/29，文档了 6 个已删端点（`/memory`、`/clear-memory`、`/messages`、`/character/name` GET/POST、`/profile` body 形状错误）并描述"好感度按关键词 ±5"（实际为 `unified_state_agent` 的 LLM 分析）。`backend/CLAUDE.md` 已含完整准确的端点清单 —— DRY，删除而非重写。

- [ ] **Step 1: 确认无代码/其他文档引用该文件（删除前校验）**

```bash
grep -rn "接口文档" --include="*.py" --include="*.ts" --include="*.vue" --include="*.md" .
```

Expected: 命中点仅在文档自身（`backend/api接口文档.md:1`）+ 两处文档引用：
- `CLAUDE.md:150`
- `PROJECT_ANALYSIS.md:53` 与 `:96`

无 `.py`/`.ts`/`.vue` 引用 —— 说明无代码依赖，删除安全。（Task 4 会处理 PROJECT_ANALYSIS.md。）

- [ ] **Step 2: 删除过期文档**

```bash
git rm backend/api接口文档.md
```

Expected: `rm 'backend/api接口文档.md'`，文件进入暂存删除。

- [ ] **Step 3: 删掉根 `CLAUDE.md:150` 指向该文档的 Known Issues 条目**

把 `CLAUDE.md` Known Issues 节里的这一行整行删除：

```markdown
- `backend/api接口文档.md` documents endpoints that no longer exist in actual code - see `api.py` for the real list.
```

删除后该节其余条目（layered degradation / lazy imports / VITE_API_BASE / .env / Legacy agents）保持原样。

- [ ] **Step 4: 复跑后端测试，确认删除文档未破坏任何东西**

```bash
cd backend
python -m pytest -q 2>&1 | tail -5
echo "EXIT:${PIPESTATUS[0]}"
cd ..
```

Expected: `70 passed`，`EXIT:0`。测试从不依赖该文档，应保持全绿。

- [ ] **Step 5: 再次 grep，确认无残留引用**

```bash
grep -rn "接口文档" --include="*.py" --include="*.ts" --include="*.vue" --include="*.md" . | grep -v "PROJECT_ANALYSIS.md"
```

Expected: 无输出（PROJECT_ANALYSIS.md 的引用留到 Task 4 处理）。

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: 删除严重过时的 backend/api接口文档.md

该文档记了 6 个已删端点 + 错误的好感度算法，backend/CLAUDE.md 已有准确端点清单。
同步删除根 CLAUDE.md 指向它的 Known Issues 条目。
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: 更新 PROJECT_ANALYSIS.md，标注 P0 已清偿

**Files:**
- Modify: `PROJECT_ANALYSIS.md`（P0 表 + 「文档一致性状态」节 + 「短期推进」节）

> 分析文档应反映现状：P0 两条已清偿，避免后续读到的分析又把已完成项当成待办。

- [ ] **Step 1: P0 表两行加 ✅ 已清偿标记**

把「3. 技术债清单」下 P0 表的这两行：

```markdown
| `api接口文档.md` 严重过时 | `backend/api接口文档.md` | 误导新开发者 | 2h |
| 前端类型错误阻断CI | `front/CLAUDE.md` 已标记 | 类型债累积 | 4h |
```

替换为：

```markdown
| ✅ `api接口文档.md` 严重过时（已删） | `backend/api接口文档.md` | 已删除，改引 `backend/CLAUDE.md` 端点清单 | done |
| ✅ 前端 type-check CI 门（已恢复阻断） | `.github/workflows/ci.yml` | 移除 `continue-on-error`，过期类型债描述已清 | done |
```

- [ ] **Step 2: 「文档一致性状态」节把 backend 文档行从"需更新"改为"已处理"**

把该节「⚠️ 需要更新」下的：

```markdown
- `backend/api接口文档.md` - **严重过时，建议删除或重写**
```

替换为：

```markdown
- `backend/api接口文档.md` - ✅ 已删除（2026-07-17），端点清单以 `backend/CLAUDE.md` 为准
```

- [ ] **Step 3: 「短期推进」节第 1 项标注完成**

把「7. 后续推进方向 > 短期 (1-2周)」下的：

```markdown
1. **清偿P0技术债**
   - 删除/重写过时的API文档
   - 修复前端类型错误，恢复CI阻断
```

替换为：

```markdown
1. **✅ 清偿P0技术债（已完成 2026-07-17）**
   - ✅ 删除过时的 `backend/api接口文档.md`
   - ✅ 恢复前端 type-check 为 CI 阻断门（类型债在代码层早已还清，仅清过期配置/文档）
```

- [ ] **Step 4: 校验 PROJECT_ANALYSIS.md 内部无遗留"建议删除或重写"等矛盾措辞**

```bash
grep -n "建议删除或重写\|严重过时" PROJECT_ANALYSIS.md
```

Expected: 仅命中 Task 4 Step 2 改后的那行（含"✅ 已删除"），无其他"建议删除或重写"残留。

- [ ] **Step 5: Commit**

```bash
git add PROJECT_ANALYSIS.md
git commit -m "docs: PROJECT_ANALYSIS 标注 P0 技术债已清偿

api接口文档已删、type-check CI 门已恢复阻断，分析文档同步反映现状。
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 最终验收

- [ ] **全量复跑前后端验证**

```bash
cd backend && python -m pytest -q 2>&1 | tail -3; echo "BACKEND_EXIT:$?"; cd ..
cd front && node_modules/.bin/vue-tsc --build --force; echo "TYPECHECK_EXIT:$?"; npx vitest run 2>&1 | tail -3; cd ..
```

Expected: `70 passed` / `BACKEND_EXIT:0`；`TYPECHECK_EXIT:0`；vitest `4 passed`。

- [ ] **确认无残留过期引用**

```bash
grep -rn "接口文档" --include="*.py" --include="*.ts" --include="*.vue" --include="*.md" .
grep -rn "continue-on-error" .github/
```

Expected: 第一条仅命中 `PROJECT_ANALYSIS.md` 那行（已含 ✅ 已删除标记）；第二条无输出（ci.yml 已无 continue-on-error）。

- [ ] **确认文件已删除**

```bash
test ! -f backend/api接口文档.md && echo "DELETED OK" || echo "STILL EXISTS"
```

Expected: `DELETED OK`。

---

## Self-Review

**1. Spec coverage（对照用户诉求「先清偿 P0 技术债」与 PROJECT_ANALYSIS.md 的 P0 清单）：**
- P0-1 `api接口文档.md` 严重过时 → Task 3（删除）+ Task 4（文档同步）。✅
- P0-2 前端类型错误阻断 CI → Task 1（恢复阻断门）+ Task 2（清过期描述）+ Task 4（文档同步）。✅
- 注：经核验，"前端类型错误"在代码层已不存在，真正待还的债是 CI 的 `continue-on-error` 与过期文档描述 —— 已如实纳入 Task 1/2，未夸大为"修类型错误"。

**2. Placeholder scan：** 无 TBD/TODO/"添加适当错误处理"等占位。每个 step 含完整命令、完整替换前后文本、明确 expected。✅

**3. Type / 命名一致性：** 本计划无新增类型/函数/方法签名（纯文档与 CI 配置）。文件路径在各 Task 间一致：`backend/api接口文档.md`、`.github/workflows/ci.yml`、`front/CLAUDE.md`、根 `CLAUDE.md`、`PROJECT_ANALYSIS.md` 均统一。✅

**4. 提交粒度：** 四个 Task 各自独立 commit，符合「frequent commits」。Task 1（CI 门）与 Task 2（front 文档）虽都关于 type-check，但一个是配置一个是文档，分开提交便于回溯。✅

**5. Working Agreement 遵守：** 改 CI 配置 + 删文档属「改 Docker/nginx/CI 配置」与「目录布局」范畴，已同步改 `CLAUDE.md`/`front/CLAUDE.md`/`PROJECT_ANALYSIS.md`。✅
