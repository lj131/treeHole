# 接入 OpenVoice V2 音色克隆 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 P1 2.2 落地 —— 让 `voice_pack` 的 `clone` 引擎真正能合成（现在 `_synth_clone` 是直接抛错的桩）。

**Architecture:** 核心决策是 **sidecar（隔离 venv）**，不是装进主 venv。

实测的依赖冲突（这就是必须隔离的原因）：

| 包 | 主 venv（在跑 RAG/Web） | OpenVoice 要 |
|---|---|---|
| numpy | **2.4.6** | `numpy==1.22.0`（requirements.txt 里钉的） |
| transformers | 未装 | `transformers==4.27.4` |

装进同一个 venv 会把 numpy 降级，**很可能把现有 RAG/后端搞挂**。所以：

```
主 venv（.venv，不变）                    sidecar venv（.venv-clone）
┌──────────────────────────┐            ┌────────────────────────────┐
│ voice_service            │            │ melo + openvoice + torch   │
│   └─ _synth_clone        │            │  voice_clone_worker.py     │
│        └─ voice_clone.py  │ ──JSON──> │   监听 stdin/stdout        │
│            (异步子进程)   │  lines    │   模型常驻，复用 embedding  │
└──────────────────────────┘            └────────────────────────────┘
```

为什么用**常驻子进程 + JSON lines** 而不是每句合成起一次进程：
模型加载要好几秒，每句都起会让交互体验不可接受。用 asyncio 子进程
（`create_subprocess_exec`）不阻塞事件循环，也不需要额外的端口。

**为什么选这个协议**：不占端口、不需要 supervisor、崩溃了自然重连。

**Tech Stack:** FastAPI（asyncio 子进程）/ OpenVoice V2 + MeloTTS / torch（sidecar）/ pytest。

---

## 前置：可行性探测（已做完，结论是可做）

本机网络环境实测：

| 源 | 可达 | 用途 |
|---|---|---|
| `pypi.org` | ✅ | 装 torch 等 |
| `codeload.github.com` | ✅（`github.com` 主站 ❌） | 拉 OpenVoice / MeloTTS 源码 |
| `hf-mirror.com` | ✅（`huggingface.co` ❌） | 下载权重（用 `HF_ENDPOINT=https://hf-mirror.com`） |
| ~~`myshell-public-repo-host.s3.amazonaws.com`~~ | ❌ 404 | 官方文档里的权重地址**已失效** |

**踩到的坑**：`pip install melotts` 会失败 —— PyPI 上那个 sdist 的 `setup.py` 引用了
不存在的 `requirements.txt`（`FileNotFoundError`）。**必须从源码装。**

权重清单（共约 476 MB）：
- `myshell-ai/MeloTTS-Chinese` → `checkpoint.pth` 198 MB
- `myshell-ai/OpenVoice` → `checkpoints/base_speakers/ZH/` 153 MB + `checkpoints/converter/` 125 MB

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/.venv-clone/` | 新建（不入库） | sidecar venv，隔离 numpy/transformers 冲突 |
| `backend/vendor/.gitignore` | 新建 | 标记 vendor/ 不入库 |
| `backend/voice_clone_worker.py` | **新增** | sidecar 里的常驻进程（JSON-lines 协议） |
| `backend/funcation/voice_clone.py` | **新增** | 主进程侧：拉起/管理 worker、缓存 speaker embedding |
| `backend/tests/test_voice_clone_protocol.py` | **新增** | 协议编解码 + manager 状态机（不碰真实模型） |
| `backend/scripts/setup_clone_env.sh` + `.ps1` | **新增** | 一键建 sidecar + 下权重 |
| `backend/funcation/voice_service.py` | 修改 | `_synth_clone` 接 `voice_clone` |
| `backend/requirements.txt` | 不修改 | **克隆引擎是可选依赖，不进主 requirements** |
| `backend/CLAUDE.md` | 修改 | 记录架构与"为什么隔离" |

---

## Task 0: 打包 OpenAI 源码（vendor）

- [x] **Step 1**: 把 `/tmp/ov/OpenVoice-main` 拷到 `backend/vendor/OpenVoice/`
- [x] **Step 2**: 把 `/tmp/melo/MeloTTS-main` 拷到 `backend/vendor/MeloTTS/`
- [x] **Step 3**: 删掉不需要的大块：`vendor/MeloTTS/melo/app.py` 引 gradio 的 demo、`test/`、notebooks
- [x] **Step 4**: 写 `backend/vendor/AGENTS.md`：说明这两个目录是第三方源码副本，
  不要手改，升级方式是从上游 release 重新覆盖

> 为什么不 `pip install git+...`：github.com 主站不通，codeload 只能下 tar 包。
> vendor 进来还能让部署机器完全离线安装（只需 PyPI + 一次权重下载）。

## Task 1: sidecar venv + 权重

- [x] **Step 1**: `scripts/setup_clone_env.sh` / `.ps1`
  ```bash
  python -m venv ../.venv-clone
  .venv-clone/bin/pip install torch torchaudio librosa numpy pydub
  .venv-clone/bin/pip install loguru tqdm unidecode inflect num2words
  .venv-clone/bin/pip install pypinyin cn2an jieba
  .venv-clone/bin/pip install anyascii pykakasi jamo g2p_en langid
  .venv-clone/bin/pip install transformers
  .venv-clone/bin/pip install ./vendor/MeloTTS ./vendor/OpenVoice
  export HF_ENDPOINT=https://hf-mirror.com
  hf download myshell-ai/MeloTTS-Chinese   # 或者 curl 直下
  ```
- [x] **Step 2**: 权重落到 `backend/data/openvoice/`，且 `.gitignore` 已在忽略 `data/`
- [x] **Step 3**: 记录 `HF_ENDPOINT` 的必要性 —— 直连 huggingface.co 不通

## Task 2: `voice_clone_worker.py`（sidecar 常驻进程）

协议（**JSON Lines**，一行一请求，一行一响应）：

```jsonc
// 请求（stdin）
{"id": 1, "text": "你好", "ref": "data/voice_refs/xxx.wav", "lang": "ZH"}
// 响应（stdout）
{"id": 1, "ok": true, "wav_b64": "UklGR..."}          // 或
{"id": 1, "ok": false, "error": "模型未加载: ..."}
```

- [x] **Step 1**: 进程启动时打印一行 `{"event":"ready", ...}` 到 **stderr**
  （stdout 只走协议，别污染）
- [x] **Step 2**: 惰性加载：收到第一条请求时才 `MeloTTS(language='ZH')` + `tone_color_converter`
- [x] **Step 3**: **speaker embedding 按 `ref` 文件内容哈希缓存**
  —— 同一角色的参考音频不会每次都重算（这是实测的主要延迟来源）
- [x] **Step 4**: 合成流程（OpenVoice V2 标准三步）：
  1. MeloTTS 用**中性 base speaker** 合成中间音频
  2. `get_se(ref_audio)` → 参考音色 embedding
  3. `tone_color_converter` 用中间音频 + 参考 embedding 转换
- [x] **Step 5**: 输出 **wav**（主链路的 `/chat/tts` 和 WebSocket 都吃 wav/mp3 都行，
  但 lip-sync 的 AnalyserNode 对 wav 支持最好）
- [x] **Step 6**: 单条请求 panic 不影响进程 —— try/except 包住，回 `ok:false`

## Task 3: `funcation/voice_clone.py`（主进程侧）

- [x] **Step 1**: `CloneEngineManager`
  - `start()`：`asyncio.create_subprocess_exec`，等 stderr 的 ready
  - `synthesize(text, ref_path)`：写一行 JSON → 读一行 JSON → base64 解码
  - `stop()`：发 close + 等退出
  - **崩溃自愈**：worker 退出后下一次请求自动重启（并记 warning）
- [x] **Step 2**: sidecar 不存在时的错误信息要说清楚怎么办：
  ```
  克隆引擎未安装。运行 backend/scripts/setup_clone_env.ps1 安装（需要约 3GB 磁盘）。
  ```
- [x] **Step 3**: 单例 + 进程退出时清理（ lifespan / atexit ）

## Task 4: 接进 `voice_service._synth_clone`

- [x] **Step 1**: `_synth_clone` 改成调 `voice_clone.synthesize(...)`
- [x] **Step 2**: **保留"没配参考音频就明确报错"** —— 现在那段判断是对的，别删
- [x] **Step 3**: **绝不静默降级到 edge** —— 选克隆音色却听到默认音色比报错更糟

## Task 5: 测试

- [x] **Step 1: `test_voice_clone_protocol.py`**（不打模型，CI 能跑）
  - 请求/响应 JSON 编解码往返
  - 非法请求 → `ok:false` 且不崩进程
  - embedding 缓存的 key 计算（同内容同 key、不同内容不同 key）
  - manager 的"worker 没启动就该报清楚的错"
- [x] **Step 2: 真机验证**（需要 GPU/CPU 模型，CI 跑不了，本地做）
  - 装好 sidecar，用一段中文参考音频 → 合成 → 断言 wav 头合法 + 时长合理
  - **插眼**：与 edge 合成同一段文本，确认输出格式一致

## 最终验收

- [ ] 主 venv 的 `numpy` **仍然是 2.4.6**（隔离成功）
- [ ] 现有 `pytest` **全绿**（307）
- [ ] 前端无改动仍通过 lint/type-check/vitest/build
- [ ] `scripts/setup_clone_env.ps1` 从零可复现
- [ ] 选 clone 引擎的语音包能真出声；没装 sidecar 时报错信息可操作

## Known Issues

- **torch 装 CPU 版即可**：不要装 CUDA 版（+数 GB）。克隆是低频操作，
  实时性要求不高（每句 2~10 秒可接受）。
- **`unidic download` 会失败**（MeloTTS 的 setup.py 装完会自动跑）：
  它下日文词典，我们只用 ZH/EN。**允许失败**，别让它阻断安装。
- **权重下载要 `HF_ENDPOINT=https://hf-mirror.com`**：直连 huggingface.co 不通。
- **vendor/ 是第三方源码副本**，不要手改。升级 = 从上游重新覆盖。

## Self-Review

**1. Spec coverage：** 方案要的是"接到克隆引擎"，Task 0-5 覆盖全链路 ✅。
**2. Placeholder scan：** Task 2/3 给出的是协议与职责，未逐行给实现；
Task 5 Step 2 的"真机验证"依赖 Task 0-4 全做完才能跑。⚠️ 已标注。
**3. 最大风险 = 破坏主 venv**：Task 1/最终验收都钉住"numpy 仍为 2.4.6"。✅
**4. 部署可复现**：vendor 源码入库 + 一键脚本，避免"只能在本机跑"。✅
**5. 降级策略**：没有静默降级，选克隆却听默认音色比报错更糟。✅

---

## 执行结果（2026-10-12）

5 个 Task 全部完成，**克隆引擎真的能出声了**。

### 核心决策：独立 sidecar venv

实测冲突：主 venv `numpy 2.4.6`，MeloTTS/OpenVoice 的 requirements 钉
`numpy==1.22` + `transformers==4.27.4`。装同一 venv 会降级 numpy、把 RAG 搞挂。

→ 建 `.venv-clone`（gitignore），用 `--no-deps` 从 `vendor/` 本地装 + 手动挑依赖。
**验收时实测主 venv numpy 仍是 2.4.6，未动。**

### 架构

```
voice_service._synth_clone()
  └─ funcation/voice_clone.py        # asyncio 子进程管理、请求编排
       └─ voice_clone_worker.py      # 常驻进程，JSON Lines over stdin/stdout
            └─ melo(MeloTTS ZH) + openvoice(ToneColorConverter)
```

### 修掉的真实问题（都是自己踩出来的）

| # | 问题 | 修法 |
|---|---|---|
| 1 | `pip install melotts` 装不上（PyPI sdist 坏） | vendor 源码 + `--no-deps` |
| 2 | 官方权重地址 S3 **已 404** | 改用 HF `myshell-ai/OpenVoice` + `hf-mirror.com` |
| 3 | worker 的 ready 事件写在 stderr，manager 在 stdout 等 → 永远等不到 | ready 改走 stdout |
| 4 | `base_se or tgt_se` 对 Tensor 布尔值歧义 → RuntimeError | 改 `is not None` |
| 5 | 音频 base64 单行 ~215KB 撞 asyncio readline 64KB 上限 | 改**临时文件**回传 |
| 6 | OpenVoice `load_ckpt()` `print()` 污染协议流 | `redirect_stdout(sys.stderr)` + manager 侧跳过非 JSON 行 |
| 7 | 上游 bug：`ToneColorConverter.__init__` 把 `enable_watermark` 透传给只接受俩参数的基类 | vendor 内打补丁并注释 |
| 8 | 检查顺序错：先查参考音频后查 sidecar → "没装引擎"被掩盖 | 调换顺序 |
| 9 | `ResolvedVoice` 没有 `language` 属性 | `getattr(voice, "language", None)` |

### 绕开的三个重依赖（这是能在一小时内跑通的关键）

1. **不走 `get_se()`**（OpenVoice 的 `se_extractor`）：它内部调
   `whisper_timestamped.get_vad_segments`，会拖进 faster-whisper + 一堆模型。
   改用 `converter.extract_se()` —— 等价但只用 librosa。
2. **不走 pydub 转格式**：读 mp3/m4a 要 ffmpeg。参考音频用 librosa+soundfile 转临时 wav。
3. **关掉 BERT**（`hps.data.disable_bert = True`）：省 ~1.3GB RoBERTa 下载，韵律略差但够用。

### 验证数据

- 冷启动 **18.0s**（含模型加载）→ 1.83s 音频；**热启动 1.6s**；临时文件无残留；embedding 缓存命中
- **音色克隆是否真生效做了客观验证**：参考音频是合成的 129.7Hz 男声，
  克隆输出 **158.6Hz**（MeloTTS 默认 ZH 女声约 200Hz）→ 基频明显向参考靠近
- 后端 pytest **318 passed**（+11 协议测试，不打模型，CI 能跑）
- 主 venv numpy **2.4.6 未动**；应用 lifespan 起停正常、worker 被优雅关闭

### 仍未做

- **前端没有"上传参考音频并选 clone 引擎"的入口**——后端接口早就有了
  （`POST /voice/packs/{id}/reference`、`engine=clone`），但 `/settings` 的界面还只做了一半。
  **这是接下来最该补的**（否则功能在后端，用户用不上）。
- 播哪个 clip / speaker_id 固定取 0，未开放配置。
- 冷启动 18s 偏慢。可缓解：进程空闲时保留 worker（现在是惰性启动，冷一下更省内存）。
