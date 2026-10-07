"""A small in-memory inventory of bookable slots (a salon / clinic style calendar).

Everything is mock data so the project runs with zero external services.
"""
from __future__ import annotations

import itertools
import threading
from dataclasses import asdict, dataclass
from datetime import date, timedelta


@dataclass
class Slot:
    slot_id: str
    service: str
    day: str  # ISO date
    time: str  # HH:MM, 24h
    price: float
    available: bool = True


@dataclass
class Booking:
    booking_id: str
    slot_id: str
    customer_name: str
    phone: str
    status: str = "confirmed"  # confirmed | cancelled


SERVICES = {"haircut": 25.0, "massage": 80.0, "dental cleaning": 120.0, "spa package": 650.0}
TIMES = ["10:00", "11:30", "14:00", "16:30"]


class Inventory:
    def __init__(self, start: date | None = None, days: int = 7) -> None:
        self._lock = threading.Lock()
        self._ids = itertools.count(1001)
        start = start or date.today() + timedelta(days=1)
        self.slots: dict[str, Slot] = {}
        self.bookings: dict[str, Booking] = {}
        n = 1
        for d in range(days):
            day = (start + timedelta(days=d)).isoformat()
            for service, price in SERVICES.items():
                for t in TIMES:
                    sid = f"S{n:03d}"
                    self.slots[sid] = Slot(sid, service, day, t, price)
                    n += 1

    def search(self, service: str, day: str | None = None, limit: int = 5) -> list[dict]:
        service = service.lower().strip()
        out = [
            asdict(s)
            for s in self.slots.values()
            if s.available and service in s.service and (day is None or s.day == day)
        ]
        return out[:limit]

    def book(self, slot_id: str, customer_name: str, phone: str) -> dict:
        with self._lock:
            slot = self.slots.get(slot_id)
            if slot is None:
                return {"ok": False, "error": f"Unknown slot {slot_id}"}
            if not slot.available:
                return {"ok": False, "error": f"Slot {slot_id} is no longer available"}
            slot.available = False
            bid = f"B{next(self._ids)}"
            self.bookings[bid] = Booking(bid, slot_id, customer_name, phone)
            return {"ok": True, "booking": asdict(self.bookings[bid]), "slot": asdict(slot)}

    def cancel(self, booking_id: str) -> dict:
        with self._lock:
            b = self.bookings.get(booking_id)
            if b is None or b.status == "cancelled":
                return {"ok": False, "error": f"No active booking {booking_id}"}
            b.status = "cancelled"
            self.slots[b.slot_id].available = True
            return {"ok": True, "booking": asdict(b)}

    def price_of(self, slot_id: str) -> float:
        slot = self.slots.get(slot_id)
        return slot.price if slot else 0.0
