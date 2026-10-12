# 系统配置页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让管理员在界面上改运行时配置，而不是「改 `.env` → 重启进程」。

**Architecture:** 现在 `/admin` 只有用户审批 + 配额；TTS / 上传限额 / 后台 tick / 嵌入模型**全是 `.env`**，
改任何一项都要动文件 + 重启。

新增 `funcation/system_config.py`，**schema 驱动**：

- 每个字段声明类型 / 范围 / 默认值 / **是否需重启**，前端按 schema 渲染（不写死表单）
- 存储 `data/system_config.json`，**只存被显式改过的键**
- 优先级：**文件值 > 环境变量 > 代码默认值**（所以不配任何东西时行为与现在完全一致）
- **绝不暴露密钥**：`JWT_SECRET_KEY`、`ADMIN_DEFAULT_PASSWORD` 等安全敏感项**不进 schema** ——
  在界面上改密码/密钥是安全风险，也会让现有会话全部失效。界面上要写明这一点

**为什么要标 `restart_required`**：有些配置是在**模块导入时**读的（world tick 间隔、嵌入模型），
进程内改不了。**如实标注比假装能热更新好** —— 否则用户改完没生效会以为坏了。

**Tech Stack:** FastAPI / pytest / Vue 3 / Pinia。

---

## 前置基线

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest -q     # 258 passed
cd front && npm run lint:ci && npm run type-check && npx vitest run   # 全绿
```

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/funcation/system_config.py` | **新增** | schema + 读写 + 校验 + 生效值解析 |
| `backend/api/api.py` | 修改 | `GET/PATCH /admin/config`（`require_admin`） |
| `backend/tests/test_system_config.py` | **新增** | 纯函数 + 存储 |
| `backend/tests/test_system_config_api.py` | **新增** | 端点 + 权限 + 校验 |
| `backend/funcation/voice_service.py` | 修改 | 全局默认音色改为读 system_config |
| `backend/funcation/model3d.py` | 修改 | `MODEL_MAX_MB` 改为读 system_config |
| `backend/funcation/voice_pack.py` | 修改 | 参考音频上限 / 包数量上限改为读 system_config |
| `backend/funcation/world_tick_scheduler.py` | 修改 | 三个间隔参数读 system_config（启动时生效） |
| `backend/funcation/embedding_manager.py` | 修改 | provider / model 读 system_config（重启后生效） |
| `front/src/api/admin.ts` | **新增** | 配置接口客户端 |
| `front/src/views/AdminView.vue` | 修改 | 「系统配置」区（按 schema 渲染） |
| `front/src/types/api.ts` | 修改 | 配置字段类型 |
| `backend/CLAUDE.md`、`front/CLAUDE.md` | 修改 | 同步 |

---

## Task 1: `system_config.py`（纯函数 + 存储）

- [x] **Step 1: 写失败测试**

`backend/tests/test_system_config.py`：

```python
"""系统配置：schema 校验 / 存储 / 生效值优先级。纯逻辑，不碰网络。"""
import json
from pathlib import Path

import pytest

from funcation import system_config as sc


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """每个用例一份独立的配置文件 + 干净的环境变量"""
    monkeypatch.setattr(sc, "CONFIG_FILE", str(tmp_path / "system_config.json"))
    monkeypatch.setattr(sc, "_cache", None)
    yield


def test_defaults_come_from_schema():
    """没配过任何东西时，取到的是 schema 默认值（= 现在的 .env 默认行为）"""
    assert sc.get_effective()["tts.voice_name"] == "zh-CN-XiaoxiaoNeural"


def test_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv("VOICE_NAME", "zh-CN-YunxiNeural")
    monkeypatch.setattr(sc, "_cache", None)
    assert sc.get_effective()["tts.voice_name"] == "zh-CN-YunxiNeural"


def test_file_value_beats_env(monkeypatch):
    """文件 > 环境变量 —— 否则界面上改完不生效"""
    monkeypatch.setenv("VOICE_NAME", "zh-CN-YunxiNeural")
    sc.save({"tts.voice_name": "zh-CN-XiaoyiNeural"})
    assert sc.get_effective()["tts.voice_name"] == "zh-CN-XiaoyiNeural"


def test_only_overrides_are_persisted():
    """只存被显式改过的键 —— 全量落盘会让默认值被冻结，以后改代码默认值就失效了"""
    sc.save({"tts.speaking_rate": 1.2})
    stored = json.loads(Path(sc.CONFIG_FILE).read_text(encoding="utf-8"))
    assert stored == {"tts.speaking_rate": 1.2}


def test_reset_removes_override(monkeypatch):
    sc.save({"tts.speaking_rate": 1.2})
    sc.save({"tts.speaking_rate": None})   # None = 恢复默认
    assert sc.get_effective()["tts.speaking_rate"] == 1.0


def test_out_of_range_rejected():
    with pytest.raises(sc.ConfigError):
        sc.save({"tts.speaking_rate": 99})


def test_unknown_key_rejected():
    """未知键直接拒 —— 静默忽略会让人以为配上了"""
    with pytest.raises(sc.ConfigError):
        sc.save({"tts.nonexistent": 1})


def test_non_numeric_rejected():
    with pytest.raises(sc.ConfigError):
        sc.save({"tts.speaking_rate": "快一点"})


def test_voice_name_validated():
    with pytest.raises(sc.ConfigError):
        sc.save({"tts.voice_name": "../../etc/passwd"})


def test_secrets_are_not_exposed():
    """密钥类配置绝不能出现在 schema 里（界面上改密钥是安全风险）"""
    keys = {f.key for f in sc.fields()}
    joined = " ".join(keys).lower()
    for forbidden in ("jwt", "secret", "password", "api_key", "apikey"):
        assert forbidden not in joined, f"schema 暴露了敏感项：{forbidden}"


def test_corrupt_config_file_falls_back_to_defaults():
    Path(sc.CONFIG_FILE).write_text("{ 这不是 json", encoding="utf-8")
    sc._cache = None
    assert sc.get_effective()["tts.speaking_rate"] == 1.0


def test_schema_declares_restart_requirement():
    """需要重启的项必须如实标注，否则用户改完没生效会以为坏了"""
    restart = {f.key for f in sc.fields() if f.restart_required}
    assert "world.tick_loop_sec" in restart
    assert "embedding.provider" in restart
    assert "tts.voice_name" not in restart   # 音色是即时生效的
```

- [x] **Step 2: 跑测试确认 FAIL**（模块不存在）

- [x] **Step 3: 实现 `funcation/system_config.py`**

要点：
- `ConfigField` dataclass：`key / label / group / kind / default / env / minimum / maximum / step / restart_required / hint`
- `FIELDS` 列表（见下）
- `fields()` 返回 FIELDS
- `load()` 读文件（损坏 → 空 dict + warning，**不抛**）
- `save(patch)`：逐键校验（未知键 → `ConfigError`；类型/范围/音色名非法 → `ConfigError`），
  值 `None` = 删除该覆盖，然后**原子写**（`.tmp` + `os.replace`）
- `get_effective()` 返回 `{key: value}`：文件值 > env > default
- `get(key)` 便捷读单个

字段清单（12 项，分 4 组）：

| key | 组 | 类型 | 范围 | env | 需重启 |
|---|---|---|---|---|---|
| `tts.voice_name` | 语音 | string | 音色名校验 | `VOICE_NAME` | 否 |
| `tts.speaking_rate` | 语音 | float | 0.5–2.0 | `SPEAKING_RATE` | 否 |
| `tts.pitch` | 语音 | float | −50–50 | `PITCH` | 否 |
| `tts.volume` | 语音 | float | 0–2 | `VOLUME` | 否 |
| `upload.model_max_mb` | 上传 | int | 1–512 | `MODEL_MAX_MB` | 否 |
| `upload.voice_ref_max_mb` | 上传 | int | 1–100 | — | 否 |
| `upload.max_voice_packs` | 上传 | int | 1–200 | — | 否 |
| `world.tick_loop_sec` | 后台 | int | 60–86400 | `WORLD_TICK_LOOP_SEC` | **是** |
| `world.tick_min_interval_min` | 后台 | int | 1–1440 | `WORLD_TICK_MIN_INTERVAL_MIN` | **是** |
| `world.active_user_days` | 后台 | int | 1–365 | `WORLD_TICK_ACTIVE_DAYS` | **是** |
| `embedding.provider` | 嵌入 | string | `fastembed`/`openai`/`huggingface` | `EMBEDDING_PROVIDER` | **是** |
| `embedding.model` | 嵌入 | string | 非空 | `EMBEDDING_MODEL` | **是** |

- [x] **Step 4: 跑测试确认 PASS**

---

## Task 2: 让消费方读配置

**每个消费方都要保留「配置没设 → 用原来的 env/常量」的行为**，否则等于偷偷改了默认值。

- [x] **Step 1: `voice_service.env_defaults()`** → 四个 TTS 项改读 `system_config.get(...)`
- [x] **Step 2: `model3d.max_model_bytes()`** → 读 `upload.model_max_mb`
- [x] **Step 3: `voice_pack.max_ref_bytes()` / 新增 `max_packs()`** →
  **回退到原模块常量**，这样现有测试里 `monkeypatch.setattr(vp, "MAX_PACKS", 2)` 仍然有效
- [x] **Step 4: `api.py` 里读 `voice_pack.MAX_PACKS` 的地方改用 `voice_pack.max_packs()`**
- [x] **Step 5: `world_tick_scheduler` 三个常量** → 模块导入时读配置（重启后生效）
- [x] **Step 6: `embedding_manager` 的 provider/model** → 读配置
- [x] **Step 7: 跑全量后端测试确认无回归**

---

## Task 3: `GET/PATCH /admin/config`

- [x] **Step 1: 写失败测试**（`test_system_config_api.py`）

覆盖：非管理员 403 / 匿名 401 / GET 返回 schema + 生效值 / PATCH 生效 / 越界 400 /
未知键 400 / `null` 恢复默认 / **响应里不能出现密钥类字段名**

- [x] **Step 2: 实现端点**

```
GET  /admin/config  → {fields: [{key,label,group,kind,value,default,min,max,step,restart_required,hint}], groups: [...]}
PATCH /admin/config → body: {values: {key: value|null}} → 返回更新后的 GET 形状
```

**两个端点都 `require_admin`。**

- [x] **Step 3: 跑测试确认 PASS**

---

## Task 4: 前端「系统配置」区

- [x] **Step 1: `types/api.ts` 加类型**（`SystemConfigField` / `SystemConfigResponse`）
- [x] **Step 2: `api/admin.ts`**（`getSystemConfig` / `updateSystemConfig`）
- [x] **Step 3: `AdminView.vue` 加区块**
  - **按 `group` 分组渲染**，字段类型决定控件（int/float → number input；string → text；provider → select）
  - 每个字段显示当前值 + 默认值，改动后高亮「未保存」
  - `restart_required` 的字段打「需重启」标记
  - 底部一个「保存」按钮（一次 PATCH 全部改动）+ 「恢复默认」
  - **页面顶部写明**：密钥类配置不在此处（安全考虑），需要改请编辑 `.env`
- [x] **Step 4: 验证**

```bash
cd front && npm run lint:ci && npm run type-check && npx vitest run && npm run build
```

---

## 最终验收

- [x] 后端 `pytest -q` 全绿（258 + 新增）
- [x] 前端 `lint:ci` / `type-check` / `vitest` / `build` 全绿
- [x] **端到端**：管理员在 `/admin` 改「默认音色」→ 保存 → 重新 `GET /voice/voices` 不报错；
      再用 `/chat/tts` 观察解析出的音色确实变了（用 mock 合成断言）
- [x] **不改任何配置时，行为与改动前完全一致**（这是最重要的一条回归）
- [x] 非管理员访问 `/admin/config` 返回 403

## Known Issues

- **不暴露密钥类配置**（`JWT_SECRET_KEY` / `ADMIN_DEFAULT_PASSWORD` / API key）——
  界面上改密钥是安全风险，也会让现有会话失效。页面会写明。
- 需重启的项**不会热更新**，只做到「存下来 + 重启后生效 + 界面如实标注」。
  真热更新要重建 scheduler / 重载嵌入模型，风险远大于收益。
- `upload.max_voice_packs` 有覆盖时以配置为准，无覆盖时回退模块常量 ——
  这样现有测试的 `monkeypatch.setattr(vp, "MAX_PACKS", 2)` 仍然有效。

## Self-Review

**1. Spec coverage：** schema 驱动 + 存储 + 优先级（Task 1）、消费方接入（Task 2）、
接口（Task 3）、界面（Task 4）✅。密钥不暴露、需重启如实标注均已落到测试里。
**2. Placeholder scan：** 字段清单给的是表格而非逐个 dataclass 字面量（12 个字段逐个列举会让文档难读），
但每列都明确了类型/范围/env/重启要求。⚠️ 已标注。
**3. 一致性：** `system_config.get/get_effective/save/fields/ConfigError` 在各 Task 中一致。
**4. 提交粒度：** Task 1（模块）/ Task 2（接入）/ Task 3（接口）/ Task 4（界面）各自 commit。
**5. 最大风险 = 偷偷改默认值**：Task 2 每个消费方都要求「没配就回退到原行为」，
并在验收里单列一条「不改配置时行为不变」。

---

## 执行结果（2026-10-12）

4 个 Task 全部完成。

### 改动

| 文件 | 内容 |
|---|---|
| `backend/funcation/system_config.py` | **新增**：schema（12 字段 / 4 组）+ 校验 + 存储 + 生效值解析 |
| `backend/api/api.py` | `GET/PATCH /admin/config`（`require_admin`） |
| `backend/tests/test_system_config.py` | **新增 24 项** |
| `backend/tests/test_system_config_api.py` | **新增 15 项** |
| `backend/funcation/voice_service.py` | 全局默认音色接进解析链 |
| `backend/funcation/voice_pack.py` | `resolve_voice_config` 支持 `global_default`；新增 `max_packs()` |
| `backend/funcation/model3d.py` | `max_model_bytes()` 读配置 |
| `backend/funcation/world_tick_scheduler.py` | 三个间隔读配置（启动时生效） |
| `backend/funcation/embedding_manager.py` | provider / model 读配置 |
| `front/src/api/admin.ts`、`types/api.ts` | 新增 |
| `front/src/views/AdminView.vue` | 「系统配置」区（schema 驱动） |
| `front/src/router/index.ts` | **修路由守卫**（见下） |
| `front/e2e/system-config.spec.ts` | **新增 3 项** |

### 过程中发现并修掉的两个真问题

1. **`tts.*` 配置差点是假功能**：`voice_service.env_defaults()` **从来没有被生产代码调用过**，
   而 `voice_pack.resolve_voice_config()` 的 default 分支**硬编码 `FALLBACK_VOICE`**。
   也就是说改了「默认音色」不会有任何效果。
   → `resolve()` 现在把 `env_defaults()` 作为 `global_default` 传进去
   （`resolve_voice_config` 保持纯函数，不直接依赖配置模块）。
   **这个 bug 是被接口测试抓出来的**（断言"改完立刻生效"失败了）。

2. **管理员刷新 `/#/admin` 会被弹回首页**：路由守卫同步判断 `auth.isAdmin`，
   而用户信息是 `App.vue` 的 `onMounted` 里异步拉的 —— 守卫跑在它之前。
   → 守卫改 async，有 token 但 `auth.user` 为空时先补一次 `fetchMe`。
   加了 E2E 回归用例钉住。

### 一个设计缺陷（被既有测试抓出来）

`system_config` 里把默认值**硬编码**成 `64` / `30` / `10`，**盖住了模块常量**
（`model3d.DEFAULT_MAX_MODEL_MB` / `voice_pack.MAX_PACKS`），
把 5 个既有测试打挂 —— 它们靠 monkeypatch 常量来调上限。

→ `ConfigField.default` 支持**零参可调用对象**，用 `_const_default()` 惰性取模块常量。
**默认值只有一份真源**，测试的 monkeypatch 仍然有效。

### 另一个「不改动既有契约」的决定

`upload.model_max_mb` **刻意是小数型**：原实现用 `float(os.getenv("MODEL_MAX_MB"))` 解析，
已有部署可能配了 `0.001` 这类值。改成整数型会**悄悄收窄既有的 env 契约**
（有个既有测试正是用 `MODEL_MAX_MB=0.001` 造超限的）。

### 验证数据

- 后端 `pytest`：**296 passed**（258 + 新增 39）
- 前端 `lint:ci` / `type-check` / `vitest`（138）/ `build` 全绿
- E2E：**11 passed / 1 skipped**（新增 3 项）
- **端到端实测**（Playwright）：
  - `fieldCount: 12`，4 个分组，`restartBadges: 5`（world×3 + embedding×2）✓
  - **`secretLeak: []`** —— schema 与页面上都没有密钥类字段 ✓
  - 改 `tts.speaking_rate=1.4` → 回读 `1.4` / `overridden=true`；置 `null` → 回读 `1` / `overridden=false` ✓
  - 界面：改动后出现「未保存」标记、保存按钮启用 ✓，无 console 报错 ✓

### 遗留（已记录理由）

- 需重启的项**不热更新**，只做到「存下来 + 重启后生效 + 界面如实标注」。
  真热更新要重建 scheduler / 重载嵌入模型，风险远大于收益。
- 密钥类配置不暴露（安全考虑），页面已写明让用户去编辑 `.env`。
