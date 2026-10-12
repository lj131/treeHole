"""把 OpenVoice 权重下到 `backend/data/openvoice/` 并摆成 worker 期望的结构。

**为什么不用 `huggingface_hub.snapshot_download`**：它会把权重塞进
`~/.cache/huggingface` 的 snapshot 目录，还得再搬一次；而且缓存在用户目录下，
`pip install` 那个 `unidic download` 也会往系统 Temp 写东西，容易被清理工具扫掉。

这里是**直接下到目标目录**（`data/` 已被 .gitignore），幂等：
已存在的文件直接跳过，可反复跑。源用 `hf-mirror.com` —— 直连 huggingface.co
在国内不通（实测 HTTP 000）。

用法：在仓库根目录
    .venv-clone/Scripts/python.exe backend/scripts/fetch_openvoice_ckpt.py
"""
from __future__ import annotations

import os
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DST = os.path.join(REPO, "backend", "data", "openvoice")

#: (仓库内相对路径, 下载源 base)
#: 主源是 hf-mirror；官方文档里的 S3 地址实测已 404，故不再作为首选。
_SOURCES = [
    "https://hf-mirror.com/myshell-ai/OpenVoice/resolve/main",
]

NEEDED = [
    "checkpoints/base_speakers/ZH/checkpoint.pth",
    "checkpoints/base_speakers/ZH/config.json",
    "checkpoints/base_speakers/ZH/zh_default_se.pth",
    "checkpoints/base_speakers/EN/checkpoint.pth",
    "checkpoints/base_speakers/EN/config.json",
    "checkpoints/base_speakers/EN/en_default_se.pth",
    "checkpoints/converter/checkpoint.pth",
    "checkpoints/converter/config.json",
]


def _download(rel: str) -> bool:
    url = f"{_SOURCES[0]}/{rel}"
    dst = os.path.join(DST, *rel.split("/"))
    if os.path.isfile(dst) and os.path.getsize(dst) > 0:
        return True
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".part"
    print(f"  下载 {rel} ...")
    try:
        with urllib.request.urlopen(url, timeout=600) as resp, open(tmp, "wb") as fh:
            shutil_copyfileobj(resp, fh)
    except Exception as e:  # noqa: BLE001
        print(f"  失败：{e}")
        if os.path.exists(tmp):
            os.remove(tmp)
        return False
    os.replace(tmp, dst)
    print(f"    {rel}  {os.path.getsize(dst) / 1024 / 1024:.1f} MB")
    return True


def shutil_copyfileobj(src, dst) -> None:
    """复制内容（用 shutil 而不是手写循环）"""
    import shutil

    shutil.copyfileobj(src, dst)


def main() -> int:
    print(f"目标目录：{DST}")
    ok = True
    for rel in NEEDED:
        if not _download(rel):
            ok = False
    if not ok:
        print("\n有文件没下下来。重跑本脚本会跳过已下好的，直接续传即可。")
        return 1
    print("\n完成。MeloTTS 中文模型首次合成时会由 huggingface_hub 自动下载"
          "（worker 里已设 HF_ENDPOINT=https://hf-mirror.com）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
