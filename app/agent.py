"""The conversational agent: an LLM tool-calling loop with a human-handoff gate."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from .llm import LLM, Message
from .tools import TOOL_SCHEMAS, ToolBox

SYSTEM_PROMPT = """You are a friendly phone receptionist that books appointments.
Today is {today}. Keep replies short and natural for speech: one or two sentences, no lists or markdown.
Use the tools to check availability before offering times. Confirm the slot and the caller's name before booking.
Never invent slots or booking numbers. If a tool says a human must approve, tell the caller a team member will confirm.
Caller phone: {phone}"""

MAX_STEPS = 5


@dataclass
class Handoff:
    handoff_id: str
    session_id: str
    tool: str
    args: dict
    reason: str
    status: str = "pending"  # pending | approved | rejected
    result: dict | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class AgentReply:
    text: str
    handoff: Handoff | None = None
    tool_calls: list[dict] = field(default_factory=list)


class BookingAgent:
    def __init__(self, llm: LLM, toolbox: ToolBox) -> None:
        self.llm = llm
        self.toolbox = toolbox
        self.sessions: dict[str, list[Message]] = {}
        self.handoffs: dict[str, Handoff] = {}

    def _history(self, session_id: str, phone: str) -> list[Message]:
        if session_id not in self.sessions:
            prompt = SYSTEM_PROMPT.format(today=date.today().isoformat(), phone=phone or "unknown")
            self.sessions[session_id] = [{"role": "system", "content": prompt}]
        return self.sessions[session_id]

    def respond(self, session_id: str, text: str, phone: str = "") -> AgentReply:
        history = self._history(session_id, phone)
        history.append({"role": "user", "content": text})
        reply = AgentReply(text="")

        for _ in range(MAX_STEPS):
            msg = self.llm.complete(history, TOOL_SCHEMAS)
            history.append(msg)
            calls = msg.get("tool_calls") or []
            if not calls:
                reply.text = msg.get("content") or ""
                return reply
            for call in calls:
                name = call["function"]["name"]
                args = json.loads(call["function"].get("arguments") or "{}")
                reply.tool_calls.append({"name": name, "args": args})
                reason = self.toolbox.risk_reason(name, args)
                if reason:
                    handoff = Handoff(uuid.uuid4().hex[:8], session_id, name, args, reason)
                    self.handoffs[handoff.handoff_id] = handoff
                    reply.handoff = handoff
                    result = {"ok": False, "status": "pending_human_approval", "reason": reason, "handoff_id": handoff.handoff_id}
                else:
                    result = self.toolbox.run(name, args)
                history.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})

        reply.text = "Sorry, I'm having trouble with that. Let me connect you to a team member."
        return reply

    # ---- human-in-the-loop -------------------------------------------
    def resolve_handoff(self, handoff_id: str, approve: bool) -> Handoff:
        h = self.handoffs[handoff_id]
        if h.status != "pending":
            return h
        if approve:
            h.result = self.toolbox.run(h.tool, h.args)
            h.status = "approved"
        else:
            h.status = "rejected"
        return h
