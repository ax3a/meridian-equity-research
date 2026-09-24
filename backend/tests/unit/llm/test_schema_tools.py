from __future__ import annotations

import json
from enum import StrEnum

from pydantic import BaseModel, Field

from meridian.providers.llm.schema_tools import inline_json_schema


class Kind(StrEnum):
    FACT = "fact"
    CALCULATED = "calculated"
    INTERPRETATION = "interpretation"


class Nested(BaseModel):
    label: str
    weight: float = 1.0


class Sample(BaseModel):
    name: str = Field(min_length=1)
    kind: Kind
    nested: Nested
    nested_list: list[Nested] = Field(default_factory=list)
    optional_note: str | None = None
    count: int = 0


def _walk(node: object) -> list[dict]:
    """Collect every dict node in the schema tree."""
    found: list[dict] = []
    if isinstance(node, dict):
        found.append(node)
        for v in node.values():
            found.extend(_walk(v))
    elif isinstance(node, list):
        for v in node:
            found.extend(_walk(v))
    return found


def test_no_ref_or_defs_remain() -> None:
    schema = inline_json_schema(Sample)
    dumped = json.dumps(schema)
    assert "$ref" not in dumped
    assert "$defs" not in schema


def test_additional_properties_false_on_every_object() -> None:
    schema = inline_json_schema(Sample)
    objects = [n for n in _walk(schema) if n.get("type") == "object" or "properties" in n]
    assert objects, "expected at least one object schema"
    for obj in objects:
        assert obj.get("additionalProperties") is False


def test_required_lists_non_default_fields() -> None:
    schema = inline_json_schema(Sample)
    # top-level: name, kind, nested have no default; nested_list/optional_note/count do.
    assert set(schema["required"]) == {"name", "kind", "nested"}

    nested_schema = schema["properties"]["nested"]
    assert set(nested_schema["required"]) == {"label"}


def test_enum_values_preserved() -> None:
    schema = inline_json_schema(Sample)
    kind_schema = schema["properties"]["kind"]
    assert set(kind_schema["enum"]) == {"fact", "calculated", "interpretation"}


def test_nested_list_items_inlined_and_strict() -> None:
    schema = inline_json_schema(Sample)
    items_schema = schema["properties"]["nested_list"]["items"]
    assert items_schema.get("additionalProperties") is False
    assert "label" in items_schema["properties"]
