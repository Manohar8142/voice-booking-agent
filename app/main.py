"""FastAPI entrypoint.

Run:  uvicorn app.main:app --reload
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .agent import BookingAgent
from .config import Settings, get_settings
from .inventory import Inventory
from .llm import MockLLM, OpenAICompatibleLLM
from .tools import ToolBox
from .tts import get_tts
from .twilio_voice import router as voice_router


class ChatIn(BaseModel):
    session_id: str = "demo"
    text: str


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Voice Booking Agent", version="1.0.0")
    inventory = Inventory()
    llm = MockLLM() if settings.llm_mock else OpenAICompatibleLLM(settings.llm_api_key, settings.llm_base_url, settings.llm_model)
    app.state.settings = settings
    app.state.inventory = inventory
    app.state.agent = BookingAgent(llm, ToolBox(inventory, settings.handoff_amount_threshold))
    app.state.tts = get_tts(settings)
    app.include_router(voice_router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "llm_mock": settings.llm_mock, "tts_mock": settings.tts_mock}

    @app.post("/chat")
    def chat(body: ChatIn) -> dict:
        """Text channel into the same agent; handy for testing without a phone."""
        r = app.state.agent.respond(body.session_id, body.text)
        return {"reply": r.text, "tool_calls": r.tool_calls, "handoff": asdict(r.handoff) if r.handoff else None}

    @app.get("/handoffs")
    def list_handoffs(status: str = "pending") -> list[dict]:
        return [asdict(h) for h in app.state.agent.handoffs.values() if h.status == status]

    @app.post("/handoffs/{handoff_id}/{decision}")
    def decide(handoff_id: str, decision: str) -> dict:
        if decision not in ("approve", "reject"):
            raise HTTPException(400, "decision must be approve or reject")
        if handoff_id not in app.state.agent.handoffs:
            raise HTTPException(404, "unknown handoff")
        return asdict(app.state.agent.resolve_handoff(handoff_id, decision == "approve"))

    return app


app = create_app()
