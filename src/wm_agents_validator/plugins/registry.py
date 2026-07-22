from __future__ import annotations

from wm_agents_validator.plugins.base import EvaluatorPlugin
from wm_agents_validator.plugins.input_context import InputContextPlugin
from wm_agents_validator.plugins.output import OutputPlugin
from wm_agents_validator.plugins.resource_usage import ResourceUsagePlugin
from wm_agents_validator.plugins.skills_loaded import SkillsLoadedPlugin
from wm_agents_validator.plugins.tool_calls import ToolCallsPlugin
from wm_agents_validator.plugins.trace_health import TraceHealthPlugin

DEFAULT_PLUGINS = [
    "skills_loaded",
    "tool_calls",
    "input_context",
    "output",
    "trace_health",
    "resource_usage",
]

# `resource_usage` is deliberately absent -- it runs (via DEFAULT_PLUGINS) and
# populates evidence but never affects `overall_score`, since it's purely
# observational (see the Scoring section of the contract schema).
PLUGIN_WEIGHTS: dict[str, float] = {
    "skills_loaded": 0.15,
    "tool_calls": 0.15,
    "input_context": 0.25,
    "output": 0.25,
    "trace_health": 0.20,
}

_PLUGIN_CLASSES: dict[str, type] = {
    "skills_loaded": SkillsLoadedPlugin,
    "tool_calls": ToolCallsPlugin,
    "input_context": InputContextPlugin,
    "output": OutputPlugin,
    "trace_health": TraceHealthPlugin,
    "resource_usage": ResourceUsagePlugin,
}


def list_plugins() -> list[str]:
    return list(_PLUGIN_CLASSES.keys())


def get_plugin(name: str) -> EvaluatorPlugin:
    if name not in _PLUGIN_CLASSES:
        raise KeyError(f"Unknown plugin: {name}. Available: {', '.join(list_plugins())}")
    return _PLUGIN_CLASSES[name]()
