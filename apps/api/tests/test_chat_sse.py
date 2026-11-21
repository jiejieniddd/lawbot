from otp_helpers import register_user


def test_chat_sse_flow(client, otp_mail):
    reg = register_user(client, otp_mail, "chat01@example.com")
    token = reg["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    conv = client.post("/api/v1/conversations", headers=headers, json={})
    assert conv.status_code == 200
    conversation_id = conv.json()["id"]

    with client.stream(
        "POST",
        "/api/v1/chat",
        headers=headers,
        json={"conversation_id": conversation_id, "content": "劳动合同纠纷咨询"},
    ) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
        assert "data:" in body
        assert "token" in body or "done" in body
        assert "citation" in body or "done" in body
