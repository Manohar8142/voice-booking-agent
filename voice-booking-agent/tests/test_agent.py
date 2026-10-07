import base64

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.twilio_voice import twilio_signature_valid


def mock_settings(**kw) -> Settings:
    base = dict(llm_api_key="", elevenlabs_api_key="", twilio_auth_token="", handoff_amount_threshold=500.0)
    base.update(kw)
    return Settings(**base)


def test_search_book_and_cancel_handoff():
    client = TestClient(create_app(mock_settings()))
    r = client.post("/chat", json={"text": "Hi, my name is Priya. Any haircut tomorrow?"}).json()
    assert r["tool_calls"][0]["name"] == "search_availability"
    assert "openings" in r["reply"]

    r = client.post("/chat", json={"text": "Yes, book the first one"}).json()
    assert r["tool_calls"][0]["name"] == "create_booking"
    assert "B1001" in r["reply"]

    r = client.post("/chat", json={"text": "Please cancel booking B1001"}).json()
    assert r["handoff"] is not None and r["handoff"]["tool"] == "cancel_booking"
    pending = client.get("/handoffs").json()
    assert len(pending) == 1

    done = client.post(f"/handoffs/{pending[0]['handoff_id']}/approve").json()
    assert done["status"] == "approved" and done["result"]["ok"] is True


def test_expensive_booking_needs_human():
    client = TestClient(create_app(mock_settings()))
    client.post("/chat", json={"session_id": "x", "text": "This is Ravi, spa package tomorrow please"})
    r = client.post("/chat", json={"session_id": "x", "text": "yes"}).json()
    assert r["handoff"] is not None and "exceeds" in r["handoff"]["reason"]


def test_twiml_flow_mock_mode():
    client = TestClient(create_app(mock_settings()))
    r = client.post("/voice/incoming", data={"CallSid": "CA1"})
    assert r.status_code == 200 and "<Gather" in r.text and "<Say>" in r.text
    r = client.post("/voice/gather", data={"CallSid": "CA1", "SpeechResult": "massage tomorrow, I'm Sam"})
    assert "openings" in r.text


def test_media_stream_sends_audio():
    client = TestClient(create_app(mock_settings()))
    with client.websocket_connect("/voice/stream") as ws:
        ws.send_json({"event": "start", "start": {"streamSid": "MZ1", "callSid": "CA9"}})
        first = ws.receive_json()
        assert first["event"] == "media" and base64.b64decode(first["media"]["payload"])
        ws.send_json({"event": "stop"})


def test_signature_validation():
    import hashlib, hmac
    url, params = "https://example.com/voice/incoming", {"CallSid": "CA1", "From": "+1555"}
    payload = url + "CallSidCA1From+1555"
    sig = base64.b64encode(hmac.new(b"secret", payload.encode(), hashlib.sha1).digest()).decode()
    assert twilio_signature_valid("secret", url, params, sig)
    assert not twilio_signature_valid("secret", url, params, "bogus")
