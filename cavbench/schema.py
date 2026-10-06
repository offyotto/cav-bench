"""Minimal JSON Schema validator (subset of draft 2020-12) with zero deps.

Supports: type (incl. list of types), enum, const, required, properties,
additionalProperties (bool), items, minItems, minLength, pattern, $ref to
local #/$defs. If the optional `jsonschema` package is installed,
`validate()` uses it instead.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "data" / "schemas"

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _is_type(value: Any, t: str) -> bool:
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, _TYPES[t])


def _resolve(ref: str, root: dict) -> dict:
    if not ref.startswith("#/"):
        raise ValueError(f"only local refs supported: {ref}")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _validate(value: Any, schema: dict, root: dict, path: str, errors: list[str]) -> None:
    if "$ref" in schema:
        _validate(value, _resolve(schema["$ref"], root), root, path, errors)
        return
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(value, t) for t in types):
            errors.append(f"{path}: expected type {types}, got {type(value).__name__}")
            return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must equal {schema['const']!r}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                _validate(item, schema["items"], root, f"{path}[{i}]", errors)
    if isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                errors.append(f"{path}: missing required field '{req}'")
        props = schema.get("properties", {})
        for k, v in value.items():
            if k in props:
                _validate(v, props[k], root, f"{path}.{k}", errors)
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected field '{k}'")


def load_schema(name: str = "scenario.schema.json") -> dict:
    return json.loads((SCHEMA_DIR / name).read_text())


def validate(instance: Any, schema: dict) -> list[str]:
    """Return a list of human-readable errors (empty list = valid)."""
    try:  # prefer the reference implementation when available
        import jsonschema  # type: ignore

        v = jsonschema.Draft202012Validator(schema)
        return [f"$.{'.'.join(map(str, e.path))}: {e.message}" for e in v.iter_errors(instance)]
    except ImportError:
        errors: list[str] = []
        _validate(instance, schema, schema, "$", errors)
        return errors
