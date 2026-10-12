# 安装 OpenVoice 克隆引擎的 sidecar 环境（PowerShell）
#
# **为什么要独立 venv**：主 venv 是 numpy 2.x（在跑 RAG / 后端），
# 而 MeloTTS/OpenVoice 要 numpy 1.x + transformers 4.x。
# 装进同一个 venv 会把 numpy 降级、把正在用的东西搞挂。
#
# 体积：约 4GB（torch ~2.5GB + 权重 ~480MB + 依赖）。磁盘要留够。
#
# 用法：在仓库根目录执行
#   pwsh backend/scripts/setup_clone_env.ps1

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    Write-Host '==> 建 sidecar venv (.venv-clone)' -ForegroundColor Cyan
    if (-not (Test-Path '.venv-clone')) {
        py -3.13 -m venv .venv-clone
    }
    $py = '.venv-clone\Scripts\python.exe'
    if (-not (Test-Path $py)) { throw "找不到 $py" }

    Write-Host '==> 升级 pip' -ForegroundColor Cyan
    & $py -m pip install --upgrade pip

    Write-Host '==> 装核心依赖（torch 是最大头，耐心等）' -ForegroundColor Cyan
    & $py -m pip install torch torchaudio librosa numpy pydub loguru tqdm
    & $py -m pip install unidecode inflect num2words pypinyin cn2an jieba
    & $py -m pip install anyascii pykakasi jamo g2p_en langid
    & $py -m pip install transformers scipy numba soundfile cached_path huggingface_hub
    # MeloTTS 的多语言文本前端：即使只用中文，import 时也会要这些
    & $py -m pip install mecab-python3 unidic-lite fugashi
    & $py -m pip install 'gruut[de,es,fr]' eng_to_ipa

    Write-Host '==> 装 vendor 里的 OpenVoice / MeloTTS' -ForegroundColor Cyan
    # --no-deps：它们的 requirements 钉了 numpy 1.22 / transformers 4.27 这类老版本，
    # 放进来会跟上面装的冲突。所以依赖手动挑，源码本地装。
    & $py -m pip install --no-deps ./backend/vendor/MeloTTS ./backend/vendor/OpenVoice

    Write-Host '==> 下权重（走 hf-mirror，直连 huggingface.co 在国内不通）' -ForegroundColor Cyan
    $env:HF_ENDPOINT = 'https://hf-mirror.com'
    $env:HF_HUB_DISABLE_TELEMETRY = '1'
    & $py -c "from huggingface_hub import snapshot_download; snapshot_download('myshell-ai/MeloTTS-Chinese'); snapshot_download('myshell-ai/OpenVoice')"
    Write-Host "    HuggingFace 缓存位置: $env:USERPROFILE\.cache\huggingface" -ForegroundColor DarkGray

    Write-Host '==> 把权重摆到 data/openvoice/' -ForegroundColor Cyan
    & $py backend/scripts/fetch_openvoice_ckpt.py

    Write-Host ''
    Write-Host '完成。重启后端即可，不需要改代码。' -ForegroundColor Green
    Write-Host '验证：' -ForegroundColor Green
    Write-Host '  cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_voice_clone_protocol.py -q' -ForegroundColor DarkGray
}
finally {
    Pop-Location
}
