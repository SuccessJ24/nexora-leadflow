from app.config import settings


def request_payload(**overrides):
    values = {
        "name": "Taylor Morgan",
        "email": "taylor@clearwater.example",
        "company": "Clearwater Systems",
        "website": "https://clearwater.example",
        "industry": "B2B SaaS",
        "budget": "$6,000 per month",
        "timeline": "Next quarter",
        "message": "We are looking for paid advertising and lead generation support.",
        "consent": "yes",
        "middle_name": "",
    }
    values.update(overrides)
    return values


def test_public_request_is_saved_and_confirmation_shown(client, mock_ai):
    response = client.post("/request", data=request_payload(), follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/request/thanks"
    assert "Thank you for reaching out" in client.get("/request/thanks").text
    detail = client.get("/api/leads/1").json()
    assert detail["email"] == "taylor@clearwater.example"
    assert detail["latest_analysis"]["lead_status"] == "HOT"
    received = next(event for event in detail["events"] if event["event_type"] == "LEAD_RECEIVED")
    assert received["event_data"] == {"source": "public_request_form", "consent_to_contact": True}


def test_public_request_validates_input_and_contact_consent(client):
    invalid_email = client.post("/request", data=request_payload(email="not-an-email"))
    assert invalid_email.status_code == 422
    assert "Please check the required fields" in invalid_email.text

    no_consent = client.post("/request", data=request_payload(consent=""))
    assert no_consent.status_code == 422
    assert "confirm that our team may contact you" in no_consent.text
    assert client.get("/api/leads").json() == []


def test_public_request_honeypot_does_not_save_spam(client):
    response = client.post("/request", data=request_payload(middle_name="bot"), follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/request/thanks"
    assert client.get("/api/leads").json() == []


def test_public_intake_stays_public_when_workspace_is_protected(client, mock_ai, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "admin_email", "owner@example.com")
    monkeypatch.setattr(settings, "admin_password", "test-only-password")

    response = client.post("/request", data=request_payload(), follow_redirects=False)

    assert response.status_code == 303
    assert client.get("/api/leads").status_code == 401
    assert client.get("/request").status_code == 200
