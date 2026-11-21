from otp_helpers import register_user


def test_user_token_forbidden_on_admin(client, otp_mail):
    reg = register_user(client, otp_mail, "normal01@example.com")
    token = reg["access_token"]
    resp = client.get(
        "/api/admin/stats/overview",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
