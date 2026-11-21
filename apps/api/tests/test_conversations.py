from __future__ import annotations

from otp_helpers import register_user


def _register(client, otp_mail, email: str) -> dict[str, str]:
    reg = register_user(client, otp_mail, email)
    token = reg["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_delete_own_conversation(client, otp_mail):
    from uuid import UUID

    from lawbot.db.models import Message
    from lawbot.db.session import get_sessionmaker
    from app.config import get_settings

    headers = _register(client, otp_mail, "conv-del-a@example.com")
    created = client.post("/api/v1/conversations", headers=headers, json={"title": "待删"})
    assert created.status_code == 200
    cid = created.json()["id"]

    session = get_sessionmaker(get_settings().database_url)()
    try:
        session.add(Message(conversation_id=UUID(cid), role="user", content="你好"))
        session.commit()
    finally:
        session.close()

    before_msgs = client.get(f"/api/v1/conversations/{cid}/messages", headers=headers)
    assert before_msgs.status_code == 200
    assert len(before_msgs.json()) >= 1

    listed = client.get("/api/v1/conversations", headers=headers)
    assert listed.status_code == 200
    assert any(c["id"] == cid for c in listed.json())

    deleted = client.delete(f"/api/v1/conversations/{cid}", headers=headers)
    assert deleted.status_code == 204

    listed_after = client.get("/api/v1/conversations", headers=headers)
    assert listed_after.status_code == 200
    assert all(c["id"] != cid for c in listed_after.json())

    messages = client.get(f"/api/v1/conversations/{cid}/messages", headers=headers)
    assert messages.status_code == 404


def test_cannot_delete_others_conversation(client, otp_mail):
    headers_a = _register(client, otp_mail, "conv-del-owner@example.com")
    headers_b = _register(client, otp_mail, "conv-del-other@example.com")

    created = client.post("/api/v1/conversations", headers=headers_a, json={})
    assert created.status_code == 200
    cid = created.json()["id"]

    denied = client.delete(f"/api/v1/conversations/{cid}", headers=headers_b)
    assert denied.status_code == 404

    still = client.get(f"/api/v1/conversations/{cid}", headers=headers_a)
    assert still.status_code == 200
    assert still.json()["id"] == cid


def test_delete_conversation_requires_auth(client, otp_mail):
    headers = _register(client, otp_mail, "conv-del-auth@example.com")
    created = client.post("/api/v1/conversations", headers=headers, json={})
    cid = created.json()["id"]

    resp = client.delete(f"/api/v1/conversations/{cid}")
    assert resp.status_code == 401
