from __future__ import annotations

import io

# 1x1 PNG
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _register(client, email: str = "avatar01"):
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret12", "display_name": "Avatar"},
    )
    assert reg.status_code == 200
    return reg.json()["access_token"]


def test_upload_avatar_ok(client):
    token = _register(client)
    headers = {"Authorization": f"Bearer {token}"}
    files = {"file": ("a.png", io.BytesIO(_PNG), "image/png")}
    resp = client.post("/api/v1/auth/me/avatar", headers=headers, files=files)
    assert resp.status_code == 200
    body = resp.json()
    assert body["avatar_url"]
    assert body["avatar_url"].startswith("/uploads/avatars/")
    assert body["avatar_url"].endswith(".png")

    static = client.get(body["avatar_url"])
    assert static.status_code == 200
    assert static.content[:8] == b"\x89PNG\r\n\x1a\n"

    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["avatar_url"] == body["avatar_url"]


def test_upload_avatar_rejects_non_image(client):
    token = _register(client, "badtype01")
    headers = {"Authorization": f"Bearer {token}"}
    files = {"file": ("x.txt", io.BytesIO(b"hello"), "text/plain")}
    resp = client.post("/api/v1/auth/me/avatar", headers=headers, files=files)
    assert resp.status_code == 400


def test_upload_avatar_rejects_too_large(client, monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("AVATAR_MAX_BYTES", "64")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.avatar_max_bytes == 64

    token = _register(client, "bigfile01")
    headers = {"Authorization": f"Bearer {token}"}
    blob = b"x" * 128
    files = {"file": ("big.png", io.BytesIO(blob), "image/png")}
    resp = client.post("/api/v1/auth/me/avatar", headers=headers, files=files)
    assert resp.status_code == 400

    monkeypatch.setenv("AVATAR_MAX_BYTES", "2097152")
    get_settings.cache_clear()


def test_upload_avatar_unauthorized(client):
    files = {"file": ("a.png", io.BytesIO(_PNG), "image/png")}
    resp = client.post("/api/v1/auth/me/avatar", files=files)
    assert resp.status_code == 401


def test_delete_avatar(client):
    token = _register(client, "delavatar01")
    headers = {"Authorization": f"Bearer {token}"}
    files = {"file": ("a.png", io.BytesIO(_PNG), "image/png")}
    up = client.post("/api/v1/auth/me/avatar", headers=headers, files=files)
    assert up.status_code == 200
    url = up.json()["avatar_url"]

    deleted = client.delete("/api/v1/auth/me/avatar", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["avatar_url"] is None

    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.json()["avatar_url"] is None
    # file may be gone; static 404 is fine
    assert client.get(url).status_code in (200, 404)
