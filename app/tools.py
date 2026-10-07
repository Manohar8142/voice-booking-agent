"""Tool definitions exposed to the LLM, plus the risk policy that gates them."""
from __future__ import annotations

from typing import Any, Callable

from .inventory import Inventory

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_availability",
            "description": "Find open appointment slots for a service, optionally on a given ISO date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string", "description": "e.g. haircut, massage, dental cleaning, spa package"},
                    "day": {"type": "string", "description": "ISO date YYYY-MM-DD (optional)"},
                },
                "required": ["service"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_booking",
            "description": "Book a slot for the caller. Only call after the caller confirmed the slot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slot_id": {"type": "string"},
                    "customer_name": {"type": "string"},
                    "phone": {"type": "string"},
                },
                "required": ["slot_id", "customer_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_booking",
            "description": "Cancel an existing booking by its booking id (e.g. B1001).",
            "parameters": {
                "type": "object",
                "properties": {"booking_id": {"type": "string"}},
                "required": ["booking_id"],
            },
        },
    },
]


class ToolBox:
    """Executes tool calls against the inventory and decides which ones are risky."""

    def __init__(self, inventory: Inventory, amount_threshold: float) -> None:
        self.inventory = inventory
        self.amount_threshold = amount_threshold
        self._fns: dict[str, Callable[..., dict]] = {
            "search_availability": self._search,
            "create_booking": self._create,
            "cancel_booking": self._cancel,
        }

    # ---- risk policy -------------------------------------------------
    def risk_reason(self, name: str, args: dict) -> str | None:
        """Return a reason string if this call must go to a human, else None."""
        if name == "cancel_booking":
            return "Cancellations are irreversible and require a human to confirm."
        if name == "create_booking":
            price = self.inventory.price_of(args.get("slot_id", ""))
            if price > self.amount_threshold:
                return f"Booking total {price:.2f} exceeds the auto-approve limit of {self.amount_threshold:.2f}."
        return None

    # ---- execution ---------------------------------------------------
    def run(self, name: str, args: dict) -> dict:
        fn = self._fns.get(name)
        if fn is None:
            return {"ok": False, "error": f"Unknown tool {name}"}
        try:
            return fn(**args)
        except TypeError as exc:
            return {"ok": False, "error": f"Bad arguments for {name}: {exc}"}

    def _search(self, service: str, day: str | None = None) -> dict:
        slots = self.inventory.search(service, day)
        return {"ok": True, "slots": slots, "count": len(slots)}

    def _create(self, slot_id: str, customer_name: str, phone: str = "") -> dict:
        return self.inventory.book(slot_id, customer_name, phone)

    def _cancel(self, booking_id: str) -> dict:
        return self.inventory.cancel(booking_id)
