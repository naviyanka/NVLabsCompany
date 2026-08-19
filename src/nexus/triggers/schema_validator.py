"""Schema validator - minimal JSON Schema validation subset.

Implements a lightweight JSON Schema validator supporting:
type, required, properties, and enum keywords. Unknown keywords
are ignored (degrade to accept, not reject).
"""

from typing import Any


def validate_against_schema(
    value: Any, schema: dict[str, Any]
) -> dict[str, bool | str]:
    """Validate a value against a minimal JSON Schema subset.

    Supports the following keywords:
    - type: string, number, integer, boolean, array, object, null
    - required: list of required property names (for objects)
    - properties: map of property name to sub-schema (for objects)
    - enum: list of allowed values

    Unknown keywords are ignored and do not cause validation failure.

    Args:
        value: The value to validate.
        schema: A JSON Schema (dict) to validate against.

    Returns:
        A dict with 'ok' (bool) and optionally 'error' (str) on failure.
    """
    # Type validation
    if "type" in schema:
        schema_type = schema["type"]
        if not _check_type(value, schema_type):
            return {
                "ok": False,
                "error": f"Expected type '{schema_type}', "
                f"got '{_python_type_name(value)}'",
            }

    # Enum validation
    if "enum" in schema:
        allowed = schema["enum"]
        if value not in allowed:
            return {
                "ok": False,
                "error": f"Value {value!r} not in enum {allowed!r}",
            }

    # Object-specific validation
    if isinstance(value, dict):
        # Required fields
        if "required" in schema:
            for req_field in schema["required"]:
                if req_field not in value:
                    return {
                        "ok": False,
                        "error": f"Missing required field '{req_field}'",
                    }

        # Properties validation
        if "properties" in schema:
            for prop_name, prop_schema in schema["properties"].items():
                if prop_name in value:
                    result = validate_against_schema(
                        value[prop_name], prop_schema
                    )
                    if not result["ok"]:
                        return {
                            "ok": False,
                            "error": f"Property '{prop_name}': "
                            f"{result['error']}",
                        }

    return {"ok": True}


def _check_type(value: Any, schema_type: str) -> bool:
    """Check if value matches the expected JSON Schema type.

    Args:
        value: The value to check.
        schema_type: The JSON Schema type string.

    Returns:
        True if the value matches the type, False otherwise.
    """
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "object":
        return isinstance(value, dict)
    if schema_type == "null":
        return value is None
    # Unknown type - degrade to accept
    return True


def _python_type_name(value: Any) -> str:
    """Get a human-readable type name for a Python value.

    Args:
        value: The value to describe.

    Returns:
        A string describing the JSON-equivalent type.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__
