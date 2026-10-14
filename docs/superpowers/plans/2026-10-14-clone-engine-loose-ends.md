# 克隆引擎的两个尾巴 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收掉上一轮留的两个尾巴：① `speaker_id` 固定取 0；② worker 随后端进程共生。

**Architecture:** 两个尾巴的处理方式**都和原设想不同** —— 查下去发现原设想的前提有问题。

---

## Task A: speaker_id —— 不是"加选择器"，是"默认值一直是错的"

**原设想**：给个下拉框让用户选说话人。

**查下去发现**：ZH 模型的配置是

```json
"n_speakers": 256,      ← 架构上的槽位数
"spk2id": {"ZH": 1}     ← 实际只训练了 1 个，id 是 1
```

- 256 个槽位里**只有 id=1 是训练过的**，其余喂进去**产出全静音**（实测 peak=0.0001）
- 官方用法是 `model.tts_to_file(text, spk2id['ZH'], ...)` —— 跟着 `spk2id` 走
- **而我们把默认写死成 0** → 合成"成功"返回一个静音 wav

**所以真正的任务是修默认值，不是加选择器**。给 256 个未训练槽位做下拉只会让用户选到静音。

- [x] **Step 1**: worker 从 `hps.data.spk2id` 读说话人表，不再硬编码
- [x] **Step 2**: `_default_speaker_id()` / `_speaker_count()` 基于 `spk2id`（不是 `n_speakers`）
- [x] **Step 3**: `_resolve_speaker_id()` 把未训练的 id 回退到已训练的那个（并告警）
- [x] **Step 4**: `op: "speakers"` 返回**已训练**的表（不是 256 个槽位）
- [x] **Step 5**: 测试钉住"默认必须来自 spk2id"+"越界回退"+"合法值原样透传"

**顺带发现的第三个问题**：输出响度只有 **-43 dBFS**，比 edge-tts 小 20 多 dB。
（之前没发现是因为一直在听静音/没量过电平。）

- [x] **Step 6**: 加 RMS 归一化到约 -20 dBFS，带增益上限和峰值保护

## Task B: worker 脱离后端 —— 真凶不是 Job Object

**原设想**：改成守护进程（socket + pidfile），后端重启后重连。

**查下去发现**（三步定位）：

1. 先以为上层 Job Object 连坐 → 加 `CREATE_BREAKAWAY_FROM_JOB`（实测该 flag 能成功）
2. 换命令再查进程 → **还是死**
3. 最后定位到真凶：**`asyncio.create_subprocess_exec` 的 transport
   在事件循环关闭时会 kill 子进程** —— 父进程一退出 worker 就死，跟 Job 无关

- [x] **Step 1**: worker 加 `--daemon`（绑 127.0.0.1 随机端口，写 `worker.json`）
- [x] **Step 2**: 管理器改成"**先找活着的 worker，找不到再拉起**"
- [x] **Step 3**: **守护进程改用普通 `subprocess.Popen` 启动**（关键修复）
- [x] **Step 4**: `stop()` **只断连、不杀 worker**；`shutdown_worker()` 才是真停
- [x] **Step 5**: 空闲自退（`VOICE_CLONE_IDLE_EXIT`，默认 20 分钟）
- [x] **Step 6**: `scripts/stop_clone_worker.py` 显式停止入口
- [x] **Step 7**: 测试钉住"`stop()` 不杀进程"+"必须用 Popen 不是 asyncio transport"

## Task C: 顺带修的健壮性

- [ ] `os.remove` 在本环境会被 CLI shim 拦（还可能抛 `SystemExit`，`except Exception` 接不住）
      → `_try_remove()` best-effort + `sweep_stale_wavs()` 兜底
- [ ] `shutdown` 之前只是抛异常，主循环不退出（异常在 asyncio 内部 task 里没人接）
      → 改用 `asyncio.Event`

## 最终验收

- [ ] 克隆输出**真的有声音**（量 peak/rms，不能只看 HTTP 200 + 文件大小）
- [ ] 后端 pytest 全绿；主 venv numpy 仍是 2.4.6
- [ ] 优雅重启后首句明显快于冷启动

## Known Issues

- **沙箱内无法演示"跨命令存活"**：本工具的命令级 Job 会回收所有进程，
  所以"杀掉后端再起一个"的验证在这里做不了（见执行结果）。
  但 `asyncio transport kill` 那个真 bug 是**验证过修好了**的。
- **改了 worker 代码必须重启 worker** —— 它是常驻进程，不会自动重载。
  用 `scripts/stop_clone_worker.py`。
- `engine_available` 只探 python.exe，不校验权重完整性。

## Self-Review

**1. Spec coverage**：两个尾巴都有对应 Task，且都记录了"原设想 vs 实际"的差异。✅
**2. Placeholder scan**：无占位，每条都有确切的文件/函数。✅
**3. 最大风险 = 假验证**：上一轮"HTTP 200 + 164KB"就当成通过了，实际是全静音。
  本轮把"量 peak/rms"写成硬性验收项，并加了测试。✅
**4. 环境限制如实记录**：Task B 里做不到的部分写进 Known Issues，不含糊。✅
**5. 过度设计检查**：没给 256 个未训练槽位做 UI；没做启动预热。✅

---

## 执行结果（2026-10-14）

三个 Task 全部完成。**并且要更正上一轮的一个错误结论。**

### ⚠️ 更正：上一轮说"端到端验证通过"是错的

上一轮我报告的验证是：

```
第 1 次（冷启动）: HTTP 200  164396 字节 (RIFF wav)  20.6s
```

**那 164KB 是全静音**（peak=0.0001）。我只验了 HTTP 状态码、RIFF 头、文件大小 ——
**没有量波形**。文件名 `clone-e2e-preview.wav` 现在还在，可以直接复现这个结论。

根因就是 Task A 那个默认值 bug：`speaker_id=0` 是未训练的槽位。

**教训**：验音频必须量 peak/rms。`HTTP 200 + 文件够大` 完全不能证明"有声音"。

### Task A 的结论：不是加选择器，是修默认值

`spk2id = {"ZH": 1}` —— 256 个槽位只有 1 个训练过。加 256 选一的下拉是**有害的**
（用户会选到静音）。真正要做的是把默认从写死的 0 改成从 `spk2id` 读。

实测（同一段文本，`_verify_sound.py`）：

| 传入 speaker_id | 实际使用 | 结果 |
|---|---|---|
| 不传 | 1 | ✅ peak=0.0515 |
| 0（旧默认） | 1（回退+告警） | ✅ peak=0.0704 |
| 1 | 1 | ✅ peak=0.0556 |
| 99 | 1（回退+告警） | ✅ peak=0.0465 |

**修复前**：speaker_id=0 → peak=0.0001（静音）。

### 顺带修了响度

实测克隆输出只有 **-43 dBFS**，比 edge-tts 小 20 多 dB（用户会觉得"克隆的声音特别小"）。
加了 RMS 归一化（目标 -20 dBFS，增益上限 +26dB，峰值保护）：

| | rms | dBFS |
|---|---|---|
| 归一化前 | 0.0071 | -42.9 |
| 归一化后 | 0.0772~0.1000 | **-22.3 ~ -20.0** |

### Task B 的结论：真凶不是 Job Object

三步定位：

1. 先以为是上层 Job Object 连坐 → 加 `CREATE_BREAKAWAY_FROM_JOB`
   （**实测该 flag 能成功**，不是被拒绝）
2. 换一条命令再查进程 → **还是死**
3. 定位到真凶：**`asyncio.create_subprocess_exec` 的 transport 在事件循环关闭时会 kill 子进程**

**修法**：守护进程改用**普通 `subprocess.Popen`** 启动。
它走 socket，本来就不需要 asyncio 的管道管理，用 Popen 反而干净。
`asyncio.to_thread(subprocess.Popen, ...)` 不阻塞事件循环。

**验证**（同一命令内，父进程 exit 后立刻探测）：

- 修复前：`❌ worker 已死: ConnectionRefusedError`
- 修复后：`✅ worker 存活: {"id":1,"ok":true,...}`

**做不到的部分（如实记录）**：本工具的**命令级 Job 会回收所有进程**，
所以"起后端 A → 结束 → 起后端 B"这种跨命令的验证在这里做不出来
（实测：即使带 BREAKAWAY，换命令后进程也没了）。
在用户自己的终端 / systemd / docker 里没有这层限制。

**自愈验证**（这个是能做到的）：端点文件指向一个已死进程时，
管理器 4.6s 内检测到并拉起新 worker。

### Task C：两个健壮性修复

- `os.remove` 被 CLI shim 拦（还可能抛 `SystemExit` —— 继承 `BaseException`，
  `except Exception` 接不住）→ `_try_remove()` best-effort + `sweep_stale_wavs()` 兜底
- `shutdown` 原来只是抛异常，异常在 asyncio 内部 task 里没人接 → **主循环不退出**
  （实测端点文件残留）→ 改用 `asyncio.Event`

### 验证

- 后端 pytest **337 passed**（322 → +15）
- 主 venv numpy **仍是 2.4.6**
- 端到端（HTTP API）：`verified.wav` 1.00s，peak=0.402，rms=0.0772（-22.3 dBFS）✅
- `scripts/stop_clone_worker.py` 可用

### 踩的坑

- **验证音频只看文件大小**（上一轮），这次把"量 peak/rms"写成硬性验收
- `asyncio.create_subprocess_exec` 会在事件循环关闭时杀子进程（本轮最大发现）
- `inspect.getsource` 做断言时，docstring 里的名字也会被算进去
- 测试文件缺 `import sys` / `os` 这种低级错误，跑一次就暴露
