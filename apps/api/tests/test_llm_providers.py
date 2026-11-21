def _admin_headers(client, admin_user):
    resp = client.post(
        "/api/admin/auth/login",
        json={"email": "root", "password": "Admin123!"},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


from otp_helpers import register_user


def test_user_forbidden_on_llm_providers(client, otp_mail):
    reg = register_user(client, otp_mail, "u_llm01@example.com")
    token = reg["access_token"]
    resp = client.get(
        "/api/admin/llm-providers",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    catalog = client.get(
        "/api/admin/llm-providers/catalog",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert catalog.status_code == 403


def test_provider_catalog(client, admin_user):
    headers = _admin_headers(client, admin_user)
    resp = client.get("/api/admin/llm-providers/catalog", headers=headers)
    assert resp.status_code == 200, resp.text
    providers = resp.json()["providers"]
    by_value = {p["value"]: p for p in providers}
    assert "deepseek" in by_value
    deepseek_models = {m["value"] for m in by_value["deepseek"]["models"]}
    assert "deepseek-chat" in deepseek_models
    assert "__custom__" in deepseek_models
    assert by_value["deepseek"]["models"][-1]["value"] == "__custom__"
    assert "zhipu" in by_value and "moonshot" in by_value


def test_provider_crud_and_redaction(client, admin_user):
    headers = _admin_headers(client, admin_user)
    create = client.post(
        "/api/admin/llm-providers",
        headers=headers,
        json={
            "name": "DeepSeek Dev",
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com",
            "api_key": "sk-secret-key-value-123456",
            "default_model": "deepseek-chat",
            "priority": 10,
            "enabled": True,
        },
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert "api_key" not in body
    assert body["api_key_masked"] != "sk-secret-key-value-123456"
    assert "****" in body["api_key_masked"]
    assert "sk-secret-key-value-123456" not in create.text
    provider_id = body["id"]

    listed = client.get("/api/admin/llm-providers", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["api_key_masked"]
    assert "sk-secret-key-value-123456" not in listed.text

    patched = client.patch(
        f"/api/admin/llm-providers/{provider_id}",
        headers=headers,
        json={"priority": 1, "api_key": "sk-rotated-new-key-9999"},
    )
    assert patched.status_code == 200
    assert "sk-rotated-new-key-9999" not in patched.text
    assert patched.json()["priority"] == 1

    deleted = client.delete(f"/api/admin/llm-providers/{provider_id}", headers=headers)
    assert deleted.status_code == 204


def test_provider_test_endpoint_ok_and_no_raw_key(client, admin_user, monkeypatch):
    headers = _admin_headers(client, admin_user)
    secret = "sk-secret-key-value-123456"
    create = client.post(
        "/api/admin/llm-providers",
        headers=headers,
        json={
            "name": "Test Conn",
            "provider": "openai_compatible",
            "base_url": "https://example.invalid/v1",
            "api_key": secret,
            "default_model": "demo-model",
            "priority": 5,
            "enabled": True,
        },
    )
    assert create.status_code == 201, create.text
    provider_id = create.json()["id"]

    monkeypatch.setattr(
        "app.routers.admin.llm_providers.test_provider_connectivity",
        lambda **_kwargs: (True, "连通正常", None),
    )
    tested = client.post(f"/api/admin/llm-providers/{provider_id}/test", headers=headers)
    assert tested.status_code == 200, tested.text
    body = tested.json()
    assert body["ok"] is True
    assert body["message"] == "连通正常"
    assert body.get("detail") is None
    assert secret not in tested.text
    assert "api_key" not in body


def test_humanize_connectivity_error_zh():
    from lawbot.llm.client import humanize_connectivity_error

    assert "API Key" in humanize_connectivity_error(Exception("AuthenticationError: Invalid API Key"))
    assert "超时" in humanize_connectivity_error(Exception("Request timed out"))
    assert "无法连接" in humanize_connectivity_error(Exception("Connection refused"))
    assert "模型" in humanize_connectivity_error(Exception("model_not_found: demo"))
    assert humanize_connectivity_error(Exception("weird upstream xyz")).startswith("连通失败：")


def test_knowledge_import_job_list(client, admin_user):
    headers = _admin_headers(client, admin_user)
    created = client.post(
        "/api/admin/knowledge-import-jobs",
        headers=headers,
        json={"source": "manual", "config": {"note": "ops"}},
    )
    assert created.status_code == 201
    assert created.json()["status"] == "pending"
    listed = client.get("/api/admin/knowledge-import-jobs", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) >= 1
