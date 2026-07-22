from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RawTracePayload(BaseModel):
    trace_id: str
    trace: dict[str, Any] | None = None
    observations: list[dict[str, Any]] = Field(default_factory=list)
    fetched_at: datetime | None = None
