"""批量给 api.py 端点加权限依赖（一次性脚本）"""
import re

with open("api/api.py", encoding="utf-8") as f:
    src = f.read()

# 函数名 → 依赖函数名
patches = {
    "def create_character(": "require_approved",
    "def upload_character_avatar(": "require_approved",
    "def save_profile(": "require_approved",
    "def add_long_memory(": "require_approved",
    "def update_long_memory(": "require_approved",
    "def delete_long_memory(": "require_approved",
    "def add_event(": "require_approved",
    "def add_memory_rag(": "require_approved",
    "def update_memory_rag(": "require_approved",
    "def delete_memory_rag(": "require_approved",
    "def clear_memory(": "require_approved",
    "def create_world_event(": "require_approved",
    "def update_world_event(": "require_approved",
    "def world_tick(": "require_approved",
    "def simulate_world_interaction(": "require_approved",
    "def switch_character(": "require_approved",
}

dep_snippet = {
    "require_approved": "user = Depends(require_approved)",
    "require_auth": "user = Depends(require_auth)",
}

for fn_name, dep in patches.items():
    if fn_name not in src:
        print(f"SKIP: {fn_name} (not found)")
        continue
    idx = src.index(fn_name)
    paren_start = idx + len(fn_name)
    depth = 1
    i = paren_start
    while i < len(src) and depth > 0:
        if src[i] == "(": depth += 1
        elif src[i] == ")": depth -= 1
        i += 1
    sig_end = i
    # 在闭括号前插入参数
    new_sig = src[idx : sig_end - 1] + ", " + dep_snippet[dep]
    src = src[:idx] + new_sig + src[sig_end - 1 :]
    print(f"OK: {fn_name} + {dep}")

with open("api/api.py", "w", encoding="utf-8", newline="\n") as f:
    f.write(src)
print("done")
