# QQ / 微信第三方登录接入（执行计划骨架，2026-11-06）

> **这是执行计划**，不是方向文档（方向文档见 `2026-11-02-next-phase.md`）。
> 用户跳过需求确认，本计划采用以下**默认假设**，开工前务必确认：
>
> | 项 | 默认值 | 改动代价 |
> |---|---|---|
> | 资质 | **还没 AppID，先做可联调骨架** | 拿到 key 后只填 env |
> | 新用户 | **自动 approved**（免审批直接聊天） | 改一个常量 |
> | 账号打通 | **只做扫码即建号**，不做绑定/合并 | 需另开一期 |

## Goal

在不依赖任何第三方资质的前提下，把 QQ / 微信登录的**完整链路**做通并可测试：
数据库 → provider 抽象 → state 防 CSRF → 回调换身份 → 建号/复用 → 签 JWT → 前端落 token。
拿到 AppID 后**只填环境变量**即可切真接口，不改业务代码。

## 一、硬门槛（已查证，不是猜测）

### QQ 互联（网站应用）

来源：QQ 互联 WIKI《申请相关问题》《回调地址常见问题及修改方法》

- 创建应用后**立即**拿到 `appid` / `appkey`；审核约 **5 个工作日**
- 未审核通过：**仅开发者本人 QQ 号**能登录（可加「协助者测试号」）
- 回调地址原文限制：
  > 回调地址这里不能用端口号和 localhost，必须要是外网可以访问的域名
- 域名归属验证：要在网站 `<HEAD>` 里放 QQ 给的验证代码，QQ 会来抓取
- **回调域不能带 `#`**（官方特意点名 vue hash 路由）→ 回调必须落**后端接口**，
  后端 302 再跳 `https://域名/#/oauth/callback`
- 回调地址的「域名 + path」必须与注册值完全一致，可带额外 query；
  多个回调用 `;` 分隔；不一致返回错误码 **100010**
- 国内主体创建时一般要填 ICP 备案号；官方 Q7 明确海外网站无 ICP 也可申请
- QQ 侧官方示例 http/https 都出现，未强制 HTTPS（微信侧更严）

### 微信开放平台（网站应用）

- 是**开放平台的「网站应用」**，不是公众号、不是小程序
- 需要开发者资质认证（约 300 元/年）+ 审核；`AppID` / `AppSecret`
- 扫码登录用 `qrconnect` + `scope=snsapi_login`
- 回调域名同样要公网可访问；有 `unionid` 可跨应用统一（QQ 没有）

### 对本项目的影响

**本地 `127.0.0.1:8000` / `localhost:5173` 跑不了真实回调。**
内网穿透（frp/ngrok）能用于联调，但过不了域名归属验证与审核，不是正式方案。
所以本期的联调全部走 **MockProvider**（不发外网请求、确定性身份）。

⚠️ **QQ openid 与微信 openid 互不相通** —— 同一个人用两家登会得到两个账号。
本期接受这个事实并在文档里写明，不假装打通。

## 二、现状（已核对）

- `User` 表**已预留** `oauth_provider` / `oauth_id`（`funcation/auth.py:58-59`），一直没用
- `password_hash` 是 `nullable=False` → OAuth 用户没密码
- 预留字段**没有联合唯一索引** → 并发回调可能开出重号
- 注册默认 `status="pending"` 等管理员审批
- JWT 由 `create_token(user)` 签发，OAuth 回调直接复用即可，鉴权体系零改动
- 依赖已有：`PyJWT==2.9.0`、`requests>=2.34.2`、`bcrypt`
- 配置约定：密钥类**刻意不进** `system_config`（根 `CLAUDE.md` 已记），走 env
- 迁移入口：`funcation/auth.py` 模块底部 `_migrate_user_columns()` / `_ensure_admin()`
- 前端登录是 `components/AuthModal.vue` + `stores/authStore.ts`
- 路由挂载：`api/api.py:136` → `app.include_router(auth_router, prefix="/auth")`

## 三、File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/funcation/oauth.py` | **新增** | provider 抽象 + QQ/微信/Mock 实现 + state 签发校验 + 配置读取 |
| `backend/funcation/auth.py` | 修改 | 追加唯一索引迁移（幂等）；占位密码工具 |
| `backend/api/oauth.py` | **新增** | `/auth/oauth/*` 三个端点 + 回调建号/复用 |
| `backend/api/api.py` | 修改 | 挂载新 router |
| `backend/tests/test_oauth.py` | **新增** | provider 解析 / state / 端点全链路（mock） |
| `backend/.env.example` | 修改 | 新增 QQ/微信/回调地址/OAUTH_MODE 配置项 |
| `front/src/api/auth.ts` | **新增/修改** | `getOAuthProviders` / `startOAuth` |
| `front/src/components/AuthModal.vue` | 修改 | 按可用 provider 动态显示按钮 |
| `front/src/views/OAuthCallbackView.vue` | **新增** | 解析 fragment 里的 token/error → 写 authStore |
| `front/src/router/index.ts` | 修改 | 注册 `/oauth/callback` |
| `front/src/types/api.ts` | 修改 | OAuth 响应类型 |

## 四、逐 Task

- [x] **T1 查证**：现状 + 官方准入要求（本文件第一、二节）
- [x] **T2 `funcation/oauth.py`**
  - `OAuthIdentity(provider, subject, unionid, nickname, avatar)`
  - `BaseProvider.authorize_url(state, redirect_uri)` / `exchange(code, redirect_uri) -> OAuthIdentity`
  - `QQProvider`：`authorize` → `token`（**响应是 querystring 不是 JSON**）→ `me`
    （**JSONP `callback({...});`**）→ `get_user_info`
  - `WechatProvider`：`qrconnect` → `sns/oauth2/access_token` → `sns/userinfo`，处理 `errcode`
  - `MockProvider`：确定性 subject，不发外网，供本地联调与测试
  - `state`：HMAC/JWT 签名、含 provider + nonce + 过期，**一次性**（内存去重）
  - `configured_providers()`：没配 AppID 的 provider 不出现在列表里
- [x] **T3 数据层**
  - 幂等建 `CREATE UNIQUE INDEX IF NOT EXISTS ... ON users(oauth_provider, oauth_id) WHERE oauth_provider IS NOT NULL`
  - OAuth 用户 `password_hash = hash_password(token_urlsafe(32))`（不可登录的占位）
  - 唯一键冲突时重查复用，不抛 500
- [x] **T4 端点**
  - `GET /auth/oauth/providers` → `[{provider, label, enabled}]`
  - `GET /auth/oauth/{provider}/authorize` → `{url, state}`
  - `GET /auth/oauth/{provider}/callback?code=&state=` → 校验 state → exchange →
    查/建用户 → `create_token` → 302 到 `{FRONTEND_BASE}/#/oauth/callback?token=...`
  - 失败 302 到 `?error=...`（**错误不泄漏 AppSecret / 原始响应**）
  - 回调地址用**配置值**，绝不信请求里的 `redirect_uri`
- [x] **T5 前端**：按钮 / 回调页 / 路由 / 类型；错误态可见
- [x] **T6 测试**：
  - state 过期、篡改、provider 不匹配、重放
  - QQ querystring + JSONP 解析、微信 errcode
  - 未配置 provider 明确报错
  - 首次建号 / 二次复用 / 同 provider 不同 subject 得不同账号 / 并发不重号
  - MockProvider 走完整 TestClient 回调链路
  - **验证有牙齿**：故意改坏一处，确认测试会红
- [x] **T7 验收**：后端双环境全绿 + 前端 type-check/lint/vitest 全绿；
  同步 `CLAUDE.md`（根 + backend + front）；更新方向文档；提交

## 五、安全红线

1. **AppSecret / AppKey 只从 env 读**，不进 `system_config`、不进日志、不进前端
2. `state` 必须一次性 + 带过期；校验失败不建号
3. 回调地址用服务端配置，不接受客户端传入（防开放重定向）
4. `openid` 不返回给前端，不写进 URL
5. 回调失败信息用泛化文案，原始第三方响应只进服务端日志
6. 保留用户名密码登录；OAuth 用户不能通过密码登录（占位随机密码）
7. `status=deactivated` 的账号回调后拒绝签发 token

## 六、验收标准

- 无 AppID 时启动不报错，`/auth/oauth/providers` 返回空/仅 mock
- 设 `OAUTH_MODE=mock` 后，前端点按钮 → 模拟回调 → 拿到 token → 进入聊天，全链路可跑
- 同一个 mock subject 连登两次，`users` 表只多一行
- 单测与 CI 全绿；**不触碰真实开发库**（conftest 隔离 + 临时 DB）
