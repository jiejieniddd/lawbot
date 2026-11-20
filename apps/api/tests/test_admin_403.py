def test_user_token_forbidden_on_admin(client):
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "normal01@example.com", "password": "secret12"},
    )
    token = reg.json()["access_token"]
    resp = client.get(
        "/api/admin/stats/overview",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
