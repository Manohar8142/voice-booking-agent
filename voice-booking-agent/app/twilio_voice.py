"""Twilio voice webhooks (TwiML <Gather> loop) and a Media Streams WebSocket."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from urllib.parse import quote
from xml.sax.saxutils import escape

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse

GREETING = "Hi, thanks for calling. I can book, check, or cancel appointments. How can I help?"

router = APIRouter(prefix="/voice", tags=["twilio"])


# ---- helpers -----------------------------------------------------------
def twilio_signature_valid(auth_token: str, url: str, params: dict, signature: str) -> bool:
    """Validate X-Twilio-Signature (HMAC-SHA1 of URL + sorted POST params)."""
    payload = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature or "")


def speak(settings, text: str) -> str:
    """TwiML that voices ``text``: ElevenLabs via <Play> when configured, else Twilio <Say>."""
    if settings.tts_mock:
        return f"<Say>{escape(text)}</Say>"
    url = f"{settings.public_base_url}/voice/tts?text={quote(text)}"
    return f"<Play>{escape(url)}</Play>"


def twiml(body: str) -> Response:
    return Response(content=f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>', media_type="application/xml")


def gather(settings, prompt: str) -> str:
    return (
        f'<Gather input="speech" action="/voice/gather" method="POST" speechTimeout="auto" language="en-US">'
        f"{speak(settings, prompt)}</Gather>"
        f"{speak(settings, 'Are you still there?')}<Redirect method=\"POST\">/voice/gather</Redirect>"
    )


async def _form(request: Request) -> dict:
    form = dict(await request.form())
    s = request.app.state.settings
    if s.twilio_auth_token:
        url = f"{s.public_base_url}{request.url.path}"
        if not twilio_signature_valid(s.twilio_auth_token, url, form, request.headers.get("X-Twilio-Signature", "")):
            raise HTTPException(status_code=403, detail="Invalid Twilio signature")
    return form


# ---- TwiML webhooks ----------------------------------------------------
@router.post("/incoming")
async def incoming(request: Request) -> Response:
    """Twilio 'A call comes in' webhook."""
    await _form(request)
    return twiml(gather(request.app.state.settings, GREETING))


@router.post("/gather")
async def on_speech(request: Request) -> Response:
    """Receives Twilio speech recognition results, runs the agent, speaks the reply."""
    form = await _form(request)
    s = request.app.state.settings
    speech = (form.get("SpeechResult") or "").strip()
    if not speech:
        return twiml(gather(s, "Sorry, I didn't catch that. What can I help you with?"))
    reply = request.app.state.agent.respond(form.get("CallSid", "local"), speech, phone=form.get("From", ""))
    if reply.handoff and s.human_agent_number:
        return twiml(f"{speak(s, reply.text + ' Connecting you now.')}<Dial>{escape(s.human_agent_number)}</Dial>")
    return twiml(gather(s, reply.text))


@router.get("/tts")
async def tts(request: Request, text: str) -> StreamingResponse:
    """Streams ElevenLabs audio to Twilio's <Play> as it is generated."""
    engine = request.app.state.tts
    media = "audio/wav" if request.app.state.settings.tts_mock else "audio/mpeg"
    return StreamingResponse(engine.stream(text[:800]), media_type=media)


@router.post("/incoming-stream")
async def incoming_stream(request: Request) -> Response:
    """Alternative webhook that opens a bidirectional Media Stream to /voice/stream."""
    await _form(request)
    ws_url = request.app.state.settings.public_base_url.replace("http", "ws", 1) + "/voice/stream"
    return twiml(f'<Connect><Stream url="{escape(ws_url)}" /></Connect>')


# ---- Media Streams -----------------------------------------------------
async def _send_audio(ws: WebSocket, tts, stream_sid: str, text: str, mark: str) -> None:
    """Stream ElevenLabs mu-law 8 kHz audio back into the live call."""
    async for chunk in tts.stream(text, output_format="ulaw_8000"):
        payload = base64.b64encode(chunk).decode()
        await ws.send_text(json.dumps({"event": "media", "streamSid": stream_sid, "media": {"payload": payload}}))
    await ws.send_text(json.dumps({"event": "mark", "streamSid": stream_sid, "mark": {"name": mark}}))


@router.websocket("/stream")
async def media_stream(ws: WebSocket) -> None:
    """Twilio Media Streams handler.

    Speaks the greeting into the call as soon as the stream starts. Inbound caller audio
    arrives as ``media`` events (mu-law 8 kHz); plug a streaming STT in ``on_media``. For
    local testing, or when an external STT posts transcripts, send
    ``{"event": "transcript", "text": "..."}`` and the agent's reply is streamed back.
    """
    await ws.accept()
    app = ws.app
    stream_sid, call_sid = "", "stream"
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            event = msg.get("event")
            if event == "start":
                stream_sid = msg["start"]["streamSid"]
                call_sid = msg["start"].get("callSid", stream_sid)
                await _send_audio(ws, app.state.tts, stream_sid, GREETING, "greeting")
            elif event == "media":
                pass  # on_media: forward base64 mu-law payload to a streaming STT here
            elif event == "transcript":
                reply = app.state.agent.respond(call_sid, msg.get("text", ""))
                await ws.send_text(json.dumps({"event": "agent_text", "text": reply.text, "handoff": bool(reply.handoff)}))
                await _send_audio(ws, app.state.tts, stream_sid, reply.text, "reply")
            elif event == "stop":
                break
    except WebSocketDisconnect:
        pass
