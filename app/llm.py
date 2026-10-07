"""LLM clients that speak the OpenAI chat-completions tool-calling format.

* ``OpenAICompatibleLLM`` works with OpenAI, Groq, Together, vLLM, Ollama... (any
  endpoint that implements ``POST /chat/completions`` with ``tools``).
* ``MockLLM`` is a deterministic rule-based stand-in so the whole agent loop
  (tool calls, handoffs, replies) runs offline and in tests.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, timedelta
from typing import Any, Protocol

import httpx

from .inventory import SERVICES

Message = dict[str, Any]


class LLM(Protocol):
    def complete(self, messages: list[Message], tools: list[dict]) -> Message: ...


class OpenAICompatibleLLM:
    def __init__(self, api_key: str, base_url: str, model: str, timeout: float = 30.0) -> None:
        self.model = model
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def complete(self, messages: list[Message], tools: list[dict]) -> Message:
        resp = self._client.post(
            "/chat/completions",
            json={"model": self.model, "messages": messages, "tools": tools, "tool_choice": "auto", "temperature": 0.2},
        )
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]
        out: Message = {"role": "assistant", "content": msg.get("content") or ""}
        if msg.get("tool_calls"):
            out["tool_calls"] = msg["tool_calls"]
        return out


def _call(name: str, args: dict) -> Message:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": f"call_{uuid.uuid4().hex[:8]}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
        ],
    }


class MockLLM:
    """Rule-based policy that imitates a tool-calling model for demos and tests."""

    def complete(self, messages: list[Message], tools: list[dict]) -> Message:
        last = messages[-1]
        if last["role"] == "tool":
            return {"role": "assistant", "content": self._summarise(messages)}
        text = (last.get("content") or "").lower()

        if "cancel" in text:
            m = re.search(r"\bb\s?(\d{3,})\b", text)
            if m:
                return _call("cancel_booking", {"booking_id": f"B{m.group(1)}"})
            return {"role": "assistant", "content": "Sure. What is your booking number? It starts with the letter B."}

        slot = re.search(r"\bs\s?(\d{3})\b", text)
        wants_book = any(w in text for w in ("book", "yes", "first one", "that one", "confirm"))
        if slot or wants_book:
            slot_id = f"S{slot.group(1)}" if slot else self._last_offered_slot(messages)
            name = self._caller_name(messages)
            if slot_id and name:
                return _call("create_booking", {"slot_id": slot_id, "customer_name": name, "phone": self._caller_phone(messages)})
            if slot_id and not name:
                return {"role": "assistant", "content": "Happy to book that. May I have your name, please?"}

        service = next((s for s in SERVICES if s in text or s.split()[0] in text), None)
        if service:
            args: dict[str, str] = {"service": service}
            day = self._parse_day(text)
            if day:
                args["day"] = day
            return _call("search_availability", args)

        if self._caller_name(messages) and self._last_offered_slot(messages):
            # caller just gave their name after we asked for it
            return _call(
                "create_booking",
                {"slot_id": self._last_offered_slot(messages), "customer_name": self._caller_name(messages), "phone": self._caller_phone(messages)},
            )
        return {"role": "assistant", "content": "I can book a haircut, massage, dental cleaning or spa package. Which would you like, and for which day?"}

    # ---- helpers -----------------------------------------------------
    @staticmethod
    def _parse_day(text: str) -> str | None:
        if "tomorrow" in text:
            return (date.today() + timedelta(days=1)).isoformat()
        m = re.search(r"\d{4}-\d{2}-\d{2}", text)
        return m.group(0) if m else None

    @staticmethod
    def _caller_name(messages: list[Message]) -> str | None:
        for msg in reversed(messages):
            if msg["role"] == "user":
                m = re.search(r"(?:my name is|this is|i am|i'm)\s+([a-z]+)", (msg.get("content") or ""), re.I)
                if m:
                    return m.group(1).title()
        return None

    @staticmethod
    def _caller_phone(messages: list[Message]) -> str:
        for msg in messages:
            if msg["role"] == "system":
                m = re.search(r"Caller phone: (\S+)", msg.get("content") or "")
                if m:
                    return m.group(1)
        return ""

    @staticmethod
    def _last_offered_slot(messages: list[Message]) -> str | None:
        for msg in reversed(messages):
            if msg["role"] == "tool":
                data = json.loads(msg["content"])
                if data.get("slots"):
                    return data["slots"][0]["slot_id"]
        return None

    @staticmethod
    def _summarise(messages: list[Message]) -> str:
        data = json.loads(messages[-1]["content"])
        if data.get("status") == "pending_human_approval":
            return f"I've passed that to a team member to confirm, because: {data['reason']} They'll follow up shortly."
        if not data.get("ok"):
            return f"Sorry, I couldn't do that: {data.get('error', 'unknown error')}."
        if "slots" in data:
            if not data["slots"]:
                return "I don't see any openings for that. Would another day work?"
            offers = "; ".join(f"{s['day']} at {s['time']} (slot {s['slot_id']}, {s['price']:.0f} dollars)" for s in data["slots"][:3])
            return f"I have {data['count']} openings. The first few are: {offers}. Which one should I book?"
        b = data["booking"]
        if b["status"] == "cancelled":
            return f"Booking {b['booking_id']} is cancelled."
        s = data["slot"]
        return f"You're booked, {b['customer_name']}: {s['service']} on {s['day']} at {s['time']}. Your booking number is {b['booking_id']}."
