from __future__ import annotations

from app.routes.auth import safe_next_url


def test_private_routes_redirect_to_login(client):
    response = client.get("/leads/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_health_endpoint_is_public_and_checks_database(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["database"] == "ok"
    assert "ai_configured" in payload


def test_login_rejects_invalid_credentials(client):
    response = client.post(
        "/login",
        data={"email": "admin@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 200
    assert b"Invalid email or password" in response.data
    with client.session_transaction() as session:
        assert "user_id" not in session


def test_login_accepts_valid_credentials_and_rejects_open_redirect(client, app):
    response = client.post(
        "/login",
        data={
            "email": "ADMIN@example.com ",
            "password": "test-password-123",
            "next": "https://evil.example/steal",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    assert "evil.example" not in response.headers["Location"]
    with client.session_transaction() as session:
        assert session["user_id"] == app.config["TEST_USER_ID"]


def test_login_relative_next_is_honoured(client):
    response = client.post(
        "/login?next=/leads/",
        data={
            "email": "admin@example.com",
            "password": "test-password-123",
            "next": "/leads/",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/leads/")


def test_safe_next_url_rejects_backslash_and_absolute_targets():
    assert safe_next_url("/leads/") == "/leads/"
    assert safe_next_url("https://evil.example/") is None
    assert safe_next_url("//evil.example/") is None
    assert safe_next_url("/\\evil.example/") is None


def test_safe_next_url_rejects_encoded_external_redirects():
    assert safe_next_url("/%2F%2Fevil.example/") is None
    assert safe_next_url("/%2f%2fevil.example/") is None
    assert safe_next_url("/%5Cevil.example/") is None
    assert safe_next_url("/%5c%5cevilsite.com/") is None
    assert safe_next_url("/leads/") == "/leads/"
    assert safe_next_url("/leads/?q=hello%20world") == "/leads/?q=hello%20world"


def test_safe_next_url_rejects_double_encoded_and_malformed_inputs():
    """Encoded redirect attempts must never resolve to an external host."""
    assert safe_next_url("/%252F%252Fevil.example/") == "/%252F%252Fevil.example/"
    assert safe_next_url("/%255C%255Cevilsite.com/") == "/%255C%255Cevilsite.com/"
    assert safe_next_url("/%5c%5cevilsite.com/") is None
    assert safe_next_url("%5C%5Cevil.example/") is None
    assert safe_next_url("javascript:alert(1)") is None
    assert safe_next_url("data:text/html,<x>") is None
    assert safe_next_url("/evil.example.com") == "/evil.example.com"


def test_login_rejects_encoded_external_next(client, app):
    """An encoded external `next` must not redirect the authenticated user off-site."""
    response = client.post(
        "/login",
        data={
            "email": "admin@example.com",
            "password": "test-password-123",
            "next": "/%2F%2Fevil.example/steal",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    assert "evil.example" not in response.headers["Location"]
    with client.session_transaction() as session:
        assert session["user_id"] == app.config["TEST_USER_ID"]


def test_login_encoded_relative_next_is_honoured(client):
    """A valid encoded relative `next` is preserved after login."""
    response = client.post(
        "/login",
        data={
            "email": "admin@example.com",
            "password": "test-password-123",
            "next": "/leads/?q=hello%20world",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/leads/?q=hello%20world")


def test_logout_clears_session(auth_client):
    response = auth_client.post("/logout")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    with auth_client.session_transaction() as session:
        assert "user_id" not in session


def test_dashboard_is_authenticated(auth_client):
    response = auth_client.get("/")
    assert response.status_code == 200
    assert b"Pipeline overview" in response.data


def test_unknown_private_path_does_not_leak_a_404_to_anonymous(client):
    response = client.get("/leads/does-not-exist")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
