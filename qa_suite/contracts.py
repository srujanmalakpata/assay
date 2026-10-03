"""JSON Schema contract validation for API responses.

Schemas live in ``qa_suite/schemas`` and are written by hand from the API's intended
contract (not generated from the server's own OpenAPI document), so a change in the
server's response shape is caught instead of silently accepted.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SCHEMA_DIR = Path(__file__).parent / "schemas"


@cache
def _registry() -> Registry:
    resources = []
    for path in sorted(SCHEMA_DIR.glob("*.json")):
        schema = json.loads(path.read_text())
        resources.append((path.name, Resource.from_contents(schema)))
    return Registry().with_resources(resources)


@cache
def validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / f"{name}.json").read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=_registry())


def schema_errors(instance: Any, name: str) -> list[str]:
    errors = sorted(validator(name).iter_errors(instance), key=lambda e: list(e.path))
    return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors]


def assert_matches_schema(instance: Any, name: str) -> None:
    errors = schema_errors(instance, name)
    assert not errors, f"response does not match schema '{name}':\n  " + "\n  ".join(errors)
