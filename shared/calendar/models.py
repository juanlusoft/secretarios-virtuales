from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CalendarEvent:
    id: str
    title: str
    start: datetime
    end: datetime
    description: str = field(default="")
    location: str = field(default="")
