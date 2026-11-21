from __future__ import annotations

from datetime import datetime, timedelta, timezone

from lawbot.db.models import Conversation, Message, User
from lawbot.domain.schemas import UserRole
from lawbot.security import hash_password
from otp_helpers import register_user


def _root_headers(client, admin_user):
    resp = client.post(
        "/api/admin/auth/login",
        json={"email": "root", "password": "Admin123!"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_stats_series_forbidden_for_end_user(client, otp_mail):
    reg = register_user(client, otp_mail, "series_denied@example.com")
    token = reg["access_token"]
    resp = client.get(
        "/api/admin/stats/series",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_stats_series_rejects_bad_days(client, admin_user):
    headers = _root_headers(client, admin_user)
    resp = client.get("/api/admin/stats/series", headers=headers, params={"days": 9})
    assert resp.status_code == 422


def test_stats_series_counts_and_zero_fill(client, admin_user, db_session):
    headers = _root_headers(client, admin_user)
    today = datetime.now(timezone.utc).date()
    day_a = today - timedelta(days=2)
    day_b = today - timedelta(days=1)
    ts_a = datetime(day_a.year, day_a.month, day_a.day, 12, 0, tzinfo=timezone.utc)
    ts_b = datetime(day_b.year, day_b.month, day_b.day, 15, 30, tzinfo=timezone.utc)

    end_user = User(
        email="series_user@example.com",
        password_hash=hash_password("Pass1234"),
        display_name="Series",
        role=UserRole.USER,
        created_at=ts_a,
    )
    db_session.add(end_user)
    db_session.flush()

    conv = Conversation(
        user_id=end_user.id,
        title="series conv",
        status="active",
        created_at=ts_b,
    )
    db_session.add(conv)
    db_session.flush()

    db_session.add_all(
        [
            Message(
                conversation_id=conv.id,
                role="user",
                content="hi",
                citations=[],
                created_at=ts_b,
            ),
            Message(
                conversation_id=conv.id,
                role="assistant",
                content="hello",
                citations=[],
                created_at=ts_b,
            ),
        ]
    )
    db_session.commit()

    resp = client.get("/api/admin/stats/series", headers=headers, params={"days": 7})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["days"] == 7
    assert body["bucket"] == "day"
    assert body["timezone"] == "UTC"
    assert len(body["points"]) == 7

    by_date = {p["date"]: p for p in body["points"]}
    assert by_date[day_a.isoformat()]["new_end_users"] == 1
    assert by_date[day_a.isoformat()]["new_conversations"] == 0
    assert by_date[day_a.isoformat()]["new_messages"] == 0

    assert by_date[day_b.isoformat()]["new_end_users"] == 0
    assert by_date[day_b.isoformat()]["new_conversations"] == 1
    assert by_date[day_b.isoformat()]["new_messages"] == 2

    assert sum(p["new_end_users"] for p in body["points"]) == 1
    assert sum(p["new_conversations"] for p in body["points"]) == 1
    assert sum(p["new_messages"] for p in body["points"]) == 2

    # Oldest day in the 7-day window should be zero-filled (no fixtures there).
    oldest = (today - timedelta(days=6)).isoformat()
    assert by_date[oldest] == {
        "date": oldest,
        "new_end_users": 0,
        "new_conversations": 0,
        "new_messages": 0,
    }
