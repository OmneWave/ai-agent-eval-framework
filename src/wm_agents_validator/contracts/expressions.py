from __future__ import annotations

import re

from wm_agents_validator.models.plugin_result import EvalContext

_PLACEHOLDER_RE = re.compile(r"\{[^}]+\}")


def evaluate_skip_if(expression: str | None, context: EvalContext | None) -> bool:
    """Return True if resource should be skipped."""
    if expression is None:
        return False
    expr = expression.strip().lower()
    if expr in ("", "null", "none", "false"):
        return False
    if expr == "true":
        return True

    ctx = context or EvalContext()

    if expr.startswith("task."):
        key = expression.strip()[5:]
        task_val = ctx.task.get(key)
        if " != " in key:
            field, expected = key.split(" != ", 1)
            return str(ctx.task.get(field.strip(), "")) != expected.strip().strip('"')
        return bool(task_val)

    return False


def resolve_path_template(path: str, context: EvalContext | None) -> str:
    ctx = context or EvalContext()
    result = path
    for key, value in ctx.bindings.items():
        result = result.replace(f"{{{key}}}", str(value))
    # Unresolved placeholders become single-segment wildcards for path matching
    return _PLACEHOLDER_RE.sub("*", result)


def glob_match(pattern: str, path: str) -> bool:
    import fnmatch

    return fnmatch.fnmatch(path, _PLACEHOLDER_RE.sub("*", pattern))
