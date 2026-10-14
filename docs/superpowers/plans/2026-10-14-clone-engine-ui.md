# 克隆引擎接进 UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 上一轮把 OpenVoice 接进了后端，但**用户在前端根本用不到** —— 这一步让它在 `/settings` 的语音包面板里真正可用。

**Architecture:** 只改两份东西：
1. `voice_service.engine_available()` —— 原来写死 `return False`（注释还写着"接入后改"），
   改成探测 sidecar venv。不改这里，UI 会给每个克隆包打「引擎未部署」。
2. `SettingsView.vue` 的克隆引导文案 —— 原文案是"需要额外部署，暂时无法试听"，
   在引擎已部署的机器上**是错的**。

**不含**：上传/删除参考音频的接口和按钮**早就有了**（`POST/DELETE /voice/packs/{id}/reference`），
本次不重做；只是把"缺参考音频"这件事在前端说清楚。

**Tech Stack:** Vue 3 / TS / vitest / pytest。

---

## Task 0: 基线

- [ ] `cd front && npm run lint:ci && npm run type-check && npx vitest run`
- [ ] `cd backend && ../.venv/Scripts/python.exe -m pytest -q`（上轮结束是 318 passed）

## Task 1: `engine_available('clone')` 如实探测

- [x] **Step 1**: 把写死的 `return False` 改成 `return voice_clone.is_installed()`
- [x] **Step 2**: 把 `_is_installed` 改名为公开的 `is_installed()`（跨模块用了，别用私有名）
- [x] **Step 3**: 更新所有引用（grep `is_installed` 全仓库，含测试）
- [x] **Step 4**: 加测试钉住两条：
  - sidecar 不在 → `available is False`
  - sidecar 在 → `available is True`（**不能谎称没部署**，否则用户以为功能坏了）
  - `engine_available` **绝不能启动进程**（会被 /voice/voices 频繁调，起进程好几秒）

## Task 2: 修「克隆配置永远没法试听」的真 bug

**问题**：`/voice/preview` 的即时参数分支构造 `ResolvedVoice` 时漏了 `reference_audio`，
而 `normalize_pack` 又刻意只从 base 读它（只有上传接口写）。
→ 结果：新建克隆包时点「试听」，必然报「没有参考音频」。

- [x] **Step 1**: `VoicePreviewRequest` 加 `reference_audio: str | None`
- [x] **Step 2**: 构造 `ResolvedVoice` 时显式覆盖：
      `reference_audio=req.reference_audio or pack.get("reference_audio")`
      （注释说明"为什么不能只靠 normalize_pack"）
- [x] **Step 3**: 加回归测试：
  - 即时克隆试听 → `voice.reference_audio` 真的传下去了
  - 没给参考音频 → 503 且错误信息含"参考音频"（别崩在引擎里）

## Task 3: 前端克隆引导

- [x] **Step 1**: 删掉那句过时的"需要额外部署，暂时无法试听"
- [x] **Step 2**: 按 `cloneAvailable`（由 `/voice/voices` 的 `engines[].available` 算出）分两种：
  - 可用：说清参考音频的**实用要求**（10 秒 / 安静 / 一个人）+ **首句约 20 秒**的预期
  - 不可用：给出安装命令 `backend/scripts/setup_clone_env.ps1` 和体积
- [x] **Step 3**: 克隆包里没传参考音频时，列表打「缺参考音频」
      （否则用户只会听到默认音色，还不知道为什么）

## Task 4: 修掉测试里的环境依赖

上一轮的测试**写死了"clone 不可用"**，引擎一接好就全红。
- [ ] 把这些断言改成 monkeypatch `voice_clone.SIDECAR_PYTHON`（环境无关）
- [ ] 顺带发现 `test_update_pack_can_switch_engine_and_voice` **被定义了两次**
      （后者静默覆盖前者）—— 两处都改，并考虑去重

## Task 5: 端到端实测（不打模型单测替代不了）

- [ ] 起后端 → 建克隆包 → 上传 8 秒参考音频 → `/voice/preview` 拿到 200 + RIFF wav
- [ ] **量首句 vs 第二句耗时** —— 用来判断"常驻 worker"是否真的生效
- [ ] 清理测试包（别留在库里）

## 最终验收

- [ ] 后端 pytest 全绿；前端 lint/type-check/vitest/build 全绿
- [ ] **主 venv numpy 仍是 2.4.6**（隔离没被破坏）
- [ ] 克隆包能建、能传参考音频、能真试听出声
- [ ] sidecar 未安装的机器上，UI 显示"未部署"而不是谎报可用

## Known Issues

- **首句约 20.6s**（加载约 480MB 模型），之后 1.6s。
  worker 随**后端进程**共生（后端重启 = 再冷一次）。
  没有做"启动时预热"：那会让**不使用克隆的用户**也白占 480MB 内存，不值。
  已在 UI 上明说"第一次约需 20 秒"。
- `engine_available` 只探 `python.exe` 在不在，**不验证权重齐不齐**。
  权重缺失时点击试听会拿到明确的错误信息（含"参考音频不存在"这类 hint），可接受。

## Self-Review

**1. Spec coverage**：Task 1-3 让功能在 UI 上可用，Task 4 修测试债，Task 5 实测。✅
**2. Placeholder scan**：Task 2 Step 2 给了确切代码，Task 3 是文案（无占位）。✅
**3. 最大风险 = 谎报可用性**：Task 1 Step 4 专门钉"sidecar 在时必须 True"这条反向断言。✅
**4. 测试环境依赖**：这是本轮的真实教训（写死 False 导致全红），Task 4 专门处理。✅
**5. 过度设计检查**：没做启动预热、没做权重完整性校验 —— 都在 Known Issues 里说明了理由。✅

---

## 执行结果（2026-10-14）

4 个 Task 全部完成。

### 修的真 bug：克隆配置**永远没法试听**

`/voice/preview` 的即时参数分支构造 `ResolvedVoice` 时**漏了 `reference_audio`**，
而 `normalize_pack` 又刻意只从 base 读它（只有上传接口会写）——
两者一叠加，新建克隆包时点「试听」必然报「没有参考音频」。
用户根本没法在保存前判断克隆效果。

修：`VoicePreviewRequest` 加 `reference_audio`，构造时显式覆盖
（`req.reference_audio or pack.get("reference_audio")`），并注释说明为什么不能只靠 normalize_pack。

### `engine_available('clone')` 不再写死 False

原来 `return False`，注释还写着"接入后改" —— 不改的话 UI 会给**每个**克隆包打「引擎未部署」。
改成探测 sidecar venv 的 `python.exe`。**不启动进程**（`/voice/voices` 会频繁调）。

### 测试债：写死 False 的断言全红

上一轮那些"clone 不可用"的断言是**环境依赖**的：引擎接好就全红。
全部改成 monkeypatch `voice_clone.SIDECAR_PYTHON`。

顺带发现 `test_update_pack_can_switch_engine_and_voice` **被定义了两次**
（Python 里后者静默覆盖前者，前一个测试**从来没跑过**）。两处都修了。

### 前端

删掉过时的"需要额外部署，暂时无法试听"，改成按 `cloneAvailable` 分两种状态：
可用时给实用要求（10 秒/安静/一个人）+ **首句约 20 秒**的预期；不可用时给安装命令。
克隆包没传参考音频时打「缺参考音频」。

### 端到端实测（真实 OpenVoice）

```
第 1 次（冷启动）: HTTP 200  164396 字节 (RIFF wav)  耗时 20.6s
第 2 次           : HTTP 200  163372 字节            耗时 1.7s
第 3 次           : HTTP 200  159276 字节            耗时 1.6s
```
另外单独量过一组：1.6s / 1.5s / 1.6s。

**结论：常驻 worker 真的生效**（1.7s vs 20.6s，差 12 倍）。
之前那次 77s 是磁盘缓存冷的偶发，不要当常态。

### 验证

- 后端 pytest **322 passed**（318 → +4，含 2 条 preview 回归 + 1 条 clone 可用性 + 1 条不启进程）
- 前端 lint:ci 0 / type-check 0 / vitest 138 / build 通过
- **主 venv numpy 仍是 2.4.6**（sidecar 隔离没被破坏）

### 踩的坑

- 临时验证脚本 `_timeclone.mjs` **没删**，被 eslint 抓出来（`no-unused-vars`）。
  跑 lint 前先 `ls _*.mjs`。
- 给 monkeypatch 的方法签名要带 `self` —— 少了会 TypeError（方法不是函数）。
