"""3D 模型 API 集成测试：/character/model 上传 / 配置 / 删除 / 权限。

依赖 conftest 的 session 级 TestClient + function 级 tmp_data_dir（cwd 隔离）。
"""
import json
import os
import uuid
from pathlib import Path

import pytest

CHAR_ID = "linwan"


def _unique(prefix="user"):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def admin_token(client):
    r = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture
def approved_user(client, admin_token):
    """注册 + admin 审批通过，返回 (token, user_id)。"""
    name = _unique()
    pwd = "pass1234"
    reg = client.post("/auth/register", json={"username": name, "password": pwd})
    assert reg.status_code == 200, reg.text
    user_id = reg.json()["user"]["id"]

    apv = client.post(f"/auth/admin/approve/{user_id}",
                      headers={"Authorization": f"Bearer {admin_token}"})
    assert apv.status_code == 200, apv.text

    lg = client.post("/auth/login", json={"username": name, "password": pwd})
    assert lg.status_code == 200, lg.text
    return lg.json()["token"], user_id


@pytest.fixture(autouse=True)
def _clear_character_cache():
    """角色文件有 mtime 缓存（类属性），跨测试的 tmp 目录可能撞 mtime，先清干净。"""
    from funcation.memory_center import MemoryCenter
    MemoryCenter._character_cache.clear()
    yield
    MemoryCenter._character_cache.clear()


@pytest.fixture
def auth(approved_user):
    token, _uid = approved_user
    return {"Authorization": f"Bearer {token}"}


def _model_files():
    """当前 cwd（测试私有 tmp）下 data/models 里已落盘的模型文件。"""
    d = Path("data/models")
    if not d.exists():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_file() and not p.name.startswith("."))


def _char_json(char_id=CHAR_ID):
    return json.loads((Path("data/characters") / f"{char_id}.json").read_text(encoding="utf-8"))


# ---------- GET ----------

def test_get_model_unconfigured(client, tmp_data_dir, auth):
    r = client.get(f"/character/model?character_id={CHAR_ID}", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["character_id"] == CHAR_ID
    assert body["model3d"] is None
    assert body["max_size_mb"] > 0
    assert "neutral" in body["supported_expressions"]


def test_get_model_requires_auth(client, tmp_data_dir):
    r = client.get(f"/character/model?character_id={CHAR_ID}")
    assert r.status_code in (401, 403), r.text


def test_get_model_unknown_character_404(client, tmp_data_dir, auth):
    r = client.get("/character/model?character_id=no_such_char", headers=auth)
    assert r.status_code == 404, r.text


# ---------- 上传 ----------

def test_upload_vrm_binds_to_character(client, tmp_data_dir, auth):
    payload = b"glTF-fake-binary" * 64
    r = client.post(
        f"/character/model?character_id={CHAR_ID}",
        files={"file": ("avatar.vrm", payload, "application/octet-stream")},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["message"] == "模型上传成功"
    cfg = body["model3d"]
    assert cfg["format"] == "vrm"
    assert cfg["url"].startswith(f"/models/{CHAR_ID}_")
    assert cfg["enabled"] is True

    # 文件真的落盘 + 内容一致
    files = _model_files()
    assert len(files) == 1, files
    assert Path("data/models", files[0]).read_bytes() == payload

    # 角色 JSON 已写入 model3d
    saved = _char_json()
    assert saved["model3d"]["url"] == cfg["url"]

    # GET 能读回同一份配置
    got = client.get(f"/character/model?character_id={CHAR_ID}", headers=auth).json()
    assert got["model3d"]["url"] == cfg["url"]


def test_upload_glb_uses_glb_format(client, tmp_data_dir, auth):
    r = client.post(
        f"/character/model?character_id={CHAR_ID}",
        files={"file": ("avatar.glb", b"x" * 128, "model/gltf-binary")},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["model3d"]["format"] == "glb"
    assert _model_files()[0].endswith(".glb")


def test_upload_rejects_unsupported_extension(client, tmp_data_dir, auth):
    r = client.post(
        f"/character/model?character_id={CHAR_ID}",
        files={"file": ("virus.exe", b"MZ" * 32, "application/octet-stream")},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert "error" in r.json()
    # 不留残渣（临时 .part 也要清掉）
    assert _model_files() == []
    assert "model3d" not in _char_json()


def test_upload_rejects_oversize(client, tmp_data_dir, auth, monkeypatch):
    monkeypatch.setenv("MODEL_MAX_MB", "0.001")  # ≈1KB
    r = client.post(
        f"/character/model?character_id={CHAR_ID}",
        files={"file": ("big.vrm", b"y" * 5000, "application/octet-stream")},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert "过大" in r.json()["error"]
    assert _model_files() == []


def test_reupload_replaces_and_cleans_old_file(client, tmp_data_dir, auth):
    first = client.post(
        f"/character/model?character_id={CHAR_ID}",
        files={"file": ("a.vrm", b"a" * 100, "application/octet-stream")},
        headers=auth,
    ).json()["model3d"]["url"]

    second = client.post(
        f"/character/model?character_id={CHAR_ID}",
        files={"file": ("b.vrm", b"b" * 100, "application/octet-stream")},
        headers=auth,
    ).json()["model3d"]["url"]

    assert first != second
    files = _model_files()
    assert len(files) == 1, files  # 旧文件被清理
    assert Path("data/models", files[0]).read_bytes() == b"b" * 100


def test_upload_requires_approved(client, tmp_data_dir):
    """pending 用户（未审批）不能上传模型。"""
    name = _unique()
    client.post("/auth/register", json={"username": name, "password": "pass1234"})
    token = client.post("/auth/login",
                        json={"username": name, "password": "pass1234"}).json()["token"]
    r = client.post(
        f"/character/model?character_id={CHAR_ID}",
        files={"file": ("a.vrm", b"z" * 10, "application/octet-stream")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403, r.text


# ---------- 配置 ----------

def test_config_requires_existing_model(client, tmp_data_dir, auth):
    r = client.post(f"/character/model/config?character_id={CHAR_ID}",
                    json={"scale": 1.5}, headers=auth)
    assert r.status_code == 200, r.text
    assert "error" in r.json()


def test_config_can_create_from_external_url(client, tmp_data_dir, auth):
    r = client.post(
        f"/character/model/config?character_id={CHAR_ID}",
        json={"url": "https://cdn.example.com/char.glb"},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    cfg = r.json()["model3d"]
    assert cfg["url"] == "https://cdn.example.com/char.glb"
    assert cfg["format"] == "glb"


def test_config_clamps_and_persists(client, tmp_data_dir, auth):
    client.post(f"/character/model?character_id={CHAR_ID}",
                files={"file": ("a.vrm", b"a" * 100, "application/octet-stream")},
                headers=auth)

    r = client.post(
        f"/character/model/config?character_id={CHAR_ID}",
        json={"scale": 99, "camera_fov": 200, "default_expression": "excited",
              "auto_rotate": True},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    cfg = r.json()["model3d"]
    assert cfg["scale"] == 5.0            # clamp 上界
    assert cfg["camera_fov"] == 90.0      # clamp 上界
    assert cfg["default_expression"] == "neutral"  # 非法表情回退
    assert cfg["auto_rotate"] is True
    assert cfg["url"].startswith("/models/")       # 未传 url 时保留原值

    # 落盘 + GET 一致
    assert _char_json()["model3d"]["scale"] == 5.0
    assert client.get(f"/character/model?character_id={CHAR_ID}",
                      headers=auth).json()["model3d"]["scale"] == 5.0


def test_config_partial_update_keeps_other_fields(client, tmp_data_dir, auth):
    client.post(f"/character/model?character_id={CHAR_ID}",
                files={"file": ("a.vrm", b"a" * 100, "application/octet-stream")},
                headers=auth)
    client.post(f"/character/model/config?character_id={CHAR_ID}",
                json={"scale": 1.7, "camera_distance": 2.2}, headers=auth)
    r = client.post(f"/character/model/config?character_id={CHAR_ID}",
                    json={"camera_fov": 45}, headers=auth)
    cfg = r.json()["model3d"]
    assert cfg["scale"] == 1.7
    assert cfg["camera_distance"] == 2.2
    assert cfg["camera_fov"] == 45.0


# ---------- 删除 ----------

def test_delete_model_removes_file_and_field(client, tmp_data_dir, auth):
    client.post(f"/character/model?character_id={CHAR_ID}",
                files={"file": ("a.vrm", b"a" * 100, "application/octet-stream")},
                headers=auth)
    assert _model_files()

    r = client.delete(f"/character/model?character_id={CHAR_ID}", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["model3d"] is None
    assert _model_files() == []
    assert "model3d" not in _char_json()
    assert client.get(f"/character/model?character_id={CHAR_ID}",
                      headers=auth).json()["model3d"] is None


def test_delete_without_model_is_noop(client, tmp_data_dir, auth):
    r = client.delete(f"/character/model?character_id={CHAR_ID}", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["model3d"] is None


def test_delete_does_not_touch_external_url(client, tmp_data_dir, auth):
    """外链 URL 不是本服务托管文件，删除时不应误删本地目录内容。"""
    client.post(f"/character/model/config?character_id={CHAR_ID}",
                json={"url": "https://cdn.example.com/x.vrm"}, headers=auth)
    client.delete(f"/character/model?character_id={CHAR_ID}", headers=auth)
    assert _model_files() == []


# ---------- 权限隔离 ----------

def test_other_users_character_is_forbidden(client, tmp_data_dir, auth):
    """普通用户不能给别人的角色配模型 → 403。"""
    other = {"id": "char_other", "name": "别人的角色", "created_by": 999999}
    (Path("data/characters") / "char_other.json").write_text(
        json.dumps(other, ensure_ascii=False), encoding="utf-8")

    r = client.get("/character/model?character_id=char_other", headers=auth)
    assert r.status_code == 403, r.text

    r = client.post("/character/model?character_id=char_other",
                    files={"file": ("a.vrm", b"a" * 10, "application/octet-stream")},
                    headers=auth)
    assert r.status_code == 403, r.text


# ---------- 列表摘要 ----------

def test_characters_list_exposes_model_summary(client, tmp_data_dir, auth):
    client.post(f"/character/model?character_id={CHAR_ID}",
                files={"file": ("a.vrm", b"a" * 100, "application/octet-stream")},
                headers=auth)

    r = client.get("/characters", headers=auth)
    assert r.status_code == 200, r.text
    chars = {c["id"]: c for c in r.json()["characters"]}
    assert chars[CHAR_ID]["model3d"]["format"] == "vrm"
    # 未配置的角色为 null
    assert chars.get("maid", {}).get("model3d") is None


# ---------- 清理失败必须降级（真实踩到的坑） ----------

def _boom_remove(*_args, **_kwargs):
    """模拟 os.remove 被环境拦下：Windows 文件占用 / 杀软 / 沙箱包装层。

    注意 SystemExit 是 BaseException，`except Exception` 接不住——
    某些沙箱 shim 正是用它表达「拒绝删除」。
    """
    raise SystemExit(1)


def test_delete_survives_file_removal_failure(client, tmp_data_dir, auth, monkeypatch):
    """文件删不掉时，DELETE 仍要解绑成功并返回 warning，不能 500。"""
    import api.api as api_module

    url = client.post(f"/character/model?character_id={CHAR_ID}",
                      files={"file": ("a.vrm", b"a" * 100, "application/octet-stream")},
                      headers=auth).json()["model3d"]["url"]

    monkeypatch.setattr(api_module.os, "remove", _boom_remove)
    r = client.delete(f"/character/model?character_id={CHAR_ID}", headers=auth)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model3d"] is None
    assert "warning" in body

    # 解绑落盘了，但文件还在（如实反映）
    assert "model3d" not in _char_json()
    assert os.path.basename(url) in _model_files()


def test_delete_without_warning_when_file_removed(client, tmp_data_dir, auth):
    """正常删除时不带 warning 字段。"""
    client.post(f"/character/model?character_id={CHAR_ID}",
                files={"file": ("a.vrm", b"a" * 100, "application/octet-stream")},
                headers=auth)
    r = client.delete(f"/character/model?character_id={CHAR_ID}", headers=auth)
    assert r.status_code == 200
    assert "warning" not in r.json()


def test_reupload_survives_old_file_cleanup_failure(client, tmp_data_dir, auth, monkeypatch):
    """旧文件清不掉也不能影响新模型上传。"""
    import api.api as api_module

    client.post(f"/character/model?character_id={CHAR_ID}",
                files={"file": ("old.vrm", b"o" * 100, "application/octet-stream")},
                headers=auth)

    monkeypatch.setattr(api_module.os, "remove", _boom_remove)
    r = client.post(f"/character/model?character_id={CHAR_ID}",
                    files={"file": ("new.vrm", b"n" * 100, "application/octet-stream")},
                    headers=auth)

    assert r.status_code == 200, r.text
    assert r.json()["model3d"]["format"] == "vrm"
    files = _model_files()
    assert len(files) == 2, files  # 旧的残留 + 新的
    # 角色指向的是新文件，且新文件内容正确
    new_url = _char_json()["model3d"]["url"]
    assert Path("data/models", os.path.basename(new_url)).read_bytes() == b"n" * 100
    assert b"o" * 100 in {Path("data/models", f).read_bytes() for f in files}


# ---------- 默认角色路径（不带 character_id） ----------

def test_default_character_path_after_switch(client, tmp_data_dir, auth):
    client.post("/character/switch", json={"character_id": "maid"}, headers=auth)
    r = client.get("/character/model", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["character_id"] == "maid"
