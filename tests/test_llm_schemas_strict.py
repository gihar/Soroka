"""Strict Structured Outputs schema compliance.

OpenAI/Azure strict mode requires `additionalProperties: false` on every object
schema node (including the root) whenever `strict: true` is sent. SpeakerMappingSchema
historically lacked this at the root, which made the speaker-mapping LLM call fail
with HTTP 400 and silently disabled the speaker-mapping confirmation UI.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _all_predefined_schemas():
    from src.models import llm_schemas

    names = [n for n in dir(llm_schemas) if n.endswith("_SCHEMA")]
    return [(n, getattr(llm_schemas, n)) for n in names]


def test_speaker_mapping_schema_root_is_closed():
    from src.models.llm_schemas import SPEAKER_MAPPING_SCHEMA

    assert SPEAKER_MAPPING_SCHEMA["strict"] is True
    assert SPEAKER_MAPPING_SCHEMA["schema"].get("additionalProperties") is False


@pytest.mark.parametrize("name,schema", _all_predefined_schemas())
def test_all_strict_schema_roots_are_closed(name, schema):
    if schema.get("strict") is True:
        root = schema["schema"]
        assert root.get("additionalProperties") is False, (
            f"{name}: strict schema root must set additionalProperties=false"
        )


def test_dict_fields_keep_typed_additional_properties():
    """Dict[str, T] maps must keep their typed additionalProperties, NOT be
    overwritten with false (that would forbid the dynamic keys the LLM fills)."""
    from src.models.llm_schemas import SPEAKER_MAPPING_SCHEMA

    props = SPEAKER_MAPPING_SCHEMA["schema"]["properties"]
    for field in ("speaker_mappings", "confidence_scores"):
        ap = props[field].get("additionalProperties")
        assert isinstance(ap, dict), f"{field} should keep a typed additionalProperties"
        assert ap is not False


def test_nested_defs_objects_are_closed():
    """Nested submodels hoisted to $defs must also get additionalProperties:false."""
    from src.models.llm_schemas import UNIFIED_PROTOCOL_SCHEMA

    defs = UNIFIED_PROTOCOL_SCHEMA["schema"].get("$defs", {})
    assert defs, "expected at least one nested $defs entry (e.g. SelfReflectionSchema)"
    for def_name, def_schema in defs.items():
        if def_schema.get("type") == "object":
            assert def_schema.get("additionalProperties") is False, (
                f"$defs.{def_name}: nested object must set additionalProperties=false"
            )
