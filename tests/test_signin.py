def test_shareable_signin_page_offers_demo_access(client):
    response = client.get("/signin")

    assert response.status_code == 200
    assert "Welcome to LeadFlow" in response.text
    assert 'href="/demo"' in response.text
    assert "Read-only demo" in response.text
    assert "Explore the LeadFlow demo" in response.text
    assert 'type="password"' not in response.text


def test_dashboard_links_to_shareable_signin_page(client):
    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/signin"' in response.text


def test_public_demo_is_synthetic_and_read_only(client):
    response = client.get("/demo")

    assert response.status_code == 200
    assert "SYNTHETIC SAMPLE DATA" in response.text
    assert "sarah.chen@northstar.example" in response.text
    assert "const DEMO_MODE = true" in response.text
    assert "id=\"newlead\"" not in response.text


def test_production_workspace_requires_signin_and_accepts_configured_owner(client, monkeypatch):
    from app.config import settings

    # The app may have been imported with production cookie settings from the
    # developer's environment, so exercise the signed session over HTTPS.
    client.base_url = "https://testserver"
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "admin_email", "owner@example.com")
    monkeypatch.setattr(settings, "admin_password", "a-long-test-password")

    assert client.get("/", follow_redirects=False).status_code == 303
    assert client.get("/api/leads").status_code == 401
    assert client.get("/demo").status_code == 200

    bad_login = client.post("/signin", data={"email": "owner@example.com", "password": "wrong"})
    assert bad_login.status_code == 401
    assert "Email or password is incorrect" in bad_login.text

    login = client.post("/signin", data={"email": "owner@example.com", "password": "a-long-test-password"}, follow_redirects=False)
    assert login.status_code == 303
    assert client.get("/").status_code == 200
    assert client.get("/api/leads").status_code == 200
    assert client.post("/logout", follow_redirects=False).status_code == 303
    assert client.get("/api/leads").status_code == 401
