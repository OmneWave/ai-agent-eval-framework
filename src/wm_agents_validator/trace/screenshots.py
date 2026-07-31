"""Utilities for extracting input/output screenshots from a TraceSnapshot.

Used by both visual_report.py and the comparison aggregator so the same
extraction logic applies whether you're generating a standalone visual report
or embedding screenshots in the compare-traces HTML.
"""
from __future__ import annotations

import json
import re
from typing import Any

from wm_agents_validator.models.raw_trace import RawTracePayload
from wm_agents_validator.models.trace_snapshot import TraceSnapshot


def base_tool_name(span_name: str) -> str:
    return span_name.split("(")[0].strip()


def iter_tool_spans(snapshot: TraceSnapshot, tool_name: str):
    for span in snapshot.spans:
        if span.type == "TOOL" and base_tool_name(span.name) == tool_name:
            yield span


def iter_spans_by_name(snapshot: TraceSnapshot, name_fragment: str):
    frag = name_fragment.lower()
    for span in snapshot.spans:
        if frag in span.name.lower():
            yield span


_B64_RE = re.compile(r"^[A-Za-z0-9+/\r\n]+=*$")


def _looks_like_base64(s: str) -> bool:
    return len(s) > 200 and bool(_B64_RE.match(s.replace("\n", "").replace("\r", "")[:80]))


def extract_image(data: Any, depth: int = 0) -> str | None:
    """Recursively search for an image in span input/output.

    Returns a data-URI string ready to embed in an <img src="...">.
    """
    if depth > 6 or data is None:
        return None

    if isinstance(data, str):
        if data.startswith("data:image"):
            return data
        if _looks_like_base64(data):
            return f"data:image/png;base64,{data}"
        if len(data) > 2 and data[0] in ("{", "["):
            try:
                parsed = json.loads(data)
                return extract_image(parsed, depth + 1)
            except (json.JSONDecodeError, ValueError):
                pass
        return None

    if isinstance(data, dict):
        # Anthropic content block: {"type": "image", "source": {"type": "base64", "data": "..."}}
        if data.get("type") == "image":
            source = data.get("source", {})
            if isinstance(source, dict) and source.get("data"):
                media = source.get("media_type", "image/png")
                return f"data:{media};base64,{source['data']}"
            # Direct base64 key (ui_getPageScreenshot format)
            if data.get("base64"):
                return f"data:image/png;base64,{data['base64']}"

        # OpenAI image_url block
        if data.get("type") == "image_url":
            url = (data.get("image_url") or {}).get("url", "")
            if url.startswith("data:image"):
                return url

        for key in ("screenshot", "image", "base64", "data", "preview", "url", "content"):
            val = data.get(key)
            if val:
                result = extract_image(val, depth + 1)
                if result:
                    return result

        for val in data.values():
            result = extract_image(val, depth + 1)
            if result:
                return result

        return None

    if isinstance(data, list):
        for item in data:
            result = extract_image(item, depth + 1)
            if result:
                return result
        return None

    return None


_INPUT_SPAN_NAMES = {"wm_screenshot_to_code_agent", "start_new_conversation_with_agent"}


def extract_input_screenshot(
    snapshot: TraceSnapshot,
    payload: RawTracePayload | None = None,
) -> str | None:
    """Find the Figma design / input screenshot from the trace."""
    for span in iter_spans_by_name(snapshot, "wm_screenshot_to_code_agent"):
        img = extract_image(span.input)
        if img:
            return img

    for span in iter_tool_spans(snapshot, "start_new_conversation_with_agent"):
        img = extract_image(span.input)
        if img:
            return img

    if snapshot.user_prompt:
        img = extract_image(snapshot.user_prompt)
        if img:
            return img

    if payload:
        if payload.trace:
            img = extract_image(payload.trace.get("input"))
            if img:
                return img

        for obs in payload.observations:
            name: str = obs.get("name", "") or ""
            if base_tool_name(name) in _INPUT_SPAN_NAMES:
                for field in ("input", "output"):
                    img = extract_image(obs.get(field))
                    if img:
                        return img

    return None


def extract_output_screenshot(
    snapshot: TraceSnapshot,
    payload: RawTracePayload | None = None,
) -> str | None:
    """Find the generated page preview from ui_getPageScreenshot."""
    for span in iter_tool_spans(snapshot, "ui_getPageScreenshot"):
        img = extract_image(span.output)
        if img:
            return img

    if payload:
        for obs in payload.observations:
            name: str = obs.get("name", "") or ""
            if base_tool_name(name) == "ui_getPageScreenshot":
                img = extract_image(obs.get("output"))
                if img:
                    return img

    return None
