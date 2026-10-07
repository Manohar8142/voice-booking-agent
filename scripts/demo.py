"""Run a scripted phone conversation against the agent in the terminal (mock mode works offline)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import create_app  # noqa: E402

TURNS = [
    "Hi, my name is Priya. Do you have a haircut tomorrow?",
    "Yes, book the first one.",
    "Actually, please cancel booking B1001.",
]


def main() -> None:
    app = create_app()
    agent = app.state.agent
    for turn in TURNS:
        print(f"CALLER: {turn}")
        reply = agent.respond("demo-call", turn, phone="+15550100")
        for call in reply.tool_calls:
            print(f"   [tool] {call['name']}({call['args']})")
        if reply.handoff:
            print(f"   [handoff] {reply.handoff.handoff_id}: {reply.handoff.reason}")
        print(f"AGENT:  {reply.text}\n")
    for h in list(agent.handoffs.values()):
        resolved = agent.resolve_handoff(h.handoff_id, approve=True)
        print(f"[human approved {h.handoff_id}] -> {resolved.result}")


if __name__ == "__main__":
    main()
