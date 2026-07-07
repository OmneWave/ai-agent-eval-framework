from __future__ import annotations

from wm_agents_validator.plugins.base import EvaluatorPlugin
from wm_agents_validator.plugins.context_grounding import ContextGroundingPlugin
from wm_agents_validator.plugins.file_mutability import FileMutabilityPlugin
from wm_agents_validator.plugins.intent_verification import IntentVerificationPlugin
from wm_agents_validator.plugins.resource_coverage import ResourceCoveragePlugin
from wm_agents_validator.plugins.resource_usage import ResourceUsagePlugin
from wm_agents_validator.plugins.tool_policy import ToolPolicyPlugin
from wm_agents_validator.plugins.trace_health import TraceHealthPlugin

DEFAULT_PLUGINS = [
    "intent_verification",
    "resource_coverage",
    "tool_policy",
    "context_grounding",
    "file_mutability",
    "trace_health",
    "resource_usage",
]

PLUGIN_WEIGHTS: dict[str, float] = {
    "intent_verification": 0.15,
    "resource_coverage": 0.15,
    "tool_policy": 0.15,
    "context_grounding": 0.15,
    "file_mutability": 0.15,
    "trace_health": 0.10,
    "resource_usage": 0.05,
}

_PLUGIN_CLASSES: dict[str, type] = {
    "intent_verification": IntentVerificationPlugin,
    "resource_coverage": ResourceCoveragePlugin,
    "tool_policy": ToolPolicyPlugin,
    "context_grounding": ContextGroundingPlugin,
    "file_mutability": FileMutabilityPlugin,
    "trace_health": TraceHealthPlugin,
    "resource_usage": ResourceUsagePlugin,
}


def list_plugins() -> list[str]:
    return list(_PLUGIN_CLASSES.keys())


def get_plugin(name: str) -> EvaluatorPlugin:
    if name not in _PLUGIN_CLASSES:
        raise KeyError(f"Unknown plugin: {name}. Available: {', '.join(list_plugins())}")
    return _PLUGIN_CLASSES[name]()
