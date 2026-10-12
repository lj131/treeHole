# vendor/ —— 第三方源码副本

这里放两份**第三方源码副本**，都是为了在本机网络环境下安装：

- `OpenVoice/` — [myshell-ai/OpenVoice](https://github.com/myshell-ai/OpenVoice)（MIT）
- `MeloTTS/` — [myshell-ai/MeloTTS](https://github.com/myshell-ai/MeloTTS)（MIT）

## 为什么不直接 pip 装

| 包 | 官方方式 | 为什么不行 |
|---|---|---|
| `melotts` | `pip install melotts` | PyPI 的 sdist **装不上**：`setup.py` 引用了不存在的 `requirements.txt` |
| 两者 | `pip install git+https://github.com/...` | `github.com` 主站不通（`codeload.github.com` 通） |

用 `--no-deps` 从本地装，依赖**手动挑**：上游的 `requirements.txt` 钉了
`numpy==1.22` / `transformers==4.27.4`，放进来会和主 venv 冲突，而且会拖进
gradio / faster-whisper / wavmark / tensorboard 一堆用不到的东西。

## 规则

**不要手改这里的代码。** 升级 = 从上游 release 重新拷贝覆盖。

唯一例外：`OpenVoice/openvoice/api.py` 里有一处**上游 bug 的本地修正**
（`ToneColorConverter.__init__` 把 `enable_watermark` 透传给只接受两个参数的基类），
已在代码里用注释标出。上游修掉后应删掉本地补丁。

## 安装

用 `scripts/setup_clone_env.ps1`（PowerShell），或照 `backend/CLAUDE.md`
「音色克隆引擎」一节的坑单列表逐个装。
