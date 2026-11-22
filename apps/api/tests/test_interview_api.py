from __future__ import annotations

import io
import uuid

from otp_helpers import register_user


def _token(client, otp_mail, email: str = "iv01@example.com"):
    reg = register_user(client, otp_mail, email, display_name="Interview")
    return reg["access_token"]


def _upload_resume(client, headers, tmp_path, monkeypatch, *, skills_line: str = "技能：Python FastAPI Docker"):
    from docx import Document

    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("RESUME_UPLOAD_DIR", str(tmp_path / "resumes"))
    get_settings.cache_clear()

    doc = Document()
    doc.add_paragraph("求职意向：Python 后端")
    doc.add_paragraph(skills_line)
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    files = {
        "file": (
            "cv.docx",
            buf,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    resp = client.post("/api/v1/me/resumes", headers=headers, files=files)
    assert resp.status_code == 201, resp.text
    get_settings.cache_clear()
    return resp.json()


class _FakeChunk:
    def __init__(self, title: str, text: str):
        self.citation = type(
            "C",
            (),
            {
                "law_name": title,
                "text": text,
                "source_id": "interview_zh:should-not-leak",
                "domain": "interview_qa",
            },
        )()
        self.score = 1.0


class _FakeRetriever:
    def retrieve(self, query: str, top_k: int = 3, *, domains=None):
        _ = query, domains
        return [
            _FakeChunk("请解释 GIL 对多线程的影响？", "GIL 限制同一进程同时执行字节码…"),
            _FakeChunk("FastAPI Depends 怎么用？", "Depends 声明可复用依赖…"),
            _FakeChunk("如何设计幂等接口？", "幂等键、去重表…"),
            _FakeChunk("Docker 多阶段构建的好处？", "减小镜像、分离构建…"),
            _FakeChunk("Redis 缓存穿透怎么防？", "空值缓存、布隆过滤…"),
            _FakeChunk("讲讲你的项目亮点", "STAR…"),
            _FakeChunk("线上 CPU 飙高怎么查", "profile…"),
            _FakeChunk("你的职业规划", "学习路径…"),
        ][:top_k]


def _answer_all(client, headers, sid: str, *, n: int = 5, prefix: str = "作答"):
    last = None
    for i in range(n):
        ans = client.post(
            f"/api/v1/interview/sessions/{sid}/answer",
            headers=headers,
            json={"answer": f"{prefix} 第{i+1}题完整说明，含原理与实践。" * 2},
        )
        assert ans.status_code == 200, ans.text
        last = ans.json()
    return last


def test_interview_without_resume_with_role(client, otp_mail, monkeypatch):
    from app import retriever_dep

    monkeypatch.setattr(retriever_dep, "get_retriever", lambda: _FakeRetriever())

    token = _token(client, otp_mail, "iv-no-resume@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/api/v1/interview/sessions",
        headers=headers,
        json={"question_count": 5, "target_role": "后端开发"},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["status"] == "in_progress"
    assert body["question_count"] == 5
    q1 = body["current_question"]["question"]
    assert "这个项目" not in q1
    assert "你的项目" not in q1
    assert "简历" not in q1
    # Dynamic: only first turn exists until answers arrive
    assert body["answered_count"] == 0
    sid = body["id"]

    done = _answer_all(client, headers, sid, n=5, prefix="无简历")
    assert done["done"] is True
    report = done["report"]
    assert report.get("has_resume") is False
    note = (report.get("resume_note") or "") + (report.get("advice") or "")
    assert "未提供简历" in note
    assert "total_score" in report
    assert isinstance(report.get("gaps"), list)
    assert "interview_zh:" not in str(report)
    assert len(report.get("turns") or []) == 5


def test_interview_requires_role_or_jd(client, otp_mail):
    token = _token(client, otp_mail, "iv-empty@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post(
        "/api/v1/interview/sessions",
        headers=headers,
        json={"question_count": 5, "target_role": "", "jd_text": ""},
    )
    assert resp.status_code == 400
    assert "岗位" in resp.json()["detail"] or "JD" in resp.json()["detail"]


def test_interview_with_session_jd_text_only(client, otp_mail, monkeypatch):
    from app import retriever_dep

    monkeypatch.setattr(retriever_dep, "get_retriever", lambda: _FakeRetriever())
    token = _token(client, otp_mail, "iv-jd-paste@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    jd = (
        "高级后端工程师\n"
        "要求：Python、FastAPI、PostgreSQL、Redis、Kubernetes\n"
        "职责：负责高并发 API 与稳定性建设"
    )
    created = client.post(
        "/api/v1/interview/sessions",
        headers=headers,
        json={"question_count": 5, "target_role": "", "jd_text": jd},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["target_role"]
    assert "source_id" not in body["current_question"]["question"]
    done = _answer_all(client, headers, body["id"], n=5, prefix="JD场")
    assert done["done"] is True
    assert done["report"]["has_resume"] is False
    assert "未提供简历" in (done["report"].get("resume_note") or done["report"].get("advice") or "")


def test_interview_full_round_and_role_gaps(client, otp_mail, tmp_path, monkeypatch):
    from app import retriever_dep
    from app.config import get_settings

    monkeypatch.setattr(retriever_dep, "get_retriever", lambda: _FakeRetriever())
    get_settings.cache_clear()

    token = _token(client, otp_mail, "iv-full@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    _upload_resume(client, headers, tmp_path, monkeypatch)

    created = client.post(
        "/api/v1/interview/sessions",
        headers=headers,
        json={"question_count": 5, "target_role": "Python 后端工程师"},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["current_question"]
    assert "interview_zh:" not in (body["current_question"]["question"] or "")
    sid = body["id"]

    done = _answer_all(client, headers, sid, n=5, prefix="有简历")
    assert done["done"] is True
    report = done["report"]
    assert report.get("has_resume") is True
    assert "未提供简历" not in (report.get("resume_note") or "")
    blob = str(report)
    assert "简历" in blob or "Python" in blob or "FastAPI" in blob
    assert "source_id=" not in blob

    report_resp = client.get(f"/api/v1/interview/sessions/{sid}/report", headers=headers)
    assert report_resp.status_code == 200
    backend_gaps = " ".join(
        f"{g.get('skill','')} {g.get('suggestion','')}" for g in report_resp.json()["report"]["gaps"]
    )

    # No-resume session for same user should be distinguishable
    created2 = client.post(
        "/api/v1/interview/sessions",
        headers=headers,
        json={"question_count": 5, "target_role": "机器学习工程师"},
    )
    # Still has resume active — delete resume first to get no-resume path contrast via has_resume on another user
    # Contrast roles instead:
    sid2 = created2.json()["id"]
    done2 = _answer_all(client, headers, sid2, n=5, prefix="ML")
    report2 = done2["report"]
    assert report2["target_role"] != report_resp.json()["report"]["target_role"] or "机器" in str(report2)
    ml_gaps = " ".join(f"{g.get('skill','')} {g.get('suggestion','')}" for g in report2["gaps"])
    assert backend_gaps != ml_gaps or report2["target_role"] != report_resp.json()["report"]["target_role"]


def test_interview_with_resume_vs_without(client, otp_mail, tmp_path, monkeypatch):
    from app import retriever_dep

    monkeypatch.setattr(retriever_dep, "get_retriever", lambda: _FakeRetriever())

    # Without resume
    token_a = _token(client, otp_mail, "iv-a@example.com")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    sid_a = client.post(
        "/api/v1/interview/sessions",
        headers=headers_a,
        json={"question_count": 5, "target_role": "后端开发"},
    ).json()["id"]
    report_a = _answer_all(client, headers_a, sid_a)["report"]
    assert report_a["has_resume"] is False

    # With resume
    token_b = _token(client, otp_mail, "iv-b@example.com")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    _upload_resume(client, headers_b, tmp_path, monkeypatch, skills_line="技能：Python FastAPI Redis Kubernetes")
    sid_b = client.post(
        "/api/v1/interview/sessions",
        headers=headers_b,
        json={"question_count": 5, "target_role": "后端开发"},
    ).json()["id"]
    report_b = _answer_all(client, headers_b, sid_b)["report"]
    assert report_b["has_resume"] is True
    assert report_a["has_resume"] != report_b["has_resume"]
    assert "未提供简历" in (report_a.get("resume_note") or report_a.get("advice") or "")
    assert "未提供简历" not in (report_b.get("resume_note") or "")


def test_interview_session_not_found(client, otp_mail):
    token = _token(client, otp_mail, "iv-404@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get(f"/api/v1/interview/sessions/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


def test_no_resume_opening_and_dynamic_project_followup(client, otp_mail, monkeypatch):
    from app import retriever_dep
    from lawbot.agent.interview.runner import build_questions, next_question

    class _ProjectHeavyRetriever(_FakeRetriever):
        def retrieve(self, query: str, top_k: int = 3, *, domains=None):
            _ = query, domains
            return [
                _FakeChunk(
                    "能详细介绍一下你在这个项目中承担的具体角色和职责吗？",
                    "预设项目题，无简历时应被过滤",
                ),
                *_FakeRetriever().retrieve(query, top_k=top_k, domains=domains),
            ][:top_k]

    monkeypatch.setattr(retriever_dep, "get_retriever", lambda: _ProjectHeavyRetriever())

    # Unit: opening must not assume a project
    qs = build_questions(
        count=3,
        target_role="后端开发",
        resume_snapshot={},
        jd_snapshot=None,
        retriever=_ProjectHeavyRetriever(),
    )
    assert qs
    assert "这个项目" not in qs[0].question
    assert "你的项目" not in qs[0].question

    token = _token(client, otp_mail, "iv-dynamic@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/api/v1/interview/sessions",
        headers=headers,
        json={"question_count": 5, "target_role": "后端开发"},
    )
    assert created.status_code == 200, created.text
    q1 = created.json()["current_question"]["question"]
    assert "这个项目" not in q1 and "你的项目" not in q1
    sid = created.json()["id"]

    ans1 = client.post(
        f"/api/v1/interview/sessions/{sid}/answer",
        headers=headers,
        json={
            "answer": (
                "我在校园二手交易平台实习项目里负责后端 API，"
                "用 FastAPI 和 PostgreSQL，做过库存扣减与接口鉴权。"
            )
        },
    )
    assert ans1.status_code == 200, ans1.text
    assert ans1.json()["done"] is False
    q2 = ans1.json()["session"]["current_question"]["question"]
    assert q2
    # Follow-up should be able to reference the mentioned project clue
    assert "项目" in q2 or "实习" in q2 or "FastAPI" in q2 or "职责" in q2 or "后端" in q2

    follow = next_question(
        seq=2,
        total=5,
        target_role="后端开发",
        resume_snapshot={},
        jd_snapshot=None,
        prior_turns=[
            {
                "seq": 1,
                "question": q1,
                "answer": "我在校园二手交易平台实习项目里负责后端 API，用 FastAPI。",
            }
        ],
        credentials=None,
        retriever=None,
    )
    assert "这个项目" not in follow.question or "实习" in follow.question or "交易" in follow.question


def test_build_questions_with_resume_allows_project_bank():
    from lawbot.agent.interview.runner import build_questions

    qs = build_questions(
        count=3,
        target_role="Python 后端",
        resume_snapshot={
            "parse_status": "ready",
            "id": "r1",
            "skills": ["Python", "FastAPI"],
            "structured": {
                "skills": ["Python", "FastAPI"],
                "projects": [{"name": "订单中心", "role": "后端", "description": "高并发下单"}],
                "intent": "后端",
            },
        },
        jd_snapshot=None,
        retriever=None,
    )
    joined = " ".join(q.question for q in qs)
    # With resume, later fallback pool may include project dig (after opening)
    assert qs[0].question  # opening still present
    assert any("项目" in q.question or "简历" in q.question for q in qs[1:]) or "自我介绍" in joined

