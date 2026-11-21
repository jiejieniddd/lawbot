from __future__ import annotations

import io

from otp_helpers import register_user


def _token(client, otp_mail, email: str = "resume01@example.com"):
    reg = register_user(client, otp_mail, email, display_name="Resume")
    return reg["access_token"]


def test_upload_docx_resume_and_active(client, otp_mail, tmp_path, monkeypatch):
    from docx import Document

    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("RESUME_UPLOAD_DIR", str(tmp_path / "resumes"))
    get_settings.cache_clear()

    doc = Document()
    doc.add_paragraph("求职意向：Python 后端")
    doc.add_paragraph("技能：Python FastAPI Docker Redis")
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)

    token = _token(client, otp_mail)
    headers = {"Authorization": f"Bearer {token}"}
    files = {
        "file": (
            "cv.docx",
            buf,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    resp = client.post("/api/v1/me/resumes", headers=headers, files=files)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["parse_status"] == "ready"
    assert any(s.lower() == "python" for s in body.get("skills") or [])

    active = client.get("/api/v1/me/resumes/active", headers=headers)
    assert active.status_code == 200
    assert active.json()["resume"]["id"] == body["id"]

    rid = body["id"]
    deleted = client.delete(f"/api/v1/me/resumes/{rid}", headers=headers)
    assert deleted.status_code == 204

    get_settings.cache_clear()


def test_upload_resume_unauthorized(client):
    files = {"file": ("x.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")}
    resp = client.post("/api/v1/me/resumes", files=files)
    assert resp.status_code == 401


def test_self_quiz_empty_index(client, otp_mail, tmp_path, monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("RAG_SELF_TEST_DIR", str(tmp_path / "empty_self_test"))
    get_settings.cache_clear()

    token = _token(client, otp_mail, "quiz01@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post("/api/v1/self-quiz", headers=headers, json={})
    assert resp.status_code == 503

    get_settings.cache_clear()
