"""JSON Schema helpers for Anthropic structured outputs and strict tool use.

Anthropic's `output_config.format` (json_schema) and strict tools both require a fully self-contained
schema: no `$ref`/`$defs` indirection, `additionalProperties: false` on every object (nested models
included), and an accurate `required` list. Pydantic's own `model_json_schema()` factors repeated
models out into `$defs` and references them with `$ref`, so we inline everything here.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def inline_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return `model`'s JSON schema with `$ref`/`$defs` inlined and strict object semantics applied."""
    return inline_schema_dict(model.model_json_schema())


def inline_schema_dict(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline `$ref`/`$defs` in an arbitrary (already-built) JSON schema dict and make it strict.

    Used both for Pydantic-model schemas (`inline_json_schema`) and for `ToolSpec.input_schema`
    dicts that already carry their own `$defs` (e.g. built elsewhere from a tool's Pydantic input model).
    """
    defs = schema.get("$defs", {})
    root = {k: v for k, v in schema.items() if k != "$defs"}
    # `_resolve_refs` walks dicts, lists and scalars alike so it is typed `Any`, but a dict going in
    # always yields a dict out -- stated here rather than left implicit at the return.
    inlined: dict[str, Any] = _resolve_refs(root, defs, frozenset())
    _enforce_strict_objects(inlined)
    return inlined


def _resolve_refs(node: Any, defs: dict[str, Any], seen: frozenset[str]) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            key = node["$ref"].rsplit("/", 1)[-1]
            if key in seen:
                raise ValueError(f"inline_json_schema: circular reference detected at {key!r}")
            if key not in defs:
                raise KeyError(f"inline_json_schema: missing $defs entry for $ref {node['$ref']!r}")
            target = _resolve_refs(defs[key], defs, seen | {key})
            siblings = {k: _resolve_refs(v, defs, seen) for k, v in node.items() if k != "$ref"}
            # Sibling keys (e.g. a field-level "description" or "default" placed next to the $ref)
            # take precedence over the referenced definition's own copy of that key.
            merged = {**target, **siblings}
            return merged
        return {k: _resolve_refs(v, defs, seen) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_refs(v, defs, seen) for v in node]
    return node


def _enforce_strict_objects(node: Any) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            node["additionalProperties"] = False
            # Pydantic already computes `required` correctly (it excludes fields with a default or a
            # default_factory, even though default_factory fields carry no literal "default" key in the
            # schema) — we only need to guarantee the key is present, never recompute it from scratch.
            node.setdefault("required", [])
        for value in node.values():
            _enforce_strict_objects(value)
    elif isinstance(node, list):
        for value in node:
            _enforce_strict_objects(value)


# The keywords a restricted endpoint is documented to accept. Gemini's function declarations take an
# OpenAPI 3.0 subset, and anything outside it is rejected with a bare "Request contains an invalid
# argument" that names no field -- so the only workable approach is to send nothing it did not ask for.
# `minItems`/`maxItems` are absent deliberately: Gemini documents them, and rejects them. A
# `maxItems: 40` on one array was half of what made a real agent schema fail, and the error named
# nothing. They only ever bounded output length as a hint, so dropping them costs nothing.
_PORTABLE_SCHEMA_KEYS = frozenset(
    {"type", "format", "description", "nullable", "enum", "items", "properties", "required"}
)


def portable_schema(node: Any) -> Any:
    """Reduce a JSON schema to the subset every OpenAI-compatible endpoint accepts.

    Anthropic tolerates a full JSON Schema, so this is a no-op there in practice. Gemini does not: a
    `DraftFinding` carrying `additionalProperties`, `title`, `default` and `maxLength` was rejected
    outright, with an error naming none of them, which cost a bisect to find.

    `anyOf: [X, null]` -- what `Optional[...]` compiles to -- becomes `X` with `nullable: true`, since
    the subset expresses optionality that way rather than as a union.
    """
    if isinstance(node, list):
        return [portable_schema(v) for v in node]
    if not isinstance(node, dict):
        return node

    if "anyOf" in node:
        options = [o for o in node["anyOf"] if isinstance(o, dict) and o.get("type") != "null"]
        nullable = len(options) != len(node["anyOf"])
        chosen = dict(options[0]) if options else {"type": "string"}
        for key, value in node.items():
            if key != "anyOf":
                chosen.setdefault(key, value)
        result = portable_schema(chosen)
        if nullable and isinstance(result, dict):
            result["nullable"] = True
        return result

    cleaned: dict[str, Any] = {}
    for key, value in node.items():
        if key not in _PORTABLE_SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            # A map of field names to schemas: recurse into the values, never filter the names --
            # filtering them here silently emptied every object of its fields.
            cleaned[key] = {name: portable_schema(sub) for name, sub in value.items()}
        else:
            cleaned[key] = portable_schema(value)
    # An object with no properties left is meaningless to a validator; give it a permissive shape.
    if cleaned.get("type") == "object" and not cleaned.get("properties"):
        cleaned.pop("required", None)
    return cleaned
