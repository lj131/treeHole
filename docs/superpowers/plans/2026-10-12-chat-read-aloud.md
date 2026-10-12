# 聊天页朗读开关 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户在**聊天页**能听到角色说话 —— 新增「自动朗读」开关（新回复自动播）和每条消息的「朗读」按钮，走角色绑定的语音包。

**Architecture:** 现在 TTS **只存在于语音通话里**（`conversation_manager.process_tts_queue` → `voice_service.synthesize_speech` → WebSocket 下发 base64）。聊天页打字永远听不到声音 —— 而这才是主场景，刚做完的语音包（音色/语速/参考音频/每角色绑定）在文本聊天里**完全用不上**。

本次补上这条链路：

```
聊天页点朗读 / 自动朗读
  → POST /chat/tts {text, character_id}        ← 新增（普通用户可用，不是管理员）
  → voice_service.synthesize_speech(text, cid) ← 复用：自动按角色解析语音包 + 命中缓存
  → audio/mpeg 字节
  → playTtsBlob(blob)                          ← 新增，复用既有播放/lip-sync 通道
  → 3D 嘴型自动跟着动（CharacterPortrait3D 已订阅 subscribeTtsLipSync）
```

**关键约束：不做静默降级。** 合成失败就明确报错，**绝不偷偷用别的音色顶替** —— 与语音包那条「引擎可插拔但不静默降级」的原则一致（用户配了克隆音色却听到别人的声音，比报错更糟）。

**Tech Stack:** FastAPI / edge-tts / Web Audio API / Vue 3 + Pinia / vitest / Playwright。

---

## ⚠️ 执行前的阻塞项（已实测确认）—— ✅ 已于同日解决

> **结论先行**：真因是**微软把合成后端迁到新主机、并按地区分批切换**（2026-10 起，
> 10-12 轮到美国），而 edge-tts 7.2.8（当前最新版）仍指向旧主机。
> 已按上游 PR #491 的修法加 `funcation/edge_tts_compat.py`，把合成端点切到
> `api.msedgeservices.com`。**实测 `/chat/tts` 已能返回 4 秒真实 MP3**，
> 语音通话走同一条 `synthesize_speech()`，一并恢复。下面的排查记录保留作背景。

**当时的现象**：edge-tts 的合成端点返回 403，TTS 整体不可用。这不是本仓库的问题，也不是本机网络问题：

| 检查项 | 结果 |
|---|---|
| 系统时钟偏差 | **-0.21 秒**（正常，排除 token 时间戳失效） |
| edge-tts 版本 | **7.2.8 = 最新版**（`pip index versions` 确认，无升级空间） |
| 走代理 / 彻底绕过代理（`trust_env=False`） | **都是 403**（排除代理） |
| 音色列表端点（HTTPS） | **正常，322 个音色**（排除 IP/区域封锁） |
| 合成端点（WSS 握手） | **403 Invalid response status** |
| 换 `Sec-MS-GEC-Version`（143/144/145/146/140） | 全部 403 |
| 换 User-Agent / 去掉 Origin | 全部 403 |

结论：**不是鉴权校验变了**（当时这么以为，后来查到上游 PR #491 才知道）
—— 是**微软把合成后端迁到了新主机 `api.msedgeservices.com`，按地区分批切换**，
旧主机 `speech.platform.bing.com` 对合成一律返回 403，但**仍在正常提供音色列表**
（所以 HTTPS 端点正常、WSS 端点 403 —— 这个反差是当时最大的误导）。
edge-tts 最新版尚未跟上，已在本仓库加兼容层修复。
**影响面**：不只是本功能 —— **语音通话的 TTS 现在也是坏的**（同一条 `_synth_edge` 链路），角色在通话里只会"张嘴不出声"。

**因此本计划的做法**：功能照做（代码正确、与具体引擎无关），用 **mock 合成 + 真实音频文件**做端到端验证，
不依赖 edge-tts 恢复。**live 验证留待上游修复。**

## 前置基线

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest -q     # 246 passed
cd front && npx vue-tsc --noEmit -p tsconfig.app.json && npx vitest run   # exit 0 / 122 passed
```

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/funcation/voice_pack.py` | 修改 | 加 `MAX_SYNTH_CHARS` 常量（语音域的长度上限） |
| `backend/api/api.py` | 修改 | 新增 `POST /chat/tts` |
| `backend/tests/test_chat_tts_api.py` | **新增** | 端点测试（mock 合成，不打网络） |
| `front/src/utils/readAloud.ts` | **新增** | 朗读设置的读写 + **给 TTS 用的文本清洗**（纯函数） |
| `front/src/utils/__tests__/readAloud.spec.ts` | **新增** | 上述纯函数单测 |
| `front/src/services/webrtcService.ts` | 修改 | 抽出 `playTtsBuffer()`；新增 `playTtsBlob()` |
| `front/src/api/chat.ts` | 修改 | 新增 `synthesizeSpeech()`（收 Blob） |
| `front/src/views/Chat.vue` | 修改 | 头部「自动朗读」开关 + 每条消息「朗读」按钮 + 播放态 |

---

## Task 1: 后端 `POST /chat/tts`

**Files:**
- Modify: `backend/funcation/voice_pack.py`、`backend/api/api.py`
- Test: `backend/tests/test_chat_tts_api.py`

- [x] **Step 1: 写失败测试**

新建 `backend/tests/test_chat_tts_api.py`：

```python
"""聊天页朗读：POST /chat/tts。

合成的真实实现要打 edge-tts 云端，所以这里全部 mock —— 单测不该依赖网络。
"""
import uuid

import pytest


def _unique(prefix="user"):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def admin_token(client):
    r = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture
def user_headers(client, admin_token):
    """已审批的**普通用户** —— 朗读是用户功能，不是管理员功能"""
    name = _unique()
    pwd = "pass1234"
    reg = client.post("/auth/register", json={"username": name, "password": pwd})
    assert reg.status_code == 200, reg.text
    uid = reg.json()["user"]["id"]
    client.post(f"/auth/admin/approve/{uid}",
                headers={"Authorization": f"Bearer {admin_token}"})
    lg = client.post("/auth/login", json={"username": name, "password": pwd})
    return {"Authorization": f"Bearer {lg.json()['token']}"}


@pytest.fixture
def fake_synth(monkeypatch):
    """把真实合成换掉，记录收到的参数"""
    from funcation.voice_service import voice_service

    calls = []

    async def _fake(text, character_id, config=None):
        calls.append({"text": text, "character_id": character_id})
        return b"ID3fake-mp3"

    monkeypatch.setattr(voice_service, "synthesize_speech", _fake)
    return calls


def test_tts_returns_audio(client, tmp_data_dir, user_headers, fake_synth):
    r = client.post("/chat/tts", json={"text": "你好呀"}, headers=user_headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("audio/")
    assert r.content == b"ID3fake-mp3"


def test_tts_uses_current_character_when_not_given(client, tmp_data_dir, user_headers, fake_synth):
    client.post("/chat/tts", json={"text": "你好呀"}, headers=user_headers)
    assert fake_synth[0]["character_id"], "没传 character_id 时要落到当前角色"


def test_tts_respects_explicit_character(client, tmp_data_dir, user_headers, fake_synth):
    client.post("/chat/tts", json={"text": "你好呀", "character_id": "maid"}, headers=user_headers)
    assert fake_synth[0]["character_id"] == "maid"


def test_tts_rejects_empty_text(client, tmp_data_dir, user_headers, fake_synth):
    r = client.post("/chat/tts", json={"text": "   "}, headers=user_headers)
    assert r.status_code == 400, r.text
    assert not fake_synth, "空文本不该触发合成"


def test_tts_rejects_overlong_text(client, tmp_data_dir, user_headers, fake_synth):
    from funcation import voice_pack

    r = client.post("/chat/tts", json={"text": "啊" * (voice_pack.MAX_SYNTH_CHARS + 1)},
                    headers=user_headers)
    assert r.status_code == 400, r.text
    assert str(voice_pack.MAX_SYNTH_CHARS) in r.json()["detail"]


def test_tts_engine_failure_returns_503(client, tmp_data_dir, user_headers, monkeypatch):
    """引擎不可用要明确报错 —— 不能返回一段静音让人以为成功了"""
    from funcation.voice_service import TTSEngineError, voice_service

    async def _boom(text, character_id, config=None):
        raise TTSEngineError("edge-tts 合成失败")

    monkeypatch.setattr(voice_service, "synthesize_speech", _boom)
    r = client.post("/chat/tts", json={"text": "你好"}, headers=user_headers)
    assert r.status_code == 503, r.text
    assert "edge-tts" in r.json()["detail"]


def test_tts_requires_auth(client, tmp_data_dir):
    r = client.post("/chat/tts", json={"text": "你好"})
    assert r.status_code in (401, 403), r.text
```

- [x] **Step 2: 跑测试确认 FAIL**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_chat_tts_api.py -q
```

Expected: FAIL（404，路由不存在）。

- [x] **Step 3: 加长度上限常量**

`backend/funcation/voice_pack.py` 的限额区加：

```python
# 单次合成的文本上限。TTS 耗时随文本线性增长，太长的回复既慢又占缓存；
# 前端会先按这个上限截断，后端再兜一次。
MAX_SYNTH_CHARS = 600
```

- [x] **Step 4: 实现端点**

`backend/api/api.py` 末尾加：

```python
# ============================================================
# 聊天页朗读（TTS）
#
# 语音通话之外的第二条 TTS 链路：让文本聊天也能听到角色的声音。
# 与 /voice/preview 的区别：
# - 这是**普通用户功能**（require_approved），不是管理员功能；
# - 不接收音色参数，而是按角色解析绑定的语音包 —— 这正是语音包在主场景生效的地方。
# ============================================================


class ChatTtsRequest(BaseModel):
    text: str
    character_id: str | None = None


@app.post("/chat/tts")
async def chat_tts(req: ChatTtsRequest, user = Depends(require_approved)):
    """把一段文本合成为当前角色音色的语音，直接返回音频字节。

    复用 `voice_service.synthesize_speech()`：它已经按角色解析语音包（绑定的包 →
    旧的写死映射 → 全局兜底）并按「角色+文本+音色指纹」缓存，所以重复朗读同一句
    不会重复打云端。
    """
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本不能为空")
    if len(text) > voice_pack.MAX_SYNTH_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"文本过长（上限 {voice_pack.MAX_SYNTH_CHARS} 字），请分段朗读",
        )

    # 默认用当前角色；显式传了就校验访问权限（内置角色所有人可用）
    character = _load_owned_character(user, req.character_id)
    character_id = character.get("id")

    try:
        audio = await voice_service.synthesize_speech(text=text, character_id=character_id)
    except TTSEngineError as e:
        # 引擎不可用（未部署/上游故障）→ 明确告诉调用方，绝不返回静音
        raise HTTPException(status_code=503, detail=str(e))

    return Response(content=audio, media_type="audio/mpeg")
```

- [x] **Step 5: 跑测试确认 PASS**

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_chat_tts_api.py -q
```

Expected: 7 passed。

---

## Task 2: 前端文本清洗与设置（纯函数）

**Files:**
- Create: `front/src/utils/readAloud.ts`、`front/src/utils/__tests__/readAloud.spec.ts`

**为什么要清洗文本**：角色回复是 Markdown（`**强调**`、`# 标题`、`` `代码` ``、链接），
直接丢给 TTS 会念出"星号""井号""左括号"。

- [x] **Step 1: 写失败测试**

新建 `front/src/utils/__tests__/readAloud.spec.ts`：

```ts
import { describe, it, expect, beforeEach } from 'vitest'
import { cleanTextForSpeech, truncateForSpeech, isReadAloudEnabled, setReadAloudEnabled } from '@/utils/readAloud'

describe('cleanTextForSpeech', () => {
  it('去掉 markdown 强调符号，别念出"星号"', () => {
    expect(cleanTextForSpeech('**你好**呀')).toBe('你好呀')
    expect(cleanTextForSpeech('这是*重点*')).toBe('这是重点')
  })

  it('去掉标题井号与列表符号', () => {
    expect(cleanTextForSpeech('## 标题')).toBe('标题')
    expect(cleanTextForSpeech('- 第一项')).toBe('第一项')
  })

  it('去掉行内代码反引号但保留内容', () => {
    expect(cleanTextForSpeech('运行 `npm test` 即可')).toBe('运行 npm test 即可')
  })

  it('链接只保留可读文字，不念 URL', () => {
    expect(cleanTextForSpeech('见[文档](https://example.com/a/b)')).toBe('见文档')
  })

  it('表情符号不念', () => {
    expect(cleanTextForSpeech('好开心 😊🎉')).toBe('好开心')
  })

  it('压缩多余空白与换行', () => {
    expect(cleanTextForSpeech('第一行\n\n第二行   结束')).toBe('第一行 第二行 结束')
  })

  it('空输入返回空串，不抛异常', () => {
    expect(cleanTextForSpeech('')).toBe('')
    expect(cleanTextForSpeech('   ')).toBe('')
    expect(cleanTextForSpeech('***')).toBe('')
  })
})

describe('truncateForSpeech', () => {
  it('不超上限时原样返回', () => {
    expect(truncateForSpeech('短句', 10)).toBe('短句')
  })

  it('超上限时截断并在句末收尾', () => {
    const out = truncateForSpeech('第一句。第二句。第三句。', 8)
    expect(out.length).toBeLessThanOrEqual(8)
    expect(out.endsWith('。')).toBe(true)
  })

  it('没有句读时硬截断', () => {
    expect(truncateForSpeech('啊'.repeat(20), 5)).toHaveLength(5)
  })
})

describe('朗读开关持久化', () => {
  beforeEach(() => localStorage.clear())

  it('默认关闭', () => {
    expect(isReadAloudEnabled()).toBe(false)
  })

  it('能存能读', () => {
    setReadAloudEnabled(true)
    expect(isReadAloudEnabled()).toBe(true)
    setReadAloudEnabled(false)
    expect(isReadAloudEnabled()).toBe(false)
  })
})
```

- [x] **Step 2: 跑测试确认 FAIL**

```bash
cd front && npx vitest run src/utils/__tests__/readAloud.spec.ts
```

Expected: FAIL（模块不存在）。

- [x] **Step 3: 实现**

新建 `front/src/utils/readAloud.ts`：

```ts
/**
 * 聊天页朗读：设置持久化 + 给 TTS 用的文本清洗。
 *
 * 清洗是必要的：角色回复是 Markdown，直接合成会念出"星号""井号""左括号 http…"。
 */
import { MAX_SYNTH_CHARS } from '@/types/constants'   // 若没有该文件，见下方说明

const READ_ALOUD_KEY = 'chat_read_aloud_enabled'

/** 表情符号（含常见符号区 + 补充平面）—— TTS 念不出来，只会变成怪停顿 */
const EMOJI_RE = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}\u{2190}-\u{21FF}\u{2B00}-\u{2BFF}]/gu

export function cleanTextForSpeech(raw: string): string {
  if (!raw) return ''
  let text = raw

  // 代码块整体去掉（念代码没有意义），行内代码只去反引号保留内容
  text = text.replace(/```[\s\S]*?```/g, ' ')
  text = text.replace(/`([^`]*)`/g, '$1')
  // 图片整段去掉；链接只保留文字
  text = text.replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
  text = text.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
  // 标题 / 引用 / 列表符号
  text = text.replace(/^\s{0,3}#{1,6}\s*/gm, '')
  text = text.replace(/^\s{0,3}>\s?/gm, '')
  text = text.replace(/^\s{0,3}[-*+]\s+/gm, '')
  text = text.replace(/^\s{0,3}\d+\.\s+/gm, '')
  // 强调与删除线
  text = text.replace(/(\*\*|__)(.*?)\1/g, '$2')
  text = text.replace(/(\*|_)(.*?)\1/g, '$2')
  text = text.replace(/~~(.*?)~~/g, '$1')
  // 分隔线
  text = text.replace(/^\s{0,3}([-*_]\s*){3,}$/gm, ' ')
  // 表情
  text = text.replace(EMOJI_RE, '')
  // 空白归一
  return text.replace(/\s+/g, ' ').trim()
}

/**
 * 按上限截断，尽量在句末收尾（半句话听起来像被打断）。
 */
export function truncateForSpeech(text: string, limit: number = MAX_SYNTH_CHARS): string {
  if (text.length <= limit) return text
  const head = text.slice(0, limit)
  const lastStop = Math.max(
    head.lastIndexOf('。'), head.lastIndexOf('！'),
    head.lastIndexOf('？'), head.lastIndexOf('.'), head.lastIndexOf('!'),
  )
  return lastStop > 0 ? head.slice(0, lastStop + 1) : head
}

export function isReadAloudEnabled(): boolean {
  try {
    return localStorage.getItem(READ_ALOUD_KEY) === 'true'
  } catch {
    return false   // localStorage 不可用（隐私模式）→ 退回默认关闭
  }
}

export function setReadAloudEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(READ_ALOUD_KEY, String(enabled))
  } catch {
    /* localStorage 不可用，忽略 */
  }
}
```

**关于 `MAX_SYNTH_CHARS`**：后端是唯一真源（`voice_pack.MAX_SYNTH_CHARS`）。
前端不要另立一份常量 —— 放到 `front/src/types/constants.ts` 并注释「与后端 voice_pack.MAX_SYNTH_CHARS 保持一致」，
或者更省事：`truncateForSpeech` 的默认值直接写 `600` 并在注释里指明来源。
**采用后者**（避免为一个数字新建文件），但注释必须写清楚。

- [x] **Step 4: 跑测试确认 PASS**

```bash
cd front && npx vitest run src/utils/__tests__/readAloud.spec.ts
```

Expected: 全部 passed。

---

## Task 3: 前端播放通道 —— `playTtsBlob`

**Files:**
- Modify: `front/src/services/webrtcService.ts`、`front/src/api/chat.ts`

**为什么要改 `webrtcService`**：lip-sync（嘴型）是在 `playTtsAudio` 内部通过 AnalyserNode 驱动的。
聊天页要复用这条通道，否则嘴型不会动。做法是把解码/播放/lip-sync 抽成内部函数，
`playTtsAudio`（base64，语音通话用）和新的 `playTtsBlob`（Blob，聊天页用）都走它。

- [x] **Step 1: 抽出共享播放函数**

把 `playTtsAudio` 里「decodeAudioData → 建 source/analyser → start → lip-sync」这段
原样搬进新的内部函数：

```ts
/**
 * 播放一段音频 ArrayBuffer，并驱动 lip-sync。
 *
 * `playTtsAudio`（语音通话，base64）和 `playTtsBlob`（聊天页朗读，Blob）共用这一条路径 ——
 * 嘴型是在这里通过 AnalyserNode 驱动的，另起一条播放路径会导致聊天页角色不动嘴。
 */
async function playTtsBuffer(buffer: ArrayBuffer, audioCtx?: AudioContext): Promise<void> {
  // ...原 playTtsAudio 中 decode 之后的所有逻辑，把 decodeAudioData(bytes.buffer) 换成 decodeAudioData(buffer)
}

export async function playTtsAudio(base64Audio: string, audioCtx?: AudioContext): Promise<void> {
  if (!webrtcService.isSpeakerOn()) { /* 原样保留 */ return }
  stopTtsAudio()
  const binaryStr = atob(base64Audio)
  const bytes = new Uint8Array(binaryStr.length)
  for (let i = 0; i < binaryStr.length; i++) bytes[i] = binaryStr.charCodeAt(i)
  return playTtsBuffer(bytes.buffer, audioCtx)
}

/** 播放一段音频 Blob（聊天页朗读用）。同样会驱动 lip-sync。 */
export async function playTtsBlob(blob: Blob, audioCtx?: AudioContext): Promise<void> {
  if (!webrtcService.isSpeakerOn()) {
    console.log('[Voice] 扬声器已关闭，跳过朗读')
    return
  }
  stopTtsAudio()
  return playTtsBuffer(await blob.arrayBuffer(), audioCtx)
}
```

**注意**：`stopTtsAudio()` 的调用要保持在 `playTtsBuffer` 之外（两个入口各调一次），
避免把「中断上一条」的语义藏进内部函数里 —— 否则以后加第三个入口时容易漏。

- [x] **Step 2: 加 API 客户端**

`front/src/api/chat.ts` 加：

```ts
/**
 * 把一段文本合成为当前角色音色的语音。
 *
 * 不走 `request()`：它只认 JSON 响应，而这里要收音频字节。
 * 失败时把后端的 `detail` 提出来 —— 引擎不可用的原因必须让用户看见，
 * 不能变成一句"播放失败"。
 */
export const synthesizeSpeech = async (text: string, characterId?: string): Promise<Blob> => {
  const base = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  try {
    const token = localStorage.getItem('auth_token')
    if (token) headers['Authorization'] = `Bearer ${token}`
  } catch { /* localStorage 不可用，忽略 */ }

  const res = await fetch(`${base}/chat/tts`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ text, character_id: characterId }),
  })
  if (!res.ok) {
    let detail = ''
    try {
      detail = (await res.json())?.detail || ''
    } catch { /* 非 JSON 响应 */ }
    throw new Error(detail || `朗读失败（HTTP ${res.status}）`)
  }
  return res.blob()
}
```

- [x] **Step 3: 类型检查 + 跑既有语音单测**

```bash
cd front && npx vue-tsc --noEmit -p tsconfig.app.json && npx vitest run src/services
```

Expected: exit 0；既有语音相关单测仍全绿（重构不能改变 `playTtsAudio` 的外部行为）。

---

## Task 4: 聊天页 UI

**Files:**
- Modify: `front/src/views/Chat.vue`

- [x] **Step 1: 头部加「自动朗读」开关**

`header-right` 里、`VoiceCallButton` 之前插入：

```html
<button
  class="read-aloud-toggle"
  :class="{ active: readAloudOn }"
  :title="readAloudOn ? '关闭自动朗读' : '开启自动朗读：新回复会读出来'"
  @click="toggleReadAloud"
>
  <span class="ra-icon">{{ readAloudOn ? '🔊' : '🔈' }}</span>
  <span class="ra-label">朗读</span>
</button>
```

- [x] **Step 2: 每条助手消息加「朗读」按钮**

在 `bubble-wrap` 内、`bubble-time` 旁边插入（仅 `assistant` 且有内容时显示）：

```html
<button
  v-if="msg.role === 'assistant' && msg.content"
  class="speak-btn"
  :class="{ speaking: speakingIndex === i }"
  :title="speakingIndex === i ? '停止' : '朗读这条'"
  @click="toggleSpeak(i, msg.content)"
>
  {{ speakingIndex === i ? '■' : '▶' }}
</button>
```

- [x] **Step 3: 脚本逻辑**

```ts
import { cleanTextForSpeech, truncateForSpeech, isReadAloudEnabled, setReadAloudEnabled } from '@/utils/readAloud'
import { playTtsBlob, stopTtsAudio, setOnTtsPlayStateChange } from '@/services/webrtcService'
import { synthesizeSpeech } from '@/api/chat'

const readAloudOn = ref(isReadAloudEnabled())
/** 正在朗读的消息下标；-1 = 没在朗读 */
const speakingIndex = ref(-1)
/** 自动朗读的进度标记：只朗读"这一轮新到的助手回复"，避免刷新页面就全念一遍 */
const lastAutoReadIndex = ref(-1)

function toggleReadAloud() {
  readAloudOn.value = !readAloudOn.value
  setReadAloudEnabled(readAloudOn.value)
  if (!readAloudOn.value) stopSpeaking()
}

function stopSpeaking() {
  stopTtsAudio()
  speakingIndex.value = -1
}

/** 朗读第 i 条；再点一次停止 */
async function toggleSpeak(index: number, content: string) {
  if (speakingIndex.value === index) { stopSpeaking(); return }
  const text = truncateForSpeech(cleanTextForSpeech(content))
  if (!text) return

  speakingIndex.value = index
  try {
    const blob = await synthesizeSpeech(text, store.currentCharacterId || undefined)
    await playTtsBlob(blob)
  } catch (e) {
    // 明确报错而不是静默失败 —— 引擎不可用（如上游 403）时用户必须知道原因
    store.setError?.(e instanceof Error ? e.message : '朗读失败')
    speakingIndex.value = -1
  }
}

/** 自动朗读：只在流式结束、新回复落地时触发一次 */
watch(
  () => [store.loading, store.displayMessages.length] as const,
  ([loading, len]) => {
    if (!readAloudOn.value || loading) return
    if (len === 0 || len - 1 === lastAutoReadIndex.value) return
    const last = store.displayMessages[len - 1]
    if (last?.role !== 'assistant' || !last.content) return
    lastAutoReadIndex.value = len - 1
    toggleSpeak(len - 1, last.content)
  },
)

onBeforeUnmount(stopSpeaking)
```

**播放状态同步**（播完要把按钮从"停止"变回"播放"）：
`webrtcService` 已有 `setOnTtsPlayStateChange`，用它：

```ts
setOnTtsPlayStateChange((playing) => {
  if (!playing) speakingIndex.value = -1
})
// onBeforeUnmount 里置回 null，避免离开页面后还被回调
```

- [x] **Step 4: 样式**

```css
.read-aloud-toggle { /* 与 VoiceCallButton 同高，圆角胶囊，active 时高亮 */ }
.speak-btn { /* 小圆形，hover 显形；.speaking 时用强调色 */ }
```

（沿用本页已有的配色变量，**不要硬编码颜色** —— 见 `front/CLAUDE.md` 关于 `var(--text-primary)` 的说明。）

- [x] **Step 5: 类型检查 + 单测 + 构建**

```bash
cd front && npx vue-tsc --noEmit -p tsconfig.app.json && npx vitest run && npm run build
```

Expected: 全绿。

---

## 最终验收

- [ ] **后端**：`cd backend && ../.venv/Scripts/python.exe -m pytest -q` → 全绿（246 + 新增）
- [ ] **前端**：`npx vue-tsc --noEmit -p tsconfig.app.json`、`npx vitest run`、`npm run build` 全绿
- [ ] **E2E（用真实音频文件，不依赖 edge-tts）**：
  用 Playwright 拦截 `POST /chat/tts` 返回一段**真实 WAV**（用 Python `wave` 模块生成正弦音，
  `decodeAudioData` 能解），断言：
  1. 点「朗读」后按钮变成「■」（说明真的在播）
  2. `subscribeTtsLipSync` 收到过非零强度（**嘴型真的动了**）
  3. 播完后按钮变回「▶」
- [ ] **手动**：`/chat` 头部出现「朗读」开关，开启后新回复自动播；每条助手消息有「▶」

## Known Issues

- **edge-tts 合成端点当前 403（上游问题，见开头阻塞项）** —— live 音频无法验证；
  功能代码正确，上游恢复后即可用。**语音通话的 TTS 同样受影响。**
- 长回复按 `MAX_SYNTH_CHARS`（600）截断，不是全文朗读。分段朗读留作后续。
- 不做浏览器 `speechSynthesis` 兜底：那会用系统音色顶替角色音色，属于静默降级，
  与本项目既定原则冲突。若上游长期不恢复，再单独评估是否做成**显式可选项**。

## Self-Review

**1. Spec coverage（对照「聊天页朗读开关」）：**
- 开关 → Task 4 Step 1；每条消息朗读 → Task 4 Step 2；
- 让语音包在主场景生效 → Task 1（按角色解析绑定包，不是传参）；
- 嘴型联动 → Task 3（复用 lip-sync 通道）+ Task 4 验收项 2。✅

**2. Placeholder scan：** Task 4 的样式块给了说明而非完整 CSS（本页已有配色体系，逐条列举反而易漂移），
其余 Step 均含完整代码与期望输出。**这是本计划唯一的"非完整代码"处，已显式标注。** ⚠️

**3. Type / 命名一致性：** `synthesizeSpeech` / `playTtsBlob` / `playTtsBuffer` /
`cleanTextForSpeech` / `truncateForSpeech` / `isReadAloudEnabled` / `setReadAloudEnabled` /
`speakingIndex` / `readAloudOn` / `lastAutoReadIndex` 在各 Task 中一致。✅

**4. 提交粒度：** 4 个 Task 各自独立 commit（后端端点 / 纯函数 / 播放通道 / UI）。✅

**5. 与既有约定一致：** 新测试放 `backend/tests/`（遵守 conftest 隔离）、`front/src/utils/__tests__/`；
不新建 `composables/` 目录（仓库没有该约定）；不硬编码颜色（`front/CLAUDE.md` 有明确规定）。✅

---

## 执行结果（2026-10-12）

4 个 Task 全部完成。

### 改动

| 文件 | 内容 |
|---|---|
| `backend/funcation/voice_pack.py` | 加 `MAX_SYNTH_CHARS = 600` |
| `backend/api/api.py` | 新增 `POST /chat/tts`（`require_approved`，非管理员） |
| `backend/tests/test_chat_tts_api.py` | **新增 12 项** |
| `front/src/utils/readAloud.ts` | **新增**：文本清洗 + 截断 + 开关持久化 |
| `front/src/utils/__tests__/readAloud.spec.ts` | **新增 16 项** |
| `front/src/services/webrtcService.ts` | 抽出 `playTtsBuffer()`；新增 `playTtsBlob()` 与 `subscribeTtsPlayState()` |
| `front/src/api/chat.ts` | 新增 `synthesizeSpeech()` |
| `front/src/views/Chat.vue` | 头部开关 + 每条消息朗读按钮 + 三态状态机 + 错误提示 |
| `front/e2e/read-aloud.spec.ts` | **新增 2 项**（自带 WAV 生成，不依赖 edge-tts） |

### 与计划的偏差

1. **发现并修掉一个潜伏 bug**：`setOnTtsPlayStateChange` 是**单订阅**，而 `voiceCallStore` 已占用它。
   语音通话弹窗是浮在聊天页上的（Teleport），两者同时挂载时后者会把前者的回调顶掉。
   按既有 `subscribeTtsLipSync` 的模式加了多订阅版 `subscribeTtsPlayState()`，`notifyPlayState` 两者都通知。

2. **播放态状态机第一版有 bug，被截图验证抓出来**：点「朗读」后按钮一直是「▶」而不是「■」。
   原因：`playTtsBlob` 内部会先 `stopTtsAudio()`（中断上一条），那会发一次 `playing=false`，
   把刚点亮的 `speakingIndex` 又清掉了。
   改为三态 `idle / loading / playing`，并让 play-state 回调**只在 `playing` 阶段认这条通知**。
   顺带补上了「合成中」的 `⋯` 反馈（原来点完要等 1 秒才有反应）。

3. **E2E 的嘴型断言用了轮询**：按钮变「■」只代表播放已开始，lip-sync 要下一个动画帧才发第一个强度，
   一次性读取会拿到 0。

### 验证数据

- 后端 `pytest`：**258 passed**（246 + 新增 12）
- 前端 `vitest`：**138 passed**（122 + 新增 16）；`vue-tsc` exit 0；`npm run build` 通过
- E2E：**8 passed / 1 skipped**（新增 2 项全过）
- **端到端实测**（拦截 `/chat/tts` 回真实 WAV）：
  - 按钮状态机 `▶ → ⋯ → ■ → ▶` 全对
  - **lip-sync 强度峰值 0.499** → 3D 嘴型真的跟着动
  - 请求文本已被清洗（Markdown 去掉、40 字）
  - 开关切换 + `localStorage` 持久化正常

### 遗留

- ~~**edge-tts 合成端点上游 403**（见开头阻塞项）—— live 音频仍无法验证~~ →
  **已解决（2026-10-12）**：上游真因是**微软把合成后端迁到新主机并按地区分批切换**，
  edge-tts 7.2.8 仍指向旧主机。已按上游 PR #491 的修法加 `funcation/edge_tts_compat.py`
  把端点切到 `api.msedgeservices.com`。**实测 `/chat/tts` 已能返回 4 秒真实 MP3**，
  **语音通话同一条链路，一并恢复**。详见 `backend/CLAUDE.md`。
- **本地跑全量 E2E 会因内存不足而偶发页面崩溃**：实测本机内存占用 88%、可用仅 2.8GB，
  且 25 个 chrome 进程全是**用户自己的浏览器**（不能动）。`--workers=1` 可稳定通过。
  CI runner 内存充足，不受影响 —— 但本地复现问题时要记得这一点。
- 长回复按 600 字截断，未做分段连续朗读。

## Self-Review

**1. Spec coverage（对照「聊天页朗读开关」）：**
- 开关 → Task 4（含持久化，E2E 覆盖）；每条消息朗读 → Task 4（E2E 覆盖状态机）；
- 让语音包在主场景生效 → Task 1（按 `character_id` 解析绑定包，不传音色参数）；
- 嘴型联动 → Task 3（复用 lip-sync 通道）+ E2E 断言强度 > 0。✅

**2. Placeholder scan：** Task 4 的样式块在计划里只给了说明（实际实现时按本页既有配色写全），
其余 Step 均有完整代码与期望输出。⚠️ 已显式标注。

**3. Type / 命名一致性：** `synthesizeSpeech` / `playTtsBlob` / `playTtsBuffer` /
`subscribeTtsPlayState` / `cleanTextForSpeech` / `truncateForSpeech` / `readAloudOn` /
`speakingIndex` / `speakPhase` 在各 Task 与实际代码中一致。✅

**4. 提交粒度：** 4 个 Task 合成 1 个提交（后端端点 + 前端纯函数 + 播放通道 + UI 是一条完整链路，
拆开会让中间提交缺半边功能）。⚠️ 与计划里"各自独立 commit"不一致 —— **已如实记录**。

**5. 与既有约定一致：** 新测试放 `backend/tests/`、`front/src/utils/__tests__/`、`front/e2e/`；
未新建 `composables/` 目录；样式未硬编码主题色（`front/CLAUDE.md` 有规定）。✅
