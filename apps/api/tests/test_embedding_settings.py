from __future__ import annotations

from app.config import get_settings
from lawbot.crypto import decrypt_secret
from lawbot.db.models import EmbeddingSettings


def _root_headers(client, admin_user) -> dict:
    resp = client.post(
        "/api/admin/auth/login",
        json={"email": "root", "password": "Admin123!"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _ops_headers(client, normal_admin) -> dict:
    resp = client.post(
        "/api/admin/auth/login",
        json={"email": "ops@lawbot.local", "password": "OpsPass12"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _emb_body(**overrides) -> dict:
    body = {
        "mode": "litellm",
        "embedding_model": "text-embedding-v3",
        "api_key": "sk-emb-test-key",
        "api_base": "https://example.invalid/v1",
        "embedding_dim": 1024,
        "reuse_llm_provider": False,
    }
    body.update(overrides)
    return body


def test_embedding_settings_requires_permission(client, normal_admin):
    ops = _ops_headers(client, normal_admin)
    denied = client.put(
        "/api/admin/settings/embedding",
        headers=ops,
        json=_emb_body(),
    )
    assert denied.status_code == 403
    readable = client.get("/api/admin/settings/embedding", headers=ops)
    assert readable.status_code == 200


def test_embedding_get_hides_api_key_and_shows_effective(client, admin_user):
    root = _root_headers(client, admin_user)
    resp = client.get("/api/admin/settings/embedding", headers=root)
    assert resp.status_code == 200
    data = resp.json()
    assert "api_key" not in data
    assert "api_key_encrypted" not in data
    assert "api_key_configured" in data
    assert "effective_mode" in data
    assert "reindex_required_hint" in data
    assert "重" in data["reindex_required_hint"] or "导入" in data["reindex_required_hint"]


def test_embedding_save_encrypts_and_empty_key_keeps_old(client, admin_user, db_session):
    root = _root_headers(client, admin_user)
    saved = client.put(
        "/api/admin/settings/embedding",
        headers=root,
        json=_emb_body(),
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["api_key_configured"] is True
    assert "sk-emb-test-key" not in saved.text
    assert "api_key" not in body
    assert body["embedding_model"] == "text-embedding-v3"
    assert body["embedding_dim"] == 1024
    assert "detail" in body and "导入" in body["detail"]

    db_session.expire_all()
    row = db_session.get(EmbeddingSettings, 1)
    assert row is not None
    assert row.api_key_encrypted != "sk-emb-test-key"
    settings = get_settings()
    plain = decrypt_secret(
        row.api_key_encrypted,
        encryption_key=settings.encryption_key or None,
        jwt_secret=settings.secret_key,
    )
    assert plain == "sk-emb-test-key"

    again = client.put(
        "/api/admin/settings/embedding",
        headers=root,
        json=_emb_body(api_key="", embedding_model="text-embedding-v2"),
    )
    assert again.status_code == 200, again.text
    assert again.json()["embedding_model"] == "text-embedding-v2"
    assert again.json()["api_key_configured"] is True
    db_session.expire_all()
    row2 = db_session.get(EmbeddingSettings, 1)
    assert row2 is not None
    plain2 = decrypt_secret(
        row2.api_key_encrypted,
        encryption_key=settings.encryption_key or None,
        jwt_secret=settings.secret_key,
    )
    assert plain2 == "sk-emb-test-key"


def test_embedding_litellm_requires_model(client, admin_user):
    root = _root_headers(client, admin_user)
    resp = client.put(
        "/api/admin/settings/embedding",
        headers=root,
        json=_emb_body(embedding_model=""),
    )
    assert resp.status_code == 400
    assert "embedding_model" in resp.json()["detail"] or "模型" in resp.json()["detail"]


def test_embedding_test_fake_ok(client, admin_user):
    root = _root_headers(client, admin_user)
    client.put(
        "/api/admin/settings/embedding",
        headers=root,
        json=_emb_body(mode="fake", embedding_model="", api_key=""),
    )
    resp = client.post(
        "/api/admin/settings/embedding/test",
        headers=root,
        json={"mode": "fake", "embedding_dim": 384},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["dim"] == 384
    assert "假" in data["detail"] or "fake" in data["detail"].lower()


def test_embedding_test_litellm_mock(client, admin_user, monkeypatch):
    root = _root_headers(client, admin_user)
    client.put(
        "/api/admin/settings/embedding",
        headers=root,
        json=_emb_body(),
    )

    class _Resp:
        data = [{"embedding": [0.1] * 1024}]

    def fake_embedding(**_kwargs):
        return _Resp()

    monkeypatch.setattr("litellm.embedding", fake_embedding)

    resp = client.post(
        "/api/admin/settings/embedding/test",
        headers=root,
        json={},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["dim"] == 1024


def test_embedding_test_failure_chinese(client, admin_user, monkeypatch):
    root = _root_headers(client, admin_user)
    client.put(
        "/api/admin/settings/embedding",
        headers=root,
        json=_emb_body(),
    )

    def boom(**_kwargs):
        raise RuntimeError("upstream timeout")

    monkeypatch.setattr("litellm.embedding", boom)

    resp = client.post(
        "/api/admin/settings/embedding/test",
        headers=root,
        json={},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "超时" in detail


def test_format_embedding_call_error_maps_common_cases():
    from app.services.embedding_config import format_embedding_call_error

    assert "API Key" in format_embedding_call_error(RuntimeError("Invalid API Key"))
    assert "向量模型" in format_embedding_call_error(
        RuntimeError("model_not_found: kimi-k3.1-pro does not exist"),
        model="kimi-k3.1-pro",
    )
    assert "限流" in format_embedding_call_error(RuntimeError("429 rate limit exceeded"))
    assert "API Base" in format_embedding_call_error(RuntimeError("Connection refused to host"))
    assert "维度" in format_embedding_call_error(RuntimeError("dimension mismatch embedding size"))
    assert "openai/" in format_embedding_call_error(
        RuntimeError("litellm.BadRequestError: LLM Provider NOT provided. Pass in the LLM provider")
    )


def test_normalize_embedding_model_adds_openai_prefix():
    from lawbot.knowledge.embedder import normalize_embedding_model

    assert (
        normalize_embedding_model(
            "qwen3.7-text-embedding-flash",
            "https://example.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        )
        == "openai/qwen3.7-text-embedding-flash"
    )
    assert normalize_embedding_model("openai/text-embedding-v3", None) == "openai/text-embedding-v3"
    assert normalize_embedding_model("text-embedding-v3", None) == "openai/text-embedding-v3"
